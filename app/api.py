"""Milestone 9: the web API and chat page.

    python -m app            # then open http://127.0.0.1:8000

Runs on this computer only (127.0.0.1). Signing in is a DEMO: you pick a person
from a list. A real deployment would use the company's login (SSO) instead.
The browser sends only who it is; each person's role is looked up here.
"""

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.answer import has_api_key, model_name
from src.pipeline import Assistant

STATIC = Path(__file__).resolve().parent / "static"

# Demo sign-in: who can be picked, and the role each one has. Roles live here, on
# the server, so the page cannot simply claim to be HR.
DEMO_USERS = {
    "oliver": {"name": "Oliver", "title": "Sales associate", "role": "employee"},
    "charlotte": {"name": "Charlotte", "title": "HR business partner", "role": "hr"},
}


class Question(BaseModel):
    user: str
    question: str = Field(min_length=1, max_length=1000)


def create_app(assistant: Assistant | None = None) -> FastAPI:
    """Build the web app. Tests pass in their own assistant; normally the real one is opened."""
    state = {"assistant": assistant}
    lock = threading.Lock()  # one question at a time touches the vault

    @asynccontextmanager
    async def lifespan(_app):
        opened_here = state["assistant"] is None
        if opened_here:
            state["assistant"] = Assistant()
        yield
        if opened_here:  # only close what this app opened; a caller's assistant is theirs to close
            state["assistant"].close()

    app = FastAPI(title="Clearance", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def user_or_404(user: str) -> dict:
        if user not in DEMO_USERS:
            raise HTTPException(404, "Unknown user")
        return DEMO_USERS[user]

    @app.get("/")
    def page():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/users")
    def users():
        return [{"id": uid, **info} for uid, info in DEMO_USERS.items()]

    @app.get("/api/status")
    def status():
        return {"documents_ready": state["assistant"].library.count() > 0,
                "chunks": state["assistant"].library.count(),
                "model": model_name(), "ai_key": has_api_key()}

    @app.post("/api/ask")
    def ask(body: Question):
        person = user_or_404(body.user)
        try:
            with lock:
                return state["assistant"].ask(body.question.strip(), user=body.user, role=person["role"])
        except Exception as error:  # e.g. the AI service is down or the key is wrong
            # Say what kind of problem it was, never the details (they could echo the question).
            raise HTTPException(502, f"The answer service failed ({type(error).__name__}). Please try again.")

    @app.get("/api/audit")
    def audit(user: str, limit: int = 50):
        if user_or_404(user)["role"] != "hr":
            raise HTTPException(403, "Only HR can view the audit log")
        with lock:
            entries = state["assistant"].vault.audit_log()
        return list(reversed(entries))[:limit]

    return app


app = create_app()  # the real app; uvicorn loads it as app.api:app
