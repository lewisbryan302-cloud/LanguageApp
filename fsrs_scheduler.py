# fsrs_scheduler.py

from datetime import date, timedelta
import math


DEFAULT_W = [
    0.4072, 1.1829, 3.1262, 15.4722,
    7.2102, 0.5316, 1.0651, 0.0234,
    1.616, 0.1544, 1.0824, 1.9813,
    0.0953, 0.2975, 2.2042, 0.2407,
    2.9466, 0.5034, 0.6567
]


RATING_AGAIN = 1
RATING_HARD = 2
RATING_GOOD = 3
RATING_EASY = 4


def retrievability(stability: float, elapsed_days: int) -> float:
    if stability <= 0:
        return 0
    return (1 + elapsed_days / (9 * stability)) ** -1


def initial_stability(rating: int, w=DEFAULT_W) -> float:
    return max(w[rating - 1], 0.1)


def initial_difficulty(rating: int, w=DEFAULT_W) -> float:
    return min(max(w[4] - math.exp((rating - 1) * w[5]) + 1, 1), 10)


def next_difficulty(difficulty: float, rating: int, w=DEFAULT_W) -> float:
    delta = [-1, -0.5, 0, 1][rating - 1]
    new_d = difficulty - w[6] * delta
    return min(max(new_d, 1), 10)


def next_stability(difficulty: float, stability: float, retrievability_value: float, rating: int, w=DEFAULT_W) -> float:
    if rating == RATING_AGAIN:
        return max(
            w[11]
            * difficulty ** -w[12]
            * ((stability + 1) ** w[13] - 1)
            * math.exp((1 - retrievability_value) * w[14]),
            0.1
        )

    hard_penalty = w[15] if rating == RATING_HARD else 1
    easy_bonus = w[16] if rating == RATING_EASY else 1

    growth = (
        math.exp(w[8])
        * (11 - difficulty)
        * stability ** -w[9]
        * (math.exp((1 - retrievability_value) * w[10]) - 1)
        * hard_penalty
        * easy_bonus
    )

    return max(stability * (1 + growth), 0.1)


def interval_from_stability(stability: float, desired_retention: float = 0.9) -> int:
    interval = 9 * stability * (1 / desired_retention - 1)
    return max(1, round(interval))


def schedule_review(card: dict, rating: int, today: date | None = None) -> dict:
    today = today or date.today()

    reps = card.get("reps", 0)
    stability = card.get("stability", 0)
    difficulty = card.get("difficulty", 0)
    last_review = card.get("last_review")

    if isinstance(last_review, str):
        last_review = date.fromisoformat(last_review)

    elapsed_days = (today - last_review).days if last_review else 0

    if reps == 0:
        new_stability = initial_stability(rating)
        new_difficulty = initial_difficulty(rating)
    else:
        r = retrievability(stability, elapsed_days)
        new_difficulty = next_difficulty(difficulty, rating)
        new_stability = next_stability(new_difficulty, stability, r, rating)

    if rating == RATING_AGAIN:
        interval = 1
        card["lapses"] = card.get("lapses", 0) + 1
    else:
        interval = interval_from_stability(new_stability)

    card["difficulty"] = new_difficulty
    card["stability"] = new_stability
    card["reps"] = reps + 1
    card["last_review"] = today.isoformat()
    card["due_date"] = (today + timedelta(days=interval)).isoformat()

    return card