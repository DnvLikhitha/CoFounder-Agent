"""Exercise the pinned SDK, retry policy, and redaction with an in-memory HTTP transport."""
import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from groq import AsyncGroq
import httpx

from backend.llm.client import LLMClient, retry_after
from backend.run_worker.workflow import ProviderFailure, ProviderTimeout


class ProviderTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.replies = []
        self.ledger = Mock()
        self.ledger.history.return_value = []
        self.ledger.reserve.side_effect = lambda *_: uuid4()

        async def transport(request):
            args = json.loads(request.content)
            self.requests.append(args)
            reply = self.replies.pop(0)
            if reply == "hang":
                await asyncio.Event().wait()
            status, headers, error = reply
            if status != 200:
                return httpx.Response(status, headers=headers, json={"error": {"code": error, "message": "secret"}})
            return httpx.Response(200, json={
                "id": "fake", "object": "chat.completion", "model": args["model"], "created": 1,
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}],
                "usage": {"prompt_tokens": 23, "completion_tokens": 19, "total_tokens": 42},
            })

        sdk = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        with patch("backend.llm.client.AsyncGroq", side_effect=lambda **kw: AsyncGroq(**kw, http_client=sdk)), \
             patch("backend.llm.client.settings.groq_api_key", "test-value"):
            self.client = LLMClient(ledger=self.ledger)
        self.addAsyncCleanup(self.client.groq.close)

    async def test_rate_limit_honors_retry_after_and_records_fallback_model(self):
        self.replies = [(429, {"Retry-After": "2"}, "rate_limit"), (200, {}, None)]
        with patch("backend.llm.client.asyncio.sleep") as wait, patch("backend.llm.client.uniform", return_value=0.25):
            self.assertEqual(await self.client.complete("private prompt"), "{}")
        wait.assert_awaited_once_with(2)
        self.assertEqual([req["model"] for req in self.requests], ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
        for request in self.requests:
            self.assertEqual(request["max_completion_tokens"], 4096)
            self.assertNotIn("max_tokens", request)
        calls = self.ledger.settle.call_args_list
        self.assertEqual(calls[0].args[1], "rate_limited")
        self.assertEqual(calls[0].kwargs["cost"], 0)
        self.assertEqual(calls[1].kwargs, {"usage": (23, 19), "actual_model": "openai/gpt-oss-20b", "cost": 7425})

    async def test_restored_attempt_without_retry_time_dispatches_immediately(self):
        for outcome in ("unknown", "succeeded"):
            with self.subTest(outcome=outcome):
                self.ledger.history.return_value = [
                    {"status": outcome, "requested_model": "openai/gpt-oss-120b", "wait": None},
                ]
                self.replies = [(200, {}, None)]
                with patch("backend.llm.client.asyncio.sleep") as wait:
                    self.assertEqual(await self.client.complete("private prompt"), "{}")
                wait.assert_not_awaited()

    async def test_transient_exhaustion_is_bounded_and_uncertain_usage_is_kept(self):
        self.replies = [(503, {}, "unavailable")] * 3
        with patch("backend.llm.client.asyncio.sleep") as wait, patch("backend.llm.client.uniform", side_effect=lambda a, b: b):
            with self.assertRaises(ProviderFailure):
                await self.client.complete("private prompt")
        self.assertEqual([call.args[0] for call in wait.await_args_list], [0.5, 1.0])
        self.assertEqual([req["model"] for req in self.requests],
                         ["openai/gpt-oss-120b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"])
        self.assertEqual([call.kwargs["cost"] for call in self.ledger.settle.call_args_list], [None] * 3)

    async def test_model_unavailability_falls_back_but_bad_credentials_do_not_retry(self):
        self.replies = [(404, {}, "model_not_found"), (401, {}, "invalid_api_key")]
        with patch("backend.llm.client.uniform", return_value=0), self.assertRaises(ProviderFailure):
            await self.client.complete("private prompt")
        self.assertEqual([req["model"] for req in self.requests], ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
        self.assertEqual([call.args[1] for call in self.ledger.settle.call_args_list], ["model_unavailable", "rejected"])

    async def test_hung_transport_times_out_and_retains_reservations_for_all_attempts(self):
        self.replies = ["hang"] * 3
        with patch("backend.llm.client.ATTEMPT_TIMEOUT", 0.5), patch("backend.llm.client.uniform", return_value=0):
            with self.assertRaises(ProviderTimeout):
                await self.client.complete("private prompt")
        self.assertEqual(len(self.requests), 3)
        self.assertEqual([call.args[1] for call in self.ledger.settle.call_args_list], ["unknown"] * 3)

    async def test_retry_after_outside_deadline_prevents_a_second_request(self):
        self.replies = [(429, {"Retry-After": "60"}, "rate_limit")]
        with patch("backend.llm.client.settings.v1_provider_timeout_seconds", 10), self.assertRaises(ProviderTimeout):
            await self.client.complete("private prompt")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.ledger.settle.call_args.kwargs["retry_delay"], 60)
        self.assertGreater(retry_after({"Retry-After": format_datetime(datetime.now(timezone.utc) + timedelta(seconds=5))}), 0)
