# auth.py - SUPABASE EDITION
import os
from typing import Optional, Dict, Any
from fastapi import HTTPException, status, Depends
from sqlalchemy.orm import Session
from database import SessionLocal
from dotenv import load_dotenv
from supabase import create_client, Client
from gotrue.errors import AuthApiError

load_dotenv()

# Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")

# Initialize Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Authentication Logic
def register_user(email: str, password: str, username: str, db: Session):
    """Register a new user with Supabase Auth and create local profile."""
    try:
        # 1. Sign up with Supabase
        res = supabase.auth.sign_up({
            "email": email, 
            "password": password,
            "options": {
                "data": {"username": username}
            }
        })
        
        if not res.user:
            raise HTTPException(status_code=400, detail="Registration failed")
            
        # 2. Create local profile in public.users
        from models import User
        new_user = User(
            id=res.user.id, # Use Supabase UUID
            email=email,
            username=username
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        return new_user
        
    except AuthApiError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        print(f"Registration Error: {e}")
        db.rollback()
        # Check if user was created in Supabase but failed in DB
        # Ideally we handles this with a transaction or cleanup, 
        # but for now we raise error.
        raise HTTPException(status_code=400, detail=str(e))

def login_user(email: str, password: str):
    """Login with Supabase Auth."""
    try:
        res = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        return res.session
    except AuthApiError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def verify_token(token: str) -> Optional[str]:
    """Verify a Supabase JWT and return user_id (UUID)."""
    try:
        # We verify by getting the user object from Supabase
        # This ensures the token is valid and not revoked
        res = supabase.auth.get_user(token)
        if res.user:
            return res.user.id
        return None
    except:
        return None

# RLS Helper
from sqlalchemy import text
def set_db_session_user(db: Session, user_id: str):
    """Set the current user ID in the Postgres session for RLS."""
    try:
        # Use simple string interpolation for safety against injection if user_id was user input,
        # but here user_id comes from verified token.
        # Parameterized query is safer.
        db.execute(text("SET app.current_user_id = :uid"), {"uid": user_id})
    except Exception as e:
        print(f"RLS Setup Error: {e}")
