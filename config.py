"""
Configuration module for SiteTesterPro
Centralizes all environment variables and application settings
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Database Configuration
    database_url: str
    
    # Supabase Configuration
    supabase_url: str
    supabase_key: str
    
    # Security Settings
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    
    # Application Settings
    environment: str = "development"
    max_upload_size_mb: int = 10
    session_timeout_minutes: int = 60
    
    # CORS Settings
    allowed_origins: List[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]
    
    # File Storage Paths
    screenshots_dir: str = "screenshots"
    videos_dir: str = "videos"
    temp_frames_dir: str = "temp_frames"
    diffs_dir: str = "diffs"
    
    # Performance Settings
    max_concurrent_audits: int = 5
    playwright_timeout_ms: int = 90000
    
    # Logging
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance
    Uses lru_cache to ensure settings are loaded only once
    """
    return Settings()


# Export settings instance for easy import
settings = get_settings()
