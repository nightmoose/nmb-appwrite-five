"""Appwrite Function entrypoint for the public storefront API.

Configuration comes only from function environment variables (set by
scripts/deploy_appwrite.py through the Appwrite API). ALLOWED_ORIGINS is a
comma-separated list of origins that may call this function from a browser.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from nmb_five.cloud_api import appwrite_api  # noqa: E402

_API = None


def _cors(origin):
    allowed = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    h = {"Vary": "Origin", "Cache-Control": "no-store"}
    if origin and origin in allowed:
        h.update({"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                  "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "600"})
    return h


def main(context):
    global _API
    req = context.req
    headers = {k.lower(): v for k, v in (req.headers or {}).items()}
    cors = _cors(headers.get("origin", ""))
    if req.method == "OPTIONS":
        return context.res.text("", 204, cors)
    try:
        if _API is None:
            _API = appwrite_api()
        try:
            body = json.loads(req.body_text or "{}") if req.method == "POST" else {}
        except ValueError:
            return context.res.json({"error": "bad json"}, 400, cors)
        ip = (headers.get("x-forwarded-for", "").split(",")[0].strip() or headers.get("x-real-ip", ""))
        status, obj = _API.route(req.method, req.path or "/", dict(req.query or {}), body, ip)
        return context.res.text(json.dumps(obj, default=str), status, dict(cors, **{"Content-Type": "application/json"}))
    except Exception as exc:  # never leak internals
        context.error(f"{type(exc).__name__}: {exc}")
        return context.res.json({"error": "internal error"}, 500, cors)
