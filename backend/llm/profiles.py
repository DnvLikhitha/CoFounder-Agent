"""Immutable Groq request profiles and a reviewed USD price schedule."""
from dataclasses import dataclass
from types import MappingProxyType

PROFILE_VERSION = "groq-gpt-oss-v1"
STARTUP_PROMPTS_V1 = "startup-prompts-v1"
PROMPT_VERSION = STARTUP_PROMPTS_V1
MAX_ATTEMPTS = 3
SYSTEM_PROMPT = (
    "You are a specialized AI agent and expert analyst. "
    "Always respond with the exact format requested. "
    "When asked for JSON, output ONLY valid JSON inside ```json ``` fences."
)


@dataclass(frozen=True)
class Model:
    name: str
    input_nanousd: int
    output_nanousd: int
    context_tokens: int = 131_072
    completion_tokens: int = 65_536

    def cost(self, prompt, completion):
        return prompt * self.input_nanousd + completion * self.output_nanousd


PROFILES = MappingProxyType({
    PROFILE_VERSION: (
        Model("openai/gpt-oss-120b", 150, 600),
        Model("openai/gpt-oss-20b", 75, 300),
    ),
})
