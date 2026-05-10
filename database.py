import psycopg2

def get_connection():
    return psycopg2.connect(
        dbname="language_app",
        user="postgres",
        password="beinGrufne5*",
        host="localhost",
        port="5432"
    )