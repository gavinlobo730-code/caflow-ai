"""
Knowledge Base + Client Instructions router (Amendment v1.1 FR-KB, Batch 6).

Firm-audience only (no portal exposure). Firm/department article endpoints under
/api/knowledge; client-scoped articles + instructions under /api/clients/{client_id}/...
(so the Batch-2.1 require_client_access guard gates the internal practice client).

RBAC: knowledge (read=ALL_STAFF, write=Manager+); client_instruction (read=ALL_STAFF,
write=Executive+). Assignment-gating + internal-client (G1) enforced in the service.
"""
from typing import Optional
from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, field_validator

from models.common import api_response
from core.permissions import rbac
from services import knowledge_service as kb

router = APIRouter(tags=["knowledge"])

_SCOPES = ("firm", "department", "client")


class ArticleCreateIn(BaseModel):
    scope: str
    title: str
    content: str = ""
    department: Optional[str] = None
    client_id: Optional[str] = None
    tags: list[str] = []

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: str) -> str:
        if v not in _SCOPES:
            raise ValueError("scope must be firm | department | client")
        return v


class ArticleEditIn(BaseModel):
    content: str


class InstructionCreateIn(BaseModel):
    title: str
    body: str = ""
    is_pinned: bool = False


class InstructionUpdateIn(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    is_pinned: Optional[bool] = None


# ── Firm / department Knowledge Base ─────────────────────────────────────────

@router.get("/api/knowledge/articles")
def list_articles(query: Optional[str] = Query(None), scope: Optional[str] = Query(None),
                  include_archived: bool = Query(False),
                  current_user: dict = Depends(rbac("knowledge", "read"))):
    return api_response(True, kb.search_articles(current_user, query, scope, None, include_archived))


@router.post("/api/knowledge/articles")
def create_article(body: ArticleCreateIn, current_user: dict = Depends(rbac("knowledge", "write"))):
    art = kb.create_article(current_user, body.scope, body.title, body.content,
                            body.department, body.client_id, body.tags)
    return api_response(True, art)


@router.get("/api/knowledge/articles/{article_id}")
def get_article(article_id: str = Path(...), current_user: dict = Depends(rbac("knowledge", "read"))):
    return api_response(True, kb.get_article(current_user, article_id))


@router.get("/api/knowledge/articles/{article_id}/versions")
def list_versions(article_id: str = Path(...), current_user: dict = Depends(rbac("knowledge", "read"))):
    return api_response(True, kb.list_versions(current_user, article_id))


@router.post("/api/knowledge/articles/{article_id}/versions")
def edit_article(article_id: str, body: ArticleEditIn, current_user: dict = Depends(rbac("knowledge", "write"))):
    return api_response(True, kb.edit_article(current_user, article_id, body.content))


@router.post("/api/knowledge/articles/{article_id}/restore/{version}")
def restore_version(article_id: str, version: int, current_user: dict = Depends(rbac("knowledge", "write"))):
    return api_response(True, kb.restore_version(current_user, article_id, version))


@router.post("/api/knowledge/articles/{article_id}/archive")
def archive_article(article_id: str, current_user: dict = Depends(rbac("knowledge", "write"))):
    return api_response(True, kb.archive_article(current_user, article_id))


# ── Client-scoped: instructions + client knowledge (guarded by require_client_access) ─

@router.get("/api/clients/{client_id}/instructions")
def list_instructions(client_id: str = Path(...), current_user: dict = Depends(rbac("client_instruction", "read"))):
    return api_response(True, kb.list_client_instructions(current_user, client_id))


@router.post("/api/clients/{client_id}/instructions")
def create_instruction(client_id: str, body: InstructionCreateIn,
                       current_user: dict = Depends(rbac("client_instruction", "write"))):
    return api_response(True, kb.create_instruction(current_user, client_id, body.title, body.body, body.is_pinned))


@router.patch("/api/clients/{client_id}/instructions/{instruction_id}")
def update_instruction(client_id: str, instruction_id: str, body: InstructionUpdateIn,
                       current_user: dict = Depends(rbac("client_instruction", "write"))):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    return api_response(True, kb.update_instruction(current_user, client_id, instruction_id, fields))


@router.post("/api/clients/{client_id}/instructions/{instruction_id}/archive")
def archive_instruction(client_id: str, instruction_id: str,
                        current_user: dict = Depends(rbac("client_instruction", "write"))):
    return api_response(True, kb.update_instruction(current_user, client_id, instruction_id, {"is_archived": True}))


@router.get("/api/clients/{client_id}/knowledge")
def client_knowledge(client_id: str = Path(...), query: Optional[str] = Query(None),
                     current_user: dict = Depends(rbac("knowledge", "read"))):
    return api_response(True, kb.search_articles(current_user, query, "client", client_id, False))
