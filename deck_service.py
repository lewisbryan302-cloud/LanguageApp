# deck_service.py

from database import get_connection


def get_home_decks() -> list:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            decks.id,
            decks.name,

            COUNT(flashcards.id) AS total_cards,

            COUNT(
                CASE
                    WHEN flashcards.times_correct > 0
                    THEN 1
                END
            ) AS words_learnt,

            COUNT(
                CASE
                    WHEN flashcards.times_seen = 0
                    THEN 1
                END
            ) AS new_cards,

            COUNT(
                CASE
                    WHEN flashcards.next_review <= NOW()
                    THEN 1
                END
            ) AS cards_to_review,

            decks.profile

        FROM decks

        LEFT JOIN flashcards
            ON flashcards.deck_id = decks.id

        GROUP BY
            decks.id,
            decks.name,
            decks.deck_order,
            decks.profile

        ORDER BY
            decks.deck_order ASC,
            decks.id ASC;
    """)

    decks = cursor.fetchall()

    cursor.close()
    conn.close()

    return decks

def get_deck_options() -> list:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name
        FROM decks
        ORDER BY id;
    """)

    decks = cursor.fetchall()

    cursor.close()
    conn.close()

    return decks

def create_language_deck(
    language_name: str,
    target_language: str
) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO decks (
            name,
            profile,
            target_language
        )
        VALUES (%s, %s, %s);
    """, (
        language_name,
        "Languages",
        target_language
    ))

    conn.commit()
    cursor.close()
    conn.close()
    
def create_deck(name: str, target_language: str) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO decks (name, target_language)
        VALUES (%s, %s);
    """, (name, target_language))

    conn.commit()
    cursor.close()
    conn.close()

def get_deck_by_id(deck_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name
        FROM decks
        WHERE id = %s;
    """, (deck_id,))

    deck = cursor.fetchone()

    cursor.close()
    conn.close()

    return deck

def get_deck_language_by_id(deck_id: int) -> str:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT target_language
        FROM decks
        WHERE id = %s;
    """, (deck_id,))

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    if not row or not row[0]:
        return "en"

    return row[0]

def rename_deck_by_id(deck_id: int, name: str) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE decks
        SET name = %s
        WHERE id = %s;
    """, (name, deck_id))

    conn.commit()
    cursor.close()
    conn.close()

def delete_deck_by_id(deck_id: int) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM flashcards
        WHERE deck_id = %s;
    """, (deck_id,))

    cursor.execute("""
        DELETE FROM decks
        WHERE id = %s;
    """, (deck_id,))

    conn.commit()
    cursor.close()
    conn.close()

def save_deck_order_by_ids(deck_ids: list[int]) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    for index, deck_id in enumerate(deck_ids):
        cursor.execute("""
            UPDATE decks
            SET deck_order = %s
            WHERE id = %s;
        """, (index, deck_id))

    conn.commit()
    cursor.close()
    conn.close()

def update_deck_profile(deck_id: int, profile: str) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE decks
        SET profile = %s
        WHERE id = %s;
    """, (profile, deck_id))

    conn.commit()
    cursor.close()
    conn.close()

def create_deck_and_return_id(name: str, target_language: str = "unknown") -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO decks (
            name,
            target_language,
            profile,
            deck_order
        )
        VALUES (
            %s,
            %s,
            %s,
            COALESCE(
                (SELECT MAX(deck_order) + 1 FROM decks),
                0
            )
        )
        RETURNING id;
    """, (
        name,
        target_language,
        "Decks"
    ))

    deck_id = cursor.fetchone()[0]

    conn.commit()
    cursor.close()
    conn.close()

    return deck_id