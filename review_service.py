from database import get_connection
from fsrs import Scheduler, Card, Rating
import json

from score_service import update_today_language_score
from deck_service import get_deck_language_and_profile


scheduler = Scheduler()


RATING_MAP = {
    1: Rating.Again,
    2: Rating.Hard,
    3: Rating.Good,
    4: Rating.Easy,
}


def get_review_page_data(deck_id: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, front, back, card_type, image_path
        FROM flashcards
        WHERE deck_id = %s
        AND next_review <= NOW()
        ORDER BY times_wrong DESC, last_reviewed ASC NULLS FIRST
        LIMIT 1;
    """, (deck_id,))

    card = cursor.fetchone()

    cursor.execute("""
        SELECT COUNT(*)
        FROM flashcards
        WHERE deck_id = %s
        AND (
            next_review IS NULL
            OR next_review <= NOW()
        );
    """, (deck_id,))

    remaining_reviews = cursor.fetchone()[0]

    cursor.execute("""
        SELECT name
        FROM decks
        WHERE id = %s;
    """, (deck_id,))

    deck_row = cursor.fetchone()
    deck_name = deck_row[0] if deck_row else "Unknown deck"

    cursor.close()
    conn.close()

    return {
        "card": card,
        "deck_id": deck_id,
        "deck_name": deck_name,
        "remaining_reviews": remaining_reviews,
    }


def submit_card_review(card_id: int, deck_id: int, rating: int) -> dict:
    if rating not in RATING_MAP:
        raise ValueError(f"Invalid rating: {rating}")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                fsrs_card,
                times_seen,
                times_correct,
                times_wrong,
                last_reviewed,
                next_review
            FROM flashcards
            WHERE id = %s;
        """, (card_id,))

        row = cursor.fetchone()

        if row is None:
            raise ValueError(f"No flashcard found with id {card_id}")

        fsrs_card_json = row[0]

        old_times_seen = row[1]
        was_new = old_times_seen == 0

        undo_data = {
            "card_id": card_id,
            "deck_id": deck_id,
            "fsrs_card": fsrs_card_json,
            "times_seen": row[1],
            "times_correct": row[2],
            "times_wrong": row[3],
            "last_reviewed": str(row[4]) if row[4] else None,
            "next_review": str(row[5]) if row[5] else None,
        }

        if fsrs_card_json:
            fsrs_card = Card.from_dict(json.loads(fsrs_card_json))
        else:
            fsrs_card = Card()

        fsrs_rating = RATING_MAP[rating]

        fsrs_card, review_log = scheduler.review_card(
            fsrs_card,
            fsrs_rating
        )

        new_fsrs_card_json = json.dumps(fsrs_card.to_dict())

        if rating == 1:
            cursor.execute("""
                UPDATE flashcards
                SET
                    fsrs_card = %s,
                    times_seen = times_seen + 1,
                    times_wrong = times_wrong + 1,
                    last_reviewed = NOW(),
                    next_review = %s
                WHERE id = %s;
            """, (
                new_fsrs_card_json,
                fsrs_card.due,
                card_id
            ))

            correct = False

        else:
            cursor.execute("""
                UPDATE flashcards
                SET
                    fsrs_card = %s,
                    times_seen = times_seen + 1,
                    times_correct = times_correct + 1,
                    last_reviewed = NOW(),
                    next_review = %s
                WHERE id = %s;
            """, (
                new_fsrs_card_json,
                fsrs_card.due,
                card_id
            ))

            correct = True

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

    # Update score after the review has successfully committed.
    # This keeps the scoring separate from the flashcard update transaction.
    learnt_delta = 1 if was_new and correct else 0

    language, profile = get_deck_language_and_profile(deck_id)

    if language is not None and profile is not None:
        update_today_language_score(
            profile=profile,
            language=language,
            cards_reviewed_delta=1,
            cards_learnt_delta=learnt_delta,
            daily_review_goal=50,
            daily_add_goal=10,
        )

    return undo_data

def restore_review_state(last_action: dict) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE flashcards
        SET
            fsrs_card = %s,
            times_seen = %s,
            times_correct = %s,
            times_wrong = %s,
            last_reviewed = %s,
            next_review = %s
        WHERE id = %s;
    """, (
        last_action["fsrs_card"],
        last_action["times_seen"],
        last_action["times_correct"],
        last_action["times_wrong"],
        last_action["last_reviewed"],
        last_action["next_review"],
        last_action["card_id"]
    ))

    conn.commit()
    cursor.close()
    conn.close()

    return last_action["deck_id"]