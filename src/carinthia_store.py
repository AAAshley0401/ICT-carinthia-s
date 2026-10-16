"""SQLite case storage with an append-only, hash-linked decision trail."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GENESIS = "0" * 64
CONCLUSIONS = frozenset({"CONFIRM_CLASS", "CORRECT_CLASS", "UNSURE", "RETAKE_IMAGE"})
LABELS = frozenset({"1", "2", "3", "4", "5", "6"})


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def event_hash(event: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json({
        key: event[key] for key in
        ("case_id", "sequence", "event_type", "actor", "occurred_at", "payload", "previous_hash")
    }).encode("utf-8")).hexdigest()


class CaseStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    image_id TEXT NOT NULL,
                    image_sha256 TEXT NOT NULL,
                    model_sha256 TEXT NOT NULL,
                    predicted_label TEXT,
                    route TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    prediction_json TEXT NOT NULL,
                    route_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    PRIMARY KEY (case_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_cases_queue ON cases(route, status, created_at);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        return db

    @staticmethod
    def _append_event(
        db: sqlite3.Connection, case_id: str, event_type: str,
        actor: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        previous = db.execute(
            "SELECT sequence, event_hash FROM events WHERE case_id=? ORDER BY sequence DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        event = {
            "case_id": case_id,
            "sequence": int(previous["sequence"]) + 1 if previous else 1,
            "event_type": event_type,
            "actor": actor,
            "occurred_at": now_utc(),
            "payload": payload,
            "previous_hash": previous["event_hash"] if previous else GENESIS,
        }
        event["event_hash"] = event_hash(event)
        db.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, event["sequence"], event_type, actor, event["occurred_at"],
             canonical_json(payload), event["previous_hash"], event["event_hash"]),
        )
        return event

    def create_case(
        self, prediction: dict[str, Any], route: dict[str, Any],
        *, case_id: str | None = None,
    ) -> str:
        case_id = case_id or uuid.uuid4().hex
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case_id must be nonempty")
        image_id = str(prediction["image_id"])
        image_sha = str(prediction["image_sha256"])
        model_sha = str(prediction["model_sha256"])
        predicted_label = prediction.get("predicted_label")
        route_name = str(route["route"])
        if route_name not in {"REVIEW_REQUIRED", "MODEL_CANDIDATE"}:
            raise ValueError("Unknown route")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (case_id, image_id, image_sha, model_sha, predicted_label,
                 route_name, "PENDING", now_utc(), canonical_json(prediction), canonical_json(route)),
            )
            self._append_event(db, case_id, "MODEL_ROUTING", "model_service", {
                "prediction": prediction, "route": route,
            })
        return case_id

    def add_review(
        self, case_id: str, *, reviewer: str, conclusion: str,
        final_label: str | None, notes: str = "",
    ) -> dict[str, Any]:
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("reviewer is required")
        if conclusion not in CONCLUSIONS:
            raise ValueError("Unknown review conclusion")
        if not isinstance(notes, str) or len(notes) > 2000:
            raise ValueError("notes must be text of at most 2000 characters")
        if conclusion in {"CONFIRM_CLASS", "CORRECT_CLASS"} and final_label not in LABELS:
            raise ValueError("A final class label 1..6 is required")
        if conclusion in {"UNSURE", "RETAKE_IMAGE"} and final_label is not None:
            raise ValueError("No final class label is allowed for this conclusion")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            case = db.execute("SELECT predicted_label FROM cases WHERE case_id=?", (case_id,)).fetchone()
            if case is None:
                raise KeyError(case_id)
            if conclusion == "CONFIRM_CLASS" and final_label != case["predicted_label"]:
                raise ValueError("Confirmed label must match model prediction")
            if conclusion == "CORRECT_CLASS" and final_label == case["predicted_label"]:
                raise ValueError("Corrected label must differ from model prediction")
            payload = {"conclusion": conclusion, "final_label": final_label, "notes": notes}
            event = self._append_event(db, case_id, "HUMAN_REVIEW", reviewer.strip(), payload)
            status = "NEEDS_RETAKE" if conclusion == "RETAKE_IMAGE" else "REVIEWED"
            db.execute("UPDATE cases SET status=? WHERE case_id=?", (status, case_id))
        return event

    def get_case(self, case_id: str) -> dict[str, Any]:
        with self._connect() as db:
            case = db.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
            if case is None:
                raise KeyError(case_id)
            rows = db.execute(
                "SELECT * FROM events WHERE case_id=? ORDER BY sequence", (case_id,)
            ).fetchall()
        events = []
        previous = GENESIS
        for row in rows:
            event = {key: row[key] for key in
                     ("case_id", "sequence", "event_type", "actor", "occurred_at", "previous_hash", "event_hash")}
            event["payload"] = json.loads(row["payload_json"])
            if event["previous_hash"] != previous or event_hash(event) != event["event_hash"]:
                raise ValueError(f"Broken event hash chain for case {case_id}")
            previous = event["event_hash"]
            events.append(event)
        return {
            "case_id": case_id, "image_id": case["image_id"],
            "image_sha256": case["image_sha256"], "model_sha256": case["model_sha256"],
            "predicted_label": case["predicted_label"], "route": case["route"],
            "status": case["status"], "created_at": case["created_at"],
            "prediction": json.loads(case["prediction_json"]),
            "routing_decision": json.loads(case["route_json"]),
            "events": events, "event_chain_valid": True,
        }

    def pending_reviews(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT case_id, image_id, predicted_label, created_at FROM cases "
                "WHERE route='REVIEW_REQUIRED' AND status='PENDING' ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]
