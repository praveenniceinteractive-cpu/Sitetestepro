
import sqlite3
import os

DB_FILE = "sitetoolpro.db"

def migrate():
    if not os.path.exists(DB_FILE):
        print(f"Database {DB_FILE} not found.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Add parent_id column
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN parent_id VARCHAR NULL REFERENCES users(id)")
            print("Added parent_id column.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("parent_id column already exists.")
            else:
                print(f"Error adding parent_id: {e}")

        # Add can_create_users column
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN can_create_users BOOLEAN DEFAULT 1")
            print("Added can_create_users column.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("can_create_users column already exists.")
            else:
                print(f"Error adding can_create_users: {e}")
                
        conn.commit()
        print("Migration complete.")
        
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
