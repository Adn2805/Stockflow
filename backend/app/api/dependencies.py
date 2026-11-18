from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_session

Database = Annotated[Session, Depends(get_session)]
bearer = HTTPBearer(auto_error=False)


class Pagination:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=2**31 - 1)] = 0,
    ):
        self.limit = limit
        self.offset = offset


Page = Annotated[Pagination, Depends()]


def require_write_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    expected = request.app.state.settings.write_token
    if expected is None:
        raise HTTPException(403, "Write access is disabled")
    if credentials is None or not compare_digest(
        credentials.credentials.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(401, "Invalid or missing write token", {"WWW-Authenticate": "Bearer"})
