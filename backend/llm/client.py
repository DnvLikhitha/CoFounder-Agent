"""Groq chat completion adapter with one bounded retry policy."""
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
from random import uniform
import re
from time import monotonic

from groq import APIConnectionError, APIStatusError, APITimeoutError, AsyncGroq

from backend.config import settings
from backend.llm.profiles import MAX_ATTEMPTS, PROFILES, PROFILE_VERSION, SYSTEM_PROMPT
from backend.run_worker.ledger import BudgetExceeded
from backend.run_worker.workflow import ProviderFailure, ProviderTimeout
from backend.safe_logging import configure_safe_logging

ATTEMPT_TIMEOUT = 20
MAX_BACKOFF = 8


def retry_after(headers):
    value = headers.get("Retry-After")
    if not value:
        return 0.0
    try:
        delay = float(value)
    except ValueError:
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0.0
    return max(0.0, delay) if math.isfinite(delay) else 0.0


def classify_error(exc):
    if isinstance(exc, (TimeoutError, APITimeoutError)):
        return "unknown"
    if isinstance(exc, APIConnectionError):
        return "transient"
    status = exc.status_code
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error", body)
    code = error.get("code") if isinstance(error, dict) else None
    if status == 429:
        return "rate_limited"
    if status in {400, 404} and code in ("model_not_found", "model_decommissioned"):
        return "model_unavailable"
    if status in {408, 409} or status >= 500:
        return "transient"
    return "rejected" if status in {400, 401, 403, 404, 413, 422} else "failed"


class LLMClient:
    def __init__(self, *, profile=PROFILE_VERSION, ledger=None, deadline=None):
        configure_safe_logging()
        self.groq = AsyncGroq(
            api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1",
            max_retries=0, timeout=ATTEMPT_TIMEOUT,
        )
        self.models = PROFILES[profile]
        self.ledger = ledger
        self.deadline = deadline

    async def complete(self, prompt, agent_name="", *, temperature=0.7, max_tokens=4096):
        # These profiles share byte-level tokenization and text-only chat framing.
        # Reserve a byte per token plus framing for the two role messages.
        prompt_bound = sum(len(message.encode("utf-8")) for message in (SYSTEM_PROMPT, prompt)) + 256
        models = [model for model in self.models if max_tokens <= model.completion_tokens
                  and prompt_bound + max_tokens <= model.context_tokens]
        if not models:
            raise ProviderFailure()
        deadline = self.deadline if self.deadline is not None else monotonic() + settings.v1_provider_timeout_seconds
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        history = self.ledger.history() if self.ledger else []
        previous = history[-1] if history else None
        if previous and previous["status"] in {"rejected", "failed"}:
            raise ProviderFailure()
        model_index = 0
        for index in range(len(history), MAX_ATTEMPTS):
            wait = previous["wait"] if previous else 0
            if monotonic() + wait >= deadline:
                raise ProviderTimeout()
            if wait:
                await asyncio.sleep(wait)
            if previous and (previous["status"] in {"rate_limited", "model_unavailable"}
                             or previous["requested_model"] == models[-1].name or index == MAX_ATTEMPTS - 1):
                model_index = len(models) - 1
            model = models[model_index]
            if self.ledger:
                try:
                    reservation = self.ledger.reserve(model, prompt_bound, max_tokens)
                except BudgetExceeded:
                    if model is models[-1]:
                        raise
                    model_index = len(models) - 1
                    model = models[model_index]
                    reservation = self.ledger.reserve(model, prompt_bound, max_tokens)
            timeout = min(ATTEMPT_TIMEOUT, deadline - monotonic())
            if timeout <= 0:
                if self.ledger:
                    self.ledger.settle(reservation, "rejected", usage=(0, 0), cost=0)
                raise ProviderTimeout()
            try:
                async with asyncio.timeout(timeout):
                    response = await self.groq.chat.completions.create(
                        model=model.name, messages=messages, temperature=temperature, timeout=timeout,
                        extra_body={"max_completion_tokens": max_tokens},
                    )
            except (TimeoutError, APIConnectionError, APIStatusError) as exc:
                status = classify_error(exc)
                definite = status in {"rate_limited", "model_unavailable", "rejected"}
                retry = status in {"unknown", "transient", "rate_limited", "model_unavailable"}
                retry = retry and not (status == "model_unavailable" and model is models[-1])
                hint = retry_after(exc.response.headers) if isinstance(exc, APIStatusError) else 0.0
                retry = retry and hint <= 86_400
                delay = max(hint, uniform(0, min(MAX_BACKOFF, 0.5 * 2 ** index))) if retry else None
                if self.ledger:
                    self.ledger.settle(reservation, status if retry else "rejected" if definite else "failed",
                                       usage=(0, 0) if definite else None,
                                       cost=0 if definite else None, retry_delay=delay)
                if not retry or index == MAX_ATTEMPTS - 1:
                    if status == "unknown":
                        raise ProviderTimeout() from None
                    raise ProviderFailure() from None
                previous = {"status": status, "wait": delay, "requested_model": model.name}
                continue

            actual = getattr(response, "model", None)
            if not isinstance(actual, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", actual):
                actual = None
            usage = getattr(response, "usage", None)
            counts = (getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None))
            reported = all(type(count) is int and 0 <= count <= 1_000_000_000 for count in counts)
            if self.ledger:
                # Preserve the reservation if usage or model pricing cannot be confirmed.
                price = next((candidate for candidate in self.models if candidate.name == actual), None)
                if reported:
                    cost = price.cost(*counts) if price else max(model.cost(prompt_bound, max_tokens), model.cost(*counts))
                    within_reservation = counts[0] <= prompt_bound and counts[1] <= max_tokens
                    accepted = actual == model.name and within_reservation
                    self.ledger.settle(reservation, "succeeded" if accepted else "failed",
                                       actual_model=actual, usage=counts, cost=cost)
                else:
                    accepted = actual == model.name
                    self.ledger.settle(reservation, "succeeded" if accepted else "failed", actual_model=actual)
                if not accepted:
                    raise ProviderFailure()
            return response.choices[0].message.content if response.choices else None
        raise ProviderFailure()
