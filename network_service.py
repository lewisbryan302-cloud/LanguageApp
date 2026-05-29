# network_service.py

import os
import pickle
from pathlib import Path

import torch
from wordfreq import top_n_list
from sentence_transformers import SentenceTransformer, util
from deep_translator import GoogleTranslator

from database import get_connection


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

CACHE_DIR = Path("network_cache")
CACHE_DIR.mkdir(exist_ok=True)

DEFAULT_N_WORDS = 5000
DEFAULT_THRESHOLD = 0.45

_model = None


def get_model():
    global _model

    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)

    return _model


def clean_word_list(words: list[str]) -> list[str]:
    cleaned_words = []
    seen = set()

    for word in words:
        if not word:
            continue

        word = word.strip().lower()

        if not word:
            continue

        if len(word) < 2:
            continue

        if " " in word:
            continue

        if word in seen:
            continue

        seen.add(word)
        cleaned_words.append(word)

    return cleaned_words


def get_network_cache_path(
    language: str,
    n_words: int = DEFAULT_N_WORDS
) -> Path:
    return CACHE_DIR / f"network_{language}_{n_words}.pkl"


def build_language_embedding_cache(
    language: str,
    n_words: int = DEFAULT_N_WORDS
) -> dict:
    print(f"Building network cache for language={language}, n_words={n_words}")

    words = top_n_list(language, n_words)
    words = clean_word_list(words)

    model = get_model()

    embeddings = model.encode(
        words,
        convert_to_tensor=True,
        normalize_embeddings=True
    )

    cache = {
        "language": language,
        "n_words": n_words,
        "words": words,
        "embeddings": embeddings.cpu()
    }

    cache_path = get_network_cache_path(language, n_words)

    with open(cache_path, "wb") as f:
        pickle.dump(cache, f)

    print(f"Saved network cache to {cache_path}")

    return cache


def load_language_embedding_cache(
    language: str,
    n_words: int = DEFAULT_N_WORDS
) -> dict:
    cache_path = get_network_cache_path(language, n_words)

    if cache_path.exists():
        print(f"Loading network cache from {cache_path}")

        with open(cache_path, "rb") as f:
            return pickle.load(f)

    return build_language_embedding_cache(
        language=language,
        n_words=n_words
    )


def get_words_in_deck(deck_id: int) -> list[str]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT front, back
        FROM flashcards
        WHERE deck_id = %s;
        """,
        (deck_id,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    words = []

    for front, back in rows:
        if front:
            words.append(front)

        if back:
            words.append(back)

    return clean_word_list(words)


def translate_network_word(
    word: str,
    source_language: str,
    target_language: str = "en"
) -> str:
    if not word:
        return ""

    if source_language == target_language:
        return word

    try:
        return GoogleTranslator(
            source=source_language,
            target=target_language
        ).translate(word)

    except Exception as error:
        print("NETWORK TRANSLATION ERROR:", error)
        return ""


def get_cached_network_suggestions_for_deck(
    deck_id: int,
    language: str,
    n_words: int = DEFAULT_N_WORDS,
    n_suggestions: int = 20,
    top_k_known_words: int = 5,
    min_similarity_to_known: float = 0.30
) -> dict:
    cache = load_language_embedding_cache(
        language=language,
        n_words=n_words
    )

    network_words = cache["words"]
    network_embeddings = cache["embeddings"]

    known_words = get_words_in_deck(deck_id)
    known_word_set = set(known_words)

    known_words_in_network = [
        word
        for word in known_words
        if word in network_words
    ]

    if not known_words_in_network:
        return {
            "suggestions": [],
            "known_word_count": len(known_words),
            "known_words_in_network_count": 0,
            "network_word_count": len(network_words),
            "language": language,
            "n_words": n_words
        }

    word_to_index = {
        word: index
        for index, word in enumerate(network_words)
    }

    known_indices = [
        word_to_index[word]
        for word in known_words_in_network
    ]

    unknown_indices = [
        index
        for index, word in enumerate(network_words)
        if word not in known_word_set
    ]

    known_embeddings = network_embeddings[known_indices]
    unknown_embeddings = network_embeddings[unknown_indices]

    similarity_matrix = util.cos_sim(
        unknown_embeddings,
        known_embeddings
    )

    top_k = min(top_k_known_words, len(known_indices))

    top_values, top_positions = similarity_matrix.topk(
        k=top_k,
        dim=1
    )

    combined_scores = top_values.mean(dim=1)
    closest_similarities = top_values[:, 0]

    ranked_indices = combined_scores.argsort(descending=True)

    suggestions = []

    for ranked_index in ranked_indices:
        ranked_index = int(ranked_index)

        closest_similarity = float(closest_similarities[ranked_index])

        if closest_similarity < min_similarity_to_known:
            continue

        unknown_word_index = unknown_indices[ranked_index]
        suggested_word = network_words[unknown_word_index]

        closest_known_position = int(top_positions[ranked_index, 0])
        closest_known_network_index = known_indices[closest_known_position]
        closest_known_word = network_words[closest_known_network_index]

        translation = translate_network_word(
            word=suggested_word,
            source_language=language,
            target_language="en"
        )

        suggestions.append({
            "word": suggested_word,
            "translation": translation,
            "combined_score": round(float(combined_scores[ranked_index]), 4),
            "closest_known_word": closest_known_word,
            "closest_similarity": round(closest_similarity, 4)
        })

        if len(suggestions) >= n_suggestions:
            break

    return {
        "suggestions": suggestions,
        "known_word_count": len(known_words),
        "known_words_in_network_count": len(known_words_in_network),
        "network_word_count": len(network_words),
        "language": language,
        "n_words": n_words
    }