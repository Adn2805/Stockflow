from dataclasses import dataclass
import re
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import LoginSession, User, token_hash
from app.db.session import get_session

Database = Annotated[Session, Depends(get_session)]
bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


class Pagination:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=2**31 - 1)] = 0,
    ):
        self.limit = limit
        self.offset = offset


Page = Annotated[Pagination, Depends()]


@dataclass(frozen=True)
class Principal:
    role: str
    session_hash: str | None = None


def get_principal(request: Request, credentials: Credentials) -> Principal:
    expected = request.app.state.settings.write_token
    if credentials is not None:
        token = credentials.credentials
        if expected is not None and compare_digest(token.encode(), expected.get_secret_value().encode()):
            return Principal("admin")
        if re.fullmatch(r"sf_[A-Za-z0-9_-]{43}", token):
            digest = token_hash(token)
            with Session(request.app.state.engine) as session:
                role = session.scalar(
                    select(User.role).join(LoginSession)
                    .where(LoginSession.token_hash == digest, LoginSession.expires_at > func.now())
                )
            if role is not None:
                return Principal(role, digest)
    raise HTTPException(401, "Invalid or missing access token", {"WWW-Authenticate": "Bearer"})


def require_staff(principal: Annotated[Principal, Depends(get_principal)]) -> None:
    if principal.role not in {"admin", "staff"}:
        raise HTTPException(403, "Staff or administrator access is required")


def require_admin(principal: Annotated[Principal, Depends(get_principal)]) -> None:
    if principal.role != "admin":
        raise HTTPException(403, "Administrator access is required")
