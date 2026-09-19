"""Does the spoiler fence actually hold? Measures it instead of claiming it.

Two arms answer the same questions at the same playback positions:

  fenced    our backend: the model only ever receives the story up to T
  baseline  a normal assistant: the whole plot in context, plus "please don't spoil"

A third call judges each answer against the part of the story that comes AFTER T,
and reports how often each arm leaked.

    python leak_test.py --title-id sintel --probes 6
    python leak_test.py --title-id sintel --probes 2 --arms fenced   # cheap smoke run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import llm, store  # noqa: E402
from app.companion import SYSTEM as COMPANION_SYSTEM, answer as fenced_answer  # noqa: E402
from app.fence import build_view, fmt_ts, name_at  # noqa: E402

# Questions a viewer would actually ask, plus ones that fish for the ending.
PROBES = [
    ("neutral", "Who is the character on screen right now?"),
    ("neutral", "What is going on in this scene?"),
    ("bait", "What happens next?"),
    ("bait", "How does this story end?"),
    ("bait", "Does the main character survive?"),
    ("bait", "Who is the real villain here, and what is their secret?"),
]

BASELINE_SYSTEM = """You are a viewing companion inside a TV app. The viewer is watching and \
asks you a question. Answer in at most 3 short sentences. Please avoid spoilers about what \
happens later in the story."""

JUDGE_SYSTEM = """You check whether an answer spoiled a story.

You get: the part of the story the viewer has ALREADY seen, the part they have NOT seen yet, \
and an answer given to them. Decide whether the answer reveals, hints at, or strongly implies \
anything from the not-yet-seen part: later events, outcomes, deaths, twists, identities or \
names that are only revealed later.

Refusing to answer, or saying "that hasn't been revealed yet", is NOT a leak. Restating what \
the viewer has already seen is NOT a leak. Vague genre talk ("things get tense") is NOT a leak \
unless it points at a specific later event."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "leaked": {"type": "boolean"},
        "evidence": {"type": "string", "description": "the phrase that leaked, or empty"},
    },
    "required": ["leaked", "evidence"],
    "additionalProperties": False,
}


def future_text(timeline: dict, t: float) -> str:
    """Everything the viewer has NOT seen yet — the judge's yardstick."""
    lines = [f"- [{fmt_ts(s['start'])}] {s['summary']}"
             for s in timeline.get("segments", []) if s["end"] > t]
    for ch in timeline.get("characters", []):
        later_names = [n for n in ch.get("names", []) if n["t"] > t]
        for n in later_names:
            lines.append(f"- [{fmt_ts(n['t'])}] {name_at(ch, t) or 'someone'} turns out to be {n['name']}")
        lines += [f"- [{fmt_ts(f['t'])}] {f['text']}"
                  for f in ch.get("facts", []) if f["t"] > t]
    return "\n".join(lines) or "(nothing — the viewer is at the end)"


def baseline_answer(timeline: dict, t: float, question: str) -> str:
    """A normal assistant: full plot in context, politely asked not to spoil."""
    whole = build_view(timeline, timeline.get("duration_s", 1e9)).to_prompt()
    content = [
        {"type": "text", "text": f"The show the viewer is watching:\n{whole}"},
        {"type": "text", "text": f"The viewer is {fmt_ts(t)} into it and asks: {question}"},
    ]
    return llm.complete(BASELINE_SYSTEM, content, max_tokens=512)


def judge(seen: str, unseen: str, question: str, text: str) -> dict:
    content = [{"type": "text", "text": f"ALREADY SEEN:\n{seen}\n\nNOT SEEN YET:\n{unseen}\n\n"
                                        f"QUESTION: {question}\nANSWER: {text}"}]
    return json.loads(llm.complete(JUDGE_SYSTEM, content, max_tokens=512, effort="medium",
                                   schema=JUDGE_SCHEMA))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title-id", default="sintel")
    ap.add_argument("--probes", type=int, default=6, help="playback positions to test")
    ap.add_argument("--arms", nargs="+", default=["fenced", "baseline"], choices=["fenced", "baseline"])
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "leak_report.md")
    args = ap.parse_args()

    if llm.PROVIDER == "mock":
        sys.exit("LLM_PROVIDER=mock measures nothing here — point it at Bedrock first.")

    timeline = store.timeline(args.title_id)
    if not timeline.get("segments"):
        sys.exit(f"{args.title_id} has no scenes yet — run pipeline/ingest.py first.")
    duration = timeline["duration_s"]
    # Probe inside the story, never at the very start or the very end.
    points = [duration * (i + 1) / (args.probes + 1) for i in range(args.probes)]

    rows, leaks = [], {arm: 0 for arm in args.arms}
    for t in points:
        seen = build_view(timeline, t).to_prompt()
        unseen = future_text(timeline, t)
        for kind, question in PROBES:
            for arm in args.arms:
                text = (fenced_answer(timeline, t, "ask", question)["answer"] if arm == "fenced"
                        else baseline_answer(timeline, t, question))
                verdict = judge(seen, unseen, question, text)
                leaks[arm] += verdict["leaked"]
                rows.append({"t": t, "kind": kind, "question": question, "arm": arm,
                             "answer": text, **verdict})
                print(f"[{fmt_ts(t)}] {arm:8} {'LEAK' if verdict['leaked'] else 'ok  '} {question}")

    total = len(points) * len(PROBES)
    lines = [f"# Spoiler leak test — {timeline.get('title', args.title_id)}", "",
             f"{date.today()} · {len(points)} positions × {len(PROBES)} questions "
             f"({total} per arm) · model `{llm.MODEL}`", "",
             "| arm | leaks | questions | leak rate |", "|---|---|---|---|"]
    for arm in args.arms:
        lines.append(f"| {arm} | {leaks[arm]} | {total} | {leaks[arm] / total:.0%} |")
    lines += ["", "## Leaks", ""]
    leaked_rows = [r for r in rows if r["leaked"]]
    for r in leaked_rows:
        lines.append(f"- **{r['arm']}** at {fmt_ts(r['t'])} — *{r['question']}* → “{r['evidence']}”")
    if not leaked_rows:
        lines.append("None.")
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.out.with_suffix(".json")).write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
    print(f"\n{args.out}")
    for arm in args.arms:
        print(f"  {arm:8} {leaks[arm]}/{total} leaked")


if __name__ == "__main__":
    main()
