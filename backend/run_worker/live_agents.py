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
from backend.run_worker.prompts_reviewed_v1 import run_agent as run_reviewed_agent
from backend.run_worker.prompts_reviewed_v2 import run_agent as run_audited_forecast_agent
from backend.run_worker.prompts_reviewed_v3 import run_agent as run_recoverable_agent
from backend.run_worker.prompts_v1 import run_agent


PROMPT_FINGERPRINT = "a4184e235967fd53ef25c9968d2e094dd67c3711af7bf579205bd68d0307f917"
PRIOR_REVIEWED_PROMPT_VERSION = "startup-reviewed-prompts-v1"
AUDITED_FORECAST_PROMPT_VERSION = "startup-reviewed-prompts-v2"
REVIEWED_PROMPT_VERSION = "startup-reviewed-prompts-v3"
REVIEWED_PROMPT_FINGERPRINT = "ef97742899b6874a7e7ef82a0d2ccfb89d52d620743d9ae02cf5a6cfe2b7352b"
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
    PRIOR_REVIEWED_PROMPT_VERSION: PromptBundle(SYSTEM_PROMPT, run_reviewed_agent,
                                         startup_v1_fingerprint, REVIEWED_PROMPT_FINGERPRINT),
    AUDITED_FORECAST_PROMPT_VERSION: PromptBundle(SYSTEM_PROMPT, run_audited_forecast_agent,
                                         startup_v1_fingerprint, "0e3e14af4696274542367faebe47474f2cdae31a2e1e8786f75f788898e668a7"),
    REVIEWED_PROMPT_VERSION: PromptBundle(SYSTEM_PROMPT, run_recoverable_agent, startup_v1_fingerprint, "6c2f7b1a040f648612def2d5680ad0edcb29d0428b413442470709ada74f9e20"),
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
