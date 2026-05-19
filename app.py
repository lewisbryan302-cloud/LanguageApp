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
import re
from markupsafe import Markup, escape
from fastapi.staticfiles import StaticFiles
from fastapi import UploadFile, File
import os
import uuid
import base64
from starlette.middleware.sessions import SessionMiddleware
import json
from fsrs import Scheduler, Card, Rating

scheduler = Scheduler()


def render_cloze_hidden(text: str) -> Markup:
    escaped = escape(text)

    hidden = re.sub(
        r"\{\{c\d+::(.*?)\}\}",
        '<span class="cloze-blank">_____</span>',
        str(escaped)
    )

    return Markup(hidden)


def render_cloze_revealed(text: str) -> Markup:
    escaped = escape(text)

    revealed = re.sub(
        r"\{\{c\d+::(.*?)\}\}",
        r'<span class="cloze-answer">\1</span>',
        str(escaped)
    )

    return Markup(revealed)

embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key="change-this-to-any-random-string"
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.filters["cloze_hidden"] = render_cloze_hidden
templates.env.filters["cloze_revealed"] = render_cloze_revealed

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

    deck_name = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "card": card,
            "deck_id": deck_id,
            "deck_name": deck_name,
            "remaining_reviews": remaining_reviews
        }
    )


