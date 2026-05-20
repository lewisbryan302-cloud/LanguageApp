import pandas as pd


KNOWN_LEMMAS = {
    "dog",
    "cat",
    "horse"
}

edges = pd.read_csv("lemma_edges.csv")

all_lemmas = set(edges["source"]) | set(edges["target"])

candidates = []

for lemma in all_lemmas:

    if lemma in KNOWN_LEMMAS:
        continue

    connected_edges = edges[
        (edges["source"] == lemma) |
        (edges["target"] == lemma)
    ]

    known_edges = connected_edges[
        (connected_edges["source"].isin(KNOWN_LEMMAS)) |
        (connected_edges["target"].isin(KNOWN_LEMMAS))
    ]

    if known_edges.empty:
        continue

    avg_similarity_to_known = known_edges["weight"].mean()
    known_neighbour_count = len(known_edges)
    total_degree = len(connected_edges)

    candidates.append({
        "lemma": lemma,
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

    suggestions.to_csv("lemma_suggestions.csv", index=False)

    print(suggestions.head(30))
    print("\nSaved: lemma_suggestions.csv")