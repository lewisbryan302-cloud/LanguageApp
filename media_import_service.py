# media_import_service.py

import re
from collections import Counter

from database import get_connection

from deep_translator import GoogleTranslator

def translate_media_word(
    word: str,
    source_language: str,
    user_language: str = "en"
) -> str:
    if not word:
        return ""

    if source_language == user_language:
        return word

    try:
        return GoogleTranslator(
            source=source_language,
            target=user_language
        ).translate(word)

    except Exception as error:
        print("MEDIA IMPORT TRANSLATION ERROR:", error)
        return ""

def normalise_word(word: str) -> str:
    return word.strip().lower()


def extract_1grams_from_text(text: str) -> list[str]:
    """
    First simple version:
    Extract alphabetic words, including accented characters.
    Good enough for Spanish/French/German/Italian first pass.
    """

    if not text:
        return []

    raw_words = re.findall(
        r"[A-Za-zÀ-ÖØ-öø-ÿñÑüÜáéíóúÁÉÍÓÚ]+",
        text.lower()
    )

    words = []

    for word in raw_words:
        word = normalise_word(word)

        if len(word) < 2:
            continue

        words.append(word)

    return words


def get_existing_deck_words(deck_id: int) -> set[str]:
    """
    First version assumes the target-language word is usually on the front.
    This avoids English translations on the back blocking Spanish/French/etc words.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT front
        FROM flashcards
        WHERE deck_id = %s;
        """,
        (deck_id,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    existing_words = set()

    for row in rows:
        front = row[0]

        if not front:
            continue

        front = normalise_word(front)

        if " " in front:
            continue

        existing_words.add(front)

    return existing_words


def extract_unknown_1grams_for_deck(
    deck_id: int,
    text: str,
    source_language: str,
    user_language: str = "en",
    minimum_count: int = 1,
    max_results: int = 100
) -> list[dict]:
    extracted_words = extract_1grams_from_text(text)

    existing_words = get_existing_deck_words(deck_id)

    counts = Counter(extracted_words)

    candidates = []

    for word, count in counts.items():
        if count < minimum_count:
            continue

        if word in existing_words:
            continue

        translation = translate_media_word(
            word=word,
            source_language=source_language,
            user_language=user_language
        )

        candidates.append({
            "word": word,
            "translation": translation,
            "count": count
        })

    candidates.sort(
        key=lambda item: (
            -item["count"],
            item["word"]
        )
    )

    return candidates[:max_results]