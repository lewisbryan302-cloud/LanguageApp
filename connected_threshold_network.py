# connected_threshold_network.py

from wordfreq import top_n_list
from sentence_transformers import SentenceTransformer, util
import networkx as nx
import numpy as np


LANGUAGE = "en"
N_WORDS = 5000

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def get_word_corpus(
    language: str = LANGUAGE,
    n_words: int = N_WORDS
) -> list[str]:
    words = top_n_list(language, n_words)

    cleaned_words = []

    for word in words:
        word = word.strip().lower()

        if not word:
            continue

        if " " in word:
            continue

        cleaned_words.append(word)

    return cleaned_words


def build_similarity_matrix(words: list[str]) -> np.ndarray:
    model = SentenceTransformer(MODEL_NAME)

    embeddings = model.encode(
        words,
        convert_to_tensor=True,
        normalize_embeddings=True
    )

    similarity_matrix = util.cos_sim(
        embeddings,
        embeddings
    ).cpu().numpy()

    return similarity_matrix


def build_complete_similarity_graph(
    words: list[str],
    similarity_matrix: np.ndarray
) -> nx.Graph:
    graph = nx.Graph()

    for word in words:
        graph.add_node(word)

    n = len(words)

    for i in range(n):
        for j in range(i + 1, n):
            similarity = float(similarity_matrix[i, j])

            graph.add_edge(
                words[i],
                words[j],
                weight=similarity
            )

    return graph


def find_max_connected_threshold(
    graph: nx.Graph
) -> tuple[float, nx.Graph]:
    maximum_spanning_tree = nx.maximum_spanning_tree(
        graph,
        weight="weight"
    )

    weakest_required_edge = min(
        edge_data["weight"]
        for _, _, edge_data in maximum_spanning_tree.edges(data=True)
    )

    return weakest_required_edge, maximum_spanning_tree


def build_threshold_graph(
    words: list[str],
    similarity_matrix: np.ndarray,
    threshold: float
) -> nx.Graph:
    graph = nx.Graph()

    for word in words:
        graph.add_node(word)

    n = len(words)

    for i in range(n):
        for j in range(i + 1, n):
            similarity = float(similarity_matrix[i, j])

            if similarity >= threshold:
                graph.add_edge(
                    words[i],
                    words[j],
                    weight=similarity
                )

    return graph


def print_weakest_tree_edges(
    tree: nx.Graph,
    n_edges: int = 20
) -> None:
    edges = sorted(
        tree.edges(data=True),
        key=lambda edge: edge[2]["weight"]
    )

    print()
    print("Weakest edges in the maximum spanning tree:")
    print("-------------------------------------------")

    for word_a, word_b, edge_data in edges[:n_edges]:
        print(
            f"{word_a:20s} <-> {word_b:20s} "
            f"similarity = {edge_data['weight']:.4f}"
        )


def run_connected_threshold_experiment(
    language: str = LANGUAGE,
    n_words: int = N_WORDS
) -> None:
    print(f"Loading top {n_words} words for language: {language}")

    words = get_word_corpus(
        language=language,
        n_words=n_words
    )

    print(f"Words after cleaning: {len(words)}")

    print("Building similarity matrix...")
    similarity_matrix = build_similarity_matrix(words)

    print("Building complete similarity graph...")
    complete_graph = build_complete_similarity_graph(
        words=words,
        similarity_matrix=similarity_matrix
    )

    print("Finding maximum connected threshold...")
    threshold, maximum_spanning_tree = find_max_connected_threshold(
        complete_graph
    )

    threshold_graph = build_threshold_graph(
        words=words,
        similarity_matrix=similarity_matrix,
        threshold=threshold
    )

    number_of_components = nx.number_connected_components(
        threshold_graph
    )

    print()
    print("RESULT")
    print("------")
    print(f"Maximum threshold for one connected component: {threshold:.4f}")
    print(f"Number of nodes: {threshold_graph.number_of_nodes()}")
    print(f"Number of edges at threshold: {threshold_graph.number_of_edges()}")
    print(f"Number of connected components: {number_of_components}")

    print_weakest_tree_edges(
        tree=maximum_spanning_tree,
        n_edges=20
    )


if __name__ == "__main__":
    run_connected_threshold_experiment(
        language="en",
        n_words=5000
    )