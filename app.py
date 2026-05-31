from fastapi import FastAPI, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import UploadFile, File
from fastapi.responses import JSONResponse

from starlette.requests import Request
from starlette.middleware.sessions import SessionMiddleware

from database import test_connection
from typing import Optional

from cloze import render_cloze_hidden, render_cloze_revealed
from review_service import (
    get_review_page_data,
    submit_card_review,
    restore_review_state,
)
from card_service import (
    quick_update_card,
    get_deck_cards_page_data,
    add_reverse_cards_for_selected,
    create_manual_card,
    delete_duplicate_front_back_cards,
    delete_card_by_id,
    delete_selected_cards_by_id,
    get_card_for_edit,
    reset_srs_for_selected_cards,
    set_card_tags,
)
from deck_service import (
    get_home_decks,
    get_deck_options,
    create_deck,
    get_deck_by_id,
    rename_deck_by_id,
    delete_deck_by_id,
    create_language_deck,
    save_deck_order_by_ids,
    update_deck_profile,
    create_deck_and_return_id,
    get_deck_language_by_id,
)

from stats_service import get_home_stats_widget_data

from import_service import import_cards_from_file

from network_service import get_cached_network_suggestions_for_deck

from media_import_service import (
    extract_unknown_1grams_for_deck,
    extract_text_from_image_file,
    get_tesseract_language_code,
)

from suggestion_service import get_smart_add_preview_data_from_query, create_smart_add_cards_from_query
from auth_service import (
    create_user,
    authenticate_user,
    get_user_by_id
)
from constants import LANGUAGE_OPTIONS
from phrase_helper import get_phrase_suggestions
from embedding_helper import translate_word

import os


def make_deck_name_from_upload(filename: str) -> str:
    if not filename:
        return "Imported Deck"

    base_name = os.path.basename(filename)

    deck_name, _ = os.path.splitext(base_name)

    deck_name = deck_name.replace("_", " ").replace("-", " ").strip()

    if not deck_name:
        return "Imported Deck"

    return deck_name    

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key="change-this-secret-key-later"
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.filters["cloze_hidden"] = render_cloze_hidden
templates.env.filters["cloze_revealed"] = render_cloze_revealed

def get_current_user(request: Request):
    user_id = request.session.get("user_id")

    if not user_id:
        return None

    return get_user_by_id(user_id)


def require_login(request: Request):
    user = get_current_user(request)

    if not user:
        return RedirectResponse(
            "/",
            status_code=303
        )

    return user

@app.get("/db-test")
def db_test():
    result = test_connection()

    return {
        "database": "connected",
        "result": result
    }

@app.get("/")
def welcome_page(request: Request):
    user = get_current_user(request)

    if user:
        return RedirectResponse(
            "/home",
            status_code=303
        )

    return templates.TemplateResponse(
        request,
        "welcome.html",
        {
            "error_message": None
        }
    )

@app.get("/home")
def home(
    request: Request,
    stats_deck_id: int | None = None,
    network_deck_id: int | None = None,
    network_threshold: float = 0.75,
    use_auto_threshold: str | None = None
):
    user = require_login(request)

    if isinstance(user, RedirectResponse):
        return user

    decks = get_home_decks(user_id=user[0])
    stats_widget = get_home_stats_widget_data(
        user_id=user[0],
        deck_id=stats_deck_id
    )

    network_data = None
    network_language = None

    if network_deck_id is not None:
        network_language = get_deck_language_by_id(network_deck_id)

        network_data = get_cached_network_suggestions_for_deck(
            deck_id=network_deck_id,
            language=network_language,
            n_words=10000,
            n_suggestions=20,
            top_k_known_words=5,
            min_similarity_to_known=0.30
        )

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "decks": decks,
            "stats_widget": stats_widget,
            "selected_stats_deck_id": stats_deck_id,
            "selected_network_deck_id": network_deck_id,
            "network_language": network_language,
            "network_data": network_data,
            "network_threshold": network_threshold,
            "use_auto_threshold": use_auto_threshold,
        }
    )

# --- Mechanism to review flashcards ---
@app.get("/review/{deck_id}")
def review_page(request: Request, deck_id: int):
    page_data = get_review_page_data(deck_id)

    return templates.TemplateResponse(
        request,
        "review.html",
        page_data
    )

