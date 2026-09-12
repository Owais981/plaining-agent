from pydantic import BaseModel


class ConversationCreate(BaseModel):
    project_id: str | None = None
    title: str = "New planning conversation"


class MessageCreate(BaseModel):
    content: str
