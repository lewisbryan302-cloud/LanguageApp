from database import get_connection


def send_friend_request(requester_user_id: int, friend_identifier: str):
    friend_identifier = friend_identifier.strip().lower()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id
            FROM YOUR_USER_TABLE
            WHERE LOWER(username) = %s;
            """,
            (friend_identifier,)
        )

        receiver = cursor.fetchone()

        if receiver is None:
            conn.rollback()
            return

        receiver_user_id = receiver[0]

        if receiver_user_id == requester_user_id:
            conn.rollback()
            return

        cursor.execute(
            """
            INSERT INTO friendships (
                requester_user_id,
                receiver_user_id,
                status
            )
            VALUES (%s, %s, 'pending')
            ON CONFLICT (requester_user_id, receiver_user_id)
            DO NOTHING;
            """,
            (requester_user_id, receiver_user_id)
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


def accept_friend_request(friendship_id: int, receiver_user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE friendships
            SET status = 'accepted',
                updated_at = NOW()
            WHERE id = %s
              AND receiver_user_id = %s;
            """,
            (friendship_id, receiver_user_id)
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


def get_friends_for_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            u.id,
            u.email
        FROM friendships f
        JOIN app_users u
            ON u.id = CASE
                WHEN f.requester_user_id = %s THEN f.receiver_user_id
                ELSE f.requester_user_id
            END
        WHERE f.status = 'accepted'
          AND (
                f.requester_user_id = %s
             OR f.receiver_user_id = %s
          )
        ORDER BY u.email;
        """,
        (user_id, user_id, user_id)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return [
        {
            "id": row[0],
            "email": row[1],
            "display_name": row[1],
        }
        for row in rows
    ]


def get_pending_friend_requests(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            f.id,
            u.id,
            u.email
        FROM friendships f
        JOIN app_users u
            ON u.id = f.requester_user_id
        WHERE f.receiver_user_id = %s
          AND f.status = 'pending'
        ORDER BY f.created_at DESC;
        """,
        (user_id,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return [
        {
            "id": row[0],
            "user_id": row[1],
            "email": row[2],
            "username": row[2],
            "display_name": row[2],
        }
        for row in rows
    ]


def get_global_leaderboard(limit: int = 50):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        WITH deck_points AS (
            SELECT
                d.user_id,
                COUNT(f.id) AS deck_score
            FROM decks d
            LEFT JOIN flashcards f
                ON f.deck_id = d.id
            GROUP BY d.user_id
        ),

        activity_points AS (
            SELECT
                u.id AS user_id,
                COALESCE(SUM(dls.daily_score), 0) AS activity_score
            FROM app_users u
            LEFT JOIN daily_language_scores dls
                ON dls.profile = u.email
            GROUP BY u.id
        )

        SELECT
            u.id,
            u.email,
            COALESCE(dp.deck_score, 0) + COALESCE(ap.activity_score, 0) AS total_score
        FROM app_users u
        LEFT JOIN deck_points dp
            ON dp.user_id = u.id
        LEFT JOIN activity_points ap
            ON ap.user_id = u.id
        ORDER BY total_score DESC
        LIMIT %s;
        """,
        (limit,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return [
        {
            "user_id": row[0],
            "username": row[1],
            "email": row[1],
            "score": float(row[2]),
        }
        for row in rows
    ]


def get_friends_leaderboard(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        WITH friend_ids AS (
            SELECT receiver_user_id AS user_id
            FROM friendships
            WHERE requester_user_id = %s
              AND status = 'accepted'

            UNION

            SELECT requester_user_id AS user_id
            FROM friendships
            WHERE receiver_user_id = %s
              AND status = 'accepted'

            UNION

            SELECT %s AS user_id
        ),

        deck_points AS (
            SELECT
                d.user_id,
                COUNT(f.id) AS deck_score
            FROM decks d
            LEFT JOIN flashcards f
                ON f.deck_id = d.id
            GROUP BY d.user_id
        ),

        activity_points AS (
            SELECT
                u.id AS user_id,
                COALESCE(SUM(dls.daily_score), 0) AS activity_score
            FROM app_users u
            LEFT JOIN daily_language_scores dls
                ON dls.profile = u.email
            GROUP BY u.id
        )

        SELECT
            u.id,
            u.email,
            COALESCE(dp.deck_score, 0) + COALESCE(ap.activity_score, 0) AS total_score
        FROM friend_ids fi
        JOIN app_users u
            ON u.id = fi.user_id
        LEFT JOIN deck_points dp
            ON dp.user_id = u.id
        LEFT JOIN activity_points ap
            ON ap.user_id = u.id
        ORDER BY total_score DESC;
        """,
        (user_id, user_id, user_id)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return [
        {
            "user_id": row[0],
            "username": row[1],
            "email": row[1],
            "score": float(row[2]),
        }
        for row in rows
    ]