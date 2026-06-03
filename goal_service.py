from database import get_connection


def save_language_goal(
    user_id: int,
    language_deck_id: int,
    target_words: int,
    time_frame: str
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO language_goals (
            user_id,
            language_deck_id,
            target_words,
            time_frame,
            updated_at
        )
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (user_id, language_deck_id)
        DO UPDATE SET
            target_words = EXCLUDED.target_words,
            time_frame = EXCLUDED.time_frame,
            updated_at = NOW();
        """,
        (
            user_id,
            language_deck_id,
            target_words,
            time_frame
        )
    )

    conn.commit()

    cursor.close()
    conn.close()


def get_language_goals_for_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            language_deck_id,
            target_words,
            time_frame
        FROM language_goals
        WHERE user_id = %s;
        """,
        (user_id,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return {
        row[0]: {
            "target_words": row[1],
            "time_frame": row[2]
        }
        for row in rows
    }