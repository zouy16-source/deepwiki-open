from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_subject
from ..db import get_db
from ..models import User
from ..schemas import UserCreate, UserOut, UserUpdate

router = APIRouter()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, f"username '{body.username}' already exists")
    user = User(**body.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("", response_model=list[UserOut])
def list_users(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return db.scalars(
        select(User).order_by(User.id).limit(min(limit, 200)).offset(offset)
    ).all()


@router.get("/me")
def me(subject: str = Depends(current_subject), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == subject))
    if user is None:
        # SSO 首登用户尚未落库时，返回 token 主体，由登录流程负责建档
        return {"username": subject, "registered": False}
    return UserOut.model_validate(user).model_dump() | {"registered": True}


@router.patch("/me", response_model=UserOut)
def update_me(
    body: UserUpdate,
    subject: str = Depends(current_subject),
    db: Session = Depends(get_db),
):
    """当前用户自助更新档案（一期主要用于绑定 TAPD 账号 tapd_nick）。"""
    user = db.scalar(select(User).where(User.username == subject))
    if user is None:
        raise HTTPException(404, "user not found; login first to provision")
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.email is not None:
        user.email = body.email
    if body.tapd_nick is not None:
        user.tapd_nick = body.tapd_nick
    db.commit()
    db.refresh(user)
    return user
