"""Question answering on top of the fenced view."""
from __future__ import annotations

import json
import re

from . import llm
from .fence import build_view, fmt_ts, name_at, recap_window

SYSTEM = """You are the viewing companion inside a TV app. The viewer pressed a button on \
their remote mid-show; your answer appears in a small overlay beside the video.

You only know what the viewer has already watched. The knowledge you are given ends at \
their current position; nothing later exists for you. Never guess, hint at, or foreshadow \
future events, identities, deaths, twists or outcomes. If the honest answer is "that hasn't \
been revealed yet", say so warmly and, if helpful, say what IS known so far.

You may recognise this title from your own training. Ignore everything you know about it. \
Every claim you make must be traceable to the scene log, the dialogue or the frame you are \
given here — names, relationships, events, all of it. If a detail is not in what you were \
handed, it has not happened for this viewer, no matter how sure you feel.

Style for a TV overlay: at most 3 short sentences (about 60 words), plain language, no \
markdown. Timestamps like "at 4:10" are welcome when they help. Answer in the language of \
the question; default to English when no question text is given.

For sport: explain calls and rules for a newcomer, using the rules reference and what \
happened on screen; never mention the final score or later plays.

If the viewer asks to go back to something ("take me back to when they met", "replay the fight"), \
put that scene's timestamp in seek_to and keep the answer to one line naming what happens there. \
Only scenes they have already watched can be jumped to; when you cannot find it in what they have \
seen, say so and leave seek_to at -1."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "2-5 word overlay title"},
        "answer": {"type": "string"},
        "character_id": {"type": "string", "description": "[cN] handle of the character the answer is about, or empty"},
        "moments": {"type": "array", "items": {"type": "number"},
                    "description": "up to 5 timestamps in seconds, from the story so far, that the answer relies on"},
        "seek_to": {"type": "number",
                    "description": "when the viewer asks to go back to a moment, the timestamp in "
                                   "seconds to jump to (inside what they have already seen); "
                                   "-1 when they are not asking to jump"},
    },
    "required": ["headline", "answer", "character_id", "moments", "seek_to"],
    "additionalProperties": False,
}

MODE_PROMPTS = {
    "who": "Who is the person/character in focus on screen right now? If several, the most prominent one.",
    "explain": "Explain what just happened on screen and why it matters.",
    "ask": "{question}",
}


def answer(timeline: dict, position_s: float, mode: str, question: str = "",
           frame_jpeg_b64: str | None = None, from_s: float | None = None) -> dict:
    view = build_view(timeline, position_s)
    content: list[dict] = [{"type": "text", "text": view.to_prompt()}]

    start = None
    if mode == "recap":
        start = max(0.0, min(from_s if from_s is not None else view.position_s - 300, view.position_s))
        missed = recap_window(view, start)
        ask = (f"The viewer missed {fmt_ts(start)}–{fmt_ts(view.position_s)} (they skipped ahead, stepped "
               f"away, or are resuming). Summarise only that part ({len(missed)} scenes) so they can "
               f"keep watching; for a resume from 0:00, give a short 'previously' recap.")
    else:
        ask = MODE_PROMPTS.get(mode, "{question}").format(question=question or "What is going on?")
        if question and mode != "ask":
            ask += f"\nViewer's words: {question}"

    if frame_jpeg_b64:
        content.append({"type": "text", "text": "Current frame on the viewer's screen:"})
        content.append(llm.image_block(frame_jpeg_b64))
    content.append({"type": "text", "text": ask})

    try:
        if llm.PROVIDER == "mock":
            data = _mock_answer(view, mode, question, start)
        else:
            data = json.loads(llm.complete(SYSTEM, content, schema=ANSWER_SCHEMA))
    except llm.Refused:
        data = {"headline": "Hmm", "answer": "I can't help with that one.", "character_id": "",
                "moments": [], "seek_to": -1}

    _redact_future_names(timeline, view, data)

    known = {c.ref: c for c in view.characters}
    ch = known.get(data.get("character_id", ""))
    data["character"] = {"id": ch.ref, "name": ch.name, "first_seen": ch.first_seen} if ch else None
    data["position_s"] = view.position_s
    data["duration_s"] = view.duration_s
    data["markers"] = _markers(view, ch, data.pop("moments", []))
    data["seek_to"] = _seek_target(view, data.pop("seek_to", -1))
    data["range"] = {"from": start, "to": view.position_s} if start is not None else None
    return data


def _redact_future_names(timeline: dict, view, data: dict) -> None:
    """Last line of defence, in code.

    The model may know the film from its own training — or read the name off the title
    ("Sintel") — and use a name the viewer hasn't heard yet. We know exactly which names are
    still unrevealed, so we swap them back for what the viewer currently calls that character.
    """
    known_by_id = {c.id: c.name for c in view.characters}
    for ch in timeline.get("characters", []):
        current = name_at(ch, view.position_s)
        for entry in ch.get("names", []):
            if entry["t"] <= view.position_s:
                continue
            # Prefer the label the viewer already uses; otherwise stay neutral and natural —
            # the character may well be on screen right now, just not introduced yet.
            stand_in = known_by_id.get(ch["id"], current) or "the person on screen"
            pattern = re.compile(rf"\b{re.escape(entry['name'])}\b", re.IGNORECASE)
            for field in ("answer", "headline"):
                if field in data and isinstance(data[field], str):
                    data[field] = pattern.sub(stand_in, data[field])


def _seek_target(view, seek_to) -> float | None:
    """Jumping is fenced too: the viewer can only be sent back into what they have seen."""
    if isinstance(seek_to, bool) or not isinstance(seek_to, (int, float)):
        return None
    return float(seek_to) if 0 <= seek_to <= view.position_s else None


def _markers(view, character, moments: list) -> list[dict]:
    """Timeline dots for the overlay. The fence applies here too: nothing after the position."""
    pos = view.position_s
    out = {}
    if character:
        out.update({round(t, 1): "appearance" for t in character.appearances})
    for t in moments[:5]:
        if isinstance(t, (int, float)) and 0 <= t <= pos:
            out.setdefault(round(float(t), 1), "moment")
    return [{"t": t, "kind": k} for t, k in sorted(out.items()) if t <= pos]


def _mock_answer(view, mode: str, question: str, start: float | None) -> dict:
    """LLM_PROVIDER=mock: exercise the app end to end without model access."""
    last = view.live_dialogue[-1]["text"] if view.live_dialogue else "(no dialogue yet)"
    scope = f"Recap of {fmt_ts(start)}–{fmt_ts(view.position_s)}. " if start is not None else ""
    return {
        "headline": f"Mock · {mode}",
        "answer": (f"{scope}{question + ' — ' if question else ''}I can see {len(view.segments)} finished "
                   f"scenes, {len(view.characters)} characters and the last line \"{last}\"."),
        "character_id": view.characters[-1].ref if view.characters else "",
        "seek_to": view.segments[-1]["start"] if view.segments else -1,
        # dialogue lines the viewer has heard stand in for the model's cited moments
        "moments": [c["start"] for c in view.live_dialogue][-5:],
    }
