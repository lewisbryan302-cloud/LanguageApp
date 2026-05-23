import psycopg2

def get_connection():
    return psycopg2.connect(
        dbname="language_app",
        user="postgres",
        password="beinGrufne5*",
        host="localhost",
        port="5432"
    )

def test_connection() -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT 1;")
    result = cursor.fetchone()

    cursor.close()
    conn.close()

    return result[0]