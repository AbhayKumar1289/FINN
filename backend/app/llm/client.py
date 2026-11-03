"""Gemini client with model routing, a response cache and cost logging.

Routing: "cheap" (flash-lite) for bulk extraction, "strong" (flash) for escalation and
reasoning. Every call is keyed by a hash of model + prompt + attachments + schema; a repeat
is served from the llm_calls table at zero cost, so re-running the pipeline is free."""
import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LLMCall

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# USD per 1M tokens (input, output), list prices used for the cost log. On the free tier the
# real spend is zero; the log still shows what the same workload would cost when paid.
PRICES = {"flash-lite": (0.10, 0.40), "flash": (0.30, 2.50), "pro": (1.25, 10.00)}


class LLMError(RuntimeError):
    pass


class QuotaError(LLMError):
    """Out of quota for this model (typically the free tier's daily cap): retrying won't help."""


class UnavailableError(LLMError):
    """The model kept answering 500/503 ("high demand") through every retry."""


@dataclass
class LLMResult:
    data: object            # parsed JSON when a schema was given, else text
    model: str
    cached: bool
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    sources: list = field(default_factory=list)  # [{title, uri}] from search grounding
    fallback: bool = False  # served by the cheap model because the strong one was out of quota


def model_for(tier: str) -> str:
    return {"cheap": settings.model_cheap, "strong": settings.model_strong}[tier]


def _price(model: str) -> tuple[float, float]:
    for key in ("flash-lite", "flash", "pro"):  # most specific first
        if key in model:
            return PRICES[key]
    return PRICES["flash"]


def pdf_part(data: bytes) -> dict:
    return {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(data).decode()}}


def _cache_key(model: str, system: str | None, parts: list, schema: dict | None, search: bool) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({"m": model, "s": system, "schema": schema, "search": search}, sort_keys=True).encode())
    for p in parts:
        if "inline_data" in p:  # hash the attachment, not its base64 text
            h.update(hashlib.sha256(p["inline_data"]["data"].encode()).digest())
        else:
            h.update(json.dumps(p, sort_keys=True).encode())
    return h.hexdigest()


def _retry_after(r: httpx.Response) -> float | None:
    """Seconds Gemini asks us to wait (RetryInfo), or None when it gives no hint."""
    try:
        for d in r.json()["error"].get("details", []):
            if d.get("@type", "").endswith("RetryInfo"):
                return float(str(d.get("retryDelay", "")).rstrip("s") or 0)
    except Exception:
        pass
    return None


def _post(model: str, body: dict) -> dict:
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set")
    delay = 4.0
    for attempt in range(4):
        r = httpx.post(API.format(model=model), json=body, timeout=180,
                       headers={"x-goog-api-key": settings.gemini_api_key})
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            wait = _retry_after(r)
            if wait is not None and wait <= 20 and attempt < 3:  # per-minute limit: worth waiting
                log.warning("gemini %s rate-limited; waiting %.0fs", model, wait)
                time.sleep(wait + 1)
                continue
            raise QuotaError(f"gemini {model} quota exhausted: {r.text[:200]}")
        if r.status_code in (500, 503) and attempt < 3:
            log.warning("gemini %s %s; retrying in %.0fs", model, r.status_code, delay)
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code in (500, 503):
            raise UnavailableError(f"gemini {model} {r.status_code}: {r.text[:300]}")
        raise LLMError(f"gemini {model} {r.status_code}: {r.text[:300]}")
    raise LLMError("unreachable")


def generate(db: Session, task: str, parts: list, *, tier: str = "cheap", system: str | None = None,
             schema: dict | None = None, search: bool = False,
             thinking: str | None = None) -> LLMResult:
    """thinking="low" caps reasoning tokens for transcription-style tasks, where thinking is
    pure cost (it was ~85% of the strong model's output tokens on results extraction).

    If the strong model is out of quota or overloaded, degrade to the cheap one instead of
    failing the feature: a slightly weaker answer beats an error card in a live demo."""
    try:
        return _generate(db, task, parts, model_for(tier), system, schema, search, thinking)
    except (QuotaError, UnavailableError) as exc:
        if tier != "strong":
            raise
        log.warning("strong model unusable for %s (%s); falling back to %s", task, type(exc).__name__,
                    settings.model_cheap)
        res = _generate(db, task, parts, settings.model_cheap, system, schema, search, thinking)
        res.fallback = True
        return res


def _generate(db: Session, task: str, parts: list, model: str, system: str | None,
              schema: dict | None, search: bool, thinking: str | None) -> LLMResult:
    key = _cache_key(model, f"{system}|thinking={thinking}", parts, schema, search)
    hit = db.scalar(select(LLMCall).where(LLMCall.cache_key == key))
    if hit is not None:
        return LLMResult(hit.response.get("data"), model, True, sources=hit.response.get("sources", []))

    body: dict = {"contents": [{"role": "user", "parts": parts}],
                  "generationConfig": {"temperature": 0}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if schema:
        body["generationConfig"] |= {"responseMimeType": "application/json", "responseSchema": schema}
    if search:
        body["tools"] = [{"google_search": {}}]
    if thinking:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking}

    try:
        resp = _post(model, body)
    except LLMError as exc:
        if not (thinking and "thinking" in str(exc).lower()):
            raise
        body["generationConfig"].pop("thinkingConfig")  # model doesn't support the knob
        resp = _post(model, body)
    cand = (resp.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])
                   if not p.get("thought"))
    if not text:
        raise LLMError(f"empty response (finishReason={cand.get('finishReason')})")
    data = json.loads(text) if schema else text.strip()

    usage = resp.get("usageMetadata") or {}
    tin = usage.get("promptTokenCount", 0)
    tout = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
    pin, pout = _price(model)
    cost = (tin * pin + tout * pout) / 1e6
    sources = [{"title": (c.get("web") or {}).get("title"), "uri": (c.get("web") or {}).get("uri")}
               for c in (cand.get("groundingMetadata") or {}).get("groundingChunks", [])]

    db.add(LLMCall(cache_key=key, task=task, model=model, input_tokens=tin, output_tokens=tout,
                   cost_usd=cost, response={"data": data, "sources": sources}))
    db.commit()
    log.info("llm %s %s in=%d out=%d $%.5f", task, model, tin, tout, cost)
    return LLMResult(data, model, False, tin, tout, cost, sources)
