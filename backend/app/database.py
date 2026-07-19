from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import settings
import ssl
from urllib.parse import unquote
from sqlalchemy.engine import URL as SA_URL

def _parse_db_url(raw_url: str, driver: str = None) -> tuple:
    """
    Robustly parse a database URL, correctly handling passwords that contain
    special characters like '@' by splitting on the LAST '@' in the URL.
    Returns (SA_URL object, connect_args dict).
    """
    url = raw_url.strip()

    # Strip query string — we handle SSL via connect_args
    if "?" in url:
        url = url.split("?")[0]

    # Determine the driver/scheme
    scheme_end = url.index("://")
    scheme = driver or url[:scheme_end]
    rest = url[scheme_end + 3:]

    # Split on the LAST '@' to correctly separate credentials from host
    last_at = rest.rfind("@")
    credentials = rest[:last_at]
    host_db = rest[last_at + 1:]

    # Parse username:password (password may itself contain ':')
    first_colon = credentials.index(":")
    username = credentials[:first_colon]
    password = unquote(credentials[first_colon + 1:])  # decode %40 → @, etc.

    # Parse host:port/database
    if "/" in host_db:
        slash = host_db.index("/")
        host_part = host_db[:slash]
        database = host_db[slash + 1:]
    else:
        host_part = host_db
        database = "postgres"

    if ":" in host_part:
        host, port_str = host_part.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_part
        port = 5432

    sa_url = SA_URL.create(
        drivername=scheme,
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
    )

    connect_args = {}
    is_remote = ".supabase.co" in host or ".supabase.com" in host
    if is_remote:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ctx

    return sa_url, connect_args


_engine_url, _connect_args = _parse_db_url(settings.DATABASE_URL)

engine = create_async_engine(
    _engine_url,
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
