"""Local HTTP wrapper around DetectorAgent; no image is read or analyzed."""

from __future__ import annotations

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if __package__:
    from .detector_agent import DetectorAgent
else:
    from detector_agent import DetectorAgent


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
            image_path = payload.get("image_path") if self.path == "/v1/detector" else payload.get("image_url")
            sample_id = payload.get("sample_id")
            if sample_id is None and isinstance(image_path, str) and image_path.strip():
                sample_id = "demo-" + hashlib.sha256(image_path.encode("utf-8")).hexdigest()[:12]
            scenario = payload.get("scenario", "normal")
            if not isinstance(scenario, str):
                raise ValueError("scenario must be a string")
            response = DetectorAgent(mode=scenario).detect(sample_id, image_path)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": "invalid_request", "message": str(exc)})
            return
        self._json(200, response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock detector API: http://{args.host}:{args.port}/v1/detector")
    server.serve_forever()


if __name__ == "__main__":
    main()
