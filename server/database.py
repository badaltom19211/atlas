from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from .config import Settings


def now():
    return datetime.now(timezone.utc)


def identifier():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "atlas_users"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # Databricks issuer + subject hash
    name: Mapped[str] = mapped_column(String(250))
    email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AppSession(Base):
    __tablename__ = "atlas_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("atlas_users.id", ondelete="CASCADE"), index=True)
    device: Mapped[str] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Conversation(Base):
    __tablename__ = "atlas_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(ForeignKey("atlas_users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    generation_started: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    messages: Mapped[list["Message"]] = relationship(cascade="all, delete-orphan", order_by="Message.created_at", lazy="selectin")


class Message(Base):
    __tablename__ = "atlas_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("atlas_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(String(4), nullable=True)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(12), default="complete")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    comments: Mapped[list["Comment"]] = relationship(cascade="all, delete-orphan", order_by="Comment.created_at", lazy="selectin")
    tools: Mapped[list["ToolRun"]] = relationship(cascade="all, delete-orphan", order_by="ToolRun.created_at", lazy="selectin")


class ToolRun(Base):
    __tablename__ = "atlas_tool_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    message_id: Mapped[str] = mapped_column(ForeignKey("atlas_messages.id", ondelete="CASCADE"), index=True)
    call_id: Mapped[str] = mapped_column(String(250))
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16))
    input: Mapped[str] = mapped_column(Text)
    output: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Comment(Base):
    __tablename__ = "atlas_comments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    message_id: Mapped[str] = mapped_column(ForeignKey("atlas_messages.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


Index("atlas_messages_order", Message.conversation_id, Message.created_at)


def create_database(settings: Settings):
    settings.validate_database()
    # Each newly opened physical connection gets a fresh short-lived OAuth credential.
    # The pool recycles connections before the one-hour credential lifetime.
    import psycopg
    import certifi
    from .databricks_client import workspace_client
    workspace = workspace_client(settings)

    def connect():
        credential = workspace.postgres.generate_database_credential(endpoint=settings.lakebase_endpoint)
        return psycopg.connect(host=settings.pg_host, port=settings.pg_port,
                              dbname=settings.pg_database, user=settings.pg_user,
                              password=credential.token, sslmode=settings.pg_sslmode,
                              sslrootcert=certifi.where() if settings.pg_sslrootcert == "certifi" else settings.pg_sslrootcert,
                              connect_timeout=10)

    engine = create_engine("postgresql+psycopg://", creator=connect, pool_size=5,
                           max_overflow=5, pool_recycle=2700, pool_pre_ping=True)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def timestamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def comment_json(comment):
    return {"id": comment.id, "text": comment.text, "createdAt": timestamp(comment.created_at)}


def message_json(message):
    return {"id": message.id, "role": message.role, "content": message.content,
            "createdAt": timestamp(message.created_at), "feedback": message.feedback,
            "saved": message.saved, "status": message.status,
            "comments": [comment_json(c) for c in message.comments],
            "tools": [{"id": t.call_id, "name": t.name, "status": t.status, "input": t.input, "output": t.output} for t in message.tools]}


def conversation_json(conversation):
    return {"id": conversation.id, "title": conversation.title,
            "createdAt": timestamp(conversation.created_at), "updatedAt": timestamp(conversation.updated_at),
            "pinned": conversation.pinned, "archived": conversation.archived,
            "messages": [message_json(m) for m in conversation.messages]}
