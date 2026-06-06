import json
import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer, util
import networkx as nx
from pathlib import Path


# -----------------------------
# Settings
# -----------------------------
FREQ_PATH = Path(r"C:\Users\lewis\OneDrive\Documents\LanguageApp\Language_Phrases\spanish_frequency_table.csv")

OUTPUT_DIR = Path(r"C:\Users\lewis\OneDrive\Documents\LanguageApp\network_cache")
OUTPUT_DIR.mkdir(exist_ok=True)

N_WORDS = 10000
SIMILARITY_THRESHOLD = 0.85

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

NODES_PATH = OUTPUT_DIR / "spanish_nodes_10000.csv"
EDGES_PATH = OUTPUT_DIR / "spanish_edges_10000_threshold_085.csv"
METADATA_PATH = OUTPUT_DIR / "spanish_network_metadata.json"


def build_threshold_network_cache():
    # --- Load frequency table ---
    freq_df = pd.read_csv(FREQ_PATH)

    nodes_df = freq_df.head(N_WORDS).copy()
    nodes_df["node_id"] = range(len(nodes_df))

    words = nodes_df["Token"].astype(str).tolist()

    print(f"Loaded {len(words)} words.")

    # --- Load model ---
    model = SentenceTransformer(MODEL_NAME)

    # --- Create embeddings ---
    embeddings = model.encode(
        words,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=True
    )

    # --- Compute similarity matrix ---
    similarity_matrix = util.cos_sim(embeddings, embeddings)
    similarity_full = similarity_matrix.cpu().numpy()

    # Remove self-connections
    np.fill_diagonal(similarity_full, 0)

    # --- Threshold edges only ---
    adjacency_matrix = similarity_full.copy()
    adjacency_matrix[adjacency_matrix < SIMILARITY_THRESHOLD] = 0

    # --- Build graph ---
    G = nx.from_numpy_array(adjacency_matrix)

    components = list(nx.connected_components(G))
    num_components = len(components)

    giant_component = max(components, key=len)
    giant_size = len(giant_component)
    frac_giant = giant_size / G.number_of_nodes()

    print("Number of nodes:", G.number_of_nodes())
    print("Number of edges:", G.number_of_edges())
    print("Number of components:", num_components)
    print("Giant component size:", giant_size)
    print("Fraction in giant component:", frac_giant)

    # --- Add component IDs to nodes ---
    component_id_lookup = {}

    for component_id, component in enumerate(components):
        for node_id in component:
            component_id_lookup[node_id] = component_id

    nodes_df["component_id"] = nodes_df["node_id"].map(component_id_lookup)
    nodes_df["in_giant_component"] = nodes_df["node_id"].apply(
        lambda node_id: node_id in giant_component
    )

    # --- Create edge list efficiently ---
    upper_i, upper_j = np.where(np.triu(adjacency_matrix, k=1) > 0)

    edges_df = pd.DataFrame({
        "source_id": upper_i,
        "target_id": upper_j,
        "source_word": [words[i] for i in upper_i],
        "target_word": [words[j] for j in upper_j],
        "similarity": adjacency_matrix[upper_i, upper_j],
        "edge_type": "threshold"
    })

    # --- Save cache files ---
    nodes_df.to_csv(NODES_PATH, index=False, encoding="utf-8-sig")
    edges_df.to_csv(EDGES_PATH, index=False, encoding="utf-8-sig")

    metadata = {
        "language": "spanish",
        "n_words": N_WORDS,
        "model": MODEL_NAME,
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "num_nodes": int(G.number_of_nodes()),
        "num_edges": int(G.number_of_edges()),
        "num_components": int(num_components),
        "giant_component_size": int(giant_size),
        "fraction_in_giant_component": float(frac_giant),
        "nodes_file": str(NODES_PATH),
        "edges_file": str(EDGES_PATH),
    }

    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=4)

    print("\nSaved:")
    print("Nodes:", NODES_PATH)
    print("Edges:", EDGES_PATH)
    print("Metadata:", METADATA_PATH)


if __name__ == "__main__":
    build_threshold_network_cache()