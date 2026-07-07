from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_subject
from ..db import get_db
from ..models import User
from ..schemas import UserCreate, UserOut

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
