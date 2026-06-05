# card_service.py
import os
import uuid
import base64
from fastapi import UploadFile

from database import get_connection
import re


def parse_tag_string(tag_string: str) -> list[str]:
    return [
        tag.strip().lower()
        for tag in re.split(r"[,;|]", tag_string)
        if tag.strip()
    ]


def quick_update_card(card_id: int, front: str, back: str) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE flashcards
        SET front = %s,
            back = %s
        WHERE id = %s;
    """, (front, back, card_id))

    conn.commit()
    cursor.close()
    conn.close()

def save_card_image(
    image: UploadFile | None,
    pasted_image_data: str | None
) -> str | None:
    upload_dir = "static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    if image and image.filename:
        ext = os.path.splitext(image.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(upload_dir, filename)

        with open(file_path, "wb") as f:
            f.write(image.file.read())

        return f"/static/uploads/{filename}"

    if pasted_image_data:
        header, encoded = pasted_image_data.split(",", 1)
        image_bytes = base64.b64decode(encoded)

        filename = f"{uuid.uuid4()}.png"
        file_path = os.path.join(upload_dir, filename)

        with open(file_path, "wb") as f:
            f.write(image_bytes)

        return f"/static/uploads/{filename}"

    return None


def insert_card(
    cursor,
    deck_id: int,
    front: str,
    back: str,
    card_type: str = "basic",
    image_path: str | None = None
) -> int:
    cursor.execute(
        """
        INSERT INTO flashcards (
            deck_id,
            front,
            back,
            card_type,
            image_path
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id;
        """,
        (deck_id, front, back, card_type, image_path)
    )

    return cursor.fetchone()[0]


def create_manual_card(
    deck_id: int,
    front: str,
    back: str,
    card_type: str = "basic",
    add_reverse: str | None = None,
    image: UploadFile | None = None,
    pasted_image_data: str | None = None
) -> int:
    image_path = save_card_image(image, pasted_image_data)

    conn = get_connection()
    cursor = conn.cursor()

    try:
        new_card_id = insert_card(
            cursor=cursor,
            deck_id=deck_id,
            front=front,
            back=back,
            card_type=card_type,
            image_path=image_path
        )

        cards_added_count = 1

        if add_reverse == "yes" and card_type == "basic":
            insert_card(
                cursor=cursor,
                deck_id=deck_id,
                front=back,
                back=front,
                card_type="basic",
                image_path=None
            )

            cards_added_count += 1

        conn.commit()

        return new_card_id

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

def get_deck_cards_page_data(deck_id: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name
        FROM decks
        WHERE id = %s;
    """, (deck_id,))
    deck = cursor.fetchone()

    cursor.execute("""
        SELECT 
            id,
            front,
            back,
            times_seen,
            times_correct,
            times_wrong,
            last_reviewed,
            next_review,
            card_type
        FROM flashcards
        WHERE deck_id = %s
        ORDER BY id;
    """, (deck_id,))
    cards = cursor.fetchall()

    card_ids = [card[0] for card in cards]
    tags_by_card_id = get_tags_for_cards(cursor, card_ids)

    cursor.close()
    conn.close()

    return {
        "deck": deck,
        "cards": cards,
        "tags_by_card_id": tags_by_card_id,
    }

def add_reverse_cards_for_selected(
    deck_id: int,
    card_ids: list[int] | None
) -> None:
    if not card_ids:
        return

    conn = get_connection()
    cursor = conn.cursor()

    for card_id in card_ids:
        cursor.execute("""
            SELECT front, back
            FROM flashcards
            WHERE id = %s AND deck_id = %s;
        """, (card_id, deck_id))

        card = cursor.fetchone()

        if not card:
            continue

        front, back = card

        cursor.execute("""
            SELECT id
            FROM flashcards
            WHERE deck_id = %s
            AND front = %s
            AND back = %s;
        """, (deck_id, back, front))

        reverse_exists = cursor.fetchone()

        if not reverse_exists:
            cursor.execute("""
                INSERT INTO flashcards (deck_id, front, back)
                VALUES (%s, %s, %s);
            """, (deck_id, back, front))

    conn.commit()
    cursor.close()
    conn.close()

def delete_duplicate_front_back_cards(deck_id: int) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM flashcards
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY deck_id, front, back
                        ORDER BY id
                    ) AS duplicate_number
                FROM flashcards
                WHERE deck_id = %s
            ) duplicates
            WHERE duplicate_number > 1
        );
    """, (deck_id,))

    conn.commit()
    cursor.close()
    conn.close()

def delete_card_by_id(card_id: int) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM flashcards
        WHERE id = %s;
    """, (card_id,))

    conn.commit()
    cursor.close()
    conn.close()

def delete_selected_cards_by_id(card_ids: list[int] | None) -> None:
    if not card_ids:
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM flashcards
        WHERE id = ANY(%s);
    """, (card_ids,))

    conn.commit()
    cursor.close()
    conn.close()

def get_card_for_edit(card_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, deck_id, front, back
        FROM flashcards
        WHERE id = %s;
    """, (card_id,))

    card = cursor.fetchone()

    cursor.close()
    conn.close()

    return card

def reset_srs_for_selected_cards(
    deck_id: int,
    card_ids: list[int] | None
) -> None:
    if not card_ids:
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE flashcards
        SET
            times_seen = 0,
            times_correct = 0,
            times_wrong = 0,
            last_reviewed = NULL,
            next_review = NOW()
        WHERE id = ANY(%s)
        AND deck_id = %s;
    """, (card_ids, deck_id))

    conn.commit()
    cursor.close()
    conn.close()

def get_or_create_tag(cursor, tag_name: str) -> int:
    tag_name = tag_name.strip().lower()

    cursor.execute(
        """
        INSERT INTO tags (name)
        VALUES (%s)
        ON CONFLICT (name)
        DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (tag_name,)
    )

    return cursor.fetchone()[0]

def set_card_tags_with_cursor(cursor, card_id: int, tag_string: str):
    tags = parse_tag_string(tag_string)

    cursor.execute(
        """
        DELETE FROM card_tags
        WHERE card_id = %s
        """,
        (card_id,)
    )

    for tag in tags:
        tag_id = get_or_create_tag(cursor, tag)

        cursor.execute(
            """
            INSERT INTO card_tags (card_id, tag_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (card_id, tag_id)
        )

def set_card_tags(card_id: int, tag_string: str):
    conn = get_connection()
    cursor = conn.cursor()

    set_card_tags_with_cursor(cursor, card_id, tag_string)

    conn.commit()
    cursor.close()
    conn.close()

def get_tags_for_cards(cursor, card_ids: list[int]) -> dict[int, list[str]]:
    if not card_ids:
        return {}

    cursor.execute(
        """
        SELECT
            card_tags.card_id,
            tags.name
        FROM card_tags
        JOIN tags
            ON card_tags.tag_id = tags.id
        WHERE card_tags.card_id = ANY(%s)
        ORDER BY tags.name
        """,
        (card_ids,)
    )

    rows = cursor.fetchall()

    tags_by_card_id = {}

    for card_id, tag_name in rows:
        if card_id not in tags_by_card_id:
            tags_by_card_id[card_id] = []

        tags_by_card_id[card_id].append(tag_name)

    return tags_by_card_id