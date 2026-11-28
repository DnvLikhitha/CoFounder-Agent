"""Run existing agent prompts and parsers against a private, committed-input context."""
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from types import MappingProxyType

from backend.llm.client import LLMClient
from backend.llm.profiles import PROFILE_VERSION, PROMPT_VERSION, STARTUP_PROMPTS_V1, SYSTEM_PROMPT
from backend.run_worker.ledger import AttemptLedger
from backend.run_worker.prompt_fingerprint import startup_v1_fingerprint
from backend.run_worker.prompts_v1 import run_agent


PROMPT_FINGERPRINT = "f1302b85226ffdb0840ed8f2f7eae514e32383e131756e9aae2946fdfd6ff7f9"
AgentRenderer = Callable[..., Awaitable[object]]


@dataclass(frozen=True)
class PromptBundle:
    system_prompt: str
    run_agent: AgentRenderer
    fingerprint: Callable[[str, AgentRenderer], str]
    expected_fingerprint: str


# Register future renderers alongside v1 before switching the submission default.
PROMPT_BUNDLES = MappingProxyType({
    STARTUP_PROMPTS_V1: PromptBundle(SYSTEM_PROMPT, run_agent, startup_v1_fingerprint, PROMPT_FINGERPRINT),
})


def verify_prompt_bundles():
    if PROMPT_VERSION not in PROMPT_BUNDLES:
        raise ValueError("Default prompt version is not registered")
    for version, bundle in PROMPT_BUNDLES.items():
        if bundle.fingerprint(bundle.system_prompt, bundle.run_agent) != bundle.expected_fingerprint:
            raise ValueError(f"Live prompt bundle {version} does not match its recorded fingerprint")


def live_provider(step_id, body, upstream, *, prompt_version, store=None, claim=None,
                  profile=PROFILE_VERSION, timeout=None):
    bundle = PROMPT_BUNDLES[prompt_version]

    async def execute():
        # The child owns its own client and event loop.
        ledger = AttemptLedger(store, *claim, step_id) if store is not None else None
        deadline = monotonic() + timeout if timeout is not None else None
        client = LLMClient(profile=profile, system_prompt=bundle.system_prompt, ledger=ledger, deadline=deadline)
        async with client.groq:
            return await bundle.run_agent(step_id, body, upstream, client)

    return asyncio.run(execute())
