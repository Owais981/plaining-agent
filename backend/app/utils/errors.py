import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    request_id = str(uuid.uuid4())
    detail = exc.detail
    if isinstance(detail, dict):
        body = {"error": detail.get("error", "HTTP_ERROR"), "message": detail.get("message", str(detail)),
                "details": detail.get("details", {}), "request_id": request_id}
    else:
        body = {"error": "HTTP_ERROR", "message": str(detail), "details": {}, "request_id": request_id}
    return JSONResponse(status_code=exc.status_code, content=body)


async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = str(uuid.uuid4())
    return JSONResponse(status_code=500, content={
        "error": "INTERNAL_ERROR",
        "message": "An unexpected error occurred. No stack trace is exposed to clients.",
        "details": {}, "request_id": request_id,
    })
