"""Agent prompt builders and evidence returned by optional research."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import re


@dataclass(frozen=True)
class Research:
    text: str = ""
    evidence: dict[str, str | list[str]] = field(default_factory=dict)


def source_urls(research: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"^Source:\s*(https?://\S+)", research, re.MULTILINE)))


class BaseAgent(ABC):
    name: str = "BaseAgent"

    async def fetch_research(self, ctx) -> Research:
        return Research()

    @abstractmethod
    def build_prompt(self, ctx, external_research: str = "") -> str:
        """Render the prompt using committed inputs and optional research."""

    @abstractmethod
    def parse_output(self, raw: str) -> dict:
        """Read the JSON envelope prepared by the provider adapter."""

    def extract_json(self, text: str):
        return json.loads(text.removeprefix("```json\n").removesuffix("\n```"))

    def safe_text(self, text: str, max_len: int = 500) -> str:
        sanitized = text.replace("Ignore previous instructions", "")
        sanitized = sanitized.replace("System:", "")
        sanitized = sanitized.replace("</s>", "")
        return sanitized[:max_len]
