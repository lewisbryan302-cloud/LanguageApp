from datetime import datetime, timedelta
from fastapi import FastAPI, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from database import get_connection
from typing import Optional
from sentence_transformers import SentenceTransformer, util
from embedding_helper import get_similar_words
from embedding_helper import get_similar_words_with_translations
from fsrs_scheduler import schedule_review
from pydantic import BaseModel

embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

app = FastAPI()
templates = Jinja2Templates(directory="templates")

def get_next_review_date(rating: int):
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


@app.get("/db-test")
def db_test():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1;")
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return {"database": "connected", "result": result[0]}

@app.get("/")
def home(request: Request):
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
            ) AS cards_to_review

        FROM decks

        LEFT JOIN flashcards
            ON flashcards.deck_id = decks.id

        GROUP BY
            decks.id,
            decks.name,
            decks.deck_order

        ORDER BY
            decks.deck_order ASC,
            decks.id ASC;
    """)

    decks = cursor.fetchall()

    cursor.close()
    conn.close()

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "decks": decks
        }
    )

# --- Mechanism to review flashcards ---
@app.get("/review/{deck_id}")
def review_page(request: Request, deck_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, front, back
    FROM flashcards
    WHERE deck_id = %s
    AND next_review <= NOW()
    ORDER BY times_wrong DESC, last_reviewed ASC NULLS FIRST
    LIMIT 1;
    """, (deck_id,))

    card = cursor.fetchone()

    cursor.close()
    conn.close()

    return templates.TemplateResponse(
    request,
    "review.html",
    {
        "card": card,
        "deck_id": deck_id
    }
    )


@app.post("/answer")
def submit_answer(
    card_id: int = Form(...),
    deck_id: int = Form(...),
    rating: int = Form(...)
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            difficulty,
            stability,
            reps,
            lapses,
            last_reviewed
        FROM flashcards
        WHERE id = %s;
    """, (card_id,))

    row = cursor.fetchone()

    card = {
        "difficulty": row[0] or 0,
        "stability": row[1] or 0,
        "reps": row[2] or 0,
        "lapses": row[3] or 0,
        "last_review": row[4].date().isoformat() if row[4] else None
    }

    updated_card = schedule_review(card, rating)

    if rating == 1:
        cursor.execute("""
            UPDATE flashcards
            SET
                times_seen = times_seen + 1,
                times_wrong = times_wrong + 1,
                difficulty = %s,
                stability = %s,
                reps = %s,
                lapses = %s,
                last_reviewed = NOW(),
                next_review = %s
            WHERE id = %s;
        """, (
            updated_card["difficulty"],
            updated_card["stability"],
            updated_card["reps"],
            updated_card["lapses"],
            updated_card["due_date"],
            card_id
        ))
    else:
        cursor.execute("""
            UPDATE flashcards
            SET
                times_seen = times_seen + 1,
                times_correct = times_correct + 1,
                difficulty = %s,
                stability = %s,
                reps = %s,
                lapses = %s,
                last_reviewed = NOW(),
                next_review = %s
            WHERE id = %s;
        """, (
            updated_card["difficulty"],
            updated_card["stability"],
            updated_card["reps"],
            updated_card["lapses"],
            updated_card["due_date"],
            card_id
        ))

    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(f"/review/{deck_id}", status_code=303)

# --- Mechanism to add new flashcards ---
@app.get("/add-card")
def add_card_page(
    request: Request,
    deck_id: int | None = None,
    add_reverse: str | None = None
):
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

    return templates.TemplateResponse(
        request,
        "add_card.html",
        {
            "decks": decks,
            "selected_deck_id": deck_id,
            "add_reverse": add_reverse
        }
    )


@app.post("/add-card")
def add_card(
    deck_id: int = Form(...),
    front: str = Form(...),
    back: str = Form(...),
    add_reverse: str | None = Form(None)
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO flashcards (deck_id, front, back)
        VALUES (%s, %s, %s);
    """, (deck_id, front, back))

    if add_reverse == "yes":
        cursor.execute("""
            INSERT INTO flashcards (deck_id, front, back)
            VALUES (%s, %s, %s);
        """, (deck_id, back, front))

    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(
        f"/add-card?deck_id={deck_id}&add_reverse={add_reverse or ''}",
        status_code=303
    )

