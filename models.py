# models.py
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.sql import func
from database import Base
import datetime
import uuid

class User(Base):
    __tablename__ = "users"
    
    # Supabase uses UUIDs for auth.users. 
    # We will use the same ID here to link profile data.
    id = Column(String, primary_key=True, index=True) 
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    # hashed_password is NOT needed as Supabase handles auth
    # keeping it optional/removed. We'll remove it.
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class AuditSession(Base):
    __tablename__ = "audit_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    # Updated ForeignKey to match User.id type (String/UUID)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
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
    # Updated ForeignKey to match User.id type (String/UUID)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class VisualAuditResult(Base):
    __tablename__ = "visual_audit_results"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("audit_sessions.session_id"), nullable=False)
    base_url = Column(String, nullable=False)
    compare_url = Column(String, nullable=False)
    diff_score = Column(Integer, default=0) # 0-100 percentage difference
    base_image_path = Column(String, nullable=False)
    compare_image_path = Column(String, nullable=False)
    diff_image_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class PerformanceAuditResult(Base):
    __tablename__ = "performance_audit_results"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("audit_sessions.session_id"), nullable=False)
    url = Column(String, nullable=False)
    device_preset = Column(String, default="Desktop")
    ttfb = Column(Integer, default=0) # ms
    fcp = Column(Integer, default=0) # ms
    dom_load = Column(Integer, default=0) # ms
    page_load = Column(Integer, default=0) # ms
    resource_count = Column(Integer, default=0)
    score = Column(Integer, default=0) # Calculated score 0-100
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class AccessibilityAuditResult(Base):
    __tablename__ = "accessibility_audit_results"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("audit_sessions.session_id"), nullable=False)
    url = Column(String, nullable=False)
    score = Column(Integer, default=0) # 0-100
    violations_count = Column(Integer, default=0)
    critical_count = Column(Integer, default=0)
    serious_count = Column(Integer, default=0)
    moderate_count = Column(Integer, default=0)
    minor_count = Column(Integer, default=0)
    report_json = Column(Text, nullable=False) # Full JSON report from Axe
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class UnifiedAuditResult(Base):
    __tablename__ = "unified_audit_results"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("audit_sessions.session_id"), nullable=False)
    url = Column(String, nullable=False)
    
    # Scores (0-100)
    performance_score = Column(Integer, default=0)
    accessibility_score = Column(Integer, default=0)
    seo_score = Column(Integer, default=0) # Based on H1/Meta
    content_score = Column(Integer, default=0) # Based on Phone/Links
    
    # Meta
    overall_score = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class StaticAuditResult(Base):
    __tablename__ = "static_audit_results"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("audit_sessions.session_id"), nullable=False)
    url = Column(String, nullable=False)
    browser = Column(String, nullable=False)
    resolution = Column(String, nullable=False)
    screenshot_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
class DynamicAuditResult(Base):
    __tablename__ = "dynamic_audit_results"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("audit_sessions.session_id"), nullable=False)
    url = Column(String, nullable=False)
    browser = Column(String, nullable=False)
    resolution = Column(String, nullable=False)
    video_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
