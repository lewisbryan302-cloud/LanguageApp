import pandas as pd
from sentence_transformers import SentenceTransformer, util


N_LEMMAS = 5000
THRESHOLD = 0.50
TOP_K = 20

lemmas_df = pd.read_csv(r"C:\Users\lewis\OneDrive\Documents\LanguageApp\lemmas.csv")

lemmas_df = lemmas_df.head(N_LEMMAS)

lemmas = lemmas_df["lemma"].tolist()

model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

embeddings = model.encode(
    lemmas,
    convert_to_tensor=True,
    normalize_embeddings=True
)

similarities = util.cos_sim(embeddings, embeddings)

edges = []

for i, source in enumerate(lemmas):
    scores = similarities[i]

    top_results = scores.topk(k=TOP_K + 1)

    for score, j in zip(top_results.values, top_results.indices):
        j = int(j)
        score = float(score)

        if i == j:
            continue

        if score < THRESHOLD:
            continue

        target = lemmas[j]

        edges.append({
            "source": source,
            "target": target,
            "weight": score
        })

edges_df = pd.DataFrame(edges)

edges_df.to_csv("lemma_edges.csv", index=False)

print("Done.")
print(f"Lemmas: {len(lemmas)}")
print(f"Edges: {len(edges_df)}")
print("Saved: lemma_edges.csv")