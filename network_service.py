# network_service.py

from wordfreq import top_n_list
from deep_translator import GoogleTranslator
from sentence_transformers import SentenceTransformer, util
import networkx as nx

from database import get_connection


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

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

        # First network version: single-word nodes only.
        # Phrases can be handled separately later.
        if " " in word:
            continue

        if word in seen:
            continue

        seen.add(word)
        cleaned_words.append(word)

    return cleaned_words

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


def get_candidate_corpus(
    language: str,
    n_words: int
) -> list[str]:
    words = top_n_list(language, n_words)

    return clean_word_list(words)


def build_similarity_matrix(words: list[str]):
    model = get_model()

    embeddings = model.encode(
        words,
        convert_to_tensor=True,
        normalize_embeddings=True
    )

    similarity_matrix = util.cos_sim(
        embeddings,
        embeddings
    )

    return similarity_matrix


def find_max_connected_threshold(
    words: list[str],
    similarity_matrix
) -> float | None:
    if len(words) < 2:
        return None

    graph = nx.Graph()

    for word in words:
        graph.add_node(word)

    n = len(words)

    for i in range(n):
        for j in range(i + 1, n):
            graph.add_edge(
                words[i],
                words[j],
                weight=float(similarity_matrix[i, j])
            )

    tree = nx.maximum_spanning_tree(
        graph,
        weight="weight"
    )

    if tree.number_of_edges() == 0:
        return None

    threshold = min(
        edge_data["weight"]
        for _, _, edge_data in tree.edges(data=True)
    )

    return threshold


def build_network_edges(
    words: list[str],
    similarity_matrix,
    threshold: float,
    max_edges: int = 250
) -> list[dict]:
    edges = []

    n = len(words)

    for i in range(n):
        for j in range(i + 1, n):
            similarity = float(similarity_matrix[i, j])

            if similarity >= threshold:
                edges.append({
                    "source": words[i],
                    "target": words[j],
                    "weight": round(similarity, 4)
                })

    edges.sort(
        key=lambda edge: edge["weight"],
        reverse=True
    )

    return edges[:max_edges]


def build_network_nodes(
    words: list[str],
    known_word_set: set[str]
) -> list[dict]:
    nodes = []

    for word in words:
        nodes.append({
            "word": word,
            "known": word in known_word_set
        })

    return nodes


def suggest_unknown_words_from_network(
    words: list[str],
    known_words: list[str],
    similarity_matrix,
    n_suggestions: int = 20,
    min_similarity_to_known: float = 0.30,
    source_language: str = "en"
) -> list[dict]:
    known_word_set = set(known_words)

    known_indices = [
        index
        for index, word in enumerate(words)
        if word in known_word_set
    ]

    unknown_indices = [
        index
        for index, word in enumerate(words)
        if word not in known_word_set
    ]

    if not known_indices or not unknown_indices:
        return []

    suggestions = []

    for unknown_index in unknown_indices:
        similarities_to_known = similarity_matrix[
            unknown_index,
            known_indices
        ]

        top_k = min(5, len(known_indices))

        top_values, top_positions = similarities_to_known.topk(
            k=top_k
        )

        combined_score = float(top_values.mean())
        closest_similarity = float(top_values[0])

        if closest_similarity < min_similarity_to_known:
            continue

        closest_known_index = known_indices[int(top_positions[0])]
        closest_known_word = words[closest_known_index]

        suggested_word = words[unknown_index]

        translation = translate_network_word(
            word=suggested_word,
            source_language=source_language,
            target_language="en"
        )

        suggestions.append({
            "word": suggested_word,
            "translation": translation,
            "combined_score": round(combined_score, 4),
            "closest_known_word": closest_known_word,
            "closest_similarity": round(closest_similarity, 4)
        })

    suggestions.sort(
        key=lambda item: item["combined_score"],
        reverse=True
    )

    return suggestions[:n_suggestions]


def build_deck_network_data(
    deck_id: int,
    language: str,
    n_candidates: int = 10000,
    threshold: float | None = 0.75,
    use_auto_threshold: bool = False,
    n_suggestions: int = 20,
    max_edges: int = 250
) -> dict:
    known_words = get_words_in_deck(deck_id)

    if not known_words:
        return {
            "nodes": [],
            "edges": [],
            "suggestions": [],
            "threshold": threshold,
            "auto_threshold": None,
            "known_word_count": 0,
            "network_word_count": 0,
            "component_count": 0
        }

    candidate_words = get_candidate_corpus(
        language=language,
        n_words=n_candidates
    )

    known_word_set = set(known_words)

    unknown_candidate_words = [
        word
        for word in candidate_words
        if word not in known_word_set
    ]

    # Keep the network small enough for the widget.
    # Known words are always included, then we add candidate words.
    network_words = clean_word_list(
        known_words + unknown_candidate_words
    )

    similarity_matrix = build_similarity_matrix(network_words)

    auto_threshold = find_max_connected_threshold(
        words=network_words,
        similarity_matrix=similarity_matrix
    )

    if use_auto_threshold and auto_threshold is not None:
        active_threshold = auto_threshold
    else:
        active_threshold = threshold if threshold is not None else 0.45

    nodes = build_network_nodes(
        words=network_words,
        known_word_set=known_word_set
    )

    edges = build_network_edges(
        words=network_words,
        similarity_matrix=similarity_matrix,
        threshold=active_threshold,
        max_edges=max_edges
    )

    graph = nx.Graph()

    for node in nodes:
        graph.add_node(node["word"])

    for edge in edges:
        graph.add_edge(
            edge["source"],
            edge["target"],
            weight=edge["weight"]
        )

    if graph.number_of_nodes() > 0:
        component_count = nx.number_connected_components(graph)
    else:
        component_count = 0

    suggestions = suggest_unknown_words_from_network(
        words=network_words,
        known_words=known_words,
        similarity_matrix=similarity_matrix,
        n_suggestions=n_suggestions,
        source_language=language
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "suggestions": suggestions,
        "threshold": round(active_threshold, 4),
        "auto_threshold": round(auto_threshold, 4) if auto_threshold is not None else None,
        "known_word_count": len(known_words),
        "network_word_count": len(network_words),
        "component_count": component_count
    }