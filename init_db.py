
import models
import database
import os

print("Resetting database...")
# Removing SQLite DB file to force recreation
if os.path.exists("sitetoolpro.db"):
    os.remove("sitetoolpro.db")
    print("Removed existing database file.")

print("Creating tables...")
models.Base.metadata.create_all(bind=database.engine)
print("Tables created successfully.")
