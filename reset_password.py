
import auth
import database
import models
import getpass

def reset_password():
    print("--- SitetesterPro Password Reset Tool ---")
    email = input("Enter the email address of the user to reset: ")
    
    db = database.SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == email).first()
        if not user:
            print(f"Error: User with email '{email}' not found.")
            return

        print(f"Found User: {user.username} ({user.email})")
        new_password = input("Enter new password: ")
        
        # Use the app's hashing logic
        hashed_pw = auth.get_password_hash(new_password)
        
        user.hashed_password = hashed_pw
        db.commit()
        
        print("Success! Password has been updated.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    reset_password()
