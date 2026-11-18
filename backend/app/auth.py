from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated, Literal

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

Role = Literal["admin", "staff", "guest"]
Username = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3,
                           max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
]
password_hasher = PasswordHasher()
dummy_hash = password_hasher.hash(token_urlsafe(32))
SESSION_DURATION = timedelta(hours=8)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'staff', 'guest')", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))


class LoginSession(Base):
    __tablename__ = "login_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Username
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    username: str
    role: Role


class LoginResponse(UserRead):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


def verify_password(user: User | None, password: str) -> bool:
    try:
        valid = password_hasher.verify(user.password_hash if user else dummy_hash, password)
    except (VerificationError, InvalidHashError):
        return False
    return user is not None and valid


def token_hash(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def new_login_session(user_id: int) -> tuple[str, LoginSession]:
    token = "sf_" + token_urlsafe(32)
    return token, LoginSession(
        token_hash=token_hash(token), user_id=user_id,
        expires_at=datetime.now(UTC) + SESSION_DURATION,
    )
