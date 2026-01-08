
from sqlalchemy.orm import Session
from models import Role, Permission, RolePermission, UserResourceRole, User
from typing import List, Optional

def create_permission(db: Session, codename: str, description: str = None) -> Permission:
    """Create a new permission if it doesn't exist."""
    perm = db.query(Permission).filter(Permission.codename == codename).first()
    if not perm:
        perm = Permission(codename=codename, description=description)
        db.add(perm)
        db.commit()
        db.refresh(perm)
    return perm

def create_role(db: Session, name: str, permission_codenames: List[str], description: str = None) -> Role:
    """Create a new role with a set of permissions."""
    role = db.query(Role).filter(Role.name == name).first()
    if not role:
        role = Role(name=name, description=description)
        db.add(role)
        db.commit()
        db.refresh(role)
    
    # Assign permissions
    current_perms = db.query(RolePermission).filter(RolePermission.role_id == role.id).all()
    # For simplicity, clear and re-add or just add missing. Here we just add missing.
    
    for codename in permission_codenames:
        perm = create_permission(db, codename)
        # Check if linked
        link = db.query(RolePermission).filter_by(role_id=role.id, permission_id=perm.id).first()
        if not link:
            link = RolePermission(role_id=role.id, permission_id=perm.id)
            db.add(link)
    db.commit()
    return role

def assign_role(db: Session, user_id: str, resource_type: str, resource_id: str, role_name: str) -> UserResourceRole:
    """Assign a role to a user for a specific resource."""
    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        raise ValueError(f"Role '{role_name}' not found")
        
    # Check if assignment exists
    assignment = db.query(UserResourceRole).filter_by(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id
    ).first()
    
    if assignment:
        # Update role
        assignment.role_id = role.id
    else:
        # Create new
        assignment = UserResourceRole(
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            role_id=role.id
        )
        db.add(assignment)
    
    db.commit()
    db.refresh(assignment)
    return assignment

def check_permission(db: Session, user_id: str, resource_type: str, resource_id: str, required_permission: str) -> bool:
    """
    Check if user has a specific permission on a resource.
    1. Get User's Role on Resource
    2. Check if Role has Permission
    """
    # 1. Get Role Assignment
    assignment = db.query(UserResourceRole).filter_by(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id
    ).first()
    
    if not assignment:
        return False
        
    # 2. Check Permission via Join
    # Join: RolePermission -> Permission
    exists = db.query(RolePermission).join(Permission).filter(
        RolePermission.role_id == assignment.role_id,
        Permission.codename == required_permission
    ).first()
    
    return exists is not None

def get_user_roles(db: Session, user_id: str, resource_type: str, resource_id: str):
    """Get the role name for a user on a resource."""
    assignment = db.query(UserResourceRole).join(Role).filter(
        UserResourceRole.user_id == user_id,
        UserResourceRole.resource_type == resource_type,
        UserResourceRole.resource_id == resource_id
    ).first()
    
    if assignment:
        role = db.query(Role).get(assignment.role_id)
        return role.name
    return None
