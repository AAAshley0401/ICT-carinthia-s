"""Local demo endpoint for wiring AgentArts before the real model is ready.

This service never downloads or inspects the supplied image. Every prediction is
simulated and marked as such in the response.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if __package__:
    from .detector_agent import DetectorAgent
else:
    from detector_agent import DetectorAgent


SAMPLES = (
    {
        "grade": "Acceptable",
        "confidence": 0.97,
        "defects": [],
    },
    {
        "grade": "Marginal NG",
        "confidence": 0.63,
        "defects": [
            {
                "category": "scratch",
                "confidence": 0.81,
                "bbox_xyxy": [320, 390, 500, 470],
                "severity": "Marginal NG",
            }
        ],
    },
    {
        "grade": "NG",
        "confidence": 0.88,
        "defects": [
            {
                "category": "particle",
                "confidence": 0.91,
                "bbox_xyxy": [570, 330, 650, 410],
                "severity": "NG",
            }
        ],
    },
    {
        "grade": "Gross NG",
        "confidence": 0.94,
        "defects": [
            {
                "category": "edge_chip",
                "confidence": 0.96,
                "bbox_xyxy": [70, 670, 270, 900],
                "severity": "Gross NG",
            }
        ],
    },
)

FIXTURE_BY_ID = {"W-0301": 0, "W-0304": 1, "W-0307": 2, "W-0312": 3}


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok", "mode": "mock"})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path not in {"/v1/inspect", "/v1/detector"}:
            self._json(404, {"error": "not_found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("JSON body must be between 1 and 65536 bytes")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            if self.path == "/v1/detector":
                sample_id = payload.get("sample_id")
                image_path = payload.get("image_path")
                scenario = payload.get("scenario", "normal")
                if not isinstance(scenario, str):
                    raise ValueError("scenario must be a string")
                detector = DetectorAgent(mode=scenario)
                response = detector.detect(sample_id, image_path)
                self._json(200, response)
                return
            image_url = payload.get("image_url")
            sample_id = payload.get("sample_id")
            if not isinstance(image_url, str) or not image_url.strip():
                raise ValueError("image_url must be a nonempty string")
            if sample_id is not None and (not isinstance(sample_id, str) or not sample_id.strip()):
                raise ValueError("sample_id must be a nonempty string when supplied")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": "invalid_request", "message": str(exc)})
            return

        key = sample_id or image_url
        index = FIXTURE_BY_ID.get(key)
        if index is None:
            index = hashlib.sha256(key.encode("utf-8")).digest()[0] % len(SAMPLES)
        example = SAMPLES[index]
        self._json(
            200,
            {
                "sample_id": sample_id or "demo-sample",
                "mode": "mock",
                "demo_only": True,
                "image_analyzed": False,
                "image_size": {"width": 1024, "height": 1024},
                "grade": example["grade"],
                "confidence": example["confidence"],
                "defects": example["defects"],
                "message": "模拟结果：未读取或分析图片，不得作为实测成绩。",
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock inference API: http://{args.host}:{args.port}/v1/inspect")
    server.serve_forever()


if __name__ == "__main__":
    main()
