import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer, util
import networkx as nx

# --- Load frequency table ---
freq_path = r"C:\Users\lewis\OneDrive\Documents\LanguageApp\Language_Phrases\spanish_frequency_table.csv"
freq_df = pd.read_csv(freq_path)

# --- Choose top words ---
N_WORDS = 500

nodes_df = freq_df.head(N_WORDS).copy()
nodes_df["node_id"] = range(len(nodes_df))

words = nodes_df["Token"].astype(str).tolist()

# --- Load multilingual embedding model ---
model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

# --- Create word embeddings ---
embeddings = model.encode(
    words,
    convert_to_tensor=True,
    normalize_embeddings=True
)

# --- Compute semantic similarity matrix ---
similarity_matrix = util.cos_sim(embeddings, embeddings)

# Convert to NumPy array
adjacency_matrix = similarity_matrix.cpu().numpy()

# Optional: remove self-connections
np.fill_diagonal(adjacency_matrix, 0)

# Optional: threshold weak edges
SIMILARITY_THRESHOLD = 0.85
print("Applying similarity threshold:", SIMILARITY_THRESHOLD)
adjacency_matrix[adjacency_matrix < SIMILARITY_THRESHOLD] = 0

# --- Save nodes and adjacency matrix ---
nodes_path = r"C:\Users\lewis\OneDrive\Documents\LanguageApp\Language_Phrases\spanish_nodes.csv"
adj_path = r"C:\Users\lewis\OneDrive\Documents\LanguageApp\Language_Phrases\spanish_adjacency_matrix.csv"

nodes_df.to_csv(nodes_path, index=False, encoding="utf-8-sig")

adjacency_df = pd.DataFrame(
    adjacency_matrix,
    index=words,
    columns=words
)

adjacency_df.to_csv(adj_path, encoding="utf-8-sig")

print("Nodes saved to:", nodes_path)
print("Adjacency matrix saved to:", adj_path)

print("Number of nodes:", len(words))
print("Adjacency matrix shape:", adjacency_matrix.shape)

# Build graph from adjacency matrix
G = nx.from_numpy_array(adjacency_matrix)

# Count connected components
num_components = nx.number_connected_components(G)

print("Number of components:", num_components)

# G is your graph built from the adjacency matrix
components = list(nx.connected_components(G))

# Find largest connected component
giant_component = max(components, key=len)

# Number of nodes in the giant component
giant_size = len(giant_component)

print("Giant component size:", giant_size)
print("Fraction of graph in giant component:", giant_size / G.number_of_nodes())

