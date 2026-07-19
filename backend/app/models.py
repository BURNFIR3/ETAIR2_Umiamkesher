import uuid
import enum
from datetime import datetime
from typing import Any, Dict, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum as SAEnum, Float, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ─── Enums ────────────────────────────────────────────────────────────────────

class FileFamily(str, enum.Enum):
    TEXT_OFFICE = "text_office"
    TABLE = "table"
    IMAGE = "image"
    AUDIO = "audio"
    CAD = "cad"
    OPERATIONAL = "operational"
    UNKNOWN = "unknown"


class FileStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class EdgeType(str, enum.Enum):
    SUPERSEDED_BY = "SUPERSEDED_BY"
    HAS_VERSION = "HAS_VERSION"
    BELONGS_TO_WORKSPACE = "BELONGS_TO_WORKSPACE"
    BELONGS_TO_ASSET = "BELONGS_TO_ASSET"
    UPLOADED_BY = "UPLOADED_BY"
    ACCESSIBLE_BY = "ACCESSIBLE_BY"
    REFERENCES = "REFERENCES"
    MENTIONS_ENTITY = "MENTIONS_ENTITY"
    SIMILAR_TO = "SIMILAR_TO"
    DERIVED_FROM = "DERIVED_FROM"
    RELATED_TO_TOPIC = "RELATED_TO_TOPIC"
    PART_OF_PROJECT = "PART_OF_PROJECT"
    LINKED_PROCEDURE = "LINKED_PROCEDURE"


class GraphMutationAction(str, enum.Enum):
    ADD = "ADD"
    DELETE = "DELETE"


# ─── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), unique=True, nullable=False, index=True)
    hashed_password = Column(String(256), nullable=False)
    full_name = Column(String(256), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    memberships = relationship("WorkspaceMember", back_populates="user")
    uploaded_files = relationship("File", back_populates="uploader")


# ─── Workspaces ───────────────────────────────────────────────────────────────

class Workspace(Base):
    __tablename__ = "workspaces"

    workspace_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(256), nullable=False)
    slug = Column(String(256), unique=True, nullable=False, index=True)
    description = Column(Text)
    industry = Column(String(128))
    site_location = Column(String(256))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    # ─ Soft-delete (Feature 2) ─
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    members = relationship("WorkspaceMember", back_populates="workspace")
    roles = relationship("WorkspaceRole", back_populates="workspace", cascade="all, delete-orphan")
    folders = relationship("WorkspaceFolder", back_populates="workspace", cascade="all, delete-orphan")
    files = relationship("File", back_populates="workspace")


class WorkspaceRole(Base):
    """
    User-defined roles for a workspace, supporting dynamic role hierarchies and branches.
    Level 1 = highest authority. Higher numbers = less authority.
    Roles can belong to organizational branches (departments) or form tree hierarchies via parent_role_id.
    Two roles cannot share the same level within the exact same branch in a workspace.
    """
    __tablename__ = "workspace_roles"

    role_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)            # e.g. "Senior Engineer"
    level = Column(Integer, nullable=False)               # 1 = highest, bigger = lower priority
    description = Column(Text)
    branch = Column(String(128), nullable=True, default="Main")  # e.g. "Engineering", "Operations", "Main"
    parent_role_id = Column(UUID(as_uuid=True), ForeignKey("workspace_roles.role_id", ondelete="SET NULL"), nullable=True)
    # ─ Human-in-the-Loop Graph permission (Feature 1) ─
    can_modify_graph = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="roles")
    members = relationship("WorkspaceMember", back_populates="workspace_role")
    parent_role = relationship("WorkspaceRole", remote_side=[role_id], backref="child_roles")

    __table_args__ = (
        UniqueConstraint("workspace_id", "branch", "level", name="uq_workspace_role_branch_level"),
        UniqueConstraint("workspace_id", "name", name="uq_workspace_role_name"),
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("workspace_roles.role_id"), nullable=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="memberships")
    workspace_role = relationship("WorkspaceRole", back_populates="members")


class WorkspaceFolder(Base):
    """
    Branches / folders inside a workspace. Serves as organization containers
    and supports hierarchical access inheritance.
    """
    __tablename__ = "workspace_folders"

    folder_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False, index=True)
    parent_folder_id = Column(UUID(as_uuid=True), ForeignKey("workspace_folders.folder_id"), nullable=True, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text)

    # Governance & ACLs
    is_inherited = Column(Boolean, nullable=False, default=True)
    allowed_role_ids = Column(ARRAY(UUID(as_uuid=True)), default=[])
    min_access_level = Column(Integer, nullable=True)

    # ─ Soft-delete (Feature 2) ─
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="folders")
    parent = relationship("WorkspaceFolder", remote_side=[folder_id], back_populates="children")
    children = relationship("WorkspaceFolder", back_populates="parent", cascade="all, delete-orphan")
    files = relationship("File", back_populates="folder")


# ─── Files ────────────────────────────────────────────────────────────────────

