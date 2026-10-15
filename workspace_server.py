"""Serve the demo workspace and adapt the existing local Agent run for its UI."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from main import run_inspection
from src.detector_agent import DetectorAgent


ROOT = Path(__file__).resolve().parent
STATIC_FILES = {
    "/": (ROOT / "prototype" / "index.html", "text/html; charset=utf-8"),
    "/index.html": (ROOT / "prototype" / "index.html", "text/html; charset=utf-8"),
    "/styles.css": (ROOT / "prototype" / "styles.css", "text/css; charset=utf-8"),
    "/live.css": (ROOT / "prototype" / "live.css", "text/css; charset=utf-8"),
    "/app.js": (ROOT / "prototype" / "app.js", "text/javascript; charset=utf-8"),
    "/demo-cases.js": (ROOT / "prototype" / "demo-cases.js", "text/javascript; charset=utf-8"),
}
SAMPLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
BASELINE_ID_PATTERN = re.compile(r"^bottle_(good|broken_large|broken_small|contamination)_([0-9]+)$")
BASELINE_DATA = ROOT / "data" / "raw" / "mvtec_anomaly_detection" / "bottle"
BASELINE_JSON = ROOT / "outputs" / "json"
BASELINE_MASKS = ROOT / "outputs" / "masks"
BASELINE_SIZE = 256


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _baseline_record(sample_id: str) -> tuple[dict[str, Any], Path, Path]:
    """Resolve one saved MVTec inference without trusting paths stored in its JSON."""
    match = BASELINE_ID_PATTERN.fullmatch(sample_id)
    if match is None:
        raise ValueError("invalid baseline sample_id")
    category, stem = match.groups()
    image_path = BASELINE_DATA / "test" / category / f"{stem}.png"
    mask_path = BASELINE_MASKS / f"{sample_id}.png"
    record_path = BASELINE_JSON / f"{sample_id}.json"
    if not image_path.is_file() or not mask_path.is_file() or not record_path.is_file():
        raise ValueError("baseline artifacts are missing")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if (
        not isinstance(record, dict)
        or record.get("sample_id") != sample_id
        or record.get("status") != "success"
        or record.get("score_type") != "raw_nearest_patch_distance_not_probability"
        or Path(record.get("image_path", "")).resolve() != image_path.resolve()
        or Path(record.get("predicted_mask", "")).resolve() != mask_path.resolve()
        or not isinstance(record.get("model_version"), str)
        or not record["model_version"]
        or not all(type(record.get(key)) in (float, int) and math.isfinite(record[key]) for key in ("anomaly_score", "image_threshold", "mask_threshold"))
    ):
        raise ValueError("baseline artifact identity or score metadata is invalid")
    from PIL import Image
    with Image.open(mask_path) as mask:
        if mask.size != (BASELINE_SIZE, BASELINE_SIZE):
            raise ValueError("baseline mask size does not match preprocessing")
    if "evidence_manifest" not in record:
        record["_integrity"] = {
            "status": "LEGACY_UNVERIFIED",
            "run_id": None,
            "image_sha256": None,
            "mask_sha256": None,
            "created_at_utc": None,
        }
    else:
        manifest = record["evidence_manifest"]
        if (
            not isinstance(manifest, dict)
            or manifest.get("manifest_version") != "1.0"
            or not isinstance(manifest.get("run_id"), str)
            or re.fullmatch(r"[0-9a-f]{32}", manifest["run_id"]) is None
            or not isinstance(manifest.get("created_at_utc"), str)
            or not manifest["created_at_utc"]
            or any(not isinstance(manifest.get(key), str) or re.fullmatch(r"[0-9a-f]{64}", manifest[key]) is None for key in ("image_sha256", "mask_sha256"))
        ):
            raise ValueError("baseline evidence manifest is invalid")
        if _file_sha256(image_path) != manifest["image_sha256"] or _file_sha256(mask_path) != manifest["mask_sha256"]:
            raise ValueError("baseline image or mask content does not match its manifest")
        record["_integrity"] = {
            "status": "CONTENT_MATCH",
            "run_id": manifest["run_id"],
            "image_sha256": manifest["image_sha256"],
            "mask_sha256": manifest["mask_sha256"],
            "created_at_utc": manifest["created_at_utc"],
        }
    return record, image_path, mask_path


def _baseline_case(sample_id: str) -> dict[str, Any]:
    record, _image_path, mask_path = _baseline_record(sample_id)
    run_id = record["_integrity"]["run_id"] or "legacy"
    from PIL import Image
    mask_bytes = mask_path.read_bytes()
    expected_mask = record["_integrity"]["mask_sha256"]
    if expected_mask is not None and hashlib.sha256(mask_bytes).hexdigest() != expected_mask:
        raise ValueError("mask changed after manifest validation")
    with Image.open(io.BytesIO(mask_bytes)) as mask:
        bbox = mask.convert("L").getbbox()
    return {
        "contract_version": "baseline-evidence/1.0",
        "sample_id": sample_id,
        "provenance": {
            "dataset": "MVTec AD",
            "category": "bottle",
            "split": "test",
            "image_analyzed": True,
            "production_usable": False,
            "threshold_status": record.get("threshold_status", "UNKNOWN"),
            "integrity": record["_integrity"],
        },
        "image": {
            "ref": f"/api/baseline-media?sample_id={sample_id}&kind=image&run_id={run_id}",
            "mask_ref": f"/api/baseline-media?sample_id={sample_id}&kind=mask&run_id={run_id}",
            "width": BASELINE_SIZE,
            "height": BASELINE_SIZE,
            "evidence_bound": True,
            "mask_bbox_xyxy": list(bbox) if bbox else None,
        },
        "evidence": {
            "anomaly_score": record["anomaly_score"],
            "score_type": record["score_type"],
            "image_threshold": record["image_threshold"],
            "is_anomaly": record["is_anomaly"],
            "mask_threshold": record["mask_threshold"],
            "model_version": record["model_version"],
            "inference_ms": record.get("inference_ms"),
        },
        "agent_status": {
            "status": "NOT_RUN",
            "reason_codes": ["SEVERITY_NOT_AVAILABLE", "UNCALIBRATED_SCORE"],
            "human_review_required": True,
        },
    }


def _baseline_media(sample_id: str, kind: str, run_id: str) -> bytes:
    record, image_path, mask_path = _baseline_record(sample_id)
    if run_id != (record["_integrity"]["run_id"] or "legacy"):
        raise ValueError("baseline record changed after case response; reload the case")
    from PIL import Image
    if kind == "image":
        raw = image_path.read_bytes()
        expected = record["_integrity"]["image_sha256"]
        if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("source image changed after manifest validation")
        with Image.open(io.BytesIO(raw)) as source:
            image = source.convert("RGB").resize((BASELINE_SIZE, BASELINE_SIZE), Image.Resampling.BILINEAR)
    elif kind == "mask":
        raw = mask_path.read_bytes()
        expected = record["_integrity"]["mask_sha256"]
        if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("mask changed after manifest validation")
        with Image.open(io.BytesIO(raw)) as source:
            alpha = source.convert("L").point(lambda value: 110 if value else 0)
        image = Image.new("RGBA", (BASELINE_SIZE, BASELINE_SIZE), (255, 76, 53, 0))
        image.putalpha(alpha)
    else:
        raise ValueError("kind must be image or mask")
    data = io.BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def _error_code(raw_error: object) -> str | None:
    if raw_error is None:
        return None
    if isinstance(raw_error, dict):
        code = raw_error.get("code")
        return code if isinstance(code, str) and code else "TOOL_ERROR"
    return str(raw_error)


def _trace_view(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the actual local steps, omitting raw paths and duplicate payloads."""
    mapped: list[dict[str, Any]] = []
    for step in steps:
        label = step["agent"]
        if label == "ValidationAgent":
            output = step.get("output_summary", {})
            mapped.append({
                "stage": "VALIDATION",
                "label": label,
                "input_summary": {"demo_only": step.get("input", {}).get("demo_only")},
                "output_summary": {"status": output.get("validation_result")},
                "reason_codes": [output["reason_code"]] if output.get("reason_code") else [],
            })
        elif label == "RoutingEngine":
            decision = step.get("decision", {})
            mapped.append({
                "stage": "ROUTING",
                "label": label,
                "input_summary": {
                    "validation_status": step.get("input", {}).get("validation_result"),
                },
                "output_summary": {
                    "validated_path": decision.get("validated_path"),
                    "preview_path": decision.get("path"),
                },
                "reason_codes": list(decision.get("validated_reason_codes", [])),
            })
        else:
            raw_input = step.get("input", {})
            output = step.get("output_summary", {})
            mapped.append({
                "stage": "DETECTION",
                "label": label,
                "input_summary": {
                    "sample_id": raw_input.get("sample_id"),
                    "scenario": raw_input.get("scenario"),
                },
                "output_summary": {
                    "status": output.get("status"),
                    "defect_probability": output.get("defect_probability"),
                    "defect_count": len(output.get("defects", [])),
                    "demo_only": output.get("demo_only"),
                },
                "reason_codes": [],
            })
    return mapped


