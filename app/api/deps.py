"""
FastAPI Depends 모음.
엔드포인트에서 Depends(get_current_user) 식으로 사용한다.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError

from app.db.base import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Authorization: Bearer <token> 헤더에서 유저를 꺼낸다.
    토큰이 없거나 유효하지 않으면 401.
    """
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")
    except JWTError:
        raise HTTPException(status_code=401, detail="토큰 검증에 실패했습니다")

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")
    return current_user


def require_agent_or_above(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (UserRole.admin, UserRole.agent):
        raise HTTPException(status_code=403, detail="상담원 이상 권한이 필요합니다")
    return current_user
