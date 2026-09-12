from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: dict = {}
    request_id: str | None = None
