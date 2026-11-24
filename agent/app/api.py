from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .graph import HelpdeskAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent = await HelpdeskAgent.create()
    yield


app = FastAPI(title="HR/IT Helpdesk Agent", version="1.0.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, examples=["How many casual leaves does E102 have left?"])
    session_id: str | None = Field(None, description="Reuse to keep conversation context")


@app.get("/health")
async def health():
    return {"status": "ok", "agent_ready": hasattr(app.state, "agent")}


@app.post("/chat")
async def chat(req: ChatRequest):
    agent: HelpdeskAgent | None = getattr(app.state, "agent", None)
    if agent is None:
        raise HTTPException(503, "Agent is still starting up")
    session_id = req.session_id or uuid.uuid4().hex
    result = await agent.ask(req.message, session_id=session_id)
    return {"session_id": session_id, **result}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")
