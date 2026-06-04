# auth_service.py

from passlib.context import CryptContext

from database import get_connection


password_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(
    plain_password: str,
    password_hash: str
) -> bool:
    return password_context.verify(
        plain_password,
        password_hash
    )


def create_user(
    username: str,
    email: str,
    password: str,
) -> int:
    email = email.strip().lower()
    username = username.strip().lower()

    password_hash = hash_password(password)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO app_users (
            username,
            email,
            password_hash
        )
        VALUES (%s, %s, %s)
        RETURNING id;
        """,
        (
            username,
            email,
            password_hash
        )
    )

    user_id = cursor.fetchone()[0]

    conn.commit()
    cursor.close()
    conn.close()

    return user_id


def get_user_by_email(email: str):
    email = email.strip().lower()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, username, email, password_hash
        FROM app_users
        WHERE email = %s;
        """,
        (email,)
    )

    user = cursor.fetchone()

    cursor.close()
    conn.close()

    return user


def get_user_by_id(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, username, email
        FROM app_users
        WHERE id = %s;
        """,
        (user_id,)
    )

    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if user is None:
        return None

    return {
        "id": user[0],
        "username": user[1],
        "email": user[2]
    }


def authenticate_user(
    email: str,
    password: str
):
    user = get_user_by_email(email)

    if not user:
        return None

    user_id = user[0]
    username = user[1]
    user_email = user[2]
    password_hash = user[3]

    if not verify_password(password, password_hash):
        return None

    return {
        "id": user_id,
        "username": username,
        "email": user_email
    }

def update_username(user_id: int, new_username: str):
    new_username = new_username.strip().lower()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE app_users
            SET username = %s
            WHERE id = %s;
            """,
            (new_username, user_id)
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()