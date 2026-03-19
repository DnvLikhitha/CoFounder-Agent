"""
api/routes/stream.py — SSE streaming endpoint for real-time pipeline updates
"""
import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.api.routes.run import run_events

router = APIRouter()


@router.get("/api/run/{run_id}/stream")
async def stream_run(run_id: str):
    """
    SSE endpoint that streams pipeline events in real-time.
    Client connects and receives events as agents complete.
    """
    async def event_generator():
        last_index = 0
        timeout_seconds = 600  # 10 minutes max
        elapsed = 0
        poll_interval = 0.5

        # Send initial connection event
        yield f"data: {json.dumps({'event': 'connected', 'run_id': run_id})}\n\n"

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
