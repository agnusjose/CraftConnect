import sqlite3

def check_orders():
    conn = sqlite3.connect("craftconnect.db")
    cursor = conn.cursor()
    cursor.execute("""
ALTER TABLE users ADD COLUMN is_logged_in integer default 0;
""")
    orders = cursor.fetchall()
    for order in orders:
        print(order)
    conn.close()

check_orders()