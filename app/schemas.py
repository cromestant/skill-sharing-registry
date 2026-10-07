"""Pydantic request/response schemas for API v0."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ---- publish ------------------------------------------------------------


class PublishRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    complaint: str = Field(
        min_length=1,
        max_length=20000,
        description="The problem this solved, in the words you'd use complaining about it.",
    )
    what_it_does: str = Field(min_length=1, max_length=20000)
    setup_doc: str = Field(min_length=1, max_length=20000)
    prerequisites: str = Field(default="", max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    manifest: dict = Field(
        default_factory=dict,
        description="Machine layer: schedules, tools, data scopes the installing agent reads.",
    )
    parent_recipe_id: uuid.UUID | None = Field(
        default=None,
        description="Set when this recipe amends/improves an existing one.",
    )


class PublishResponse(BaseModel):
    id: uuid.UUID
    status: str


# ---- search -------------------------------------------------------------


class SearchRequest(BaseModel):
    query_text: str | None = Field(default=None, max_length=2000)
    query_vector: list[float] | None = Field(default=None)
    model: str | None = Field(
        default=None, description="Embedding model id, required with query_vector."
    )
    tags: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=10, ge=1, le=50)


class SearchHit(BaseModel):
    id: uuid.UUID
    title: str
    complaint: str
    what_it_does: str
    tags: list[str]
    score: float
    similarity: float
    clean_attestations: int
    parent_recipe_id: uuid.UUID | None = None


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    model: dict


# ---- fetch --------------------------------------------------------------


class RecipeResponse(BaseModel):
    id: uuid.UUID
    title: str
    complaint: str
    what_it_does: str
    setup_doc: str
    prerequisites: str
    tags: list[str]
    manifest: dict
    parent_recipe_id: uuid.UUID | None
    status: str
    clean_attestations: int
    created_at: datetime


# ---- attest / report ----------------------------------------------------


class AttestRequest(BaseModel):
    outcome: str = Field(
        description="installed_clean | installed_with_issues | failed"
    )
    runs: int = Field(default=1, ge=1)
    note: str = Field(default="", max_length=5000)


class AttestResponse(BaseModel):
    id: uuid.UUID
    outcome: str


class ReportRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=5000)


class ReportResponse(BaseModel):
    id: uuid.UUID
    status: str


# ---- invites ------------------------------------------------------------


class InviteRequest(BaseModel):
    expires_in_days: int = Field(
        default=7, ge=1, le=30, description="How long the code stays redeemable."
    )
    max_uses: int = Field(
        default=1, ge=1, le=25, description="How many agents may redeem this code."
    )
    note: str = Field(default="", max_length=200, description="Who this code is for.")


class InviteResponse(BaseModel):
    code: str = Field(description="Plaintext invite code — shown once, store it now.")
    expires_at: datetime
    max_uses: int


class RedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)


class RedeemResponse(BaseModel):
    agent_id: uuid.UUID
    api_key: str = Field(description="The new agent's API key — shown once.")
    display_name: str


# ---- public join --------------------------------------------------------


class JoinRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)


class JoinResponse(BaseModel):
    agent_id: uuid.UUID
    api_key: str = Field(description="The new agent's API key — shown once.")
    display_name: str


class StatsResponse(BaseModel):
    agents_active: int
    spots_total: int
    spots_remaining: int
    recipes_active: int
