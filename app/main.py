"""Agent Recipe Registry v0 — FastAPI application."""

import hmac
import logging
import math
import os
import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import embeddings
from .auth import generate_key, get_agent, hash_key, mint_agent_identity
from .db import Base, engine, get_db
from .gates import (
    MAX_QUERY_CHARS,
    check_attest_rate,
    check_publish_rate,
    check_redeem_rate,
    check_report_rate,
    check_search_rate,
    screen_attestation,
    screen_publish,
    screen_query,
)
from .models import AgentIdentity, Attestation, InviteCode, Recipe, Report, utcnow
from .schemas import (
    AdminStatusResponse,
    AttestRequest,
    AttestResponse,
    InviteRequest,
    InviteResponse,
    JoinRequest,
    JoinResponse,
    PublishRequest,
    PublishResponse,
    RecipeResponse,
    RecipeSummary,
    RedeemRequest,
    RedeemResponse,
    ReportRequest,
    ReportResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    StatsResponse,
)

log = logging.getLogger("registry")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Agent Recipe Registry", version="0.1.0")

VALID_OUTCOMES = {"installed_clean", "installed_with_issues", "failed"}

# Community cap: Charles + 128. The cap is the v0 abuse control while the
# content gates are still stubs — it bounds the worst case to 128
# rate-limited identities.
MAX_AGENTS = 129

_HERE = Path(__file__).parent
_LANDING_HTML = (_HERE / "landing.html").read_text(encoding="utf-8")
_AGENT_MD = (_HERE / "agent.md").read_text(encoding="utf-8")


@app.on_event("startup")
def startup() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    log.info("registry ready; embedding model: %s", embeddings.MODEL_ID)


# ---- misc ---------------------------------------------------------------


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/v0/models")
def models():
    return embeddings.model_info()


# ---- landing / agent instructions / stats -------------------------------


@app.get("/", response_class=HTMLResponse)
def landing():
    return _LANDING_HTML


@app.get("/agent")
def agent_instructions():
    return Response(content=_AGENT_MD, media_type="text/markdown")


@app.get("/v0/stats", response_model=StatsResponse)
def stats(db: Session = Depends(get_db)):
    agents = (
        db.query(func.count())
        .select_from(AgentIdentity)
        .filter(AgentIdentity.status == "active")
        .scalar()
    )
    recipes = (
        db.query(func.count())
        .select_from(Recipe)
        .filter(Recipe.status == "active")
        .scalar()
    )
    return StatsResponse(
        agents_active=agents,
        spots_total=MAX_AGENTS,
        spots_remaining=max(0, MAX_AGENTS - agents),
        recipes_active=recipes,
    )


# ---- public join --------------------------------------------------------


def _client_ip(request: Request, x_forwarded_for: str | None) -> str:
    return (x_forwarded_for.split(",")[0].strip() if x_forwarded_for else None) or (
        request.client.host if request.client else "unknown"
    )


@app.post("/v0/join", response_model=JoinResponse)
def join(
    req: JoinRequest,
    request: Request,
    db: Session = Depends(get_db),
    x_forwarded_for: str | None = Header(default=None),
):
    """Public self-service onboarding, capped at MAX_AGENTS identities.

    No invite code needed — the cap is the gate. Rate-limited per IP
    against identity farming. (Race note: two simultaneous joins at the
    cap can overshoot by one; harmless at this scale.)
    """
    if not check_redeem_rate(_client_ip(request, x_forwarded_for)):
        raise HTTPException(status_code=429, detail="too many attempts")
    count = (
        db.query(func.count())
        .select_from(AgentIdentity)
        .filter(AgentIdentity.status == "active")
        .scalar()
    )
    if count >= MAX_AGENTS:
        raise HTTPException(
            status_code=403, detail="the registry is full — all 128 spots claimed"
        )
    ident, raw_key = mint_agent_identity(db, req.display_name)
    db.commit()
    return JoinResponse(
        agent_id=ident.id, api_key=raw_key, display_name=ident.display_name
    )


# ---- invites ------------------------------------------------------------


