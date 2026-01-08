
import models
import database
import permissions
import uuid

# 1. Setup Database Session
db = database.SessionLocal()

try:
    print("--- Setting up Editor Role ---")
    
    # 2. Define what "Editor" can do (Update/Write, but maybe not Delete)
    # Ensure permissions exist
    p_read = permissions.create_permission(db, "session:read", "Can read session")
    p_update = permissions.create_permission(db, "session:update", "Can update session data")
    p_write = permissions.create_permission(db, "session:write", "Can write/add items")
    
    # 3. Create the Role
    # Editor gets Read, Update, Write
    role_editor = permissions.create_role(db, "Editor", ["session:read", "session:update", "session:write"])
    print(f"Role '{role_editor.name}' ensures permissions: [session:read, session:update, session:write]")

    # 4. Assign to a User
    # Using dummy IDs for demonstration
    user_id = str(uuid.uuid4()) # In real app, this comes from current_user.id
    target_session_id = "session_123"
    
    print(f"\nAssigning User {user_id} as 'Editor' on Session {target_session_id}...")
    
    assignment = permissions.assign_role(
        db, 
        user_id=user_id, 
        resource_type="audit_session", 
        resource_id=target_session_id, 
        role_name="Editor"
    )
    
    print(f"Success! Assignment ID: {assignment.id}")
    print(f"User now has role: {permissions.get_user_roles(db, user_id, 'audit_session', target_session_id)}")

    # 5. Verify
    can_update = permissions.check_permission(db, user_id, "audit_session", target_session_id, "session:update")
    print(f"Can User Update? {can_update}")

finally:
    db.close()
