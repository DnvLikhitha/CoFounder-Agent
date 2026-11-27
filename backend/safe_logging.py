"""Keep access URLs and third-party request details out of service logs."""
import logging
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse


class DropRecords(logging.Filter):
    def filter(self, record):
        return False


DROP_RECORDS = DropRecords()


def configure_safe_logging():
    for name in ("uvicorn.access", "httpx", "httpcore", "groq"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
    # Groq installs its own handler when GROQ_LOG is set. Filter SDK records even then.
    for name in ("groq._base_client", "groq._client"):
        logging.getLogger(name).addFilter(DROP_RECORDS)


class ClientDisconnected(Exception):
    pass


class SafeRequests:
    def __init__(self, app, *, private=False):
        self.app = app
        self.private = private

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False
        finished = False

        async def send_safe(message):
            nonlocal started, finished
            if message["type"] == "http.response.start":
                if self.private:
                    MutableHeaders(scope=message)["Cache-Control"] = "private, no-store"
                started = True
            elif message["type"] == "http.response.body":
                finished = not message.get("more_body", False)
            try:
                await send(message)
            except OSError:
                raise ClientDisconnected() from None

        try:
            await self.app(scope, receive, send_safe)
        except ClientDisconnected:
            return
        except Exception:
            logging.error("Request processing failed")
            if not started:
                await self._error(scope, receive, send_safe)
            elif not finished:
                await send({"type": "http.response.body", "body": b""})

    @staticmethod
    async def _error(scope, receive, send):
        response = JSONResponse({"error": {"code": "internal_error", "message": "Request processing failed",
                                          "retryable": False}}, status_code=500)
        await response(scope, receive, send)
