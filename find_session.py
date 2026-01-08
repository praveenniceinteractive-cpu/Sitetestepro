
import database
import models
from sqlalchemy.orm import Session

db = database.SessionLocal()
try:
    # Find a static session
    session = db.query(models.AuditSession).filter(models.AuditSession.session_type == "static").order_by(models.AuditSession.created_at.desc()).first()
    if session:
        print(f"FOUND_SESSION_ID: {session.session_id}")
    else:
        print("NO_SESSIONS_FOUND")
finally:
    db.close()
