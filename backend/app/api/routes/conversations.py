import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Conversation, ConversationMessage
from app.schemas.conversation import ConversationCreate, MessageCreate
from app.security.deps import get_current_user
from app.ai.agent import PlanningAgent
from app.ai.anthropic_provider import AnthropicProvider

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])

_provider = AnthropicProvider()
_agent = PlanningAgent(_provider)


@router.post("", status_code=201)
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    convo = Conversation(project_id=body.project_id, user_id=user.id, title=body.title)
    db.add(convo)
    db.commit()
    return {"id": convo.id, "title": convo.title, "project_id": convo.project_id}


def _history_for(db: Session, conversation_id: str) -> list[dict]:
    rows = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).order_by(ConversationMessage.created_at).all()
    history = []
    for r in rows:
        if r.role == "user":
            history.append({"role": "user", "content": r.content})
        elif r.role == "assistant":
            history.append({"role": "assistant", "content": r.content})
    return history


@router.post("/{conversation_id}/messages")
async def post_message(conversation_id: str, body: MessageCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    convo = db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": "Conversation not found"})

    if not _provider.is_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail={
            "error": "AI_NOT_CONFIGURED",
            "message": "ANTHROPIC_API_KEY is not set. The conversational agent is unavailable; use the REST endpoints directly.",
        })

    db.add(ConversationMessage(conversation_id=conversation_id, role="user", content=body.content))
    db.commit()

    history = _history_for(db, conversation_id)
    result = await _agent.handle_message(body.content, history[:-1], db, user.id)

    db.add(ConversationMessage(
        conversation_id=conversation_id, role="assistant", content=result.final_text,
        tool_calls=[{"tool": t["tool"], "input": t["input"]} for t in result.tool_trace],
    ))
    db.commit()

    return {
        "response": result.final_text,
        "tool_calls": [{"tool": t["tool"], "status": "ok" if "error" not in t["output"] else "error"} for t in result.tool_trace],
    }


@router.get("/{conversation_id}/stream")
async def stream_conversation(conversation_id: str, db: Session = Depends(get_db)):
    """SSE stream of high-level operational status only (build doc section
    57) -- never internal reasoning or hidden chain-of-thought."""
    convo = db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": "Conversation not found"})

    async def event_generator():
        messages = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).order_by(ConversationMessage.created_at).all()
        for m in messages:
            yield f"data: {json.dumps({'role': m.role, 'content': m.content})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
