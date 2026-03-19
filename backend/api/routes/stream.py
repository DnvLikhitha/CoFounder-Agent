"""
api/routes/stream.py — SSE streaming endpoint for real-time pipeline updates
"""
import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.api.routes.run import run_events
from backend.db.session import get_run, get_agent_outputs

router = APIRouter()


@router.get("/api/run/{run_id}/stream")
async def stream_run(run_id: str):
    """
    SSE endpoint that streams pipeline events in real-time.
    Client connects and receives events as agents complete.
    For already-completed runs (e.g. from history), emits from DB and finishes.
    """
    async def event_generator():
        last_index = 0
        timeout_seconds = 600  # 10 minutes max
        elapsed = 0
        poll_interval = 0.5

        # Send initial connection event
        yield f"data: {json.dumps({'event': 'connected', 'run_id': run_id})}\n\n"

        # If no in-memory events, check if run is completed in DB (e.g. user opened from history)
        events = run_events.get(run_id, [])
        if not events:
            run = await get_run(run_id)
            if run and run.get("status") == "completed":
                outputs = await get_agent_outputs(run_id)
                for out in sorted(outputs, key=lambda x: (x.get("agent_layer", 0), x.get("agent_name", ""))):
                    yield f"event: agent_done\ndata: {json.dumps({'agent': out['agent_name'], 'layer': out.get('agent_layer', 0), 'output': out.get('output_data', {}), 'latency_ms': out.get('latency_ms', 0)})}\n\n"
                yield f"event: pipeline_complete\ndata: {json.dumps({'run_id': run_id})}\n\n"
                return

        while elapsed < timeout_seconds:
            # Get new events since last poll
            events = run_events.get(run_id, [])
            new_events = events[last_index:]

            for event in new_events:
                event_type = event.get("event", "message")
                data = event.get("data", {})
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                last_index += 1

                # Stop streaming when pipeline is complete or errored
                if event_type in ["pipeline_complete", "pipeline_error"]:
                    return

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # Timeout
        yield f"event: timeout\ndata: {json.dumps({'message': 'Stream timeout'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