class File(Base):
    __tablename__ = "files"

    file_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # stable logical doc ID
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False, index=True)
    folder_id = Column(UUID(as_uuid=True), ForeignKey("workspace_folders.folder_id"), nullable=True, index=True)
    version_number = Column(Integer, nullable=False, default=1)
    parent_file_id = Column(UUID(as_uuid=True), ForeignKey("files.file_id"), nullable=True)

    # Identity
    original_name = Column(String(512), nullable=False)
    storage_key = Column(Text, nullable=False)          # S3/MinIO object key
    content_hash = Column(String(64), nullable=False, index=True)  # SHA-256
    mime_type = Column(String(256), nullable=False)
    file_family = Column(String(64), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)

    # Provenance
    uploader_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    uploader_level = Column(Integer, nullable=False)    # level of uploader's role at time of upload
    upload_ts = Column(DateTime(timezone=True), server_default=func.now())
    source_system = Column(String(128), default="manual_upload")

    # Status
    status = Column(String(32), nullable=False, default=FileStatus.DRAFT.value)
    processing_status = Column(String(32), nullable=False, default=ProcessingStatus.PENDING.value)
    processing_error = Column(Text, nullable=True)

    # Enriched fields (populated by workers)
    title = Column(String(512))
    description = Column(Text)
    language = Column(String(16))
    tags = Column(ARRAY(Text), default=[])
    keywords = Column(ARRAY(Text), default=[])

    # Access control — inheritance and group/clearance ACLs
    is_inherited = Column(Boolean, nullable=False, default=True)
    allowed_role_ids = Column(ARRAY(UUID(as_uuid=True)), default=[])
    min_access_level = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="files")
    folder = relationship("WorkspaceFolder", back_populates="files")
    uploader = relationship("User", back_populates="uploaded_files")
    file_metadata = relationship("FileMetadata", back_populates="file", uselist=False)
    chunks = relationship("FileChunk", back_populates="file")
    entities = relationship("FileEntity", back_populates="file")
    access_overrides = relationship("FileAccessOverride", back_populates="file")
    comments = relationship("FileComment", back_populates="file")

    __table_args__ = (
        Index("idx_files_workspace_status", "workspace_id", "status"),
        Index("idx_files_content_hash", "content_hash"),
    )


class FileMetadata(Base):
    """Family-specific metadata stored as JSONB."""
    __tablename__ = "file_metadata"

    file_id = Column(UUID(as_uuid=True), ForeignKey("files.file_id"), primary_key=True)
    family_data = Column(JSONB, nullable=False, default=dict)

    file = relationship("File", back_populates="file_metadata")


class FileAccessOverride(Base):
    __tablename__ = "file_access_overrides"

    file_id = Column(UUID(as_uuid=True), ForeignKey("files.file_id"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True)
    access_type = Column(String(8), nullable=False)   # 'grant' or 'deny'
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    file = relationship("File", back_populates="access_overrides")


# ─── Chunks + Embeddings ──────────────────────────────────────────────────────

class FileChunk(Base):
    __tablename__ = "file_chunks"

    chunk_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.file_id"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_type = Column(String(64), nullable=False)  # page, paragraph, slide, row_group, transcript_segment, region
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    token_count = Column(Integer)

    # Location metadata (family-specific, nullable)
    page_number = Column(Integer)
    slide_number = Column(Integer)
    row_start = Column(Integer)
    row_end = Column(Integer)
    timestamp_start = Column(Float)   # audio
    timestamp_end = Column(Float)     # audio

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    file = relationship("File", back_populates="chunks")
    embedding = relationship("ChunkEmbedding", back_populates="chunk", uselist=False)


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    chunk_id = Column(UUID(as_uuid=True), ForeignKey("file_chunks.chunk_id"), primary_key=True)
    embedding = Column(Vector(768))   # Gemini text-embedding-004 (768-dim)
    model_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chunk = relationship("FileChunk", back_populates="embedding")


# ─── Entities ─────────────────────────────────────────────────────────────────

class FileEntity(Base):
    __tablename__ = "file_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.file_id"), nullable=False, index=True)
    entity_type = Column(String(64), nullable=False)  # equipment, person, location, standard, work_order, asset
    entity_value = Column(String(512), nullable=False)
    confidence = Column(Float)
    source_chunk_id = Column(UUID(as_uuid=True), ForeignKey("file_chunks.chunk_id"), nullable=True)

    file = relationship("File", back_populates="entities")

    __table_args__ = (
        Index("idx_entities_type_value", "entity_type", "entity_value"),
    )


# ─── Knowledge Graph ──────────────────────────────────────────────────────────

