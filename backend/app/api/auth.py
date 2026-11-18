from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, func, select

from app.api.dependencies import Database, Principal, get_principal
from app.auth import LoginRequest, LoginResponse, LoginSession, User, new_login_session, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Database, response: Response):
    with db.begin():
        user = db.scalar(select(User).where(User.username == data.username))
        if not verify_password(user, data.password.get_secret_value()) or user is None:
            raise HTTPException(401, "Invalid credentials")
        token, login_session = new_login_session(user.id)
        db.execute(delete(LoginSession).where(LoginSession.expires_at <= func.now()))
        db.add(login_session)
        result = LoginResponse(username=user.username, role=user.role, access_token=token)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/logout", status_code=204)
def logout(principal: Annotated[Principal, Depends(get_principal)], db: Database):
    if principal.session_hash is not None:
        with db.begin():
            db.execute(delete(LoginSession).where(LoginSession.token_hash == principal.session_hash))
