from database import get_connection

conn = get_connection()
cursor = conn.cursor()
cursor.execute("SELECT 1;")
print(cursor.fetchone())

cursor.close()
conn.close()