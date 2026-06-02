# deck_service.py

from database import get_connection


def get_home_decks(user_id: int) -> list:
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
            ) AS to_review,

            decks.profile

        FROM decks
        LEFT JOIN flashcards
            ON flashcards.deck_id = decks.id

        WHERE decks.user_id = %s

        GROUP BY
            decks.id,
            decks.name,
            decks.deck_order,
            decks.profile

        ORDER BY
            decks.deck_order ASC,
            decks.id ASC;
    """, (user_id,))

    decks = cursor.fetchall()

    cursor.close()
    conn.close()

    return decks

def user_owns_deck(user_id: int, deck_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 1
        FROM decks
        WHERE id = %s
        AND user_id = %s;
    """, (
        deck_id,
        user_id
    ))

    result = cursor.fetchone()

    cursor.close()
    conn.close()

    return result is not None

def get_deck_options(user_id: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name
        FROM decks
        WHERE user_id = %s
        AND profile != 'Languages'
        ORDER BY id;
    """, (user_id,))

    decks = cursor.fetchall()

    cursor.close()
    conn.close()

    return decks

def create_language_deck(
    language_name: str,
    target_language: str,
    user_id: int
) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO decks (
            name,
            profile,
            target_language,
            user_id,
            deck_order
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            COALESCE(
                (
                    SELECT MAX(deck_order) + 1
                    FROM decks
                    WHERE user_id = %s
                ),
                0
            )
        );
    """, (
        language_name,
        "Languages",
        target_language,
        user_id,
        user_id
    ))

    conn.commit()
    cursor.close()
    conn.close()
    
def create_deck(
    name: str,
    user_id: int,
    target_language: str = "unknown",
    profile: str = "Decks"
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO decks (
            name,
            target_language,
            profile,
            user_id,
            deck_order
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            COALESCE(
                (
                    SELECT MAX(deck_order) + 1
                    FROM decks
                    WHERE user_id = %s
                ),
                0
            )
        );
    """, (
        name,
        target_language,
        profile,
        user_id,
        user_id
    ))

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

def create_deck_and_return_id(
    name: str,
    user_id: int,
    target_language: str = "unknown",
    profile: str = "Decks"
) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO decks (
            name,
            target_language,
            profile,
            user_id,
            deck_order
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            COALESCE(
                (
                    SELECT MAX(deck_order) + 1
                    FROM decks
                    WHERE user_id = %s
                ),
                0
            )
        )
        RETURNING id;
    """, (
        name,
        target_language,
        profile,
        user_id,
        user_id
    ))

    deck_id = cursor.fetchone()[0]

    conn.commit()
    cursor.close()
    conn.close()

    return deck_id

def get_language_deck_id_for_deck(deck_id: int, user_id: int) -> int | None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT target_language, profile
        FROM decks
        WHERE id = %s
        AND user_id = %s;
    """, (
        deck_id,
        user_id
    ))

    deck = cursor.fetchone()

    if not deck:
        cursor.close()
        conn.close()
        return None

    target_language = deck[0]
    profile = deck[1]

    if profile == "Languages":
        cursor.close()
        conn.close()
        return deck_id

    cursor.execute("""
        SELECT id
        FROM decks
        WHERE user_id = %s
        AND profile = 'Languages'
        AND target_language = %s
        ORDER BY deck_order ASC, id ASC
        LIMIT 1;
    """, (
        user_id,
        target_language
    ))

    language_deck = cursor.fetchone()

    cursor.close()
    conn.close()

    if not language_deck:
        return None

    return language_deck[0]

def get_language_deck_context(
    language_deck_id: int,
    user_id: int
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, target_language
        FROM decks
        WHERE id = %s
        AND user_id = %s
        AND profile = 'Languages';
    """, (
        language_deck_id,
        user_id
    ))

    language_deck = cursor.fetchone()

    cursor.close()
    conn.close()

    return language_deck

def get_deck_options_for_language_deck(
    language_deck_id: int,
    user_id: int
) -> list:
    language_deck = get_language_deck_context(
        language_deck_id=language_deck_id,
        user_id=user_id
    )

    if not language_deck:
        return []

    target_language = language_deck[2]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name
        FROM decks
        WHERE user_id = %s
        AND profile != 'Languages'
        AND target_language = %s
        ORDER BY deck_order ASC, id ASC;
    """, (
        user_id,
        target_language
    ))

    decks = cursor.fetchall()

    cursor.close()
    conn.close()

    return decks

def get_existing_language_codes_for_user(user_id: int) -> set[str]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT target_language
        FROM decks
        WHERE user_id = %s
          AND profile = 'Languages'
          AND target_language IS NOT NULL;
        """,
        (user_id,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return {
        row[0].strip().lower()
        for row in rows
        if row[0]
    }