"""A stand-in for spark7: an OpenAI-compatible server (vLLM's routes) on a real socket, streaming included.

Scripted per test: queue :class:`Reply` objects, or set ``responder`` to compute a reply from the request.
Every request is recorded with its headers, so a test can check what the client sent (and that the real
token never reached it: the tests configure fake values).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

MODEL = "google/gemma-4-31B-it-qat-w4a16-ct"


@dataclass
class Reply:
    content: str = ""
    status: int = 200
    #: Seconds before the first byte.
    delay_s: float = 0.0
    #: Seconds between two stream chunks.
    chunk_delay_s: float = 0.0
    #: The model name echoed; ``None`` echoes the requested one.
    model: Optional[str] = None
    #: End the stream after the first chunk, with no finish reason and no [DONE].
    drop: bool = False
    finish_reason: str = "stop"
    #: Error body for a non-200 status.
    body: str = ""


class StandIn:
    def __init__(self, served: tuple[str, ...] = (MODEL,)):
        self.served = served
        self.replies: deque[Reply] = deque()
        self.responder: Optional[Callable[[dict[str, Any]], Reply]] = None
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.app = self._build()
        self.server: Optional[uvicorn.Server] = None
        self.thread: Optional[threading.Thread] = None
        self.url = ""

    # -- scripting -----------------------------------------------------------

    def reset(self) -> None:
        with self._lock:
            self.replies.clear()
            self.requests.clear()
            self.responder = None

    def queue(self, *replies: Reply) -> None:
        with self._lock:
            self.replies.extend(replies)

    def chat_requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [r for r in self.requests if r["path"] == "/v1/chat/completions"]

    def _next(self, body: dict[str, Any]) -> Reply:
        with self._lock:
            if self.replies:
                return self.replies.popleft()
            responder = self.responder
        if responder is not None:
            return responder(body)
        return Reply(content='{"status": "out_of_domain", "from_notes": "", "general": "", "cited": []}')

    # -- the server ------------------------------------------------------------

    def _build(self) -> FastAPI:
        app = FastAPI()

        @app.get("/v1/models")
        async def models(request: Request):
            with self._lock:
                self.requests.append({"path": "/v1/models", "headers": dict(request.headers), "body": None})
            return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "vllm"} for m in self.served]}

        @app.post("/v1/chat/completions")
        async def chat(request: Request):
            body = await request.json()
            with self._lock:
                self.requests.append({"path": "/v1/chat/completions", "headers": dict(request.headers), "body": body})
            reply = self._next(body)
            if reply.delay_s:
                await asyncio.sleep(reply.delay_s)
            if reply.status != 200:
                return PlainTextResponse(reply.body or f"stand-in error {reply.status}", status_code=reply.status)
            model = reply.model or body.get("model")
            if not body.get("stream"):
                return JSONResponse({"id": "chatcmpl-standin", "object": "chat.completion", "model": model,
                                     "choices": [{"index": 0, "message": {"role": "assistant", "content": reply.content},
                                                  "finish_reason": reply.finish_reason}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

            async def events():
                def frame(payload: dict[str, Any]) -> bytes:
                    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")

                base = {"id": "chatcmpl-standin", "object": "chat.completion.chunk", "model": model}
                yield frame({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""},
                                                  "finish_reason": None}]})
                pieces = [reply.content[i:i + 7] for i in range(0, len(reply.content), 7)] or [""]
                for n, piece in enumerate(pieces):
                    if reply.chunk_delay_s:
                        await asyncio.sleep(reply.chunk_delay_s)
                    yield frame({**base, "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
                    if reply.drop and n == 0:
                        return
                yield frame({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": reply.finish_reason}]})
                yield frame({**base, "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": len(pieces),
                                                               "total_tokens": 10 + len(pieces)}})
                yield b"data: [DONE]\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")

        return app

    def start(self) -> "StandIn":
        config = uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True, name="spark7-standin")
        self.thread.start()
        deadline = time.time() + 20
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("the spark7 stand-in did not start")
            time.sleep(0.02)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        return self

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=10)


def answer_json(from_notes: str, cited: list[str], general: str = "", status: str = "answer") -> str:
    """A reply in the shape of prompt chatbot-prompt@1.1.0 and 1.2.0: ``{status, from_notes, general, cited}``."""
    return json.dumps({"status": status, "from_notes": from_notes, "general": general, "cited": cited},
                      ensure_ascii=False)
