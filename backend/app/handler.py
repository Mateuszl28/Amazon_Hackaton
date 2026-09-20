"""AWS Lambda entry point (API Gateway HTTP API / Function URL, payload v2).

GET  /titles                 -> catalog
POST /ask                    -> {title_id, position_s, mode: who|explain|recap|ask,
                                 question?, frame_jpeg_b64?, from_s?}
"""
from __future__ import annotations

import base64
import json
import logging
import time

from . import store
from .companion import answer

log = logging.getLogger()
log.setLevel(logging.INFO)

MODES = {"who", "explain", "recap", "ask"}


def _resp(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(body, ensure_ascii=False)}


def route(method: str, path: str, body: dict) -> tuple[int, dict]:
    if method == "GET" and path == "/titles":
        return 200, {"titles": store.catalog()}
    if method == "POST" and path == "/ask":
        mode = body.get("mode", "ask")
        if mode not in MODES:
            return 400, {"error": f"mode must be one of {sorted(MODES)}"}
        try:
            title_id, pos = str(body["title_id"]), float(body["position_s"])
        except (KeyError, TypeError, ValueError):
            return 400, {"error": "title_id and position_s are required"}
        try:
            tl = store.timeline(title_id)
        except KeyError:
            return 404, {"error": f"unknown title {title_id}"}
        t0 = time.perf_counter()
        audience = "kid" if body.get("audience") == "kid" else "adult"
        out = answer(tl, pos, mode, body.get("question", ""), body.get("frame_jpeg_b64"),
                     body.get("from_s"), audience)
        log.info(json.dumps({"mode": mode, "pos": pos, "audience": audience, "ms": int((time.perf_counter() - t0) * 1000)}))
        return 200, out
    if method == "GET" and path == "/health":
        return 200, {"ok": True}
    return 404, {"error": "not found"}


def lambda_handler(event, _context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return _resp(400, {"error": "invalid json"})
    status, out = route(method, path, body)
    return _resp(status, out)
