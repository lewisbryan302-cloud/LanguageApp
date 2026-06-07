# network_service.py

from pathlib import Path
from functools import lru_cache

import pandas as pd
from deep_translator import GoogleTranslator

from database import get_connection
from constants import LANGUAGE_OPTIONS


# --------------------------------------------------
# Network cache settings
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

# If network_service.py is inside a services/ folder, use this instead:
# BASE_DIR = Path(__file__).resolve().parent.parent

NETWORK_CACHE_DIR = BASE_DIR / "network_cache"

DEFAULT_N_WORDS = 10000
DEFAULT_THRESHOLD_LABEL = "085"
DEFAULT_N_SUGGESTIONS = 20


# --------------------------------------------------
# Language helpers
# --------------------------------------------------

LANGUAGE_NAME_TO_CODE = {
    item["name"].lower(): item["code"]
    for item in LANGUAGE_OPTIONS
}

LANGUAGE_CODE_SET = {
    item["code"]
    for item in LANGUAGE_OPTIONS
}


def clean_word(word: str) -> str:
    if word is None:
        return ""

    return str(word).strip().lower()


def normalise_language_code(language: str) -> str:
    """
    Accepts:
        Spanish, spanish, es
        German, german, de
        Mandarin, zh-cn

    Returns:
        es, de, fr, it, no, ja, zh-cn, ko
    """
    language = clean_word(language)

    if language in LANGUAGE_CODE_SET:
        return language

    if language in LANGUAGE_NAME_TO_CODE:
        return LANGUAGE_NAME_TO_CODE[language]

    return language


def google_translate_code(language_code: str) -> str:
    """
    Map your internal language codes to codes accepted by deep_translator.
    """
    language_code = normalise_language_code(language_code)

    if language_code == "zh-cn":
        return "zh-CN"

    return language_code


def clean_word_list(words: list[str]) -> list[str]:
    cleaned_words = []
    seen = set()

    for word in words:
        word = clean_word(word)

        if not word:
            continue

        if word in seen:
            continue

        seen.add(word)
        cleaned_words.append(word)

    return cleaned_words


# --------------------------------------------------
# Cache paths
# --------------------------------------------------

def get_network_cache_paths(
    language: str,
    n_words: int = DEFAULT_N_WORDS,
    threshold_label: str = DEFAULT_THRESHOLD_LABEL
) -> tuple[Path, Path]:
    language_code = normalise_language_code(language)

    nodes_path = NETWORK_CACHE_DIR / f"{language_code}_nodes_{n_words}.csv"
    edges_path = NETWORK_CACHE_DIR / f"{language_code}_edges_{n_words}_threshold_{threshold_label}.csv"

    return nodes_path, edges_path


def get_legacy_spanish_cache_paths() -> tuple[Path, Path]:
    """
    Temporary fallback for your existing Spanish cache names.
    """
    nodes_path = NETWORK_CACHE_DIR / "spanish_nodes_10000.csv"
    edges_path = NETWORK_CACHE_DIR / "spanish_edges_10000_threshold_085.csv"

    return nodes_path, edges_path


# --------------------------------------------------
# Load cached network
# --------------------------------------------------

@lru_cache(maxsize=16)
def load_language_network(
    language: str,
    n_words: int = DEFAULT_N_WORDS,
    threshold_label: str = DEFAULT_THRESHOLD_LABEL
):
    """
    Load a precomputed semantic network from CSV.

    Returns:
        nodes_df
        edges_df
        adjacency dict
    """
    language_code = normalise_language_code(language)

    nodes_path, edges_path = get_network_cache_paths(
        language=language_code,
        n_words=n_words,
        threshold_label=threshold_label
    )

    # Temporary fallback for your existing Spanish file names
    if language_code == "es" and (not nodes_path.exists() or not edges_path.exists()):
        legacy_nodes_path, legacy_edges_path = get_legacy_spanish_cache_paths()

        if legacy_nodes_path.exists() and legacy_edges_path.exists():
            nodes_path = legacy_nodes_path
            edges_path = legacy_edges_path

    if not nodes_path.exists():
        raise FileNotFoundError(f"Missing nodes cache for {language_code}: {nodes_path}")

    if not edges_path.exists():
        raise FileNotFoundError(f"Missing edges cache for {language_code}: {edges_path}")

    nodes_df = pd.read_csv(nodes_path)
    edges_df = pd.read_csv(edges_path)

    adjacency = {}

    for _, row in edges_df.iterrows():
        source_word = clean_word(row["source_word"])
        target_word = clean_word(row["target_word"])
        similarity = float(row["similarity"])

        adjacency.setdefault(source_word, []).append({
            "word": target_word,
            "similarity": similarity
        })

        adjacency.setdefault(target_word, []).append({
            "word": source_word,
            "similarity": similarity
        })

    for word in adjacency:
        adjacency[word].sort(
            key=lambda item: item["similarity"],
            reverse=True
        )

    return nodes_df, edges_df, adjacency


# --------------------------------------------------
# Deck cards / deck words
# --------------------------------------------------