@app.post("/answer")
def submit_answer(
    request: Request,
    card_id: int = Form(...),
    deck_id: int = Form(...),
    rating: int = Form(...)
):
    conn = get_connection()
    cursor = conn.cursor()

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

    fsrs_card_json = row[0]

    request.session["last_review_action"] = {
        "card_id": card_id,
        "deck_id": deck_id,
        "fsrs_card": fsrs_card_json,
        "times_seen": row[1],
        "times_correct": row[2],
        "times_wrong": row[3],
        "last_reviewed": str(row[4]) if row[4] else None,
        "next_review": str(row[5]) if row[5] else None
    }

    if fsrs_card_json:
        fsrs_card = Card.from_dict(json.loads(fsrs_card_json))
    else:
        fsrs_card = Card()

    rating_map = {
        1: Rating.Again,
        2: Rating.Hard,
        3: Rating.Good,
        4: Rating.Easy
    }

    fsrs_rating = rating_map[rating]

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

    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(
        f"/review/{deck_id}",
        status_code=303
    )

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
    card_type: str = Form("basic"),
    add_reverse: str | None = Form(None),
    image: UploadFile | None = File(None),
    pasted_image_data: str | None = Form(None)
):
    
    image_path = None

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO flashcards (deck_id, front, back, card_type, image_path)
        VALUES (%s, %s, %s, %s, %s);
    """, (deck_id, front, back, card_type, image_path))

    if add_reverse == "yes" and card_type == "basic":
        cursor.execute("""
            INSERT INTO flashcards (deck_id, front, back)
            VALUES (%s, %s, %s);
        """, (deck_id, back, front))

    image_path = None

    upload_dir = "static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    if image and image.filename:
        ext = os.path.splitext(image.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(upload_dir, filename)

        with open(file_path, "wb") as f:
            f.write(image.file.read())

        image_path = f"/static/uploads/{filename}"

    elif pasted_image_data:
        header, encoded = pasted_image_data.split(",", 1)
        image_bytes = base64.b64decode(encoded)

        filename = f"{uuid.uuid4()}.png"
        file_path = os.path.join(upload_dir, filename)

        with open(file_path, "wb") as f:
            f.write(image_bytes)

        image_path = f"/static/uploads/{filename}"

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
def add_deck(name: str = Form(...), target_language: str = Form(...)):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO decks (name, target_language)
        VALUES (%s, %s);
    """, (name, target_language))

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
            next_review,
            card_type
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

    cursor.execute("""
        SELECT target_language
        FROM decks
        WHERE id = %s;
    """, (deck_id,))
    target_language_row = cursor.fetchone()

    cursor.close()
    conn.close()

    if target_language_row:
        target_language = target_language_row[0]
    else:
        target_language = "de"

    suggestions = []

    for card in existing_cards:
        card_id, existing_front, existing_back = card

        score_front = embedding_similarity(front, existing_front)
        score_back = embedding_similarity(back, existing_back)
        score_cross_1 = embedding_similarity(front, existing_back)
        score_cross_2 = embedding_similarity(back, existing_front)

        score = max(
            score_front,
            score_back,
            score_cross_1,
            score_cross_2
        )

        if score > 0.75:
            suggestions.append(
                (
                    card_id,
                    existing_front,
                    existing_back,
                    score
                )
            )

    suggestions.sort(key=lambda x: x[3], reverse=True)

    raw_word_suggestions = get_similar_words_with_translations(
        front,
        k=10,
        threshold=0.45,
        source="en",
        target=target_language
    )

    existing_pairs = {
        (existing_front.strip().lower(), existing_back.strip().lower())
        for _, existing_front, existing_back in existing_cards
    }

    word_suggestions = []

    for item in raw_word_suggestions:
        suggested_pair = (
            item["word"].strip().lower(),
            item["translation"].strip().lower()
        )

        reverse_pair = (
            item["translation"].strip().lower(),
            item["word"].strip().lower()
        )

        if suggested_pair not in existing_pairs and reverse_pair not in existing_pairs:
            word_suggestions.append(item)

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

    cursor.execute("""
        SELECT id
        FROM flashcards
        WHERE deck_id = %s
        AND front = %s
        AND back = %s;
    """, (deck_id, front, back))

    main_duplicate_exists = cursor.fetchone()

    if not main_duplicate_exists:
        cursor.execute("""
            INSERT INTO flashcards (deck_id, front, back)
            VALUES (%s, %s, %s);
        """, (deck_id, front, back))

    if add_reverse == "yes":
        cursor.execute("""
            SELECT id
            FROM flashcards
            WHERE deck_id = %s
            AND front = %s
            AND back = %s;
        """, (deck_id, back, front))

        main_reverse_duplicate_exists = cursor.fetchone()

        if not main_reverse_duplicate_exists:
            cursor.execute("""
                INSERT INTO flashcards (deck_id, front, back)
                VALUES (%s, %s, %s);
            """, (deck_id, back, front))

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
                SELECT id
                FROM flashcards
                WHERE deck_id = %s
                AND front = %s
                AND back = %s;
            """, (deck_id, word, translation))

            duplicate_exists = cursor.fetchone()

            if not duplicate_exists:
                cursor.execute("""
                    INSERT INTO flashcards (deck_id, front, back)
                    VALUES (%s, %s, %s);
                """, (deck_id, word, translation))

            if add_reverse == "yes":
                cursor.execute("""
                    SELECT id
                    FROM flashcards
                    WHERE deck_id = %s
                    AND front = %s
                    AND back = %s;
                """, (deck_id, translation, word))

                reverse_duplicate_exists = cursor.fetchone()

                if not reverse_duplicate_exists:
                    cursor.execute("""
                        INSERT INTO flashcards (deck_id, front, back)
                        VALUES (%s, %s, %s);
                    """, (deck_id, translation, word))

    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(
        f"/deck/{deck_id}/cards",
        status_code=303
    )


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

@app.post("/cards/delete-front-back-duplicates")
def delete_front_back_duplicates(deck_id: int = Form(...)):
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

    return RedirectResponse(
        f"/deck/{deck_id}/cards",
        status_code=303
    )

@app.post("/undo-review")
def undo_review(request: Request):
    last_action = request.session.get("last_review_action")

    if not last_action:
        return {"status": "nothing_to_undo"}

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

    deck_id = last_action["deck_id"]

    request.session["last_review_action"] = None

    return {
        "status": "success",
        "deck_id": deck_id
    }

@app.post("/card/{card_id}/quick-edit")
def quick_edit_card(
    card_id: int,
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

    return {"status": "success"}

@app.post("/deck/{deck_id}/set-profile")
def set_deck_profile(
    deck_id: int,
    profile: str = Form(...)
):
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

    return RedirectResponse("/", status_code=303)

@app.get("/add-language")
def add_language_page(request: Request):

    languages = [
        {
            "name": "Spanish",
            "code": "es",
            "icon": "🇪🇸"
        },
        {
            "name": "German",
            "code": "de",
            "icon": "🇩🇪"
        },
        {
            "name": "French",
            "code": "fr",
            "icon": "🇫🇷"
        },
        {
            "name": "Italian",
            "code": "it",
            "icon": "🇮🇹"
        },
        {
            "name": "Norwegian",
            "code": "no",
            "icon": "🇳🇴"
        }
    ]

    return templates.TemplateResponse(
        request,
        "add_language.html",
        {
            "languages": languages
        }
    )

@app.post("/add-language")
def add_language(
    language_name: str = Form(...),
    target_language: str = Form(...)
):
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

    return RedirectResponse("/", status_code=303)