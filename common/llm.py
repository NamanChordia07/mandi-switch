"""Thin, budget-guarded wrapper over the OpenAI API used by Mandi Core and the custom agents.

Rules (see docs/architecture.md):
- The LLM writes words and proposes extractions. Code decides numbers and state, and validates every number
  the LLM returns before it is used or posted.
- A small model (MANDI_OPENAI_MODEL, default gpt-4o-mini) at temperature 0, structured JSON via
  `response_format={"type": "json_schema", "strict": true}`, validated again with Pydantic.
- Budget guards: an on-disk response cache (.state/llm-cache/, so rehearsals repeat for free), a per-process call
  cap (MANDI_LLM_MAX_CALLS), and a usage log with estimated cost (logs/llm-usage.jsonl).
- MANDI_OFFLINE_LLM=1 (or no key) raises LLMUnavailable so callers use their deterministic templates.

(The two Claude Code gate agents don't use this module: Switch Console runs them with the Claude Code provider.)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger("mandi.llm")
T = TypeVar("T", bound=BaseModel)

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".state" / "llm-cache"
USAGE = ROOT / "logs" / "llm-usage.jsonl"
DEFAULT_MODEL = "gpt-4o-mini"
# USD per 1M tokens (input, output) for the estimate in logs/llm-usage.jsonl
PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4.1-mini": (0.40, 1.60), "gpt-5-nano": (0.05, 0.40),
          "gpt-5-mini": (0.25, 2.00)}

_client = None
_lock = threading.Lock()
_calls = 0


class LLMUnavailable(RuntimeError):
    """No API key, offline mode, budget cap reached, or the API failed. Callers fall back to templates."""


def model() -> str:
    return os.environ.get("MANDI_OPENAI_MODEL") or DEFAULT_MODEL


def offline() -> bool:
    return os.environ.get("MANDI_OFFLINE_LLM", "0") == "1" or not os.environ.get("OPENAI_API_KEY")


def client():
    global _client
    if offline():
        raise LLMUnavailable("LLM offline (MANDI_OFFLINE_LLM=1 or OPENAI_API_KEY empty)")
    with _lock:
        if _client is None:
            from openai import OpenAI
            _client = OpenAI(timeout=45.0, max_retries=2)
        return _client


def _key(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def _cached(k: str) -> str | None:
    p = CACHE / f"{k}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))["text"]
        except (json.JSONDecodeError, KeyError):
            return None
    return None


def _store(k: str, text: str) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{k}.json").write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")


def _log_usage(m: str, purpose: str, usage: Any, ms: int) -> None:
    try:
        pin, pout = PRICES.get(m, (0.15, 0.60))
        it = getattr(usage, "prompt_tokens", 0) or 0
        ot = getattr(usage, "completion_tokens", 0) or 0
        USAGE.parent.mkdir(parents=True, exist_ok=True)
        with USAGE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": m, "purpose": purpose,
                                 "in": it, "out": ot, "usd": round(it * pin / 1e6 + ot * pout / 1e6, 6), "ms": ms}) + "\n")
    except Exception:  # never let accounting break the workflow
        pass


def _chat(*, system: str, messages: list[dict[str, Any]], max_tokens: int, purpose: str,
          response_format: dict[str, Any] | None = None) -> str:
    global _calls
    payload = {"m": model(), "s": system, "msgs": messages, "rf": response_format, "mt": max_tokens}
    k = _key(payload)
    hit = _cached(k)
    if hit is not None:
        return hit
    cap = int(os.environ.get("MANDI_LLM_MAX_CALLS", "80"))
    with _lock:
        if _calls >= cap:
            raise LLMUnavailable(f"LLM call cap reached ({cap}) for this process — using templates")
        _calls += 1
    import openai

    c = client()
    t0 = time.time()
    try:
        kwargs: dict[str, Any] = dict(model=model(), temperature=0, max_tokens=max_tokens,
                                      messages=[{"role": "system", "content": system}, *messages])
        if response_format:
            kwargs["response_format"] = response_format
        r = c.chat.completions.create(**kwargs)
    except (openai.APIConnectionError, openai.RateLimitError, openai.APITimeoutError,
            openai.InternalServerError) as exc:
        raise LLMUnavailable(f"OpenAI unavailable: {exc}") from exc
    except openai.APIStatusError as exc:
        raise LLMUnavailable(f"OpenAI error {exc.status_code}: {exc.message}") from exc
    _log_usage(model(), purpose, r.usage, int((time.time() - t0) * 1000))
    choice = r.choices[0]
    if getattr(choice.message, "refusal", None):
        raise LLMUnavailable("model refused")
    text = (choice.message.content or "").strip()
    if text:
        _store(k, text)
    return text


def complete_text(system: str, user: str, *, max_tokens: int = 300, effort: str = "", purpose: str = "text") -> str:
    return _chat(system=system, messages=[{"role": "user", "content": user}], max_tokens=min(max_tokens, 400),
                 purpose=purpose)


def complete_json(system: str, user: str, schema_model: Type[T], schema: dict[str, Any], *,
                  max_tokens: int = 900, effort: str = "", purpose: str = "json") -> T:
    """Structured output against a strict JSON schema, validated again with Pydantic. One retry."""
    rf = {"type": "json_schema", "json_schema": {"name": schema_model.__name__.lower()[:60], "strict": True,
                                                 "schema": schema}}
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    last: Exception | None = None
    for attempt in range(2):
        raw = _chat(system=system, messages=messages, max_tokens=min(max_tokens, 1200), purpose=purpose,
                    response_format=rf)
        try:
            return schema_model.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            last = exc
            log.warning("LLM JSON failed validation (attempt %d): %s", attempt + 1, exc)
            messages = messages + [{"role": "assistant", "content": raw},
                                   {"role": "user", "content": f"That failed validation: {exc}. Return corrected JSON."}]
    raise LLMUnavailable(f"LLM output never validated: {last}")


def spend() -> dict[str, Any]:
    """Total estimated spend recorded in logs/llm-usage.jsonl."""
    total, calls = 0.0, 0
    if USAGE.exists():
        for line in USAGE.read_text(encoding="utf-8").splitlines():
            try:
                total += json.loads(line)["usd"]
                calls += 1
            except (json.JSONDecodeError, KeyError):
                pass
    return {"calls": calls, "usd": round(total, 4)}