@app.post("/answer")
def submit_answer(
    request: Request,
    card_id: int = Form(...),
    deck_id: int = Form(...),
    rating: int = Form(...)
):
    undo_data = submit_card_review(card_id, deck_id, rating)

    request.session["last_review_action"] = undo_data

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
    decks = get_deck_options()

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
    pasted_image_data: str | None = Form(None),
    tags: str = Form("")
):
    new_card_id = create_manual_card(
        deck_id=deck_id,
        front=front,
        back=back,
        card_type=card_type,
        add_reverse=add_reverse,
        image=image,
        pasted_image_data=pasted_image_data,
    )

    if tags.strip():
        set_card_tags(new_card_id, tags)

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
    create_deck(name, target_language)

    return RedirectResponse("/", status_code=303)

# --- Mechanism to rename decks ---
@app.get("/rename-deck/{deck_id}")
def rename_deck_page(request: Request, deck_id: int):
    deck = get_deck_by_id(deck_id)

    return templates.TemplateResponse(
        request,
        "rename_deck.html",
        {
            "deck": deck
        }
    )

@app.post("/rename-deck/{deck_id}")
def rename_deck(deck_id: int, name: str = Form(...)):
    rename_deck_by_id(deck_id, name)

    return RedirectResponse("/", status_code=303)

# --- Mechanism to delete decks ---
@app.post("/delete-deck/{deck_id}")
def delete_deck(deck_id: int):
    delete_deck_by_id(deck_id)

    return RedirectResponse("/", status_code=303)

# --- Mechanism to view flashcards in a deck ---
@app.get("/deck/{deck_id}/cards")
def view_deck_cards(request: Request, deck_id: int):
    page_data = get_deck_cards_page_data(deck_id)

    return templates.TemplateResponse(
        request,
        "deck_cards.html",
        page_data
    )

# --- Mechanism to delete single flashcards ---
@app.post("/card/{card_id}/delete")
def delete_single_card_route(card_id: int, deck_id: int = Form(...)):
    delete_card_by_id(card_id)

    return RedirectResponse(
        f"/deck/{deck_id}/cards",
        status_code=303
    )

@app.post("/cards/delete-selected")
def delete_selected_cards(
    deck_id: int = Form(...),
    card_ids: Optional[list[int]] = Form(None)
):
    delete_selected_cards_by_id(card_ids)

    return RedirectResponse(
        f"/deck/{deck_id}/cards",
        status_code=303
    )

# --- Mechanism to add reverse of selected cards ---
@app.post("/cards/add-reverse-selected")
def add_reverse_selected_cards(
    deck_id: int = Form(...),
    card_ids: Optional[list[int]] = Form(None)
):
    add_reverse_cards_for_selected(deck_id, card_ids)

    return RedirectResponse(
        f"/deck/{deck_id}/cards",
        status_code=303
    )

# --- Mechanism to edit flashcard content ---
@app.get("/card/{card_id}/edit")
def edit_card_page(request: Request, card_id: int):
    card = get_card_for_edit(card_id)

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
    quick_update_card(card_id, front, back)

    return RedirectResponse(
        f"/deck/{deck_id}/cards",
        status_code=303
    )

# --- Mechanism to reset SRS data for selected cards ---
@app.post("/cards/reset-srs-selected")
def reset_srs_selected_cards(
    deck_id: int = Form(...),
    card_ids: Optional[list[int]] = Form(None)
):
    reset_srs_for_selected_cards(deck_id, card_ids)

    return RedirectResponse(
        f"/deck/{deck_id}/cards",
        status_code=303
    )


def choose_german_phrase_query(front: str, back: str) -> str | None:
    """
    Choose which side of the card should be used for German phrase search.

    Since the phrase corpus is German, we want to use the German side,
    whether the user put it in Front or Back.
    """
    front = front.strip()
    back = back.strip()

    # Very simple first version:
    # Try the front first, then the back.
    # The phrase helper will return [] if the word is not found.
    return front or back

# --- Smart add card mechanism ---
@app.get("/smart-add-card")
def smart_add_card_page(
    request: Request,
    deck_id: int | None = None
):
    decks = get_deck_options()

    return templates.TemplateResponse(
        request,
        "smart_add_card.html",
        {
            "decks": decks,
            "deck_id": deck_id,
            "query_word": "",
            "suggestions": None,
            "word_suggestions": None,
            "phrase_suggestions": None,
            "phrase_query": None,
        }
    )