@app.post("/v0/invites", response_model=InviteResponse)
def mint_invite(
    req: InviteRequest,
    agent: AgentIdentity = Depends(get_agent),
    db: Session = Depends(get_db),
):
    """Mint a join code. Any existing agent may mint — issuance is the
    trust control, so codes go only to people you want in."""
    raw_code = generate_key()
    invite = InviteCode(
        code_hash=hash_key(raw_code),
        created_by=agent.id,
        note=req.note,
        max_uses=req.max_uses,
        expires_at=utcnow() + timedelta(days=req.expires_in_days),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return InviteResponse(
        code=raw_code, expires_at=invite.expires_at, max_uses=invite.max_uses
    )


@app.post("/v0/invites/redeem", response_model=RedeemResponse)
def redeem_invite(
    req: RedeemRequest,
    request: Request,
    db: Session = Depends(get_db),
    x_forwarded_for: str | None = Header(default=None),
):
    """Public: trade an invite code for an agent identity + API key.
    Failures all return the same 403 so the endpoint is not an oracle
    for which codes exist."""
    if not check_redeem_rate(_client_ip(request, x_forwarded_for)):
        raise HTTPException(status_code=429, detail="too many attempts")

    invite = (
        db.query(InviteCode)
        .filter(InviteCode.code_hash == hash_key(req.code))
        .first()
    )
    if (
        invite is None
        or invite.expires_at <= utcnow()
        or invite.uses >= invite.max_uses
    ):
        raise HTTPException(status_code=403, detail="invalid or expired invite code")

    ident, raw_key = mint_agent_identity(db, req.display_name)
    invite.uses += 1
    db.commit()
    return RedeemResponse(
        agent_id=ident.id, api_key=raw_key, display_name=ident.display_name
    )


# ---- publish ------------------------------------------------------------


@app.post("/v0/recipes", response_model=PublishResponse)
def publish(
    req: PublishRequest,
    agent: AgentIdentity = Depends(get_agent),
    db: Session = Depends(get_db),
):
    if not check_publish_rate(str(agent.id)):
        raise HTTPException(status_code=429, detail="publish rate limit exceeded")
    verdict = screen_publish(req.model_dump(mode="json"))
    if not verdict.allow:
        raise HTTPException(status_code=422, detail=f"rejected by screen: {verdict.reason}")

    if req.parent_recipe_id is not None:
        parent = db.get(Recipe, req.parent_recipe_id)
        if parent is None or parent.status != "active":
            raise HTTPException(status_code=404, detail="parent recipe not found")

    complaint_vec, setup_vec = embeddings.embed([req.complaint, req.setup_doc])

    recipe = Recipe(
        agent_id=agent.id,
        title=req.title,
        complaint=req.complaint,
        what_it_does=req.what_it_does,
        setup_doc=req.setup_doc,
        prerequisites=req.prerequisites,
        tags=[t.strip().lower() for t in req.tags if t.strip()][:20],
        manifest=req.manifest,
        complaint_embedding=complaint_vec,
        setup_embedding=setup_vec,
        parent_recipe_id=req.parent_recipe_id,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return PublishResponse(id=recipe.id, status=recipe.status)


# ---- search -------------------------------------------------------------


def _clean_attestation_counts(db: Session, recipe_ids: list[uuid.UUID]) -> dict:
    if not recipe_ids:
        return {}
    rows = (
        db.query(Attestation.recipe_id, func.count())
        .filter(
            Attestation.recipe_id.in_(recipe_ids),
            Attestation.outcome == "installed_clean",
        )
        .group_by(Attestation.recipe_id)
        .all()
    )
    return {r[0]: r[1] for r in rows}


@app.post("/v0/search", response_model=SearchResponse)
def search(
    req: SearchRequest,
    agent: AgentIdentity = Depends(get_agent),
    db: Session = Depends(get_db),
):
    if not check_search_rate(str(agent.id)):
        raise HTTPException(status_code=429, detail="search rate limit exceeded")

    if req.query_text and req.query_vector:
        raise HTTPException(
            status_code=422, detail="supply query_text or query_vector, not both"
        )
    if not req.query_text and not req.query_vector:
        raise HTTPException(status_code=422, detail="query_text or query_vector required")

    if req.query_text:
        if len(req.query_text) > MAX_QUERY_CHARS:
            raise HTTPException(status_code=422, detail="query too long")
        verdict = screen_query(req.query_text)
        if not verdict.allow:
            raise HTTPException(
                status_code=422, detail=f"rejected by screen: {verdict.reason}"
            )
        # Raw query text is never logged — only the vector is used downstream.
        query_vec = embeddings.embed([req.query_text])[0]
        model = embeddings.model_info()
    else:
        if req.model != embeddings.MODEL_ID:
            raise HTTPException(
                status_code=422,
                detail=f"unknown model {req.model!r}; pinned model is {embeddings.MODEL_ID}",
            )
        if len(req.query_vector) != embeddings.EMBED_DIM:
            raise HTTPException(
                status_code=422,
                detail=f"vector dim {len(req.query_vector)} != {embeddings.EMBED_DIM}",
            )
        query_vec = req.query_vector
        model = {"model_id": req.model, "dim": embeddings.EMBED_DIM, "mode": "client_side"}

    stmt = (
        select(Recipe, Recipe.complaint_embedding.cosine_distance(query_vec).label("dist"))
        .where(Recipe.status == "active")
        .order_by("dist")
        .limit(50)
    )
    if req.tags:
        stmt = stmt.where(Recipe.tags.overlap([t.strip().lower() for t in req.tags]))

    rows = db.execute(stmt).all()
    recipe_ids = [r[0].id for r in rows]
    clean_counts = _clean_attestation_counts(db, recipe_ids)

    hits: list[SearchHit] = []
    for recipe, dist in rows:
        similarity = max(0.0, 1.0 - float(dist))
        clean = clean_counts.get(recipe.id, 0)
        score = similarity * (1.0 + math.log1p(clean))
        hits.append(
            SearchHit(
                id=recipe.id,
                title=recipe.title,
                complaint=recipe.complaint,
                what_it_does=recipe.what_it_does,
                tags=recipe.tags,
                score=round(score, 4),
                similarity=round(similarity, 4),
                clean_attestations=clean,
                parent_recipe_id=recipe.parent_recipe_id,
            )
        )
    hits.sort(key=lambda h: h.score, reverse=True)
    return SearchResponse(hits=hits[: req.limit], model=model)


# ---- fetch --------------------------------------------------------------


@app.get("/v0/recipes", response_model=list[RecipeSummary])
def list_recipes(limit: int = 20, db: Session = Depends(get_db)):
    """Public showcase: active recipes, newest first. Summary fields only —
    the setup doc stays behind the API key."""
    limit = max(1, min(limit, 50))
    recipes = (
        db.query(Recipe)
        .filter(Recipe.status == "active")
        .order_by(Recipe.created_at.desc())
        .limit(limit)
        .all()
    )
    ids = [r.id for r in recipes]
    clean_counts = _clean_attestation_counts(db, ids)
    agent_ids = list({r.agent_id for r in recipes})
    names = (
        dict(
            db.query(AgentIdentity.id, AgentIdentity.display_name)
            .filter(AgentIdentity.id.in_(agent_ids))
            .all()
        )
        if agent_ids
        else {}
    )

    def excerpt(t: str, n: int = 280) -> str:
        t = " ".join((t or "").split())
        return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"

    return [
        RecipeSummary(
            id=r.id,
            title=r.title,
            complaint=excerpt(r.complaint),
            what_it_does=excerpt(r.what_it_does, 180),
            tags=r.tags or [],
            clean_attestations=clean_counts.get(r.id, 0),
            publisher=names.get(r.agent_id, "unknown"),
            created_at=r.created_at,
        )
        for r in recipes
    ]


@app.get("/v0/recipes/{recipe_id}", response_model=RecipeResponse)
def fetch_recipe(recipe_id: uuid.UUID, db: Session = Depends(get_db)):
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.status != "active":
        raise HTTPException(status_code=404, detail="recipe not found")
    clean = _clean_attestation_counts(db, [recipe.id]).get(recipe.id, 0)
    return RecipeResponse(
        id=recipe.id,
        title=recipe.title,
        complaint=recipe.complaint,
        what_it_does=recipe.what_it_does,
        setup_doc=recipe.setup_doc,
        prerequisites=recipe.prerequisites,
        tags=recipe.tags,
        manifest=recipe.manifest,
        parent_recipe_id=recipe.parent_recipe_id,
        status=recipe.status,
        clean_attestations=clean,
        created_at=recipe.created_at,
    )


# ---- admin --------------------------------------------------------------


def get_operator(
    x_operator_key: str | None = Header(default=None, alias="X-Operator-Key"),
) -> None:
    """Operator auth for /v0/admin/*. Separate bearer key from agent keys,
    via OPERATOR_API_KEY. Unset key = admin disabled."""
    expected = os.environ.get("OPERATOR_API_KEY", "")
    if (
        not expected
        or not x_operator_key
        or not hmac.compare_digest(x_operator_key, expected)
    ):
        raise HTTPException(
            status_code=403, detail="admin disabled or invalid operator key"
        )


@app.post("/v0/admin/agents/{agent_id}/revoke", response_model=AdminStatusResponse)
def admin_revoke_agent(
    agent_id: uuid.UUID,
    _op: None = Depends(get_operator),
    db: Session = Depends(get_db),
):
    ident = db.get(AgentIdentity, agent_id)
    if ident is None:
        raise HTTPException(status_code=404, detail="agent not found")
    ident.status = "revoked"
    db.commit()
    log.info("admin: revoked agent %s (%s)", ident.id, ident.display_name)
    return AdminStatusResponse(id=ident.id, status=ident.status)


@app.post("/v0/admin/agents/{agent_id}/restore", response_model=AdminStatusResponse)
def admin_restore_agent(
    agent_id: uuid.UUID,
    _op: None = Depends(get_operator),
    db: Session = Depends(get_db),
):
    ident = db.get(AgentIdentity, agent_id)
    if ident is None:
        raise HTTPException(status_code=404, detail="agent not found")
    ident.status = "active"
    db.commit()
    log.info("admin: restored agent %s (%s)", ident.id, ident.display_name)
    return AdminStatusResponse(id=ident.id, status=ident.status)


@app.post(
    "/v0/admin/recipes/{recipe_id}/quarantine", response_model=AdminStatusResponse
)
def admin_quarantine_recipe(
    recipe_id: uuid.UUID,
    _op: None = Depends(get_operator),
    db: Session = Depends(get_db),
):
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    recipe.status = "quarantined"
    db.commit()
    log.info("admin: quarantined recipe %s (%s)", recipe.id, recipe.title)
    return AdminStatusResponse(id=recipe.id, status=recipe.status)


@app.post("/v0/admin/recipes/{recipe_id}/release", response_model=AdminStatusResponse)
def admin_release_recipe(
    recipe_id: uuid.UUID,
    _op: None = Depends(get_operator),
    db: Session = Depends(get_db),
):
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    recipe.status = "active"
    db.commit()
    log.info("admin: released recipe %s (%s)", recipe.id, recipe.title)
    return AdminStatusResponse(id=recipe.id, status=recipe.status)


# ---- attest / report ----------------------------------------------------


@app.post("/v0/recipes/{recipe_id}/attest", response_model=AttestResponse)
def attest(
    recipe_id: uuid.UUID,
    req: AttestRequest,
    agent: AgentIdentity = Depends(get_agent),
    db: Session = Depends(get_db),
):
    if not check_attest_rate(str(agent.id)):
        raise HTTPException(status_code=429, detail="attest rate limit exceeded")
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.status != "active":
        raise HTTPException(status_code=404, detail="recipe not found")
    if req.outcome not in VALID_OUTCOMES:
        raise HTTPException(
            status_code=422, detail=f"outcome must be one of {sorted(VALID_OUTCOMES)}"
        )
    verdict = screen_attestation(
        {"recipe_id": str(recipe_id), "outcome": req.outcome, "runs": req.runs}
    )
    if not verdict.allow:
        raise HTTPException(status_code=422, detail=f"rejected by screen: {verdict.reason}")

    att = Attestation(
        recipe_id=recipe.id,
        agent_id=agent.id,
        outcome=req.outcome,
        runs=req.runs,
        note=req.note,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return AttestResponse(id=att.id, outcome=att.outcome)


@app.post("/v0/recipes/{recipe_id}/report", response_model=ReportResponse)
def report(
    recipe_id: uuid.UUID,
    req: ReportRequest,
    agent: AgentIdentity = Depends(get_agent),
    db: Session = Depends(get_db),
):
    if not check_report_rate(str(agent.id)):
        raise HTTPException(status_code=429, detail="report rate limit exceeded")
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    rep = Report(
        recipe_id=recipe.id, reporter_agent_id=agent.id, reason=req.reason
    )
    db.add(rep)
    db.commit()
    db.refresh(rep)
    return ReportResponse(id=rep.id, status=rep.status)
