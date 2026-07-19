from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import settings

import ssl
from urllib.parse import urlparse

# Handle Supabase/remote Postgres SSL parameters for asyncpg
_db_url = settings.DATABASE_URL
_connect_args = {}
if ".supabase.co" in _db_url or ".supabase.com" in _db_url or "ssl=require" in _db_url or "sslmode=require" in _db_url:
    # asyncpg expects connect_args={"ssl": ssl_context} rather than ?sslmode=require query params
    # Supabase pooler uses self-signed cert chain — disable verification
    if "?" in _db_url:
        _db_url = _db_url.split("?")[0]
    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE
    _connect_args["ssl"] = _ssl_ctx

engine = create_async_engine(
    _db_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables():
    """Create all tables. Used in dev; production uses Alembic migrations."""
    from app.models import Base
    async with engine.begin() as conn:
        await conn.execute(
            __import__("sqlalchemy", fromlist=["text"]).text("CREATE EXTENSION IF NOT EXISTS vector")
        )
        await conn.run_sync(Base.metadata.create_all)
