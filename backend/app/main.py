import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.utils.errors import http_exception_handler, unhandled_exception_handler
from app.utils.logging import configure_logging, get_logger
from app.api.routes import auth, projects, locations, tasks, crew, equipment, plans, routing, conversations, reference

configure_logging()
logger = get_logger("app.main")
settings = get_settings()

app = FastAPI(
    title="Crew, Equipment & Travel Planning Agent",
    version="1.0.0",
    description=(
        "Conversation layer (Claude + tool calling) orchestrates a deterministic "
        "optimization layer (OR-Tools CP-SAT + routing + conflict/cost/risk engines) "
        "backed by PostgreSQL as the source of truth. The LLM never invents or "
        "constructs the final schedule -- see /api/v1/conversations and "
        "/api/v1/plans/optimize."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.middleware("http")
async def request_size_limit(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_request_body_bytes:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=413, content={"error": "PAYLOAD_TOO_LARGE", "message": "Request body too large", "details": {}, "request_id": None})
    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({elapsed*1000:.0f}ms)")
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(locations.router)
app.include_router(tasks.router)
app.include_router(crew.router)
app.include_router(equipment.router)
app.include_router(plans.router)
app.include_router(routing.router)
app.include_router(conversations.router)
app.include_router(reference.router)
