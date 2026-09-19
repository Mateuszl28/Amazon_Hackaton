"""Timeline storage: local directory for dev, S3 in AWS (DATA_BUCKET)."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

DATA_BUCKET = os.environ.get("DATA_BUCKET")
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data" / "titles"))


def _read(key: str) -> dict:
    if DATA_BUCKET:
        import boto3
        body = boto3.client("s3").get_object(Bucket=DATA_BUCKET, Key=f"titles/{key}")["Body"].read()
        return json.loads(body)
    return json.loads((DATA_DIR / key).read_text(encoding="utf-8"))


@lru_cache(maxsize=32)
def timeline(title_id: str) -> dict:
    if not title_id.replace("-", "").replace("_", "").isalnum():
        raise KeyError(title_id)
    try:
        return _read(f"{title_id}/timeline.json")
    except Exception as e:  # missing file or S3 key
        raise KeyError(title_id) from e


def catalog() -> list[dict]:
    if DATA_BUCKET:
        return _read("catalog.json")["titles"]
    out = []
    for p in sorted(DATA_DIR.glob("*/timeline.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        out.append({k: t.get(k) for k in ("title_id", "title", "kind", "video_url", "duration_s", "poster_url")})
    return out
