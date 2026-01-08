@app.post("/api/impersonate/{user_id}")
async def impersonate_user(
    user_id: str,
    response: Response,
    current_user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    """
    Allow a parent user to log in as one of their sub-users without a password.
    """
    # 1. Verify Parent-Child Relationship
    # The target user (user_id) MUST have parent_id == current_user.id
    target_user = db.query(models.User).filter_by(id=user_id).first()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if target_user.parent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only impersonate your own sub-users.")
        
    # 2. Generate Token for Target User
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": target_user.username}, expires_delta=access_token_expires
    )
    
    # 3. Return response (Frontend will handle the cookie setting usually, but here we can set it too)
    # However, for API calls, usually we return the token and let front-end set cookie.
    # But since this is a "Login As" action, setting the cookie directly is cleaner for the redirect.
    
    response.set_cookie(
        key="access_token",
        value=f"{access_token}",
        httponly=True,
        max_age=1800,
        expires=1800,
        samesite="Lax",
        secure=False 
    )
    
    return {"message": f"Logged in as {target_user.username}", "redirect_url": "/platform/dashboard"}
