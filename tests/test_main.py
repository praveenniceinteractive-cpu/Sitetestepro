"""
SiteTesterPro - Test Suite
Tests for authentication, audit workflows, and API endpoints
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from database import Base
import models

# Test database setup
TEST_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create test client
client = TestClient(app)


@pytest.fixture(scope="function")
def test_db():
    """Create a fresh database for each test"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


class TestAuthentication:
    """Test authentication endpoints"""
    
    def test_register_success(self, test_db):
        """Test successful user registration"""
        response = client.post("/api/auth/register", json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "SecurePass123!"
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["username"] == "testuser"
    
    def test_register_duplicate_username(self, test_db):
        """Test registration with duplicate username fails"""
        # First registration
        client.post("/api/auth/register", json={
            "email": "test1@example.com",
            "username": "duplicate",
            "password": "SecurePass123!"
        })
        
        # Duplicate username
        response = client.post("/api/auth/register", json={
            "email": "test2@example.com",
            "username": "duplicate",
            "password": "SecurePass123!"
        })
        assert response.status_code == 400
    
    def test_login_with_username(self, test_db):
        """Test login with username"""
        # Register first
        client.post("/api/auth/register", json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "SecurePass123!"
        })
        
        # Login
        response = client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "SecurePass123!"
        })
        assert response.status_code == 200
        assert "access_token" in response.json()
    
    def test_login_with_email(self, test_db):
        """Test login with email"""
        # Register first
        client.post("/api/auth/register", json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "SecurePass123!"
        })
        
        # Login with email
        response = client.post("/api/auth/login", json={
            "username": "test@example.com",
            "password": "SecurePass123!"
        })
        assert response.status_code == 200
        assert "access_token" in response.json()
    
    def test_login_invalid_credentials(self, test_db):
        """Test login with invalid credentials fails"""
        response = client.post("/api/auth/login", json={
            "username": "nonexistent",
            "password": "WrongPassword"
        })
        assert response.status_code == 400
    
    def test_logout(self, test_db):
        """Test logout clears cookie"""
        response = client.post("/api/auth/logout")
        assert response.status_code == 200
        assert "access_token" not in response.cookies


class TestProtectedRoutes:
    """Test protected routes require authentication"""
    
    def test_profile_without_auth(self, test_db):
        """Test accessing profile without authentication redirects"""
        response = client.get("/profile", follow_redirects=False)
        assert response.status_code == 307  # Temporary redirect
        assert "/login" in response.headers["location"]
    
    def test_static_audit_without_auth(self, test_db):
        """Test accessing static audit without authentication fails"""
        response = client.get("/responsive/static", follow_redirects=False)
        assert response.status_code == 307


class TestAuditWorkflows:
    """Test audit creation and management"""
    
    @pytest.fixture
    def auth_token(self, test_db):
        """Get authentication token for tests"""
        response = client.post("/api/auth/register", json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "SecurePass123!"
        })
        return response.json()["access_token"]
    
    def test_static_audit_upload(self, test_db, auth_token):
        """Test uploading URLs for static audit"""
        import io
        
        files = {"file": ("urls.txt", io.BytesIO(b"https://example.com\\n"), "text/plain")}
        data = {
            "browsers": '["Chrome"]',
            "resolutions": '["1920x1080"]',
            "session_name": "Test Audit"
        }
        
        response = client.post(
            "/upload/static",
            files=files,
            data=data,
            cookies={"access_token": auth_token}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "session" in data
        assert data["type"] == "static"
        assert data["total_expected"] == 1  # 1 URL × 1 browser × 1 resolution
    
    def test_upload_without_auth(self, test_db):
        """Test upload without authentication fails"""
        import io
        
        files = {"file": ("urls.txt", io.BytesIO(b"https://example.com\\n"), "text/plain")}
        response = client.post("/upload/static", files=files)
        assert response.status_code == 401
    
    def test_upload_empty_file(self, test_db, auth_token):
        """Test uploading empty file returns error"""
        import io
        
        files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
        data = {
            "browsers": '["Chrome"]',
            "resolutions": '["1920x1080"]',
            "session_name": "Test"
        }
        
        response = client.post(
            "/upload/static",
            files=files,
            data=data,
            cookies={"access_token": auth_token}
        )
        
        assert response.status_code == 400
        assert "No valid URLs found" in response.json()["error"]


class TestSessionManagement:
    """Test session CRUD operations"""
    
    @pytest.fixture
    def auth_token(self, test_db):
        """Get authentication token"""
        response = client.post("/api/auth/register", json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "SecurePass123!"
        })
        return response.json()["access_token"]
    
    def test_delete_session(self, test_db, auth_token):
        """Test deleting a session"""
        # Create a session first
        import io
        files = {"file": ("urls.txt", io.BytesIO(b"https://example.com\\n"), "text/plain")}
        data = {
            "browsers": '["Chrome"]',
            "resolutions": '["1920x1080"]',
            "session_name": "Test"
        }
        
        create_response = client.post(
            "/upload/static",
            files=files,
            data=data,
            cookies={"access_token": auth_token}
        )
        session_id = create_response.json()["session"]
        
        # Delete the session
        delete_response = client.delete(
            f"/api/sessions/{session_id}",
            cookies={"access_token": auth_token}
        )
        
        assert delete_response.status_code == 200
        assert "deleted" in delete_response.json()["message"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