def get_cards_in_deck(deck_id: int) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, front, back
        FROM flashcards
        WHERE deck_id = %s;
        """,
        (deck_id,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    cards = []

    for card_id, front, back in rows:
        cards.append({
            "id": card_id,
            "front": front or "",
            "back": back or "",
            "front_clean": clean_word(front),
            "back_clean": clean_word(back),
        })

    return cards


def get_words_in_deck(deck_id: int) -> list[str]:
    cards = get_cards_in_deck(deck_id)

    words = []

    for card in cards:
        if card["front"]:
            words.append(card["front"])

        if card["back"]:
            words.append(card["back"])

    return clean_word_list(words)


# --------------------------------------------------
# Translation
# --------------------------------------------------

_translation_cache = {}


def translate_network_word(
    word: str,
    source_language: str,
    target_language: str = "en"
) -> str:
    word = clean_word(word)

    if not word:
        return ""

    source_code = google_translate_code(source_language)
    target_code = google_translate_code(target_language)

    if source_code == target_code:
        return word

    cache_key = (word, source_code, target_code)

    if cache_key in _translation_cache:
        return _translation_cache[cache_key]

    try:
        translation = GoogleTranslator(
            source=source_code,
            target=target_code
        ).translate(word)

        _translation_cache[cache_key] = translation
        return translation

    except Exception as error:
        print("NETWORK TRANSLATION ERROR:", error)
        _translation_cache[cache_key] = ""
        return ""


def translate_query_to_network_language(
    query_word: str,
    source_language: str = "en",
    target_language: str = "es"
) -> str:
    query_word = clean_word(query_word)

    if not query_word:
        return ""

    source_code = google_translate_code(source_language)
    target_code = google_translate_code(target_language)

    if source_code == target_code:
        return query_word

    try:
        translated = GoogleTranslator(
            source=source_code,
            target=target_code
        ).translate(query_word)

        return clean_word(translated)

    except Exception as error:
        print("QUERY TRANSLATION ERROR:", error)
        return query_word


# --------------------------------------------------
# Existing adjacent cards in deck
# --------------------------------------------------

def get_adjacent_existing_cards_for_deck(
    deck_id: int,
    query_word: str,
    language: str,
    n_suggestions: int = 20
) -> list[dict]:
    """
    Return existing cards in this deck whose target-language word is adjacent
    to query_word in the cached threshold network.
    """
    language_code = normalise_language_code(language)
    query_word = clean_word(query_word)

    try:
        _, _, adjacency = load_language_network(language_code)
    except FileNotFoundError as error:
        print("NETWORK CACHE ERROR:", error)
        return []

    neighbours = adjacency.get(query_word, [])

    if not neighbours:
        return []

    neighbour_similarity = {
        clean_word(item["word"]): float(item["similarity"])
        for item in neighbours
    }

    cards = get_cards_in_deck(deck_id)

    existing_matches = []

    for card in cards:
        front_word = card["front_clean"]
        back_word = card["back_clean"]

        matched_word = None
        translation = ""
        similarity = None

        # Usually target-language word is on the front
        if front_word in neighbour_similarity:
            matched_word = front_word
            translation = card["back"]
            similarity = neighbour_similarity[front_word]

        # Fallback: target-language word is on the back
        elif back_word in neighbour_similarity:
            matched_word = back_word
            translation = card["front"]
            similarity = neighbour_similarity[back_word]

        if matched_word is None:
            continue

        existing_matches.append({
            "card_id": card["id"],
            "word": matched_word,
            "translation": translation,
            "closest_known_word": query_word,
            "closest_similarity": round(float(similarity), 4),
            "score": round(float(similarity), 4),
        })

    existing_matches.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return existing_matches[:n_suggestions]


# --------------------------------------------------
# New adjacent words not already in deck
# --------------------------------------------------

def get_adjacent_network_words_for_deck(
    deck_id: int,
    query_word: str,
    language: str,
    n_suggestions: int = 20,
    translate_suggestions: bool = True
) -> list[dict]:
    """
    Return adjacent network words not already in the selected deck.
    """
    language_code = normalise_language_code(language)
    query_word = clean_word(query_word)

    try:
        _, _, adjacency = load_language_network(language_code)
    except FileNotFoundError as error:
        print("NETWORK CACHE ERROR:", error)
        return []

    deck_words = get_words_in_deck(deck_id)
    deck_word_set = set(deck_words)

    neighbours = adjacency.get(query_word, [])

    word_suggestions = []

    for item in neighbours:
        suggested_word = clean_word(item["word"])
        similarity = float(item["similarity"])

        if not suggested_word:
            continue

        if suggested_word in deck_word_set:
            continue

        if translate_suggestions:
            translation = translate_network_word(
                word=suggested_word,
                source_language=language_code,
                target_language="en"
            )
        else:
            translation = ""

        word_suggestions.append({
            "word": suggested_word,
            "translation": translation,
            "score": round(similarity, 4),
            "combined_score": round(similarity, 4),
            "closest_known_word": query_word,
            "closest_similarity": round(similarity, 4),
        })

        if len(word_suggestions) >= n_suggestions:
            break

    return word_suggestions


# --------------------------------------------------
# Legacy compatibility wrapper
# --------------------------------------------------

def get_cached_network_suggestions_for_deck(
    deck_id: int,
    language: str,
    n_words: int = DEFAULT_N_WORDS,
    n_suggestions: int = 20,
    top_k_known_words: int = 5,
    min_similarity_to_known: float = 0.85
) -> dict:
    """
    Compatibility wrapper for older app code.
    """
    known_words = get_words_in_deck(deck_id)

    return {
        "suggestions": [],
        "known_word_count": len(known_words),
        "known_words_in_network_count": 0,
        "network_word_count": 0,
        "language": language,
        "n_words": n_words
    }