import sqlite3
import os
from models import add_alert, get_connection, init_db

DB_PATH = "/home/ubuntu/courtalert/courtalert.db"

def check_alerts_table():
    print(f"Checking DB at {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("❌ DB file not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check schema
    cursor.execute("PRAGMA table_info(alerts)")
    columns = cursor.fetchall()
    print("Alerts Table Schema:")
    for col in columns:
        print(col)
        
    # Check count
    cursor.execute("SELECT count(*) FROM alerts")
    count = cursor.fetchone()[0]
    print(f"Alerts count: {count}")
    
    conn.close()

def test_insert():
    print("\nTesting manual insert...")
    try:
        # We need a user first
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (phone_number) VALUES ('9999999999')")
        conn.commit()
        cursor.execute("SELECT id FROM users WHERE phone_number = '9999999999'")
        user_id = cursor.fetchone()[0]
        conn.close()
        
        add_alert(user_id, "TEST-CASE-001", None, "test", "Test Message")
        
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM alerts WHERE case_number = 'TEST-CASE-001'")
        row = cursor.fetchone()
        if row:
            print("✅ Manual insert successful!")
            print(dict(row))
        else:
            print("❌ Manual insert failed!")
        conn.close()
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    init_db()
    check_alerts_table()
    test_insert()