class GraphNode(Base):
    __tablename__ = "graph_nodes"

    node_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_type = Column(String(64), nullable=False)   # file, document, asset, person, role, workspace, topic, equipment, work_order
    external_id = Column(String(256), index=True)    # FK to actual table PK as string
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=True)
    label = Column(String(512), nullable=False)
    properties = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    outgoing_edges = relationship("GraphEdge", foreign_keys="GraphEdge.from_node_id", back_populates="from_node")
    incoming_edges = relationship("GraphEdge", foreign_keys="GraphEdge.to_node_id", back_populates="to_node")


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    edge_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.node_id"), nullable=False)
    to_node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.node_id"), nullable=False)
    edge_type = Column(String(64), nullable=False)
    weight = Column(Float, default=1.0)
    properties = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    from_node = relationship("GraphNode", foreign_keys=[from_node_id], back_populates="outgoing_edges")
    to_node = relationship("GraphNode", foreign_keys=[to_node_id], back_populates="incoming_edges")

    __table_args__ = (
        Index("idx_edges_from_type", "from_node_id", "edge_type"),
        Index("idx_edges_to_type", "to_node_id", "edge_type"),
    )


# ─── Human-in-the-Loop Graph Mutations (Feature 1 — Shadow Overlay) ───────────

class UserGraphMutation(Base):
    """
    Shadow overlay layer for the machine-generated knowledge graph.
    Users with can_modify_graph=True on their role may ADD or DELETE virtual
    edges without mutating the base graph_edges table.
    """
    __tablename__ = "user_graph_mutations"

    mutation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False, index=True)
    from_node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.node_id"), nullable=False)
    to_node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.node_id"), nullable=False)
    action = Column(
        SAEnum(GraphMutationAction, name="graphmutationaction", create_type=True),
        nullable=False,
    )
    label = Column(String(256), nullable=True)        # user-defined edge label e.g. "referenced by"
    comment = Column(Text, nullable=True)             # user annotation/note on this edge
    weight = Column(Float, default=0.5, nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    workspace = relationship("Workspace")
    from_node = relationship("GraphNode", foreign_keys=[from_node_id])
    to_node = relationship("GraphNode", foreign_keys=[to_node_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    __table_args__ = (
        Index("idx_mutations_workspace", "workspace_id"),
        Index("idx_mutations_nodes", "from_node_id", "to_node_id"),
    )


# ─── RCA Insights (Feature 3 — SOPRAG Agent) ──────────────────────────────────

class RcaInsight(Base):
    """
    Stores the structured output from the SOPRAG Predictive RCA Agent.
    Each insight is generated asynchronously by the analyze_anomaly_task Celery worker.
    """
    __tablename__ = "rca_insights"

    insight_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False, index=True)
    asset_id = Column(String(256), nullable=False, index=True)
    severity_level = Column(String(64), nullable=False)          # e.g. CRITICAL, HIGH, MEDIUM, LOW
    root_cause_summary = Column(Text, nullable=False)
    regulatory_violations = Column(JSONB, default=list)          # e.g. [{"standard": "OSHA 1910.147", "clause": "..."}]
    predictive_recommendation = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    workspace = relationship("Workspace")

    __table_args__ = (
        Index("idx_rca_workspace_asset", "workspace_id", "asset_id"),
        Index("idx_rca_created_at", "created_at"),
    )


# ─── Comments ─────────────────────────────────────────────────────────────────

class FileComment(Base):
    __tablename__ = "file_comments"

    comment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.file_id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    content = Column(Text, nullable=False)
    page_number = Column(Integer)   # optional: page-anchored comment
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    file = relationship("File", back_populates="comments")


# ─── Audit Log ────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.file_id"), nullable=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=True)
    action = Column(String(64), nullable=False)  # view, download, query_used, upload, approve, supersede
    ip_address = Column(INET, nullable=True)
    extra = Column(JSONB, default=dict)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# ─── Query History ────────────────────────────────────────────────────────────

class QueryHistory(Base):
    __tablename__ = "query_history"

    query_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    query_text = Column(Text, nullable=False)
    answer_text = Column(Text)
    source_file_ids = Column(ARRAY(UUID(as_uuid=True)), default=[])
    confidence = Column(Float)
    no_answer = Column(Boolean, default=False)
    model_used = Column(String(64))
    latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# ─── Maintenance Calendar Events ──────────────────────────────────────────────

class MaintenanceEvent(Base):
    __tablename__ = "maintenance_events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.workspace_id"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    equipment_id = Column(String(256), nullable=True, index=True)  # matching asset tag e.g. P-101
    event_type = Column(String(64), nullable=False, default="preventive")  # preventive, shutdown, inspection, calibration, test, other
    start_at = Column(DateTime(timezone=True), nullable=True, index=True)
    end_at = Column(DateTime(timezone=True), nullable=True)
    repeat_rule = Column(String(256), nullable=True)  # e.g. "every 3 months"
    description = Column(Text, nullable=True)
    source_type = Column(String(32), nullable=False, default="document")  # document, query, manual
    source_id = Column(String(256), nullable=False, index=True)  # document_id or query ID
    confidence = Column(String(32), nullable=False, default="high")  # high, medium, low
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_maintenance_events_workspace_start", "workspace_id", "start_at"),
        Index("idx_maintenance_events_workspace_equip", "workspace_id", "equipment_id"),
    )
