"""Model access behind one `complete()` call.

LLM_PROVIDER picks the backend:
  bedrock    Claude on Amazon Bedrock (default; what the submission should ship with)
  anthropic  Claude on the first-party API
  gemini     Google Gemini via AI Studio — free tier, used while AWS billing is pending
  mock       canned answers, no network (see companion.py)

Callers pass provider-neutral content blocks ({"type": "text"|"image"}), so switching
providers is one environment variable.
"""
from __future__ import annotations

import base64
import os
import random
import time
from functools import lru_cache
from pathlib import Path

DEFAULT_MODELS = {
    "bedrock": "anthropic.claude-opus-5",
    "anthropic": "claude-opus-5",
    "gemini": "gemini-3.6-flash",
}


def _load_env_file() -> None:
    """Dev convenience: .env.local at the repo root (gitignored) holds keys and provider."""
    path = Path(__file__).resolve().parents[2] / ".env.local"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_env_file()

PROVIDER = os.environ.get("LLM_PROVIDER", "bedrock")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL = os.environ.get("LLM_MODEL", DEFAULT_MODELS.get(PROVIDER, "claude-opus-5"))


class Refused(Exception):
    """The model declined to answer."""


@lru_cache(maxsize=1)
def client():
    if PROVIDER == "gemini":
        from google import genai
        return genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    import anthropic
    if PROVIDER == "bedrock":
        return anthropic.AnthropicBedrockMantle(aws_region=AWS_REGION)
    return anthropic.Anthropic()


def complete(system: str, content: list[dict], *, max_tokens: int = 1024,
             effort: str = "low", schema: dict | None = None) -> str:
    """One call, returns the text (JSON when `schema` is given)."""
    if PROVIDER == "gemini":
        return _gemini(system, content, max_tokens, schema)
    return _claude(system, content, max_tokens, effort, schema)


def _claude(system: str, content: list[dict], max_tokens: int, effort: str,
            schema: dict | None) -> str:
    output_config: dict = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    resp = client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        output_config=output_config,
    )
    if resp.stop_reason == "refusal":
        raise Refused(getattr(resp.stop_details, "explanation", None) or "refused")
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _gemini(system: str, content: list[dict], max_tokens: int, schema: dict | None) -> str:
    from google.genai import types
    parts = [
        types.Part.from_text(text=b["text"]) if b["type"] == "text"
        else types.Part.from_bytes(data=base64.b64decode(b["source"]["data"]), mime_type="image/jpeg")
        for b in content
    ]
    # Gemini 3 spends part of max_output_tokens on internal reasoning, which truncated
    # JSON answers mid-string; keep reasoning minimal and leave room for the reply.
    config = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max(max_tokens, 2048),
        thinking_config=types.ThinkingConfig(thinking_level="low"),
        response_mime_type="application/json" if schema else "text/plain",
        response_json_schema=_gemini_schema(schema),
    )
    resp = _with_backoff(lambda: client().models.generate_content(
        model=MODEL, contents=parts, config=config))
    text = (resp.text or "").strip()
    finish = getattr((resp.candidates or [None])[0], "finish_reason", None)
    if str(finish).endswith("MAX_TOKENS"):
        raise Refused(f"answer truncated at {max_tokens} tokens")
    if not text:
        raise Refused(str(getattr(resp, "prompt_feedback", "") or f"empty response ({finish})"))
    return text


def _gemini_schema(schema: dict | None):
    """Gemini rejects some JSON Schema keywords Claude accepts (e.g. additionalProperties)."""
    if schema is None:
        return None
    if isinstance(schema, dict):
        return {k: _gemini_schema(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [_gemini_schema(v) for v in schema]
    return schema


def _with_backoff(call, attempts: int = 5):
    """The free tier rate-limits by the minute; wait it out instead of failing a long ingest."""
    for attempt in range(attempts):
        try:
            return call()
        except Exception as e:
            transient = any(s in str(e) for s in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
            if not transient or attempt == attempts - 1:
                raise
            time.sleep(min(60, 2 ** attempt * 5) + random.uniform(0, 2))


def image_block(jpeg_b64: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": jpeg_b64}}
