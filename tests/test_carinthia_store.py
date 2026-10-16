"""Check that human conclusions persist and event tampering is detected."""

import sqlite3

import pytest

from src.carinthia_store import CaseStore


def test_review_history_and_hash_chain(tmp_path):
    store = CaseStore(tmp_path / "cases.sqlite3")
    prediction = {
        "image_id": "sample-1", "image_sha256": "a" * 64,
        "model_sha256": "b" * 64, "predicted_label": "2",
    }
    route = {"route": "REVIEW_REQUIRED", "reason_codes": ["LOW_CLASS_SCORE"]}
    case_id = store.create_case(prediction, route)
    assert [item["case_id"] for item in store.pending_reviews()] == [case_id]

    store.add_review(case_id, reviewer="reviewer A", conclusion="CORRECT_CLASS",
                     final_label="1", notes="Image evidence")
    store.add_review(case_id, reviewer="reviewer B", conclusion="UNSURE",
                     final_label=None, notes="Second opinion needed")
    case = store.get_case(case_id)
    assert case["status"] == "REVIEWED"
    assert [event["event_type"] for event in case["events"]] == [
        "MODEL_ROUTING", "HUMAN_REVIEW", "HUMAN_REVIEW",
    ]
    assert case["events"][1]["payload"]["final_label"] == "1"
    assert case["event_chain_valid"]
    assert store.pending_reviews() == []

    with sqlite3.connect(tmp_path / "cases.sqlite3") as db:
        db.execute("UPDATE events SET payload_json='{}' WHERE case_id=? AND sequence=2", (case_id,))
    with pytest.raises(ValueError, match="Broken event hash chain"):
        store.get_case(case_id)