# --- Mechanism to add new decks ---
@app.get("/add-deck")
def add_deck_page(request: Request):
    return templates.TemplateResponse(
        request,
        "add_deck.html"
    )


@app.post("/add-deck")
def add_deck(name: str = Form(...)):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO decks (name)
        VALUES (%s);
    """, (name,))

    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse("/", status_code=303)

# --- Mechanism to rename decks ---
@app.get("/rename-deck/{deck_id}")
def rename_deck_page(request: Request, deck_id: int):
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

    return templates.TemplateResponse(
        request,
        "rename_deck.html",
        {
            "deck": deck
        }
    )


@app.post("/rename-deck/{deck_id}")
def rename_deck(deck_id: int, name: str = Form(...)):
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

    return RedirectResponse("/", status_code=303)

# --- Mechanism to delete decks ---
@app.post("/delete-deck/{deck_id}")
def delete_deck(deck_id: int):
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

    return RedirectResponse("/", status_code=303)

# --- Mechanism to view flashcards in a deck ---
@app.get("/deck/{deck_id}/cards")
def view_deck_cards(request: Request, deck_id: int):
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
            next_review
        FROM flashcards
        WHERE deck_id = %s
        ORDER BY id;
    """, (deck_id,))
    cards = cursor.fetchall()

    cursor.close()
    conn.close()

    return templates.TemplateResponse(
        request,
        "deck_cards.html",
        {
            "deck": deck,
            "cards": cards
        }
    )

# --- Mechanism to delete single flashcards ---
@app.post("/card/{card_id}/delete")
def delete_single_card(card_id: int, deck_id: int = Form(...)):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM flashcards
        WHERE id = %s;
    """, (card_id,))

    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(f"/deck/{deck_id}/cards", status_code=303)


@app.post("/cards/delete-selected")
def delete_selected_cards(
    deck_id: int = Form(...),
    card_ids: Optional[list[int]] = Form(None)
):
    if not card_ids:
        return RedirectResponse(f"/deck/{deck_id}/cards", status_code=303)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM flashcards
        WHERE id = ANY(%s);
    """, (card_ids,))

    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(f"/deck/{deck_id}/cards", status_code=303)

# --- Mechanism to add reverse of selected cards ---
@app.post("/cards/add-reverse-selected")
def add_reverse_selected_cards(
    deck_id: int = Form(...),
    card_ids: Optional[list[int]] = Form(None)
):
    if not card_ids:
        return RedirectResponse(f"/deck/{deck_id}/cards", status_code=303)

    conn = get_connection()
    cursor = conn.cursor()

    for card_id in card_ids:
        cursor.execute("""
            SELECT front, back
            FROM flashcards
            WHERE id = %s AND deck_id = %s;
        """, (card_id, deck_id))

        card = cursor.fetchone()

        if card:
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

    return RedirectResponse(f"/deck/{deck_id}/cards", status_code=303)

# --- Mechanism to edit flashcard content ---
@app.get("/card/{card_id}/edit")
def edit_card_page(request: Request, card_id: int):
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

    return templates.TemplateResponse(
        request,
        "edit_card.html",
        {
            "card": card
        }
    )


@app.post("/card/{card_id}/edit")
def edit_card(
    card_id: int,
    deck_id: int = Form(...),
    front: str = Form(...),
    back: str = Form(...)
):
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

    return RedirectResponse(f"/deck/{deck_id}/cards", status_code=303)

# --- Mechanism to reset SRS data for selected cards ---
@app.post("/cards/reset-srs-selected")
def reset_srs_selected_cards(
    deck_id: int = Form(...),
    card_ids: Optional[list[int]] = Form(None)
):
    if not card_ids:
        return RedirectResponse(f"/deck/{deck_id}/cards", status_code=303)

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

    return RedirectResponse(f"/deck/{deck_id}/cards", status_code=303)

# --- Smart add card mechanism ---
@app.get("/smart-add-card")
def smart_add_card_page(request: Request):
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

    return templates.TemplateResponse(
        request,
        "smart_add_card.html",
        {"decks": decks, "suggestions": None}
    )

def embedding_similarity(a: str, b: str) -> float:
    embedding_a = embedding_model.encode(a, convert_to_tensor=True)
    embedding_b = embedding_model.encode(b, convert_to_tensor=True)

    similarity = util.cos_sim(embedding_a, embedding_b)

    return float(similarity[0][0])

