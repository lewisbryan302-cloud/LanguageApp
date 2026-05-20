from wordfreq import top_n_list
from sentence_transformers import SentenceTransformer, util
import numpy as np
import pandas as pd


# --- CONFIGURATION ---
LANGUAGE = "en"
N_WORDS = 5000
THRESHOLD = 0.65

KNOWN_WORDS = {"dog", "cat", "horse", "animal", "pet"}


# --- LOAD MODEL AND WORDS ---
model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

words = top_n_list(LANGUAGE, N_WORDS)


# --- CREATE EMBEDDINGS ---
embeddings = model.encode(
    words,
    convert_to_tensor=True,
    normalize_embeddings=True
)


# --- CREATE SIMILARITY MATRIX ---
similarity_matrix = util.cos_sim(
    embeddings,
    embeddings
)

adjacency_matrix = similarity_matrix.cpu().numpy()


# --- CLEAN ADJACENCY MATRIX ---
np.fill_diagonal(adjacency_matrix, 0)

adjacency_matrix[adjacency_matrix < THRESHOLD] = 0


# --- SAVE ADJACENCY MATRIX ---
adjacency_df = pd.DataFrame(
    adjacency_matrix,
    index=words,
    columns=words
)

adjacency_df.to_csv("word_adjacency_matrix.csv")


# --- CREATE EDGE LIST ---
edges = []

for i, source in enumerate(words):
    for j, target in enumerate(words):

        # Avoid duplicate symmetric edges
        if j <= i:
            continue

        weight = adjacency_matrix[i, j]

        if weight > 0:
            edges.append({
                "source": source,
                "target": target,
                "weight": weight
            })

edges_df = pd.DataFrame(edges)

edges_df.to_csv("word_edges.csv", index=False)


print("Network built.")
print(f"Words: {N_WORDS}")
print(f"Edges: {len(edges)}")
print("Saved:")
print("- word_adjacency_matrix.csv")
print("- word_edges.csv")


# --- SUGGEST NEW WORDS FROM KNOWN WORDS ---
all_words = set(edges_df["source"]) | set(edges_df["target"])

candidates = []

for word in all_words:

    if word in KNOWN_WORDS:
        continue

    connected_edges = edges_df[
        (edges_df["source"] == word) |
        (edges_df["target"] == word)
    ]

    known_edges = connected_edges[
        (
            connected_edges["source"].isin(KNOWN_WORDS)
        ) |
        (
            connected_edges["target"].isin(KNOWN_WORDS)
        )
    ]

    if known_edges.empty:
        continue

    avg_similarity_to_known = known_edges["weight"].mean()
    known_neighbour_count = len(known_edges)
    total_degree = len(connected_edges)

    candidates.append({
        "word": word,
        "avg_similarity_to_known": avg_similarity_to_known,
        "known_neighbour_count": known_neighbour_count,
        "total_degree": total_degree
    })


suggestions = pd.DataFrame(candidates)

if suggestions.empty:
    print("No suggestions found.")

else:
    suggestions["known_neighbour_score"] = (
        suggestions["known_neighbour_count"] /
        suggestions["known_neighbour_count"].max()
    )

    suggestions["degree_score"] = (
        suggestions["total_degree"] /
        suggestions["total_degree"].max()
    )

    suggestions["score"] = (
        0.5 * suggestions["avg_similarity_to_known"]
        + 0.3 * suggestions["known_neighbour_score"]
        + 0.2 * suggestions["degree_score"]
    )

    suggestions = suggestions.sort_values(
        "score",
        ascending=False
    )

    suggestions.to_csv("word_suggestions.csv", index=False)

    print("\nTop suggestions:")
    print(suggestions.head(20))

    print("\nSaved:")
    print("- word_suggestions.csv")