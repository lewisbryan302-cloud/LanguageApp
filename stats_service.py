# stats_service.py

from database import get_connection


def get_home_stats_widget_data(deck_id: int | None = None) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) AS total_cards,

            COUNT(
                CASE
                    WHEN created_at::date = CURRENT_DATE
                    THEN 1
                END
            ) AS cards_added_today,

            COUNT(
                CASE
                    WHEN created_at >= NOW() - INTERVAL '7 days'
                    THEN 1
                END
            ) AS cards_added_this_week,

            COUNT(
                CASE
                    WHEN next_review <= NOW()
                    THEN 1
                END
            ) AS cards_due_now,

            COUNT(
                CASE
                    WHEN next_review::date = CURRENT_DATE
                    THEN 1
                END
            ) AS cards_due_today,

            COUNT(
                CASE
                    WHEN next_review::date = CURRENT_DATE + INTERVAL '1 day'
                    THEN 1
                END
            ) AS cards_due_tomorrow,

            COUNT(
                CASE
                    WHEN next_review::date >= CURRENT_DATE
                    AND next_review::date < CURRENT_DATE + INTERVAL '7 days'
                    THEN 1
                END
            ) AS cards_due_next_7_days

        FROM flashcards
        WHERE (%s IS NULL OR deck_id = %s);
    """, (
        deck_id,
        deck_id
    ))

    stats_row = cursor.fetchone()

    cursor.execute("""
        SELECT
            next_review::date AS review_date,
            COUNT(*) AS card_count
        FROM flashcards
        WHERE (%s IS NULL OR deck_id = %s)
        AND next_review::date >= CURRENT_DATE
        AND next_review::date < CURRENT_DATE + INTERVAL '7 days'
        GROUP BY next_review::date
        ORDER BY review_date ASC;
    """, (
        deck_id,
        deck_id
    ))

    future_due_rows = cursor.fetchall()

    cursor.close()
    conn.close()

    future_due_by_day = [
        {
            "date": row[0],
            "count": row[1]
        }
        for row in future_due_rows
    ]

    return {
        "total_cards": stats_row[0],
        "cards_added_today": stats_row[1],
        "cards_added_this_week": stats_row[2],
        "cards_due_now": stats_row[3],
        "cards_due_today": stats_row[4],
        "cards_due_tomorrow": stats_row[5],
        "cards_due_next_7_days": stats_row[6],
        "future_due_by_day": future_due_by_day,
    }