@app.post("/smart-add-card/preview")
def smart_add_card_preview(
    request: Request,
    deck_id: int = Form(...),
    front: str = Form(...),
    back: str = Form(...),
    add_reverse: str | None = Form(None)
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, front, back
        FROM flashcards
        WHERE deck_id = %s;
    """, (deck_id,))

    existing_cards = cursor.fetchall()

    cursor.execute("""
        SELECT id, name
        FROM decks
        ORDER BY id;
    """)
    decks = cursor.fetchall()

    cursor.close()
    conn.close()

    suggestions = []

    for card in existing_cards:
        card_id, existing_front, existing_back = card

        score_front = embedding_similarity(front, existing_front)
        score_back = embedding_similarity(back, existing_back)
        score_cross_1 = embedding_similarity(front, existing_back)
        score_cross_2 = embedding_similarity(back, existing_front)

        score = max(score_front, score_back, score_cross_1, score_cross_2)

        if score > 0.75:
            suggestions.append((card_id, existing_front, existing_back, score))

    suggestions.sort(key=lambda x: x[3], reverse=True)

    word_suggestions = get_similar_words_with_translations(
        front,
        k=10,
        threshold=0.45,
        source="en",
        target="de"
    )

    return templates.TemplateResponse(
        request,
        "smart_add_card.html",
        {
            "decks": decks,
            "suggestions": suggestions[:10],
            "word_suggestions": word_suggestions,
            "deck_id": deck_id,
            "front": front,
            "back": back,
            "add_reverse": add_reverse
        }
    )

@app.post("/smart-add-card/create")
def smart_add_card_create(
    deck_id: int = Form(...),
    front: str = Form(...),
    back: str = Form(...),
    add_reverse: str | None = Form(None),
    selected_card_ids: Optional[list[int]] = Form(None),
    selected_suggestion_indices: Optional[list[int]] = Form(None),
    suggested_words: Optional[list[str]] = Form(None),
    suggested_translations: Optional[list[str]] = Form(None)
):
    conn = get_connection()
    cursor = conn.cursor()

    # Add main card
    cursor.execute("""
        INSERT INTO flashcards (deck_id, front, back)
        VALUES (%s, %s, %s);
    """, (deck_id, front, back))

    if add_reverse == "yes":
        cursor.execute("""
            INSERT INTO flashcards (deck_id, front, back)
            VALUES (%s, %s, %s);
        """, (deck_id, back, front))

    # Add reverse versions of selected similar cards if missing
    if selected_card_ids:
        for card_id in selected_card_ids:
            cursor.execute("""
                SELECT front, back
                FROM flashcards
                WHERE id = %s AND deck_id = %s;
            """, (card_id, deck_id))

            card = cursor.fetchone()

            if card:
                old_front, old_back = card

                cursor.execute("""
                    SELECT id
                    FROM flashcards
                    WHERE deck_id = %s
                    AND front = %s
                    AND back = %s;
                """, (deck_id, old_back, old_front))

                reverse_exists = cursor.fetchone()

                if not reverse_exists:
                    cursor.execute("""
                        INSERT INTO flashcards (deck_id, front, back)
                        VALUES (%s, %s, %s);
                    """, (deck_id, old_back, old_front))

    if selected_suggestion_indices and suggested_words and suggested_translations:
        for index in selected_suggestion_indices:
            word = suggested_words[index]
            translation = suggested_translations[index]

            cursor.execute("""
                INSERT INTO flashcards (deck_id, front, back)
                VALUES (%s, %s, %s);
            """, (deck_id, word, translation))

            if add_reverse == "yes":
                cursor.execute("""
                    INSERT INTO flashcards (deck_id, front, back)
                    VALUES (%s, %s, %s);
                """, (deck_id, translation, word))
    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(f"/deck/{deck_id}/cards", status_code=303)

class DeckOrderRequest(BaseModel):
    deck_ids: list[int]


@app.post("/save-deck-order")
def save_deck_order(data: DeckOrderRequest):
    conn = get_connection()
    cursor = conn.cursor()

    for index, deck_id in enumerate(data.deck_ids):
        cursor.execute("""
            UPDATE decks
            SET deck_order = %s
            WHERE id = %s;
        """, (index, deck_id))

    conn.commit()
    cursor.close()
    conn.close()

    return {"status": "success"}