@app.post("/smart-add-card/preview")
def smart_add_card_preview(
    request: Request,
    deck_id: int = Form(...),
    query_word: str = Form(...)
):
    query_word = query_word.strip()

    page_data = get_smart_add_preview_data_from_query(
        deck_id=deck_id,
        query_word=query_word,
    )

    target_language = page_data["target_language"]
    phrase_query = page_data["target_query_word"]

    print("SMART ADD DEBUG")
    print("query_word:", query_word)
    print("target_language:", target_language)
    print("phrase_query:", phrase_query)

    phrase_suggestions = get_phrase_suggestions(
        query_word=phrase_query,
        target_language=target_language,
        top_n=10,
        window=2,
        max_candidates=10000,
        max_matches=1000
    )

    for item in phrase_suggestions:
        item["translation"] = translate_word(
            item["phrase"],
            source=target_language,
            target="en"
        )

    page_data["phrase_suggestions"] = phrase_suggestions
    page_data["phrase_query"] = phrase_query

    return templates.TemplateResponse(
        request,
        "smart_add_card.html",
        page_data
    )


@app.post("/smart-add-card/create")
def smart_add_card_create(
    request: Request,
    deck_id: int = Form(...),
    query_word: str = Form(...),
    selected_card_ids: Optional[list[int]] = Form(None),
    selected_suggestion_indices: Optional[list[int]] = Form(None),
    suggested_words: Optional[list[str]] = Form(None),
    suggested_translations: Optional[list[str]] = Form(None),
    selected_phrase_indices: Optional[list[int]] = Form(None),
    suggested_phrases: Optional[list[str]] = Form(None),
    suggested_phrase_translations: Optional[list[str]] = Form(None)
):
    query_word = query_word.strip()

    inserted_count = create_smart_add_cards_from_query(
        deck_id=deck_id,
        query_word=query_word,
        selected_card_ids=selected_card_ids,
        selected_suggestion_indices=selected_suggestion_indices,
        suggested_words=suggested_words,
        suggested_translations=suggested_translations,
        selected_phrase_indices=selected_phrase_indices,
        suggested_phrases=suggested_phrases,
        suggested_phrase_translations=suggested_phrase_translations,
    )

    # Re-run the same preview search after adding cards.
    page_data = get_smart_add_preview_data_from_query(
        deck_id=deck_id,
        query_word=query_word,
    )

    phrase_query = page_data.get("target_query_word", query_word)
    target_language = page_data.get("target_language")

    phrase_suggestions = get_phrase_suggestions(
        query_word=phrase_query,
        target_language=target_language,
        top_n=10,
        window=2,
        max_candidates=10000,
        max_matches=1000
    )

    for item in phrase_suggestions:
        item["translation"] = translate_word(
            item["phrase"],
            source=target_language,
            target="en"
        )

    page_data["phrase_suggestions"] = phrase_suggestions
    page_data["phrase_query"] = phrase_query
    if inserted_count > 0:
        page_data["success_message"] = (
            f"{inserted_count} card{'s' if inserted_count != 1 else ''} successfully added"
        )
    else:
        page_data["success_message"] = "No new cards were added"

    return templates.TemplateResponse(
        request,
        "smart_add_card.html",
        page_data
    )

@app.post("/cards/delete-front-back-duplicates")
def delete_front_back_duplicates(deck_id: int = Form(...)):
    delete_duplicate_front_back_cards(deck_id)

    return RedirectResponse(
        f"/deck/{deck_id}/cards",
        status_code=303
    )

@app.post("/undo-review")
def undo_review(request: Request):
    last_action = request.session.get("last_review_action")

    if not last_action:
        return {"status": "nothing_to_undo"}

    deck_id = restore_review_state(last_action)

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
    quick_update_card(card_id, front, back)

    return {"status": "success"}

@app.post("/deck/{deck_id}/set-profile")
def set_deck_profile(
    deck_id: int,
    profile: str = Form(...)
):
    update_deck_profile(deck_id, profile)

    return RedirectResponse("/", status_code=303)

@app.get("/add-language")
def add_language_page(request: Request):
    return templates.TemplateResponse(
        request,
        "add_language.html",
        {
            "languages": LANGUAGE_OPTIONS
        }
    )

