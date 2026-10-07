"""API-key auth. Each opted-in agent instance holds a bearer key;
only the SHA-256 hash is stored server-side."""

import hashlib
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import AgentIdentity


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key() -> str:
    return secrets.token_urlsafe(32)


def mint_agent_identity(db: Session, display_name: str) -> tuple["AgentIdentity", str]:
    """Create an agent identity and return (identity, raw API key).

    Flushes (assigning the id) without committing — the caller commits.
    The raw key is returned once; only its hash is stored.
    """
    raw_key = generate_key()
    ident = AgentIdentity(display_name=display_name, api_key_hash=hash_key(raw_key))
    db.add(ident)
    db.flush()
    return ident, raw_key


def get_agent(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> AgentIdentity:
    ident = (
        db.query(AgentIdentity)
        .filter(
            AgentIdentity.api_key_hash == hash_key(x_api_key),
            AgentIdentity.status == "active",
        )
        .first()
    )
    if ident is None:
        raise HTTPException(status_code=401, detail="invalid or revoked API key")
    return ident
