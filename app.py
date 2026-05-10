from datetime import datetime, timedelta
from fastapi import FastAPI, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from database import get_connection

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
def home():
    return RedirectResponse("/review")

# --- Mechanism to review flashcards ---
@app.get("/review")
def review_page(request: Request):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, front, back
        FROM flashcards
        WHERE next_review <= NOW()
        ORDER BY times_wrong DESC, last_reviewed ASC NULLS FIRST
        LIMIT 1;
    """)

    card = cursor.fetchone()

    cursor.close()
    conn.close()

    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "card": card
        }
    )


@app.post("/answer")
def submit_answer(card_id: int = Form(...), rating: int = Form(...)):
    next_review = get_next_review_date(rating)

    conn = get_connection()
    cursor = conn.cursor()

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
    cursor.close()
    conn.close()

    return RedirectResponse("/review", status_code=303)

# --- Mechanism to add new flashcards ---
@app.get("/add-card")
def add_card_page(request: Request):
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
            "decks": decks
        }
    )


@app.post("/add-card")
def add_card(
    deck_id: int = Form(...),
    front: str = Form(...),
    back: str = Form(...)
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO flashcards (deck_id, front, back)
        VALUES (%s, %s, %s);
    """, (deck_id, front, back))

    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse("/add-card", status_code=303)