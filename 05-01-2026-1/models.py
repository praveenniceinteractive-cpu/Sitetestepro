# models.py
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.sql import func
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class AuditSession(Base):
    __tablename__ = "audit_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_type = Column(String, nullable=False)  # 'static', 'dynamic', or 'h1'
    name = Column(String, nullable=False)  # User-friendly name
    urls = Column(Text, nullable=False)  # JSON string of URLs
    browsers = Column(Text, nullable=False)  # JSON string of browsers
    resolutions = Column(Text, nullable=False)  # JSON string of resolutions
    status = Column(String, default="running")  # running, completed, stopped, error
    total_expected = Column(Integer, default=0)
    completed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

class H1AuditResult(Base):
    __tablename__ = "h1_audit_results"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("audit_sessions.session_id"), nullable=False)
    url = Column(String, nullable=False)
    h1_count = Column(Integer, default=0)
    h1_texts = Column(Text, nullable=False)  # JSON string of H1 texts
    issues = Column(Text, nullable=False)  # JSON string of issues
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    # Add this to the end of models.py, before the last line

class PhoneAuditResult(Base):
    __tablename__ = "phone_audit_results"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("audit_sessions.session_id"), nullable=False)
    url = Column(String, nullable=False)
    phone_numbers = Column(Text, nullable=False)  # JSON string of phone numbers found
    phone_count = Column(Integer, default=0)
    formats_detected = Column(Text, nullable=False)  # JSON string of formats detected
    issues = Column(Text, nullable=False)  # JSON string of issues
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)