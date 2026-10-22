"""
llm_pool.py — one interface over several free / cheap LLM providers.

Every provider here speaks the OpenAI chat-completions format, so one HTTP
client covers them all. The pool:
  * reads keys from the environment (a comma-separated list = several keys)
  * respects each provider's requests-per-minute and tokens-per-minute budget
  * on a 429 / timeout / server error, cools that provider down and tries the next
  * asks for JSON and validates it, retrying once on malformed output
  * counts calls and tokens per provider (shown in the run summary)

Environment variables (any subset; at least one is needed for real agents):
  GROQ_API_KEY        GROQ_MODEL        (default openai/gpt-oss-120b; free tier ~30 RPM / 8K TPM / 1K req per day)
  CEREBRAS_API_KEY    CEREBRAS_MODEL    (default gpt-oss-120b; free tier is 5 RPM / 30K TPM per key)
  GEMINI_API_KEY      GEMINI_MODEL      (default gemini-2.5-flash-lite)
  MISTRAL_API_KEY     MISTRAL_MODEL     (default mistral-small-latest)
  OPENROUTER_API_KEY  OPENROUTER_MODEL  (default meta-llama/llama-3.3-70b-instruct:free)
  ECOSIM_OLLAMA=1     OLLAMA_MODEL      (default qwen2.5:7b, local, no key)
  <NAME>_RPM / <NAME>_TPM override the rate budgets below.

Provider terms: use keys you are entitled to. Creating extra free accounts to
multiply a provider's free quota usually breaks its terms of service.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# name: (base_url, key_env, default_model, rpm, tpm, supports_json_mode)
PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b", 28, 7500, True),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "gpt-oss-120b", 5, 30000, True),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY",
               "gemini-2.5-flash-lite", 14, 200000, True),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest", 50, 400000, True),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
                   "meta-llama/llama-3.3-70b-instruct:free", 18, 100000, False),
    "ollama": ("http://localhost:11434/v1", None, "qwen2.5:7b", 1000, 10 ** 9, True),
}

REQUEST_TIMEOUT = 40.0


class LLMUnavailable(RuntimeError):
    """Raised when no provider could answer. Callers decide how to degrade."""


@dataclass
class Provider:
    name: str
    base_url: str
    api_key: Optional[str]
    model: str
    rpm: int
    tpm: int
    json_mode: bool
    label: str = ""
    req_times: Deque[float] = field(default_factory=deque)
    tok_times: Deque[list] = field(default_factory=deque)     # [time, tokens] per request
    cooldown_until: float = 0.0       # rate-limit cooldown (we wait for it)
    down_until: float = 0.0           # hard-error circuit breaker (we skip it)
    consecutive_errors: int = 0
    calls: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def _trim(self, now: float) -> None:
        while self.req_times and now - self.req_times[0] > 60:
            self.req_times.popleft()
        while self.tok_times and now - self.tok_times[0][0] > 60:
            self.tok_times.popleft()

    def wait_needed(self, est_tokens: int, now: float) -> float:
        """Seconds until this provider can take a request of est_tokens."""
        self._trim(now)
        waits = [max(0.0, self.cooldown_until - now)]
        if len(self.req_times) >= self.rpm:
            waits.append(60 - (now - self.req_times[0]) + 0.05)
        used = sum(t for _, t in self.tok_times)
        if used + est_tokens > self.tpm and self.tok_times:
            # wait until enough old tokens expire
            need = used + est_tokens - self.tpm
            freed = 0
            for ts, t in self.tok_times:
                freed += t
                if freed >= need:
                    waits.append(60 - (now - ts) + 0.05)
                    break
        return max(waits)

    def reserve(self, est_tokens: int, now: float) -> list:
        """Book capacity for a request; returns the booking so the real token count can replace the estimate."""
        self.req_times.append(now)
        booking = [now, est_tokens]
        self.tok_times.append(booking)
        return booking

    def usage(self) -> dict:
        return {"provider": self.label, "model": self.model, "calls": self.calls, "failures": self.failures,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}


def load_env() -> None:
    """Load keys from backend/.env and the repo-root .env (whichever exist), wherever we're run from."""
    from dotenv import load_dotenv
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(os.getcwd(), ".env"), os.path.join(here, "..", ".env"),
                 os.path.join(here, "..", "..", ".env")):
        if os.path.isfile(path):
            load_dotenv(path, override=False)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def providers_from_env() -> List[Provider]:
    out: List[Provider] = []
    for name, (url, key_env, model, rpm, tpm, json_mode) in PROVIDERS.items():
        up = name.upper()
        if name == "ollama":
            if os.getenv("ECOSIM_OLLAMA") == "1":
                out.append(Provider(name, os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/v1",
                                    None, os.getenv("OLLAMA_MODEL", model), _env_int("OLLAMA_RPM", rpm),
                                    _env_int("OLLAMA_TPM", tpm), json_mode, label="ollama"))
            continue
        keys = [k.strip() for k in os.getenv(key_env, "").split(",") if k.strip()]
        for i, key in enumerate(keys):
            out.append(Provider(name, url, key, os.getenv(f"{up}_MODEL", model), _env_int(f"{up}_RPM", rpm),
                                _env_int(f"{up}_TPM", tpm), json_mode,
                                label=name if len(keys) == 1 else f"{name}#{i + 1}"))
    return out


