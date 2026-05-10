import psycopg2
from datetime import datetime, timedelta

conn = psycopg2.connect(
    dbname="language_app",
    user="postgres",
    password="beinGrufne5*",
    host="localhost",
    port="5432"
)

cursor = conn.cursor()


def get_next_review_date(rating):
    """
    rating:
    0 = forgot completely
    1 = hard
    2 = okay
    3 = easy
    """

    if rating == 0:
        return datetime.now() + timedelta(minutes=10)
    elif rating == 1:
        return datetime.now() + timedelta(days=1)
    elif rating == 2:
        return datetime.now() + timedelta(days=3)
    elif rating == 3:
        return datetime.now() + timedelta(days=7)
    else:
        return datetime.now() + timedelta(days=1)


cursor.execute("""
    SELECT id, front, back
    FROM flashcards
    WHERE next_review <= NOW()
    ORDER BY times_wrong DESC, last_reviewed ASC NULLS FIRST
    LIMIT 10;
""")

cards = cursor.fetchall()

if not cards:
    print("No cards due for review.")
else:
    for card_id, front, back in cards:
        print("\n---------------------")
        print(f"Front: {front}")
        input("Press Enter to reveal answer...")

        print(f"Back: {back}")

        print("\nHow well did you remember it?")
        print("0 = forgot")
        print("1 = hard")
        print("2 = okay")
        print("3 = easy")

        rating = int(input("Rating: "))

        next_review = get_next_review_date(rating)

        if rating == 0:
            cursor.execute("""
                UPDATE flashcards
                SET
                    times_seen = times_seen + 1,
                    times_wrong = times_wrong + 1,
                    last_reviewed = NOW(),
                    next_review = %s
                WHERE id = %s;
            """, (next_review, card_id))
        else:
            cursor.execute("""
                UPDATE flashcards
                SET
                    times_seen = times_seen + 1,
                    times_correct = times_correct + 1,
                    last_reviewed = NOW(),
                    next_review = %s
                WHERE id = %s;
            """, (next_review, card_id))

        conn.commit()

        print(f"Next review scheduled for: {next_review}")

cursor.close()
conn.close()