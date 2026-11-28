"""Production prompt and bounded validation recovery for finance and risk."""
from types import SimpleNamespace

from backend.run_worker.evaluator import domain_errors
from backend.run_worker.prompts_reviewed_v2 import run_agent as render_reviewed
from backend.run_worker.prompts_v1 import parse_json
from backend.run_worker.workflow import REVIEWED_VERSION, InvalidOutput, validate_output


GUIDANCE = {
    "financial_projections": (
        "Return a single complete JSON object. Include 12 monthly_projections in order, with integer month "
        "and total_customers, and numeric mrr_usd and net_profit_usd. Keep each month's note short. "
        "Include nonempty assumptions and all summary keys, using null for unavailable summary metrics. "
        "Use JSON numbers without units or grouping separators. Do not copy example values. "
        "Compute ARR from the final month's recurring revenue, and LTV/CAC from supplied compatible values."
    ),
    "risk_register": (
        "Return one object with a nonempty risks array. Give each risk a distinct risk_id, title and "
        "actionable mitigation_strategy. For probability and impact use exactly one lowercase value "
        "from high, medium or low. Keep supporting text concise and specific to the provided business model."
    ),
}
COMPLETION_TOKENS = {"financial_projections": 8192, "risk_register": 6144}


def check_response(step_id, raw, upstream):
    content = parse_json(step_id, raw)
    validate_output(REVIEWED_VERSION, step_id, content)
    return next(iter(domain_errors(step_id, content, upstream)), None)


async def run_agent(step_id, body, upstream, llm):
    if step_id not in GUIDANCE:
        return await render_reviewed(step_id, body, upstream, llm)

    async def complete(prompt, **options):
        prompt += "\n\n" + GUIDANCE[step_id]
        options["max_tokens"] = COMPLETION_TOKENS[step_id]
        raw = await llm.complete(prompt, **options)
        try:
            reason = check_response(step_id, raw, upstream)
        except InvalidOutput:
            reason = "The previous response was incomplete JSON or did not match the required shape."
        if reason is None:
            return raw
        # Calls share the original deadline, durable attempt limit and run ledger.
        raw = await llm.complete(
            prompt + "\n\n" + reason + " Regenerate the entire JSON using the original inputs.", **options)
        if check_response(step_id, raw, upstream) is not None:
            raise InvalidOutput(step_id)
        return raw

    return await render_reviewed(step_id, body, upstream, SimpleNamespace(complete=complete))