@app.post("/add-language")
def add_language(
    language_name: str = Form(...),
    target_language: str = Form(...)
):
    create_language_deck(language_name, target_language)

    return RedirectResponse("/", status_code=303)

@app.post("/rename-deck-inline/{deck_id}")
def rename_deck_inline(deck_id: int, name: str = Form(...)):
    rename_deck_by_id(deck_id, name)

    return JSONResponse({
        "status": "success",
        "name": name
    })

@app.get("/import-deck")
def import_deck_page(request: Request, deck_id: int):
    deck = get_deck_by_id(deck_id)

    return templates.TemplateResponse(
        request,
        "import_deck.html",
        {
            "deck": deck
        }
    )

@app.post("/import-deck")
def import_deck(
    request: Request,
    deck_id: int = Form(...),
    import_format: str = Form(...),
    file: UploadFile = File(...)
):
    # For now, we will build CSV/TSV first.
    # Anki and Memrise can be routed later by import_format.

    imported_count = import_cards_from_file(
        deck_id=deck_id,
        import_format=import_format,
        file=file
    )

    return RedirectResponse(
        f"/deck/{deck_id}/cards",
        status_code=303
    )

@app.post("/save-deck-order")
def save_deck_order(deck_ids: list[int] = Form(...)):
    save_deck_order_by_ids(deck_ids)

    return JSONResponse({
        "status": "success"
    })

@app.get("/import-new-deck")
def import_new_deck_page(request: Request):
    return templates.TemplateResponse(
        request,
        "import_new_deck.html"
    )


@app.post("/import-new-deck")
def import_new_deck(
    request: Request,
    import_format: str = Form(...),
    file: UploadFile = File(...)
):
    deck_name = make_deck_name_from_upload(file.filename)

    new_deck_id = create_deck_and_return_id(
        name=deck_name,
        target_language="unknown"
    )

    imported_count = import_cards_from_file(
        deck_id=new_deck_id,
        import_format=import_format,
        file=file
    )

    return RedirectResponse(
        f"/deck/{new_deck_id}/cards",
        status_code=303
    )

@app.post("/network/add-suggestion")
def add_network_suggestion(
    deck_id: int = Form(...),
    front: str = Form(...),
    back: str = Form(""),
    network_threshold: float = Form(0.45),
    use_auto_threshold: str | None = Form(None),
    stats_deck_id: int | None = Form(None)
):
    new_card_id = create_manual_card(
        deck_id=deck_id,
        front=front,
        back=back or "",
        card_type="basic",
        add_reverse=None,
        image=None,
        pasted_image_data=None
    )

    set_card_tags(
        new_card_id,
        "network-suggestion"
    )

    redirect_url = (
        f"/?network_deck_id={deck_id}"
        f"&network_threshold={network_threshold}"
    )

    if use_auto_threshold == "yes":
        redirect_url += "&use_auto_threshold=yes"

    if stats_deck_id is not None:
        redirect_url += f"&stats_deck_id={stats_deck_id}"

    redirect_url += "#network-widget"

    return RedirectResponse(
        redirect_url,
        status_code=303
    )

@app.post("/network/add-selected-suggestions")
def add_selected_network_suggestions(
    deck_id: int = Form(...),
    selected_words: list[str] = Form(...),
    selected_translations: list[str] = Form(...),
    network_threshold: float = Form(0.45),
    use_auto_threshold: str | None = Form(None),
    stats_deck_id: int | None = Form(None)
):
    added_count = 0

    for word, translation in zip(selected_words, selected_translations):
        word = word.strip()
        translation = translation.strip()

        if not word:
            continue

        new_card_id = create_manual_card(
            deck_id=deck_id,
            front=word,
            back=translation,
            card_type="basic",
            add_reverse=None,
            image=None,
            pasted_image_data=None
        )

        set_card_tags(
            new_card_id,
            "network-suggestion"
        )

        added_count += 1

    redirect_url = (
        f"/?network_deck_id={deck_id}"
        f"&network_threshold={network_threshold}"
    )

    if use_auto_threshold == "yes":
        redirect_url += "&use_auto_threshold=yes"

    if stats_deck_id is not None:
        redirect_url += f"&stats_deck_id={stats_deck_id}"

    redirect_url += "#network-widget"

    return RedirectResponse(
        redirect_url,
        status_code=303
    )

