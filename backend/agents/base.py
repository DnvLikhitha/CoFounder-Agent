"""
agents/base.py — BaseAgent ABC with retry logic and JSON extraction
"""
from abc import ABC, abstractmethod
from typing import Callable
import json
import re
import asyncio
from loguru import logger


class BaseAgent(ABC):
    MAX_RETRIES = 3
    name: str = "BaseAgent"
    layer: int = 0

    def __init__(self, llm_client):
        self.llm = llm_client

    async def fetch_research(self, ctx) -> str:
        """Override to fetch external data (SerpAPI, FRED, etc.). Return string for prompt injection."""
        return ""

    @abstractmethod
    def build_prompt(self, ctx, external_research: str = "") -> str:
        """Build the LLM prompt from the current RunContext. Use external_research if provided."""
        pass

    @abstractmethod
    def parse_output(self, raw: str) -> dict:
        """Parse the raw LLM string output into a structured dict."""
        pass

    @abstractmethod
    def write_to_context(self, ctx, parsed: dict):
        """Write parsed output to the correct field in RunContext."""
        pass

    def write_fallback(self, ctx):
        """Write an empty structure on failure to prevent downstream crashes."""
        return ctx

    async def run(self, ctx, event_callback: Callable = None) -> "RunContext":
        """Execute the agent with retry logic and SSE event emission."""
        ctx.status[self.name] = "running"
        if event_callback:
            await event_callback("agent_start", {
                "agent": self.name, "layer": self.layer
            })

        external_research = await self.fetch_research(ctx)
        prompt = self.build_prompt(ctx, external_research)

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                import time
                t0 = time.time()
                raw = await self.llm.complete(prompt, agent_name=self.name)
                latency = int((time.time() - t0) * 1000)

                parsed = self.parse_output(raw)
                ctx = self.write_to_context(ctx, parsed)
                ctx.status[self.name] = "done"

                if event_callback:
                    await event_callback("agent_done", {
                        "agent": self.name,
                        "layer": self.layer,
                        "latency_ms": latency,
                        "output": parsed
                    })

                logger.info(f"✅ {self.name} completed in {latency}ms")
                return ctx

            except Exception as e:
                last_error = str(e)
                logger.warning(f"⚠️ {self.name} attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)  # exponential backoff

        # All retries exhausted
        ctx.status[self.name] = f"error: {last_error}"
        if event_callback:
            await event_callback("agent_error", {
                "agent": self.name,
                "error": last_error
            })
        ctx = self.write_fallback(ctx)
        return ctx

    def extract_json(self, text: str) -> dict:
        """Extract JSON from LLM output that may contain markdown fences, extra text, or be truncated."""

        def try_parse(s: str):
            try:
                return json.loads(s.strip())
            except (json.JSONDecodeError, ValueError):
                return None

        def repair_truncated(s: str):
            """Attempt to close truncated JSON strings/objects."""
            s = s.strip()
            # Try simple suffixes to close an open string + object
            for suffix in ['"}}', '"}', '"]\n}', '"}\n}']:
                result = try_parse(s + suffix)
                if result:
                    return result
            # Scan backwards for last complete key-value pair and close object
            for i in range(len(s) - 1, max(len(s) - 300, 5), -1):
                if s[i] in (',', '{'):
                    result = try_parse(s[:i] + '}')
                    if result and isinstance(result, dict):
                        return result
            return None

        # 1. Try JSON code fence
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if match:
            extracted = match.group(1).strip()
            result = try_parse(extracted)
            if result is not None:
                return result
            result = repair_truncated(extracted)
            if result is not None:
                logger.warning(f"[{self.name}] Repaired truncated JSON from code fence.")
                return result

        # 2. Try raw JSON object
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            result = try_parse(match.group(0))
            if result is not None:
                return result
            result = repair_truncated(match.group(0))
            if result is not None:
                logger.warning(f"[{self.name}] Repaired truncated raw JSON object.")
                return result

        # 3. Scan from first '{' to end of text (handles truncated output with no closing })
        brace_pos = text.find('{')
        if brace_pos != -1:
            result = repair_truncated(text[brace_pos:])
            if result is not None:
                logger.warning(f"[{self.name}] Repaired partially-extracted JSON.")
                return result

        # 4. Try JSON array
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            result = try_parse(match.group(0))
            if result is not None:
                return result

        raise ValueError(f"Could not extract JSON from LLM output: {text[:200]}...")

    def safe_text(self, text: str, max_len: int = 500) -> str:
        """Sanitize user input to prevent prompt injection."""
        sanitized = text.replace("Ignore previous instructions", "")
        sanitized = sanitized.replace("System:", "")
        sanitized = sanitized.replace("</s>", "")
        return sanitized[:max_len]
