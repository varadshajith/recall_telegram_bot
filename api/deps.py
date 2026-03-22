from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from db.database import get_db
from shared.config import settings


def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ")[1]
    if token != settings.api_token:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token


def get_database(db: Session = Depends(get_db)):
    return db
