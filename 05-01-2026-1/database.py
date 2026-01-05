# database.py
from sqlalchemy import create_engine, MetaData
from databases import Database
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os


# Create database directory if it doesn't exist
os.makedirs("database", exist_ok=True)
DATABASE_URL = "sqlite:///./database/audit.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
metadata = MetaData()

# We'll use this for async operations
database = Database(DATABASE_URL)