@app.get("/import-media")
def import_media_page(
    request: Request,
    deck_id: int | None = None
):
    decks = get_deck_options()

    return templates.TemplateResponse(
        request,
        "import_media.html",
        {
            "decks": decks,
            "selected_deck_id": deck_id,
            "source_type": "text",
            "source_text": "",
            "candidates": None,
        }
    )


@app.post("/import-media/preview")
def import_media_preview(
    request: Request,
    deck_id: int = Form(...),
    source_type: str = Form("text"),
    source_text: str = Form(""),
    minimum_count: int = Form(1),
    image_file: UploadFile | None = File(None)
):
    decks = get_deck_options()

    source_language = get_deck_language_by_id(deck_id)
    user_language = "en"

    error_message = None
    text_to_extract = source_text

    if source_type == "image":
        try:
            if image_file is None or not image_file.filename:
                raise ValueError("Please upload an image first.")

            tesseract_language = get_tesseract_language_code(source_language)

            text_to_extract = extract_text_from_image_file(
                file=image_file,
                language=tesseract_language
            )

        except Exception as error:
            error_message = str(error)
            text_to_extract = ""

    candidates = []

    if text_to_extract:
        candidates = extract_unknown_1grams_for_deck(
            deck_id=deck_id,
            text=text_to_extract,
            source_language=source_language,
            user_language=user_language,
            minimum_count=minimum_count,
            max_results=150
        )

    return templates.TemplateResponse(
        request,
        "import_media.html",
        {
            "decks": decks,
            "selected_deck_id": deck_id,
            "source_type": source_type,
            "source_text": text_to_extract if source_type == "image" else source_text,
            "minimum_count": minimum_count,
            "candidates": candidates,
            "source_language": source_language,
            "user_language": user_language,
            "error_message": error_message,
        }
    )


@app.post("/import-media/add-selected")
def import_media_add_selected(
    deck_id: int = Form(...),
    selected_words: list[str] = Form(...),
    selected_translations: list[str] = Form(...)
):
    added_count = 0

    for word, translation in zip(selected_words, selected_translations):
        word = word.strip().lower()
        translation = translation.strip()

        if not word:
            continue

        new_card_id = create_manual_card(
            deck_id=deck_id,
            front=word,
            back=translation,
            card_type="basic",
            add_reverse=None,
            image=None,
            pasted_image_data=None
        )

        set_card_tags(
            new_card_id,
            "media-import"
        )

        added_count += 1

    return RedirectResponse(
        f"/import-media?deck_id={deck_id}",
        status_code=303
    )

@app.post("/signup")
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    email = email.strip().lower()

    if password != confirm_password:
        return templates.TemplateResponse(
            request,
            "welcome.html",
            {
                "error_message": "Passwords do not match."
            }
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "welcome.html",
            {
                "error_message": "Password must be at least 8 characters."
            }
        )

    try:
        user_id = create_user(
            email=email,
            password=password
        )

    except Exception as error:
        print("SIGNUP ERROR:", error)

        return templates.TemplateResponse(
            request,
            "welcome.html",
            {
                "error_message": f"Signup failed: {error}"
            }
        )

    request.session["user_id"] = user_id

    return RedirectResponse(
        "/home",
        status_code=303
    )


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    user = authenticate_user(
        email=email,
        password=password
    )

    if not user:
        return templates.TemplateResponse(
            request,
            "welcome.html",
            {
                "error_message": "Invalid email or password."
            }
        )

    request.session["user_id"] = user["id"]

    return RedirectResponse(
        "/home",
        status_code=303
    )


@app.post("/logout")
def logout(request: Request):
    request.session.clear()

    return RedirectResponse(
        "/",
        status_code=303
    )


@app.get("/forgot-password")
def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {
            "message": None
        }
    )


@app.post("/forgot-password")
def forgot_password_submit(
    request: Request,
    email: str = Form(...)
):
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {
            "message": (
                "If an account exists for that email, "
                "a password reset link would be sent."
            )
        }
    )

@app.get("/profile")
def profile_page(request: Request):
    user = require_login(request)

    if isinstance(user, RedirectResponse):
        return user

    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "user": user
        }
    )