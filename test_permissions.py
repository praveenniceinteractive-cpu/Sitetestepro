
import os
import sys
# Use a test database
os.environ["DATABASE_URL"] = "sqlite:///./test_permissions.db"

import models
import database
import permissions
from sqlalchemy.orm import Session
import uuid

def test_acm_rbac():
    print("Initializing Test Database...")
    if os.path.exists("test_permissions.db"):
        os.remove("test_permissions.db")
    
    models.Base.metadata.create_all(bind=database.engine)
    db = database.SessionLocal()
    
    try:
        # 1. Setup Roles and Permissions
        print("Setting up Roles...")
        p_read = permissions.create_permission(db, "session:read", "Can read session")
        p_delete = permissions.create_permission(db, "session:delete", "Can delete session")
        
        role_owner = permissions.create_role(db, "Owner", ["session:read", "session:delete"])
        role_viewer = permissions.create_role(db, "Viewer", ["session:read"])
        
        # 2. Create Users
        print("Creating Users...")
        # Mock users (just need IDs for ACM)
        alice_id = str(uuid.uuid4())
        bob_id = str(uuid.uuid4())
        
        # Create user records to satisfy FK
        alice = models.User(id=alice_id, email="alice@test.com", username="alice", hashed_password="pw")
        bob = models.User(id=bob_id, email="bob@test.com", username="bob", hashed_password="pw")
        db.add(alice)
        db.add(bob)
        db.commit()
        
        # 3. Create Resources
        session_a_id = "session_a"
        session_b_id = "session_b"
        resource_type = "audit_session"
        
        # 4. Assign Roles (The ACM part)
        print("Assigning Roles...")
        # Alice is Owner of Session A
        permissions.assign_role(db, alice_id, resource_type, session_a_id, "Owner")
        
        # Bob is Viewer of Session A
        permissions.assign_role(db, bob_id, resource_type, session_a_id, "Viewer")
        
        # Bob is Owner of Session B
        permissions.assign_role(db, bob_id, resource_type, session_b_id, "Owner")
        
        # 5. Verify Permissions
        print("Verifying Permissions...")
        
        # Case A: Alice on Session A (Owner)
        assert permissions.check_permission(db, alice_id, resource_type, session_a_id, "session:read") == True, "Alice should read Session A"
        assert permissions.check_permission(db, alice_id, resource_type, session_a_id, "session:delete") == True, "Alice should delete Session A"
        
        # Case B: Bob on Session A (Viewer)
        assert permissions.check_permission(db, bob_id, resource_type, session_a_id, "session:read") == True, "Bob should read Session A"
        assert permissions.check_permission(db, bob_id, resource_type, session_a_id, "session:delete") == False, "Bob should NOT delete Session A"
        
        # Case C: Bob on Session B (Owner)
        assert permissions.check_permission(db, bob_id, resource_type, session_b_id, "session:delete") == True, "Bob should delete Session B"
        
        # Case D: Alice on Session B (No Role)
        assert permissions.check_permission(db, alice_id, resource_type, session_b_id, "session:read") == False, "Alice has no role on Session B"
        
        print("\nSUCCESS: All ACM/RBAC checks passed!")
        
    except Exception as e:
        print(f"\nFAILED: {e}")
        raise
    finally:
        db.close()
        # Cleanup
        if os.path.exists("test_permissions.db"):
            os.remove("test_permissions.db")

if __name__ == "__main__":
    test_acm_rbac()
