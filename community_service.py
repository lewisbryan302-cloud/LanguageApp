from database import get_connection

def current_week_filter_sql():
    return """
        dls.score_date >= date_trunc('week', CURRENT_DATE)::date
        AND dls.score_date < (date_trunc('week', CURRENT_DATE)::date + INTERVAL '7 days')
    """

def send_friend_request(requester_user_id: int, friend_identifier: str):
    friend_identifier = friend_identifier.strip().lower()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id
            FROM app_users
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
            u.username
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
        ORDER BY u.username;
        """,
        (user_id, user_id, user_id)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return [
        {
            "id": row[0],
            "username": row[1],
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
            u.username
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
        SELECT
            u.id,
            u.username,
            COALESCE(SUM(dls.daily_score), 0) AS weekly_points
        FROM app_users u
        LEFT JOIN daily_language_scores dls
            ON dls.profile = u.username
            AND dls.score_date >= date_trunc('week', CURRENT_DATE)::date
            AND dls.score_date < (date_trunc('week', CURRENT_DATE)::date + INTERVAL '7 days')
        GROUP BY
            u.id,
            u.username
        ORDER BY
            weekly_points DESC,
            u.username ASC
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
            "points": float(row[2]),
            "weekly_points": float(row[2]),
        }
        for row in rows
    ]


def get_friends_leaderboard(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        WITH friend_ids AS (
            SELECT
                CASE
                    WHEN requester_user_id = %s THEN receiver_user_id
                    ELSE requester_user_id
                END AS friend_user_id
            FROM friendships
            WHERE status = 'accepted'
              AND (
                    requester_user_id = %s
                    OR receiver_user_id = %s
              )

            UNION

            SELECT %s AS friend_user_id
        )

        SELECT
            u.id,
            u.username,
            COALESCE(SUM(dls.daily_score), 0) AS weekly_points
        FROM friend_ids f
        JOIN app_users u
            ON u.id = f.friend_user_id
        LEFT JOIN daily_language_scores dls
            ON dls.profile = u.username
            AND dls.score_date >= date_trunc('week', CURRENT_DATE)::date
            AND dls.score_date < (date_trunc('week', CURRENT_DATE)::date + INTERVAL '7 days')
        GROUP BY
            u.id,
            u.username
        ORDER BY
            weekly_points DESC,
            u.username ASC;
        """,
        (
            user_id,
            user_id,
            user_id,
            user_id
        )
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return [
        {
            "user_id": row[0],
            "username": row[1],
            "points": float(row[2]),
            "weekly_points": float(row[2]),
        }
        for row in rows
    ]