def build_agent_case_result(sample_id: str, scenario: str) -> dict[str, Any]:
    """Adapt a mock run; this does not read or bind an image."""
    if not SAMPLE_ID_PATTERN.fullmatch(sample_id):
        raise ValueError("sample_id must contain 1-64 letters, digits, '-' or '_'")
    if scenario not in DetectorAgent.MODES:
        raise ValueError("scenario must be normal, boundary or failure")

    run = run_inspection(sample_id, "demo://image-not-analyzed", scenario)
    steps = run["execution_trace"]
    validation_step = next(step for step in steps if step["agent"] == "ValidationAgent")
    detection = validation_step["input"]
    validation = validation_step["output_summary"]
    actual = run["validated_decision"]
    preview = {
        "path": run["path"],
        "reason_codes": list(run["reason_codes"]),
        "human_review_required": run["human_review_required"],
        "explanation": run["explanation"],
    }

    return {
        "contract_version": "1.0",
        "sample_id": sample_id,
        "provenance": {
            "source_kind": "LOCAL_WORKFLOW",
            "demo_only": True,
            "image_analyzed": False,
            "decision_scope": "SIMULATION_PREVIEW",
            "production_usable": False,
        },
        "image": {"ref": None, "width": None, "height": None, "evidence_bound": False},
        "detection": {
            "status": detection["status"],
            "model_version": detection["model_version"],
            "calibration_version": detection["calibration_version"],
            "defect_probability": detection["defect_probability"],
            "defects": detection["defects"],
            "error_code": _error_code(detection["error"]),
        },
        "validation": {
            "status": validation["validation_result"],
            "reason_code": validation["reason_code"],
        },
        "routing": {
            "path": actual["selected_path"],
            "reason_codes": list(actual["reason_codes"]),
            "human_review_required": actual["human_review_required"],
            "recommended_action": actual["recommended_action"],
            "preview": preview,
        },
        "trace": _trace_view(steps),
    }


