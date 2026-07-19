import asyncio
from app.database import engine
from app.models import Base
async def main():
    async with engine.begin() as conn:
        await conn.execute(
            __import__("sqlalchemy", fromlist=["text"]).text("CREATE EXTENSION IF NOT EXISTS vector")
        )
        await conn.run_sync(Base.metadata.create_all)
        from sqlalchemy import text
        await conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;'))
        await conn.execute(text('ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;'))
        await conn.execute(text('ALTER TABLE workspace_folders ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;'))
        await conn.execute(text('ALTER TABLE workspace_folders ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;'))
        await conn.execute(text('ALTER TABLE workspace_roles ADD COLUMN IF NOT EXISTS can_modify_graph BOOLEAN NOT NULL DEFAULT false;'))
        await conn.execute(text("ALTER TABLE workspace_roles ADD COLUMN IF NOT EXISTS branch VARCHAR(128) DEFAULT 'Main';"))
        await conn.execute(text("ALTER TABLE workspace_roles ADD COLUMN IF NOT EXISTS parent_role_id UUID REFERENCES workspace_roles(role_id) ON DELETE SET NULL;"))
        try:
            await conn.execute(text("ALTER TABLE workspace_roles DROP CONSTRAINT IF EXISTS uq_workspace_role_level;"))
            await conn.execute(text("ALTER TABLE workspace_roles DROP CONSTRAINT IF EXISTS uq_workspace_role_branch_level;"))
            await conn.execute(text("ALTER TABLE workspace_roles ADD CONSTRAINT uq_workspace_role_branch_level UNIQUE (workspace_id, branch, level);"))
        except Exception:
            pass
        try:
            await conn.execute(text('ALTER TABLE chunk_embeddings ALTER COLUMN embedding TYPE vector(768);'))
        except Exception:
            pass
asyncio.run(main())
