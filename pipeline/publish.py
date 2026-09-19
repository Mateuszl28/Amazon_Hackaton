"""Upload data/titles/*/timeline.json and a catalog.json to the backend's S3 bucket.

    python publish.py --bucket <DataBucketName from `sam deploy`>
    python publish.py --dry-run            # only print what would be uploaded
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_KEYS = ("title_id", "title", "kind", "video_url", "duration_s", "poster_url")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data" / "titles")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.bucket and not args.dry_run:
        ap.error("--bucket is required unless --dry-run")

    uploads: list[tuple[str, bytes]] = []
    catalog = []
    for path in sorted(args.data_dir.glob("*/timeline.json")):
        timeline = json.loads(path.read_text(encoding="utf-8"))
        catalog.append({k: timeline.get(k) for k in CATALOG_KEYS})
        uploads.append((f"titles/{timeline['title_id']}/timeline.json", path.read_bytes()))
    uploads.append(("titles/catalog.json", json.dumps({"titles": catalog}, ensure_ascii=False).encode()))

    for key, body in uploads:
        print(f"{'would upload' if args.dry_run else 'uploading'} s3://{args.bucket or '<bucket>'}/{key} ({len(body)} B)")
    if args.dry_run:
        return

    import boto3
    s3 = boto3.client("s3")
    for key, body in uploads:
        s3.put_object(Bucket=args.bucket, Key=key, Body=body, ContentType="application/json")
    print(f"published {len(catalog)} titles")


if __name__ == "__main__":
    main()