class WorkspaceHandler(BaseHTTPRequestHandler):
    server_version = "HairlineWorkspace/1.0"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_OPTIONS(self) -> None:
        if self.path == "/api/agent-case":
            self._send(204, b"", "text/plain; charset=utf-8")
        else:
            self._json(404, {"error": "not_found"})

    def do_GET(self) -> None:
        request = urlsplit(self.path)
        if request.path == "/api/health":
            self._json(200, {"status": "ok", "mode": "mock", "contract_version": "1.0", "baseline_evidence_available": BASELINE_JSON.is_dir()})
            return
        if request.path == "/api/baseline-cases":
            cases = []
            for record_path in sorted(BASELINE_JSON.glob("bottle_*.json")):
                sample_id = record_path.stem
                if BASELINE_ID_PATTERN.fullmatch(sample_id):
                    cases.append(sample_id)
            self._json(200, {"source": "MVTec AD bottle", "cases": cases})
            return
        if request.path in {"/api/baseline-case", "/api/baseline-media"}:
            params = parse_qs(request.query)
            sample_ids = params.get("sample_id", [])
            if len(sample_ids) != 1:
                self._json(400, {"error": "invalid_request", "message": "one sample_id is required"})
                return
            try:
                if request.path == "/api/baseline-case":
                    self._json(200, _baseline_case(sample_ids[0]))
                else:
                    kinds = params.get("kind", [])
                    run_ids = params.get("run_id", [])
                    if len(kinds) != 1 or len(run_ids) != 1:
                        raise ValueError("one kind and one run_id are required")
                    self._send(200, _baseline_media(sample_ids[0], kinds[0], run_ids[0]), "image/png")
            except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
                self._json(400, {"error": "invalid_baseline_artifact", "message": str(exc)})
            return
        static = STATIC_FILES.get(request.path) if not request.query else None
        if static is None:
            self._json(404, {"error": "not_found"})
            return
        path, content_type = static
        self._send(200, path.read_bytes(), content_type)

    def do_POST(self) -> None:
        if self.path != "/api/agent-case":
            self._json(404, {"error": "not_found"})
            return
        try:
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("Content-Type must be application/json")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise ValueError("JSON body must be between 1 and 8192 bytes")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or set(body) != {"sample_id", "scenario"}:
                raise ValueError("body must contain only sample_id and scenario")
            result = build_agent_case_result(body["sample_id"], body["scenario"])
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": "invalid_request", "message": str(exc)})
            return
        self._json(200, result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), WorkspaceHandler)
    print(f"Agent workspace: http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
