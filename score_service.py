import math
from datetime import date, timedelta
from database import get_connection

def improved_daily_score(
    b: int,
    c: int,
    added: int,
    d: int,
    a: int,
    streak: int,
    A: float = 5
) -> float:
    """
    b      = cards reviewed today
    c      = review goal
    added  = cards added today
    d      = add goal
    a      = cards moved from new to learnt today
    streak = current streak
    A      = learning saturation scale
    """

    review_points = 10 * min(1, b / c) if c > 0 else 0
    add_points = 5 * min(1, added / d) if d > 0 else 0
    learning_points = 20 * (1 - math.exp(-a / A)) if A > 0 else 0
    streak_bonus = 5 * math.log1p(streak)

    return review_points + add_points + learning_points + streak_bonus

def improved_daily_score(
    b: int,
    c: int,
    added: int,
    d: int,
    a: int,
    streak: int,
    A: float = 5
) -> float:
    review_points = 10 * min(1, b / c) if c > 0 else 0
    add_points = 5 * min(1, added / d) if d > 0 else 0
    learning_points = 20 * (1 - math.exp(-a / A)) if A > 0 else 0
    streak_bonus = 5 * math.log1p(streak)

    return review_points + add_points + learning_points + streak_bonus


def get_today_language_score(profile: str, language: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            cards_reviewed,
            cards_added,
            cards_learnt,
            streak,
            daily_score
        FROM daily_language_scores
        WHERE profile = %s
          AND language = %s
          AND score_date = CURRENT_DATE;
        """,
        (profile, language)
    )

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    if row is None:
        return {
            "cards_reviewed": 0,
            "cards_added": 0,
            "cards_learnt": 0,
            "streak": 0,
            "daily_score": 0,
        }

    return {
        "cards_reviewed": row[0],
        "cards_added": row[1],
        "cards_learnt": row[2],
        "streak": row[3],
        "daily_score": float(row[4]),
    }


def get_current_streak(profile: str, language: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT streak
        FROM daily_language_scores
        WHERE profile = %s
          AND language = %s
          AND score_date = CURRENT_DATE - INTERVAL '1 day';
        """,
        (profile, language)
    )

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    if row is None:
        return 0

    return int(row[0])


def update_today_language_score(
    profile: str,
    language: str,
    cards_reviewed_delta: int = 0,
    cards_added_delta: int = 0,
    cards_learnt_delta: int = 0,
    daily_review_goal: int = 50,
    daily_add_goal: int = 10,
):
    """
    Updates today's score row for one language.

    Call this when:
    - a card is reviewed
    - a card is added
    - a card moves from new to learnt
    """

    conn = get_connection()
    cursor = conn.cursor()

    # Ensure today's row exists
    cursor.execute(
        """
        INSERT INTO daily_language_scores (
            profile,
            language,
            score_date,
            cards_reviewed,
            cards_added,
            cards_learnt,
            streak,
            daily_score
        )
        VALUES (%s, %s, CURRENT_DATE, 0, 0, 0, 0, 0)
        ON CONFLICT (profile, language, score_date)
        DO NOTHING;
        """,
        (profile, language)
    )

    # Apply deltas
    cursor.execute(
        """
        UPDATE daily_language_scores
        SET
            cards_reviewed = cards_reviewed + %s,
            cards_added = cards_added + %s,
            cards_learnt = cards_learnt + %s
        WHERE profile = %s
          AND language = %s
          AND score_date = CURRENT_DATE;
        """,
        (
            cards_reviewed_delta,
            cards_added_delta,
            cards_learnt_delta,
            profile,
            language
        )
    )

    # Fetch updated daily activity
    cursor.execute(
        """
        SELECT cards_reviewed, cards_added, cards_learnt
        FROM daily_language_scores
        WHERE profile = %s
          AND language = %s
          AND score_date = CURRENT_DATE;
        """,
        (profile, language)
    )

    row = cursor.fetchone()

    cards_reviewed = int(row[0])
    cards_added = int(row[1])
    cards_learnt = int(row[2])

    yesterday_streak = get_current_streak(profile, language)

    if cards_reviewed >= daily_review_goal and cards_added >= daily_add_goal:
        streak = yesterday_streak + 1
    else:
        streak = 0

    daily_score = improved_daily_score(
        b=cards_reviewed,
        c=daily_review_goal,
        added=cards_added,
        d=daily_add_goal,
        a=cards_learnt,
        streak=streak,
        A=5
    )

    cursor.execute(
        """
        UPDATE daily_language_scores
        SET
            streak = %s,
            daily_score = %s
        WHERE profile = %s
          AND language = %s
          AND score_date = CURRENT_DATE;
        """,
        (
            streak,
            daily_score,
            profile,
            language
        )
    )

    conn.commit()
    cursor.close()
    conn.close()

    return daily_score