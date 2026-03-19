"""
llm/client.py — Groq API wrapper with fallback chain support
"""
import asyncio
from typing import Optional
from loguru import logger
from groq import AsyncGroq
from backend.config import settings


# Model registry — each agent specifies a preferred model
MODEL_MAP = {
    "fast": "llama-3.1-8b-instant",      # Fast agents (0, 4, 8, 10, 13)
    "smart": "llama-3.3-70b-versatile",  # Heavy reasoning (1, 2, 5, 6, 9, 11, 12, 14, 15)
    "long": "mixtral-8x7b-32768",        # Long context (3, 7)
}


class LLMClient:
    """
    Unified LLM client wrapping Groq API with automatic model selection
    and graceful fallback.
    """

    def __init__(self):
        self.groq = AsyncGroq(api_key=settings.groq_api_key)

    async def complete(
        self,
        prompt: str,
        agent_name: str = "",
        model_tier: str = "smart",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        Call Groq LLM and return raw text response.
        Falls back through model tiers if rate limits are hit.
        """
        model = MODEL_MAP.get(model_tier, MODEL_MAP["smart"])

        for attempt in range(3):
            try:
                logger.debug(f"🤖 {agent_name} calling {model}")
                response = await self.groq.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a specialized AI agent and expert analyst. "
                                "Always respond with the exact format requested. "
                                "When asked for JSON, output ONLY valid JSON inside ```json ``` fences."
                            )
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content

            except Exception as e:
                error_str = str(e)
                logger.warning(f"⚠️ LLM error for {agent_name} (attempt {attempt+1}): {error_str}")

                if "rate_limit" in error_str.lower() or "429" in error_str:
                    # Try a smaller/different model
                    if model == MODEL_MAP["smart"]:
                        model = MODEL_MAP["fast"]
                        logger.info(f"↪️ Falling back to fast model for {agent_name}")
                    await asyncio.sleep(5 * (attempt + 1))
                elif attempt < 2:
                    await asyncio.sleep(2)
                else:
                    raise

        raise RuntimeError(f"LLM failed after all retries for {agent_name}")
