from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ─── Auth ─────────────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=256)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    full_name: str


class UserOut(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Workspace Roles (level-based) ────────────────────────────────────────────

class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    level: int = Field(ge=1, le=9999, description="1 = highest authority, higher numbers = lower priority")
    description: Optional[str] = None
    branch: Optional[str] = Field("Main", max_length=128, description="Organizational branch or department name")
    parent_role_id: Optional[UUID] = None
    can_modify_graph: Optional[bool] = False


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None
    branch: Optional[str] = Field(None, max_length=128)
    parent_role_id: Optional[UUID] = None
    can_modify_graph: Optional[bool] = None


class RoleOut(BaseModel):
    role_id: UUID
    workspace_id: UUID
    name: str
    level: int
    description: Optional[str]
    branch: Optional[str] = "Main"
    parent_role_id: Optional[UUID] = None
    member_count: int = 0
    can_modify_graph: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class SwapLevelsRequest(BaseModel):
    """
    Swaps the level numbers of two roles within the same workspace.
    All members of each role retain their role_id; only the level numbers exchange.
    This is useful when reorganizing the hierarchy (e.g. inserting a new level).
    """
    role_id_a: UUID
    role_id_b: UUID


# ─── Workspaces ───────────────────────────────────────────────────────────────

class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: Optional[str] = None
    industry: Optional[str] = None
    site_location: Optional[str] = None


class WorkspaceOut(BaseModel):
    workspace_id: UUID
    name: str
    slug: str
    description: Optional[str]
    industry: Optional[str]
    site_location: Optional[str]
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WorkspaceDetailOut(WorkspaceOut):
    member_count: int
    file_count: int
    my_role_name: str
    my_role_level: int


class WorkspaceDeleteRequest(BaseModel):
    """GitHub-style deletion: user must type the exact workspace name to confirm."""
    confirmation_name: str


class InviteMember(BaseModel):
    email: EmailStr
    role_id: UUID


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    role_id: UUID
    role_name: str
    role_level: int
    joined_at: datetime

    class Config:
        from_attributes = True


class UpdateMemberRole(BaseModel):
    role_id: UUID


# ─── Folders / Branches ───────────────────────────────────────────────────────

class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    parent_folder_id: Optional[UUID] = None
    description: Optional[str] = None
    is_inherited: bool = True
    allowed_role_ids: List[UUID] = []
    min_access_level: Optional[int] = None


class FolderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=256)
    description: Optional[str] = None
    is_inherited: Optional[bool] = None
    allowed_role_ids: Optional[List[UUID]] = None
    min_access_level: Optional[int] = None


class FolderOut(BaseModel):
    folder_id: UUID
    workspace_id: UUID
    parent_folder_id: Optional[UUID]
    name: str
    description: Optional[str]
    is_inherited: bool
    allowed_role_ids: List[UUID] = []
    min_access_level: Optional[int]
    created_at: datetime
    file_count: int = 0
    subfolder_count: int = 0

    class Config:
        from_attributes = True


# ─── Files ────────────────────────────────────────────────────────────────────

class FileOut(BaseModel):
    file_id: UUID
    document_id: UUID
    workspace_id: UUID
    folder_id: Optional[UUID] = None
    version_number: int
    parent_file_id: Optional[UUID]
    original_name: str
    mime_type: str
    file_family: str
    file_size_bytes: int
    uploader_id: UUID
    uploader_level: int
    status: str
    processing_status: str
    title: Optional[str]
    description: Optional[str]
    language: Optional[str]
    tags: Optional[list]
    keywords: Optional[list]
    is_inherited: bool = True
    allowed_role_ids: List[UUID] = []
    min_access_level: Optional[int]
    upload_ts: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class FileVersionOut(BaseModel):
    file_id: UUID
    version_number: int
    status: str
    uploader_id: UUID
    upload_ts: datetime
    file_size_bytes: int

    class Config:
        from_attributes = True


class FileStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v not in ["draft", "approved", "superseded", "archived"]:
            raise ValueError("Invalid status")
        return v


class UpdateFileACL(BaseModel):
    folder_id: Optional[UUID] = None
    is_inherited: Optional[bool] = None
    allowed_role_ids: Optional[List[UUID]] = None
    min_access_level: Optional[int] = None


class CommentCreate(BaseModel):
    content: str = Field(min_length=1)
    page_number: Optional[int] = None


