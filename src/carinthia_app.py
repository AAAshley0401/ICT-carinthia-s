"""Local Carinthia-S inspect -> review queue -> human decision API.

The service binds to loopback by default. Reviewer names are self-reported;
authentication and AgentArts deployment are separate integration work.
"""

from __future__ import annotations

import argparse
import io
import uuid
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, request, send_file

from .carinthia_inference import CarinthiaPredictor, sha256
from .carinthia_route import route_prediction
from .carinthia_store import CaseStore


def create_app(
    data_root: Path, checkpoint: Path, database: Path,
    artifacts: Path, *, cpu: bool = False,
) -> Flask:
    predictor = CarinthiaPredictor(data_root, checkpoint, artifacts, cpu=cpu)
    store = CaseStore(database)
    app = Flask(__name__)
    app.json.ensure_ascii = False

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "mode": "real_carinthia_model",
                        "model_sha256": predictor.model_sha256})

    @app.get("/carinthia")
    def review_page():
        return send_file(Path(__file__).resolve().parents[1] / "prototype" / "carinthia_review.html")

    @app.post("/api/carinthia/inspect")
    def inspect():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("image_id"), str):
            return jsonify({"error": "image_id is required"}), 400
        image_id = body["image_id"]
        if image_id not in predictor.rows:
            return jsonify({"error": "unknown image_id"}), 404
        case_id = uuid.uuid4().hex
        try:
            prediction = predictor.predict(image_id, case_id)
            route = route_prediction(
                str(prediction["predicted_label"]), float(prediction["class_score"]),
                float(prediction["mask_fraction"]),
            )
        except Exception as exc:
            source_row = predictor.rows[image_id]
            prediction = {
                "case_id": case_id, "image_id": image_id,
                "image_sha256": source_row["image_sha256"],
                "image_hash_verified": False,
                "model_sha256": predictor.model_sha256,
                "predicted_label": None,
                "error": {"type": type(exc).__name__, "message": str(exc)[:500]},
            }
            route = {
                "route": "REVIEW_REQUIRED", "human_review_required": True,
                "reason_codes": ["MODEL_OR_IMAGE_FAILURE"],
                "evidence": {"error": prediction["error"]},
                "production_action_allowed": False,
            }
        store.create_case(prediction, route, case_id=case_id)
        return jsonify({"case_id": case_id, "prediction": prediction, "routing_decision": route}), 201

    @app.get("/api/carinthia/review-queue")
    def review_queue():
        return jsonify({"cases": store.pending_reviews()})

    @app.get("/api/carinthia/cases/<case_id>")
    def get_case(case_id: str):
        try:
            return jsonify(store.get_case(case_id))
        except KeyError:
            return jsonify({"error": "case not found"}), 404

    @app.get("/api/carinthia/cases/<case_id>/mask")
    def get_mask(case_id: str):
        try:
            case = store.get_case(case_id)
        except KeyError:
            return jsonify({"error": "case not found"}), 404
        prediction = case["prediction"]
        path_text = prediction.get("predicted_mask_path")
        if not isinstance(path_text, str):
            return jsonify({"error": "no mask available"}), 404
        path = Path(path_text).resolve()
        if not path.is_relative_to(predictor.artifact_root) or not path.is_file():
            return jsonify({"error": "mask unavailable"}), 404
        if sha256(path) != prediction["predicted_mask_sha256"]:
            return jsonify({"error": "mask hash mismatch"}), 409
        return send_file(path, mimetype="image/png")

    @app.get("/api/carinthia/cases/<case_id>/preview-mask")
    def get_preview_mask(case_id: str):
        try:
            case = store.get_case(case_id)
        except KeyError:
            return jsonify({"error": "case not found"}), 404
        prediction = case["prediction"]
        path_text = prediction.get("predicted_mask_path")
        if not isinstance(path_text, str):
            return jsonify({"error": "no mask available"}), 404
        path = Path(path_text).resolve()
        if not path.is_relative_to(predictor.artifact_root) or not path.is_file():
            return jsonify({"error": "mask unavailable"}), 404
        if sha256(path) != prediction["predicted_mask_sha256"]:
            return jsonify({"error": "mask hash mismatch"}), 409
        mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            return jsonify({"error": "mask unreadable"}), 409
        overlay = np.zeros((*mask.shape, 4), dtype=np.uint8)
        overlay[:, :, 2] = 255  # OpenCV uses BGRA; red is channel 2.
        overlay[:, :, 3] = np.where(mask > 0, 150, 0).astype(np.uint8)
        ok, encoded = cv2.imencode(".png", overlay)
        if not ok:
            return jsonify({"error": "mask preview failed"}), 500
        return send_file(io.BytesIO(encoded.tobytes()), mimetype="image/png")

    @app.get("/api/carinthia/cases/<case_id>/image")
    def get_image(case_id: str):
        try:
            case = store.get_case(case_id)
        except KeyError:
            return jsonify({"error": "case not found"}), 404
        row = predictor.rows.get(case["image_id"])
        if row is None:
            return jsonify({"error": "source image unavailable"}), 404
        path = (predictor.data_root / row["image_path"]).resolve()
        if not path.is_relative_to(predictor.data_root) or not path.is_file():
            return jsonify({"error": "source image unavailable"}), 404
        if sha256(path) != case["image_sha256"]:
            return jsonify({"error": "source image hash mismatch"}), 409
        return send_file(path, mimetype="image/jpeg")

    @app.post("/api/carinthia/cases/<case_id>/reviews")
    def add_review(case_id: str):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "JSON object required"}), 400
        try:
            event = store.add_review(
                case_id,
                reviewer=body.get("reviewer"),
                conclusion=body.get("conclusion"),
                final_label=body.get("final_label"),
                notes=body.get("notes", ""),
            )
            return jsonify({"event": event, "case": store.get_case(case_id)}), 201
        except KeyError:
            return jsonify({"error": "case not found"}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    app = create_app(args.data, args.checkpoint, args.db, args.artifacts, cpu=args.cpu)
    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
