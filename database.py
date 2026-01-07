# database.py
from sqlalchemy import create_engine, MetaData
from databases import Database
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

# Create database directory if it doesn't exist
os.makedirs("database", exist_ok=True)
# SQLite Configuration
DATABASE_URL = "sqlite:///./sitetoolpro.db"

# Connection pooling configuration
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}, # Required for SQLite
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
metadata = MetaData()

# Async database instance (currently unused but kept for future async operations)
database = Database(DATABASE_URL)