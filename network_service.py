# network_service.py

from pathlib import Path
from functools import lru_cache

import pandas as pd
from deep_translator import GoogleTranslator

from database import get_connection


# --------------------------------------------------
# Network cache settings
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

NETWORK_CACHE_DIR = BASE_DIR / "network_cache"

SPANISH_NODES_PATH = NETWORK_CACHE_DIR / "spanish_nodes_10000.csv"
SPANISH_EDGES_PATH = NETWORK_CACHE_DIR / "spanish_edges_10000_threshold_085.csv"

DEFAULT_LANGUAGE = "spanish"
DEFAULT_N_SUGGESTIONS = 20


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def clean_word(word: str) -> str:
    if not word:
        return ""

    return str(word).strip().lower()


def clean_word_list(words: list[str]) -> list[str]:
    cleaned_words = []
    seen = set()

    for word in words:
        word = clean_word(word)

        if not word:
            continue

        if len(word) < 2:
            continue

        if word in seen:
            continue

        seen.add(word)
        cleaned_words.append(word)

    return cleaned_words


# --------------------------------------------------
# Load cached network
# --------------------------------------------------

@lru_cache(maxsize=1)
def load_spanish_network():
    """
    Load the precomputed Spanish semantic network from CSV.

    Returns:
        nodes_df
        edges_df
        adjacency dict:
            {
                "comer": [
                    {"word": "beber", "similarity": 0.91},
                    ...
                ]
            }
    """
    if not SPANISH_NODES_PATH.exists():
        raise FileNotFoundError(f"Missing nodes cache: {SPANISH_NODES_PATH}")

    if not SPANISH_EDGES_PATH.exists():
        raise FileNotFoundError(f"Missing edges cache: {SPANISH_EDGES_PATH}")

    nodes_df = pd.read_csv(SPANISH_NODES_PATH)
    edges_df = pd.read_csv(SPANISH_EDGES_PATH)

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

    # Sort neighbours by highest similarity first
    for word in adjacency:
        adjacency[word] = sorted(
            adjacency[word],
            key=lambda item: item["similarity"],
            reverse=True
        )

    return nodes_df, edges_df, adjacency


# --------------------------------------------------
# Deck words
# --------------------------------------------------

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


# --------------------------------------------------
# Translation
# --------------------------------------------------

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


# --------------------------------------------------
# Direct neighbours for one word
# --------------------------------------------------

def get_similar_words_spanish(
    query_word: str,
    n_suggestions: int = DEFAULT_N_SUGGESTIONS,
    exclude_words=None
) -> list[dict]:
    if exclude_words is None:
        exclude_words = set()
    else:
        exclude_words = {clean_word(word) for word in exclude_words}

    query_word = clean_word(query_word)

    _, _, adjacency = load_spanish_network()

    neighbours = adjacency.get(query_word, [])

    suggestions = []

    for item in neighbours:
        word = item["word"]

        if word in exclude_words:
            continue

        suggestions.append({
            "word": word,
            "similarity": round(float(item["similarity"]), 4)
        })

        if len(suggestions) >= n_suggestions:
            break

    return suggestions


# --------------------------------------------------
# Suggestions for a deck
# --------------------------------------------------

def get_cached_network_suggestions_for_deck(
    deck_id: int,
    language: str,
    n_words: int = 10000,
    n_suggestions: int = 20,
    top_k_known_words: int = 5,
    min_similarity_to_known: float = 0.85
) -> dict:
    """
    Suggest words from the cached thresholded network.

    This no longer builds embeddings at request time.
    It uses the precomputed edge list.
    """

    # At the moment we only have Spanish cache.
    # Later you can add German/French/etc. cache files.
    if language not in ["spanish", "spa", "es"]:
        return {
            "suggestions": [],
            "known_word_count": 0,
            "known_words_in_network_count": 0,
            "network_word_count": 0,
            "language": language,
            "n_words": n_words,
            "error": f"No cached network available for language={language}"
        }

    nodes_df, edges_df, adjacency = load_spanish_network()

    known_words = get_words_in_deck(deck_id)
    known_word_set = set(known_words)

    network_word_set = set(nodes_df["Token"].astype(str).str.lower())

    known_words_in_network = [
        word for word in known_words
        if word in network_word_set
    ]

    if not known_words_in_network:
        return {
            "suggestions": [],
            "known_word_count": len(known_words),
            "known_words_in_network_count": 0,
            "network_word_count": len(network_word_set),
            "language": language,
            "n_words": n_words
        }

    candidate_scores = {}

    for known_word in known_words_in_network:
        neighbours = adjacency.get(known_word, [])

        for item in neighbours:
            candidate_word = item["word"]
            similarity = float(item["similarity"])

            if candidate_word in known_word_set:
                continue

            if similarity < min_similarity_to_known:
                continue

            if candidate_word not in candidate_scores:
                candidate_scores[candidate_word] = {
                    "word": candidate_word,
                    "best_similarity": similarity,
                    "closest_known_word": known_word,
                    "all_similarities": [similarity]
                }
            else:
                candidate_scores[candidate_word]["all_similarities"].append(similarity)

                if similarity > candidate_scores[candidate_word]["best_similarity"]:
                    candidate_scores[candidate_word]["best_similarity"] = similarity
                    candidate_scores[candidate_word]["closest_known_word"] = known_word

    ranked_candidates = []

    for candidate_word, data in candidate_scores.items():
        similarities = sorted(data["all_similarities"], reverse=True)

        top_values = similarities[:top_k_known_words]
        combined_score = sum(top_values) / len(top_values)

        ranked_candidates.append({
            "word": candidate_word,
            "combined_score": combined_score,
            "closest_similarity": data["best_similarity"],
            "closest_known_word": data["closest_known_word"]
        })

    ranked_candidates.sort(
        key=lambda item: item["combined_score"],
        reverse=True
    )

    suggestions = []

    for item in ranked_candidates[:n_suggestions]:
        translation = translate_network_word(
            word=item["word"],
            source_language="es",
            target_language="en"
        )

        suggestions.append({
            "word": item["word"],
            "translation": translation,
            "combined_score": round(float(item["combined_score"]), 4),
            "closest_known_word": item["closest_known_word"],
            "closest_similarity": round(float(item["closest_similarity"]), 4)
        })

    return {
        "suggestions": suggestions,
        "known_word_count": len(known_words),
        "known_words_in_network_count": len(known_words_in_network),
        "network_word_count": len(network_word_set),
        "language": language,
        "n_words": n_words
    }

def get_adjacent_network_words_for_deck(
    deck_id: int,
    query_word: str,
    language: str,
    n_suggestions: int = 20,
    translate_suggestions: bool = False
) -> list[dict]:
    """
    Return words adjacent to query_word in the cached threshold network,
    excluding words already in the selected deck.
    """

    query_word = clean_word(query_word)

    if language not in ["spanish", "spa", "es"]:
        return []

    _, _, adjacency = load_spanish_network()

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
                source_language="es",
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

def translate_query_to_network_language(
    query_word: str,
    source_language: str = "en",
    target_language: str = "es"
) -> str:
    query_word = clean_word(query_word)

    if not query_word:
        return ""

    if source_language == target_language:
        return query_word

    try:
        translated = GoogleTranslator(
            source=source_language,
            target=target_language
        ).translate(query_word)

        return clean_word(translated)

    except Exception as error:
        print("QUERY TRANSLATION ERROR:", error)
        return query_word