def estimate_tokens(messages: List[dict], max_tokens: int) -> int:
    chars = sum(len(m.get("content", "")) for m in messages)
    return int(chars / 3.6) + max_tokens + 150


def extract_json(text: str) -> Optional[dict]:
    """Parse the first JSON object in a model reply (tolerates ``` fences and chatter)."""
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


class LLMPool:
    def __init__(self, providers: Optional[List[Provider]] = None, max_concurrency: int = 6,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.providers = providers if providers is not None else providers_from_env()
        self._max_concurrency = max_concurrency
        self._lock: Optional[asyncio.Lock] = None      # created inside the running loop (Python 3.9)
        self._sem: Optional[asyncio.Semaphore] = None
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def describe(self) -> str:
        if not self.providers:
            return "no LLM providers configured"
        return ", ".join(f"{p.label} ({p.model})" for p in self.providers)

    def usage(self) -> List[dict]:
        return [p.usage() for p in self.providers]

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT, transport=self._transport)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _ensure_sync_primitives(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
            self._sem = asyncio.Semaphore(self._max_concurrency)

    async def _pick(self, est: int, exclude: set) -> Tuple[Provider, list]:
        """Wait for the provider that can serve soonest, then reserve capacity on it."""
        while True:
            async with self._lock:
                now = time.monotonic()
                cands = [(p.wait_needed(est, now), i, p) for i, p in enumerate(self.providers)
                         if p.label not in exclude and p.down_until <= now]
                if not cands:
                    raise LLMUnavailable("every provider is failing right now")
                wait, _, best = min(cands, key=lambda c: (c[0], c[1]))
                if wait <= 0:
                    return best, best.reserve(est, now)
            await asyncio.sleep(min(wait, 5.0))

    async def chat_json(self, system: str, user: str, max_tokens: int = 400, temperature: float = 0.7,
                        validate: Optional[Callable[[dict], Optional[str]]] = None,
                        max_attempts: int = 4) -> Tuple[dict, str]:
        """
        Returns (parsed_json, provider_label). `validate` returns an error string
        for bad output, which triggers one corrective retry.
        """
        if not self.providers:
            raise LLMUnavailable("no LLM providers configured (set GROQ_API_KEY etc.)")
        self._ensure_sync_primitives()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        est = estimate_tokens(messages, max_tokens)
        broken: set = set()     # providers that errored (not just rate-limited) on this request
        last_err = ""
        async with self._sem:
            for attempt in range(max_attempts):
                if len(broken) >= len(self.providers):
                    break        # everyone failed hard: give up now, the caller degrades gracefully
                prov, booking = await self._pick(est, broken)
                try:
                    text, usage = await self._post(prov, messages, max_tokens, temperature)
                except _RateLimited as e:
                    # a 429 is temporary: cool this provider down; others (or it, later) can retry
                    prov.cooldown_until = time.monotonic() + e.retry_after
                    prov.failures += 1
                    last_err = f"{prov.label}: rate limited"
                    continue
                except Exception as e:  # network, 5xx, bad request: trip the breaker for a while
                    prov.failures += 1
                    prov.consecutive_errors += 1
                    prov.down_until = time.monotonic() + min(120.0, 15.0 * 2 ** (prov.consecutive_errors - 1))
                    last_err = f"{prov.label}: {e}"
                    logger.warning("LLM call failed on %s: %s", prov.label, e)
                    broken.add(prov.label)
                    continue
                prov.calls += 1
                prov.consecutive_errors = 0
                real = usage.get("total_tokens") or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
                if real:
                    booking[1] = real      # free up what the estimate over-booked
                prov.prompt_tokens += usage.get("prompt_tokens", 0)
                prov.completion_tokens += usage.get("completion_tokens", 0)
                data = extract_json(text)
                problem = "reply was not valid JSON" if data is None else (validate(data) if validate else None)
                if problem is None:
                    return data, prov.label
                last_err = f"{prov.label}: {problem}"
                messages = messages[:2] + [
                    {"role": "assistant", "content": text[:1500]},
                    {"role": "user", "content": f"That reply was unusable: {problem}. Reply again with ONLY the JSON object."},
                ]
        raise LLMUnavailable(last_err or "no usable reply")

    async def _post(self, prov: Provider, messages: List[dict], max_tokens: int, temperature: float):
        client = await self._http()
        body: Dict[str, Any] = {"model": prov.model, "messages": messages, "max_tokens": max_tokens,
                                "temperature": temperature}
        if prov.json_mode:
            body["response_format"] = {"type": "json_object"}
        if "gpt-oss" in prov.model:
            # gpt-oss thinks before answering; thinking tokens count against max_tokens and the
            # rate budget, so keep it short. The plan's own "thought" field carries the reasoning.
            body["reasoning_effort"] = os.getenv("ECOSIM_REASONING_EFFORT", "low")
            body["max_tokens"] = max_tokens + 300
        headers = {"Content-Type": "application/json"}
        if prov.api_key:
            headers["Authorization"] = f"Bearer {prov.api_key}"
        r = await client.post(f"{prov.base_url}/chat/completions", json=body, headers=headers)
        if r.status_code == 429:
            ra = r.headers.get("retry-after")
            try:
                wait = float(ra) if ra else 20.0
            except ValueError:
                wait = 20.0
            raise _RateLimited(min(max(wait, 2.0), 90.0))
        if r.status_code == 400 and prov.json_mode and "response_format" in r.text:
            prov.json_mode = False   # this model/provider doesn't support JSON mode; rely on the prompt
            body.pop("response_format", None)
            r = await client.post(f"{prov.base_url}/chat/completions", json=body, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        return text, data.get("usage", {}) or {}

    async def check(self) -> List[dict]:
        """Send one tiny request to every provider; used by `python -m town.check_llm`."""
        results = []
        for p in self.providers:
            t0 = time.monotonic()
            try:
                text, _ = await self._post(p, [{"role": "user", "content": 'Reply with the JSON {"ok": true} only.'}], 60, 0.0)
                ok = extract_json(text) is not None
                results.append({"provider": p.label, "model": p.model, "ok": ok,
                                "latency_s": round(time.monotonic() - t0, 2),
                                "note": "" if ok else f"unexpected reply: {text[:80]!r}"})
            except _RateLimited:
                results.append({"provider": p.label, "model": p.model, "ok": False, "note": "rate limited right now"})
            except Exception as e:
                results.append({"provider": p.label, "model": p.model, "ok": False, "note": str(e)[:200]})
        return results

    async def list_models(self, prov: Provider) -> List[str]:
        client = await self._http()
        headers = {"Authorization": f"Bearer {prov.api_key}"} if prov.api_key else {}
        r = await client.get(f"{prov.base_url}/models", headers=headers)
        if r.status_code >= 400:
            return []
        return sorted(m.get("id", "") for m in r.json().get("data", []))


class _RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after
