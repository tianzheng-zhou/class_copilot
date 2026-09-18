"""ASGI body limits also cover chunked uploads without Content-Length."""

import json

from starlette.formparsers import MultiPartException

from . import audio


class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        is_upload = scope["path"].endswith("/uploads")
        maximum = audio.MAX_BYTES + 1024 * 1024 if is_upload else 1024 * 1024
        size, exceeded, replaced = 0, False, False

        async def limited_receive():
            nonlocal size, exceeded
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > maximum:
                    exceeded = True
                    # Multipart parser catches this type and closes spooled files.
                    raise MultiPartException("Request too large")
            return message

        async def limited_send(message):
            nonlocal replaced
            if exceeded:
                if message["type"] == "http.response.start":
                    request_id = scope.get("state", {}).get("request_id", "")
                    content = json.dumps(
                        {
                            "error": {
                                "code": "file_too_large" if is_upload else "request_too_large",
                                "message": "请求超过大小限制",
                                "retryable": False,
                                "details": {},
                                "request_id": request_id,
                            }
                        },
                        ensure_ascii=False,
                    ).encode()
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 413,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(content)).encode()),
                                (b"x-request-id", request_id.encode()),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": content})
                    replaced = True
                return
            if not replaced:
                await send(message)

        await self.app(scope, limited_receive, limited_send)
