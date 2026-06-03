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

def get_language_goal_progress_for_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            g.language_deck_id,
            g.target_words,
            g.time_frame,

            CASE
                WHEN g.time_frame = 'day' THEN (
                    SELECT COUNT(*)
                    FROM flashcards f
                    WHERE f.deck_id = g.language_deck_id
                      AND f.created_at >= CURRENT_DATE
                )

                WHEN g.time_frame = 'week' THEN (
                    SELECT COUNT(*)
                    FROM flashcards f
                    WHERE f.deck_id = g.language_deck_id
                      AND f.created_at >= date_trunc('week', CURRENT_DATE)
                )

                ELSE 0
            END AS current_words

        FROM language_goals g
        WHERE g.user_id = %s;
        """,
        (user_id,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    goal_progress = {}

    for row in rows:
        language_deck_id = row[0]
        target_words = row[1]
        time_frame = row[2]
        current_words = row[3]

        if target_words <= 0:
            progress_percent = 0
        else:
            progress_percent = min(
                100,
                round((current_words / target_words) * 100)
            )

        goal_progress[language_deck_id] = {
            "target_words": target_words,
            "time_frame": time_frame,
            "current_words": current_words,
            "progress_percent": progress_percent,
        }

    return goal_progress