# card_service.py
import os
import uuid
import base64
from fastapi import UploadFile

from database import get_connection


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
) -> None:
    cursor.execute("""
        INSERT INTO flashcards (deck_id, front, back, card_type, image_path)
        VALUES (%s, %s, %s, %s, %s);
    """, (deck_id, front, back, card_type, image_path))


def create_manual_card(
    deck_id: int,
    front: str,
    back: str,
    card_type: str = "basic",
    add_reverse: str | None = None,
    image: UploadFile | None = None,
    pasted_image_data: str | None = None
) -> None:
    image_path = save_card_image(image, pasted_image_data)

    conn = get_connection()
    cursor = conn.cursor()

    insert_card(
        cursor=cursor,
        deck_id=deck_id,
        front=front,
        back=back,
        card_type=card_type,
        image_path=image_path
    )

    if add_reverse == "yes" and card_type == "basic":
        insert_card(
            cursor=cursor,
            deck_id=deck_id,
            front=back,
            back=front,
            card_type="basic",
            image_path=None
        )

    conn.commit()
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

    cursor.close()
    conn.close()

    return {
        "deck": deck,
        "cards": cards,
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