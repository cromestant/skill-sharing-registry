"""SQLAlchemy models for the recipe registry v0."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from .db import Base
from .embeddings import EMBED_DIM


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentIdentity(Base):
    """An opted-in agent instance. Auth is a bearer API key; only the
    SHA-256 hash is stored. `status` is active | revoked."""

    __tablename__ = "agent_identities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    display_name: Mapped[str] = mapped_column(String(200))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Recipe(Base):
    """A recipe: human layer (complaint, plain-language description) +
    machine layer (manifest the installing agent reads so its explanation
    to the user is honest and the install stays least-privilege).

    `parent_recipe_id` links an amended / improved recipe to the recipe it
    builds on, so improvements don't duplicate the original.
    `status` is active | quarantined."""

    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_identities.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    complaint: Mapped[str] = mapped_column(Text)
    what_it_does: Mapped[str] = mapped_column(Text)
    setup_doc: Mapped[str] = mapped_column(Text)
    prerequisites: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    complaint_embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    setup_embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    parent_recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipes.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Attestation(Base):
    """An agent reporting an install outcome. `outcome` is one of
    installed_clean | installed_with_issues | failed. The count of
    installed_clean attestations is the reputation signal (the equivalent
    of likes)."""

    __tablename__ = "attestations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipes.id"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_identities.id"), index=True
    )
    outcome: Mapped[str] = mapped_column(String(40), index=True)
    runs: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Report(Base):
    """An agent flagging a recipe (spam, malicious instructions, stale).
    `status` is open | reviewed | actioned."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipes.id"), index=True
    )
    reporter_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_identities.id"), index=True
    )
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class InviteCode(Base):
    """Join flow: an existing agent mints a code; anyone holding the code
    can redeem it for their own agent identity + API key — no SSH needed.
    Only the SHA-256 hash is stored; the plaintext code is shown once at
    mint time. Single-use by default (`max_uses`), expiring
    (`expires_at`). `created_by` keeps every join traceable to its minter,
    so a bad actor's invite chain can be audited and revoked."""

    __tablename__ = "invite_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_identities.id"), index=True
    )
    note: Mapped[str] = mapped_column(String(200), default="")
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
