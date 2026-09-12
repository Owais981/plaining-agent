from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.auth import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str
    password: str
    full_name: str = ""
    role: str = "viewer"


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"error": "EMAIL_TAKEN", "message": "Email already registered"})
    if body.role not in ("viewer", "editor", "approver", "admin"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"error": "INVALID_ROLE", "message": "Invalid role"})
    user = User(email=body.email, hashed_password=hash_password(body.password), full_name=body.full_name, role=body.role)
    db.add(user)
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, user.role))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"error": "INVALID_CREDENTIALS", "message": "Incorrect email or password"})
    return TokenOut(access_token=create_access_token(user.id, user.role))
