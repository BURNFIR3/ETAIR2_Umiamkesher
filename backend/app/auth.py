import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User, WorkspaceMember, WorkspaceRole

bearer_scheme = HTTPBearer()


def _truncate_password(password: str) -> bytes:
    """bcrypt only processes the first 72 bytes — truncate explicitly to avoid errors."""
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate_password(password), bcrypt.gensalt(12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate_password(plain), hashed.encode("ascii"))
    except Exception:
        return False


def create_access_token(user_id: str, expires_minutes: Optional[int] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.JWT_EXPIRE_MINUTES
    )
    payload = {"sub": user_id, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    result = await db.execute(select(User).where(User.user_id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


async def get_user_workspace_level(
    user_id: UUID,
    workspace_id: UUID,
    db: AsyncSession,
) -> Optional[int]:
    """
    Returns the user's role LEVEL in the workspace, or None if not a member.
    Lower level number = higher authority. Level 1 = top.
    """
    result = await db.execute(
        select(WorkspaceRole.level)
        .join(WorkspaceMember, WorkspaceMember.role_id == WorkspaceRole.role_id)
        .where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def get_user_workspace_role(
    user_id: UUID,
    workspace_id: UUID,
    db: AsyncSession,
) -> Optional[tuple]:
    """
    Returns (role_id, role_name, level) for the user in the workspace,
    or None if not a member.
    """
    result = await db.execute(
        select(WorkspaceRole.role_id, WorkspaceRole.name, WorkspaceRole.level)
        .join(WorkspaceMember, WorkspaceMember.role_id == WorkspaceRole.role_id)
        .where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    return result.one_or_none()


async def require_workspace_member(
    user: User,
    workspace_id: UUID,
    db: AsyncSession,
    max_level: Optional[int] = None,  # user's level must be <= max_level to proceed
) -> tuple:
    """
    Verifies membership and optionally enforces a minimum authority requirement.
    max_level: the highest (worst) level allowed. e.g. max_level=2 means only
               level-1 and level-2 users may proceed. None = any member.
    Returns (role_id, role_name, level).
    """
    row = await get_user_workspace_role(user.user_id, workspace_id, db)
    if row is None:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    role_id, role_name, level = row
    if max_level is not None and level > max_level:
        raise HTTPException(
            status_code=403,
            detail=f"Insufficient authority. Required level ≤ {max_level}, your level is {level}."
        )
    return role_id, role_name, level
