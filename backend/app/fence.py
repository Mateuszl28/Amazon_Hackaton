"""Spoiler fence: builds the knowledge view of a title as of playback position T.

The model never sees anything that happens after T. That guarantee lives here,
in plain code, instead of in a "please don't spoil" prompt.

Timeline schema (produced by pipeline/ingest.py):
{
  "title_id": str, "title": str, "kind": "film" | "series" | "sport",
  "video_url": str, "duration_s": float,
  "cues":      [{"start": s, "end": s, "text": str}],            # subtitles
  "segments":  [{"start": s, "end": s, "summary": str,
                 "characters": [char_id], "events": [str]}],
  "characters": [{"id": str,
                  "names": [{"t": s, "name": str}],               # label -> real name reveals
                  "appearance": str,
                  "facts": [{"t": s, "text": str}]}],
  "rules": [str]                                                   # sport only, not time-bound
}
"""
from __future__ import annotations

from dataclasses import dataclass, field

LIVE_WINDOW_S = 90  # verbatim dialogue kept for "what just happened" questions


@dataclass
class CharacterView:
    id: str
    ref: str  # opaque handle shown to the model; stored ids may hint at a name
    name: str
    appearance: str
    first_seen: float
    last_seen: float | None
    facts: list[dict] = field(default_factory=list)
    appearances: list[float] = field(default_factory=list)  # scene starts, all <= position


@dataclass
class FencedView:
    title: str
    duration_s: float
    kind: str
    position_s: float
    segments: list[dict]
    live_dialogue: list[dict]
    characters: list[CharacterView]
    rules: list[str]

    def to_prompt(self) -> str:
        lines = [f"# {self.title} ({self.kind}) — viewer is at {fmt_ts(self.position_s)}", ""]
        if self.rules:
            lines.append("## Rules reference")
            lines += [f"- {r}" for r in self.rules]
            lines.append("")
        lines.append("## Characters known so far")
        if not self.characters:
            lines.append("(none yet)")
        for c in self.characters:
            seen = f"first seen {fmt_ts(c.first_seen)}"
            if c.last_seen is not None:
                seen += f", last seen {fmt_ts(c.last_seen)}"
            lines.append(f"- **{c.name}** [{c.ref}] ({seen}). Looks like: {c.appearance}")
            lines += [f"  - {fmt_ts(f['t'])}: {f['text']}" for f in c.facts]
        lines += ["", "## Story so far (scene by scene)"]
        for s in self.segments:
            ev = f" Events: {'; '.join(s['events'])}." if s.get("events") else ""
            lines.append(f"- [{fmt_ts(s['start'])}–{fmt_ts(s['end'])}] {s['summary']}{ev}")
        lines += ["", "## Dialogue in the last ~90 seconds"]
        lines += [f"[{fmt_ts(c['start'])}] {c['text']}" for c in self.live_dialogue] or ["(silence)"]
        return "\n".join(lines)


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def name_at(char: dict, t: float) -> str | None:
    """Latest name revealed at or before t (a stranger stays 'hooded stranger' until unmasked)."""
    revealed = [n for n in char.get("names", []) if n["t"] <= t]
    return max(revealed, key=lambda n: n["t"])["name"] if revealed else None


def build_view(timeline: dict, position_s: float) -> FencedView:
    t = max(0.0, float(position_s))

    segments = [s for s in timeline.get("segments", []) if s["end"] <= t]
    live = [c for c in timeline.get("cues", []) if c["start"] <= t and c["start"] >= t - LIVE_WINDOW_S]

    # The in-progress scene counts for "who is on screen" (the viewer can see them),
    # but its summary stays hidden until the scene ends.
    appearances: dict[str, list[float]] = {}
    for s in (s for s in timeline.get("segments", []) if s["start"] <= t):
        for cid in s.get("characters", []):
            appearances.setdefault(cid, []).append(s["start"])

    characters = []
    for ch in timeline.get("characters", []):
        name = name_at(ch, t)
        facts = sorted((f for f in ch.get("facts", []) if f["t"] <= t), key=lambda f: f["t"])
        seen = appearances.get(ch["id"], [])
        if name is None or (not seen and not facts):
            continue
        first = min(seen + [f["t"] for f in facts])
        characters.append(CharacterView(
            id=ch["id"], ref="", name=name, appearance=ch.get("appearance", ""),
            first_seen=first, last_seen=max(seen) if seen else None, facts=facts,
            appearances=sorted(seen),
        ))
    characters.sort(key=lambda c: c.first_seen)
    for i, c in enumerate(characters, 1):
        c.ref = f"c{i}"

    return FencedView(
        title=timeline.get("title", timeline.get("title_id", "?")),
        duration_s=float(timeline.get("duration_s") or 0),
        kind=timeline.get("kind", "film"),
        position_s=t,
        segments=segments,
        live_dialogue=live,
        characters=characters,
        rules=timeline.get("rules", []),
    )


def recap_window(view: FencedView, from_s: float) -> list[dict]:
    """Segments the viewer missed between from_s and the current position."""
    return [s for s in view.segments if s["end"] > from_s]