class CommentOut(BaseModel):
    comment_id: UUID
    file_id: UUID
    user_id: UUID
    content: str
    page_number: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Query / Retrieval ────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    workspace_id: UUID
    top_k: int = Field(default=8, ge=1, le=20)
    use_graph: bool = True
    use_vector: bool = True
    use_metadata: bool = True


class SourceCitation(BaseModel):
    file_id: UUID
    title: Optional[str]
    original_name: str
    version_number: int
    file_family: str
    chunk_type: Optional[str]
    page_number: Optional[int]
    relevance_score: float


class QueryResponse(BaseModel):
    query_id: UUID
    answer: str
    citations: List[SourceCitation]
    related_files: List[FileOut]
    confidence: float
    no_answer: bool
    model_used: str
    latency_ms: int


# ─── Audit Log ────────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id: int
    user_id: Optional[UUID]
    workspace_id: Optional[UUID]
    file_id: Optional[UUID]
    action: str
    extra: dict
    ts: datetime

    class Config:
        from_attributes = True


# ─── Graph Mutations (Feature 1 — Shadow Overlay) ──────────────────────────────

class GraphNodeCreate(BaseModel):
    """Payload to add a custom node to the knowledge graph."""
    workspace_id: UUID
    label: str = Field(min_length=1, max_length=256)
    node_type: str = Field("entity", max_length=64)
    branch: Optional[str] = Field("Entities", max_length=128)
    properties: Optional[Dict[str, Any]] = None


class GraphEdgeCreate(BaseModel):
    """Payload to add a shadow edge to the user-overlay graph."""
    workspace_id: UUID
    from_node_id: UUID
    to_node_id: UUID
    label: Optional[str] = Field(default=None, max_length=256)  # e.g. "referenced by"
    comment: Optional[str] = Field(default=None)                 # user annotation
    weight: float = Field(default=0.5, ge=0.0, le=1.0)


class GraphEdgeDelete(BaseModel):
    """Payload to mark a base graph edge as deleted in the shadow overlay."""
    workspace_id: UUID
    from_node_id: UUID
    to_node_id: UUID


class GraphMutationOut(BaseModel):
    mutation_id: UUID
    workspace_id: UUID
    from_node_id: UUID
    to_node_id: UUID
    action: str
    label: Optional[str] = None
    comment: Optional[str] = None
    weight: float
    created_by_user_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ─── RCA / SOPRAG Agent (Feature 3) ──────────────────────────────────────────

class AnomalyTrigger(BaseModel):
    """Payload to trigger the SOPRAG RCA agent for a specific asset."""
    workspace_id: UUID
    asset_id: str = Field(min_length=1, max_length=256)
    anomaly_data: Dict[str, Any] = Field(
        description="Free-form telemetry payload: sensor readings, timestamps, alert codes, etc."
    )


class RcaInsightOut(BaseModel):
    insight_id: UUID
    workspace_id: UUID
    asset_id: str
    severity_level: str
    root_cause_summary: str
    regulatory_violations: List[Dict[str, Any]]
    predictive_recommendation: str
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Maintenance Calendar Events ──────────────────────────────────────────────

class MaintenanceEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    equipment_id: Optional[str] = None
    workspace_id: UUID
    event_type: str = Field("preventive", description="preventive, shutdown, inspection, calibration, test, other")
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    repeat_rule: Optional[str] = None
    description: Optional[str] = None
    source_type: str = Field("document", description="document, query, manual")
    source_id: str = Field(..., description="document_id or query string")
    confidence: str = Field("high", description="high, medium, low")


class MaintenanceEventUpdate(BaseModel):
    title: Optional[str] = None
    equipment_id: Optional[str] = None
    event_type: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    repeat_rule: Optional[str] = None
    description: Optional[str] = None
    confidence: Optional[str] = None


class MaintenanceEventOut(BaseModel):
    event_id: UUID
    workspace_id: UUID
    title: str
    equipment_id: Optional[str]
    event_type: str
    start_at: Optional[datetime]
    end_at: Optional[datetime]
    repeat_rule: Optional[str]
    description: Optional[str]
    source_type: str
    source_id: str
    confidence: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CalendarQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language command e.g. 'Add monthly vibration analysis for compressor C-17'")
    query_id: Optional[str] = None
