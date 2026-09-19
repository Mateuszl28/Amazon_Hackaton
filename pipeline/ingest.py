"""Turn a video (+ subtitles) into a time-indexed timeline.json for the companion.

Windows are processed strictly in order and each call only sees the past, so the
generated descriptions cannot foreshadow: the spoiler fence starts at ingest time.

    python ingest.py --title-id sintel --title "Sintel" \
        --video sintel.mp4 --subs sintel_en.srt \
        --video-url https://.../sintel.mp4
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import llm  # noqa: E402

SYSTEM = """You are building a scene-by-scene knowledge log of a video for a spoiler-free \
viewing companion. You watch it in order, one short window at a time, and you only know what \
has been shown so far. Describe only what is visible or said in THIS window. Never speculate \
about what will happen, who someone "really" is, or how things end.

Characters: reuse an existing id when the same character appears again. For a new character, \
invent a neutral snake_case id from how they look (e.g. "old_man_eyepatch"), never from a name \
you merely suspect. Report a name in name_reveals only when it is clearly said or shown in this \
window. Facts are short things a viewer has now learned about a character."""

WINDOW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "1-2 sentences, what happens in this window"},
        "events": {"type": "array", "items": {"type": "string"}},
        "present_ids": {"type": "array", "items": {"type": "string"}},
        "new_characters": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "label": {"type": "string"},
                           "appearance": {"type": "string"}},
            "required": ["id", "label", "appearance"], "additionalProperties": False}},
        "name_reveals": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
            "required": ["id", "name"], "additionalProperties": False}},
        "facts": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
            "required": ["id", "text"], "additionalProperties": False}},
    },
    "required": ["summary", "events", "present_ids", "new_characters", "name_reveals", "facts"],
    "additionalProperties": False,
}

SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(path: Path) -> list[dict]:
    cues = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig").replace("\r", "")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = SRT_TIME.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                text = re.sub(r"<[^>]+>", "", " ".join(lines[i + 1:])).strip()
                if text:
                    cues.append({"start": round(start, 2), "end": round(end, 2), "text": text})
                break
    return cues


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit("ffmpeg not found: install it (winget install ffmpeg) or `pip install imageio-ffmpeg`")


def probe_duration(video: str) -> float:
    out = subprocess.run([ffmpeg_exe(), "-i", video], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
    if not m:
        sys.exit(f"could not read duration of {video}")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def extract_frames(video: str, every_s: float, out_dir: Path) -> list[tuple[float, Path]]:
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-i", video,
                    "-vf", f"fps=1/{every_s},scale=512:-2", "-q:v", "5",
                    str(out_dir / "f%05d.jpg")], check=True)
    frames = sorted(out_dir.glob("f*.jpg"))
    return [(i * every_s + every_s / 2, p) for i, p in enumerate(frames)]


def analyse_window(start: float, end: float, frames: list[Path], cues: list[dict],
                   characters: list[dict], recent: list[dict]) -> dict:
    roster = [{"id": c["id"], "known_as": c["names"][-1]["name"], "appearance": c["appearance"]}
              for c in characters]
    context = {
        "window": f"{start:.0f}s-{end:.0f}s",
        "characters_so_far": roster,
        "previous_scenes": [s["summary"] for s in recent],
        "dialogue_in_window": [c["text"] for c in cues],
    }
    content: list[dict] = [{"type": "text", "text": json.dumps(context, ensure_ascii=False)}]
    for p in frames:
        content.append(llm.image_block(base64.b64encode(p.read_bytes()).decode()))
    content.append({"type": "text", "text": "Log this window."})
    return json.loads(llm.complete(SYSTEM, content, max_tokens=4096, effort="medium",
                                   schema=WINDOW_SCHEMA))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title-id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--video", required=True, help="local path or URL readable by ffmpeg")
    ap.add_argument("--video-url", help="URL the TV app streams from (defaults to --video)")
    ap.add_argument("--subs", type=Path)
    ap.add_argument("--kind", default="film", choices=["film", "series", "sport"])
    ap.add_argument("--rules", type=Path, help="sport: text file, one rule per line")
    ap.add_argument("--window", type=float, default=40)
    ap.add_argument("--frame-every", type=float, default=8)
    ap.add_argument("--limit-s", type=float, help="only ingest the first N seconds (cheap test run)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--resume", action="store_true",
                    help="continue an interrupted run from the existing timeline.json")
    ap.add_argument("--subs-only", action="store_true",
                    help="no frames, no model calls: timeline with subtitles only (UI/dev testing)")
    ap.add_argument("--duration", type=float, help="seconds; skips probing the video")
    args = ap.parse_args()

    out = args.out or ROOT / "data" / "titles" / args.title_id / "timeline.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.subs_only:
        cues = parse_srt(args.subs) if args.subs else []
        timeline = {
            "title_id": args.title_id, "title": args.title, "kind": args.kind,
            "video_url": args.video_url or args.video,
            "duration_s": args.duration or (cues[-1]["end"] if cues else 0),
            "cues": cues, "segments": [], "characters": [], "rules": [],
        }
        out.write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {out} (subtitles only, {len(cues)} cues)")
        return

    duration = args.duration or probe_duration(args.video)
    horizon = min(duration, args.limit_s or duration)
    cues = parse_srt(args.subs) if args.subs else []

    characters: list[dict] = []
    by_id: dict[str, dict] = {}
    segments: list[dict] = []
    start_at = 0.0
    if args.resume and out.is_file():
        done = json.loads(out.read_text(encoding="utf-8"))
        segments, characters = done.get("segments", []), done.get("characters", [])
        by_id = {c["id"]: c for c in characters}
        start_at = segments[-1]["end"] if segments else 0.0
        print(f"resuming at {start_at:.0f}s ({len(segments)} scenes, {len(characters)} characters)")

    with tempfile.TemporaryDirectory() as tmp:
        print(f"extracting frames every {args.frame_every}s ...")
        frames = extract_frames(args.video, args.frame_every, Path(tmp))
        t = start_at
        while t < horizon:
            end = min(t + args.window, duration)
            win_frames = [p for ft, p in frames if t <= ft < end][:4]
            win_cues = [c for c in cues if t <= c["start"] < end]
            res = analyse_window(t, end, win_frames, win_cues, characters, segments[-3:])

            # Knowledge from a window becomes available when the window ends.
            for nc in res["new_characters"]:
                if nc["id"] not in by_id:
                    ch = {"id": nc["id"], "names": [{"t": t, "name": nc["label"]}],
                          "appearance": nc["appearance"], "facts": []}
                    characters.append(ch)
                    by_id[ch["id"]] = ch
            for r in res["name_reveals"]:
                if r["id"] in by_id and by_id[r["id"]]["names"][-1]["name"] != r["name"]:
                    by_id[r["id"]]["names"].append({"t": end, "name": r["name"]})
            for f in res["facts"]:
                if f["id"] in by_id:
                    by_id[f["id"]]["facts"].append({"t": end, "text": f["text"]})
            present = {i for i in res["present_ids"] if i in by_id} | {n["id"] for n in res["new_characters"]}
            segments.append({"start": t, "end": end, "summary": res["summary"],
                             "characters": sorted(present), "events": res["events"]})
            print(f"[{t:6.0f}s] {res['summary']}")

            timeline = {
                "title_id": args.title_id, "title": args.title, "kind": args.kind,
                "video_url": args.video_url or args.video, "duration_s": round(duration, 2),
                "cues": cues, "segments": segments, "characters": characters,
                "rules": args.rules.read_text(encoding="utf-8").splitlines() if args.rules else [],
            }
            out.write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
            t = end

    print(f"wrote {out} ({len(segments)} scenes, {len(characters)} characters)")


if __name__ == "__main__":
    main()
