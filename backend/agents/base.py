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

    @abstractmethod
    def build_prompt(self, ctx) -> str:
        """Build the LLM prompt from the current RunContext."""
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

        prompt = self.build_prompt(ctx)

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
        """Extract JSON from LLM output that may contain markdown fences or extra text."""
        # Try JSON code fence first
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # Try to find JSON array
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not extract JSON from LLM output: {text[:200]}...")

    def safe_text(self, text: str, max_len: int = 500) -> str:
        """Sanitize user input to prevent prompt injection."""
        sanitized = text.replace("Ignore previous instructions", "")
        sanitized = sanitized.replace("System:", "")
        sanitized = sanitized.replace("</s>", "")
        return sanitized[:max_len]
