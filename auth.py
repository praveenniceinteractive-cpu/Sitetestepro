# auth.py - LOCAL SQLITE EDITION
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, status, Depends
from sqlalchemy.orm import Session
from database import SessionLocal
from dotenv import load_dotenv
import jwt
from passlib.context import CryptContext
import uuid
from models import User

load_dotenv()

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key-change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 1 week

# Password Hashing
# Migrated to Argon2 to avoid bcrypt 72-byte limit and version issues
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

import hashlib

# Hash & Verify
def verify_password(plain_password, hashed_password):
    # Try verifying as-is first (backward compatibility)
    if pwd_context.verify(plain_password, hashed_password):
        return True
    
    # Try verifying the pre-hashed version (for new/long passwords)
    # This handles the 72-byte bcrypt limit
    pre_hashed = hashlib.sha256(plain_password.encode()).hexdigest()
    return pwd_context.verify(pre_hashed, hashed_password)

def get_password_hash(password):
    # Always pre-hash with SHA256 to ensure length < 72 bytes (hexdigest is 64 chars)
    # This works for ANY password length
    pre_hashed = hashlib.sha256(password.encode()).hexdigest()
    return pwd_context.hash(pre_hashed)

# Token Management
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[str]:
    """Verify a JWT and return user_id (UUID string)."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        return user_id
    except jwt.PyJWTError:
        return None

# User Logic
def register_user(email: str, password: str, username: str, db: Session):
    """Register a new user locally."""
    # Check existing email
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Check existing username
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
        
    new_user_id = str(uuid.uuid4())
    hashed_pw = get_password_hash(password)
    
    user = User(
        id=new_user_id,
        email=email,
        username=username,
        hashed_password=hashed_pw
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def login_user(email: str, password: str, db: Session):
    """Login locally and return access token."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
        
    if not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid credentials")
        
    # Create Token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.id, "email": user.email},
        expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer", "user": user}
