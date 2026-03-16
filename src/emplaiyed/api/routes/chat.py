"""WebSocket chat endpoint for the application detail page."""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from emplaiyed.api.deps import get_db
from emplaiyed.core.database import get_application, get_opportunity
from emplaiyed.generation.chat_assistant import build_system_prompt
from emplaiyed.generation.pipeline import get_asset_dir
from emplaiyed.llm.config import DEFAULT_MODEL, get_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.websocket("/ws/chat/{application_id}")
async def chat_ws(
    websocket: WebSocket,
    application_id: str,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Stream chat responses over WebSocket using Pydantic AI agent.

    Protocol:
        Client sends: plain text query
        Server sends: {"type":"chunk","data":"..."} for each token
                      {"type":"done"} when complete
                      {"type":"error","data":"..."} on failure
    """
    await websocket.accept()

    # Load application context
    app = get_application(conn, application_id)
    if app is None:
        await websocket.send_json({"type": "error", "data": "Application not found"})
        await websocket.close()
        return

    opp = get_opportunity(conn, app.opportunity_id)
    if opp is None:
        await websocket.send_json({"type": "error", "data": "Opportunity not found"})
        await websocket.close()
        return

    # Read generated assets for context
    asset_dir = get_asset_dir(app.id)
    cv_md_path = asset_dir / "cv.md"
    letter_md_path = asset_dir / "letter.md"

    if cv_md_path.exists() and letter_md_path.exists():
        cv_md = cv_md_path.read_text(encoding="utf-8")
        letter_md = letter_md_path.read_text(encoding="utf-8")
    else:
        cv_md = "(No CV generated yet)"
        letter_md = "(No cover letter generated yet)"

    system_prompt = build_system_prompt(
        cv_md, letter_md, opp.description, opp.company, opp.title
    )

    # Conversation loop
    try:
        while True:
            query = await websocket.receive_text()

            try:
                llm = OpenAIChatModel(
                    DEFAULT_MODEL,
                    provider=OpenRouterProvider(api_key=get_api_key()),
                )
                agent: Agent[None, str] = Agent(
                    llm, output_type=str, system_prompt=system_prompt
                )

                async with agent.run_stream(query) as streamed:
                    async for chunk in streamed.stream_text(delta=True):
                        await websocket.send_json({"type": "chunk", "data": chunk})

                await websocket.send_json({"type": "done"})

            except Exception as exc:
                logger.exception("Chat error for %s", application_id)
                await websocket.send_json({"type": "error", "data": str(exc)})

    except WebSocketDisconnect:
        logger.debug("Chat WebSocket disconnected for %s", application_id)
