import asyncio
import json
import logging
from datetime import timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, update

from .config import Settings
from .database import (Comment, Conversation, Message, ToolRun, User, comment_json,
                       conversation_json, create_database, message_json, now)
from .deep_agent import HIDDEN_TOOLS, DeepContractAgent
from .databricks_client import DatabricksHTTP
from .auth import install_auth

logger = logging.getLogger("atlas")


class CreateConversation(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Title must not be blank")
        return value.strip()


class EditConversation(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def not_blank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Title must not be blank")
        return value.strip() if value else value


class EditMessage(BaseModel):
    feedback: Literal["up", "down"] | None = None
    saved: bool


class AddComment(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Comment must not be blank")
        return value.strip()


class SendMessage(BaseModel):
    content: str = Field(default="", max_length=66000)
    style: Literal["balanced", "concise", "detailed"] = "balanced"
    regenerate: bool = False
    user_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,36}$')
    assistant_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,36}$')


def create_app(settings=None, session_factory=None, model=None, *, testing=False, identity_resolver=None):
    settings = settings or Settings()
    if not testing:
        settings.validate()
    if identity_resolver is not None and not testing:
        raise RuntimeError('Test identity resolvers cannot be used in production.')
    if session_factory is None:
        _, session_factory = create_database(settings)
    app = FastAPI(title="AIA API", docs_url="/api/docs" if testing else None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def security_headers(request, call_next):
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 300000):
            return Response("Request too large", status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def database():
        with session_factory() as db:
            yield db

    current = install_auth(app, settings, database, identity_resolver)

    def own_conversation(db, conversation_id, user_id):
        conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))
        if not conversation:
            raise HTTPException(404, "Conversation not found.")
        return conversation

    def own_message(db, message_id, user_id):
        message = db.scalar(select(Message).join(Conversation).where(Message.id == message_id, Conversation.user_id == user_id))
        if not message:
            raise HTTPException(404, "Response not found.")
        if message.role != "assistant":
            raise HTTPException(400, "Feedback and notes are only available on assistant responses.")
        return message

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/bootstrap")
    def bootstrap(session=Depends(current), db=Depends(database)):
        user = db.get(User, session.user_id)
        conversations = db.scalars(select(Conversation).where(Conversation.user_id == session.user_id).order_by(Conversation.updated_at.desc())).all()
        return {"user": {"id": user.id, "name": user.name, "email": user.email},
                "conversations": [conversation_json(c) for c in conversations],
                "historyStorage": "lakebase" if settings.history_backend == "lakebase" else "local",
                "authMode": settings.auth_mode}

    @app.get("/api/sessions")
    def list_sessions(session=Depends(current)):
        return [{"id": "current", "device": "This browser", "createdAt": "", "expiresAt": "", "current": True}]

    @app.post("/api/conversations", status_code=201)
    def create_conversation(body: CreateConversation, session=Depends(current), db=Depends(database)):
        count = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.user_id == session.user_id))
        if count >= 500:
            raise HTTPException(409, "This workspace has reached 500 conversations. Export and delete old conversations to make room.")
        conversation = Conversation(user_id=session.user_id, title=body.title)
        db.add(conversation)
        db.commit()
        return conversation_json(conversation)

    @app.patch("/api/conversations/{conversation_id}")
    def edit_conversation(conversation_id: str, body: EditConversation, session=Depends(current), db=Depends(database)):
        conversation = own_conversation(db, conversation_id, session.user_id)
        conversation.updated_at = now()
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(conversation, field, value)
        db.commit()
        return conversation_json(conversation)

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str, session=Depends(current), db=Depends(database)):
        conversation = own_conversation(db, conversation_id, session.user_id)
        if conversation.generation_started and conversation.generation_started.replace(tzinfo=timezone.utc) > now() - timedelta(minutes=3):
            raise HTTPException(409, "Stop the response before deleting this conversation.")
        db.delete(conversation)
        db.commit()
        return Response(status_code=204)

    @app.patch("/api/messages/{message_id}")
    def edit_message(message_id: str, body: EditMessage, session=Depends(current), db=Depends(database)):
        message = own_message(db, message_id, session.user_id)
        message.feedback, message.saved = body.feedback, body.saved
        db.commit()
        return message_json(message)

    @app.post("/api/messages/{message_id}/comments", status_code=201)
    def add_comment(message_id: str, body: AddComment, session=Depends(current), db=Depends(database)):
        message = own_message(db, message_id, session.user_id)
        if len(message.comments) >= 100:
            raise HTTPException(409, "This response has reached its limit of 100 notes.")
        comment = Comment(message_id=message_id, text=body.text)
        db.add(comment)
        db.commit()
        return comment_json(comment)

    @app.delete("/api/comments/{comment_id}", status_code=204)
    def delete_comment(comment_id: str, session=Depends(current), db=Depends(database)):
        comment = db.scalar(select(Comment).join(Message).join(Conversation).where(Comment.id == comment_id, Conversation.user_id == session.user_id))
        if not comment:
            raise HTTPException(404, "Note not found.")
        db.delete(comment)
        db.commit()
        return Response(status_code=204)

    @app.post("/api/conversations/{conversation_id}/messages")
    async def send_message(conversation_id: str, body: SendMessage, session=Depends(current), db=Depends(database)):
        conversation = own_conversation(db, conversation_id, session.user_id)
        if not body.regenerate and not body.content.strip():
            raise HTTPException(422, "Please enter a message.")
        if len(conversation.messages) >= 200:
            raise HTTPException(409, "Start a new conversation to continue. This one has reached 200 messages.")
        recent = db.scalar(select(func.count()).select_from(Message).join(Conversation).where(Conversation.user_id == session.user_id, Message.role == "assistant", Message.created_at > now() - timedelta(minutes=1)))
        if recent >= 20:
            raise HTTPException(429, "Please wait a minute before sending more messages.")
        messages = [{"role": m.role, "content": m.content} for m in conversation.messages if m.status == "complete" and m.content]
        if body.regenerate:
            last_user = next((i for i in range(len(messages) - 1, -1, -1) if messages[i]["role"] == "user"), None)
            if last_user is None:
                raise HTTPException(400, "There is no message to regenerate.")
            messages = messages[:last_user + 1]
        else:
            messages.append({"role": "user", "content": body.content.strip()})
        # Keep complete recent turns inside a bounded request, preserving the latest user input.
        context, size = [], 0
        for item in reversed(messages):
            if context and size + len(item["content"]) > 100000:
                break
            context.insert(0, item)
            size += len(item["content"])
        while context and context[0]["role"] != "user":
            context.pop(0)
        # Browser-generated IDs keep optimistic messages addressable after a
        # disconnect or tool error. Reject collisions before inserting any turn.
        ids = [i for i in (body.user_id, body.assistant_id) if i]
        if len(ids) != len(set(ids)) or (ids and db.scalar(select(Message.id).where(Message.id.in_(ids)))):
            raise HTTPException(409, 'This message was already submitted. Reload the conversation.')
        lease = now()
        claim = db.execute(update(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == session.user_id,
                           or_(Conversation.generation_started.is_(None), Conversation.generation_started < lease - timedelta(minutes=3)))
                           .values(generation_started=lease, updated_at=lease).execution_options(synchronize_session=False))
        if claim.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "A response is already being generated in this conversation.")
        user_message = None
        if not body.regenerate:
            user_message = Message(conversation_id=conversation_id, role="user", content=body.content.strip())
            if body.user_id:
                user_message.id = body.user_id
            db.add(user_message)
            db.flush()
        assistant = Message(conversation_id=conversation_id, role="assistant", content="", status="stopped")
        assistant.created_at = now() + timedelta(microseconds=1)
        if body.assistant_id:
            assistant.id = body.assistant_id
        db.add(assistant)
        db.commit()
        assistant_id = assistant.id
        user_json = message_json(user_message) if user_message else None
        # Drop the database connection while the model and remote tools run.
        db.close()

        async def generate():
            content, status, failure = "", "stopped", None
            tool_runs = {}
            try:
                async with asyncio.timeout(settings.agent_timeout_seconds):
                    request_model = model or await asyncio.to_thread(
                        lambda: DeepContractAgent(settings, http=DatabricksHTTP(settings, token=session.token)))
                    async for item in request_model.stream(context, body.style):
                        if isinstance(item, dict) and item.get("type") == "tool":
                            tool = item["tool"]
                            if tool["id"] not in tool_runs and len(tool_runs) >= 32:
                                raise ValueError("Agent tool limit reached")
                            tool_runs[tool["id"]] = tool
                            # Contract evidence is persisted and returned as metadata,
                            # never inserted into the chat's visible tool panel.
                            if tool["name"] not in HIDDEN_TOOLS:
                                yield json.dumps(item) + "\n"
                        elif isinstance(item, str):
                            content += item
                            yield json.dumps({"type": "delta", "text": item}) + "\n"
                if not content:
                    raise ValueError("Empty response")
                status = "complete"
            except asyncio.CancelledError:
                raise
            except Exception as error:
                status = "error"
                failure = "The assistant could not complete the response. Check Databricks access and try again."
                logger.warning("Model generation failed (%s)", type(error).__name__)
            finally:
                # Persist completed, partial, and failed answers; never discard an existing version.
                with session_factory() as final_db:
                    record = final_db.get(Message, assistant_id)
                    if record:
                        record.content, record.status = content or failure or "Response stopped.", status
                        for tool in tool_runs.values():
                            tool_status = tool["status"]
                            if tool_status == "running":
                                tool_status = "error" if status == "error" else "stopped"
                            final_db.add(ToolRun(message_id=assistant_id, call_id=tool["id"][:250],
                                                name=tool["name"][:100], status=tool_status,
                                                input=tool["input"][:16000], output=tool["output"][:64000]))
                        final_db.execute(update(Conversation).where(Conversation.id == conversation_id, Conversation.generation_started == lease).values(generation_started=None, updated_at=now()))
                        final_db.commit()
                        final_db.expire(record, ["tools"])
                        result = message_json(record)
                    else:
                        result = None
            if failure:
                yield json.dumps({"type": "error", "message": failure}) + "\n"
            elif result:
                yield json.dumps({"type": "done", "user": user_json, "assistant": result}) + "\n"

        return StreamingResponse(generate(), media_type="application/x-ndjson", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"})

    dist = Path(__file__).resolve().parents[1] / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/favicon.svg")
    def favicon():
        return FileResponse(Path(__file__).resolve().parents[1] / "public" / "favicon.svg")

    @app.get("/")
    def index():
        if not (dist / "index.html").is_file():
            raise HTTPException(503, "Build the React frontend first, or use the Vite development server.")
        return FileResponse(dist / "index.html")

    return app
