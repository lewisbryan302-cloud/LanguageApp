import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer, util
import networkx as nx
import matplotlib.pyplot as plt


def connect_components_to_giant(adjacency_matrix, similarity_full):
    """
    Connect every disconnected component to the giant component using
    the strongest semantic-similarity edge available.

    Returns:
        connected_adjacency_matrix
        added_edges: list of (node_i, node_j, similarity)
    """
    new_adj = adjacency_matrix.copy()
    G = nx.from_numpy_array(new_adj)

    added_edges = []

    while nx.number_connected_components(G) > 1:
        components = list(nx.connected_components(G))

        # Current giant component
        giant = max(components, key=len)

        # All other components
        other_components = [component for component in components if component != giant]

        best_i = None
        best_j = None
        best_similarity = -1

        # Find strongest edge from the giant component to any other component
        for component in other_components:
            for i in giant:
                for j in component:
                    similarity = similarity_full[i, j]

                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_i = i
                        best_j = j

        # Add the best bridge edge
        new_adj[best_i, best_j] = best_similarity
        new_adj[best_j, best_i] = best_similarity

        G.add_edge(best_i, best_j, weight=best_similarity)

        added_edges.append((best_i, best_j, best_similarity))

    return new_adj, added_edges

def connect_highest_edges():
    # --- Load frequency table ---
    freq_path = r"C:\Users\lewis\OneDrive\Documents\LanguageApp\Language_Phrases\spanish_frequency_table.csv"
    freq_df = pd.read_csv(freq_path)

    # --- Settings ---
    N_WORDS = [100, 200, 300, 500, 1000, 2000, 3000, 5000, 10000]
    SIMILARITY_THRESHOLD = 0.85

    fracs_before = []
    fracs_after = []
    giant_sizes_before = []
    giant_sizes_after = []
    num_components_before_list = []
    num_components_after_list = []
    num_edges_before_list = []
    num_edges_after_list = []
    added_edge_counts = []

    # --- Load model ONCE ---
    model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

    for n in N_WORDS:
        print("\n==============================")
        print(f"Processing top {n} words")
        print("==============================")

        nodes_df = freq_df.head(n).copy()
        nodes_df["node_id"] = range(len(nodes_df))

        words = nodes_df["Token"].astype(str).tolist()

        # --- Create word embeddings ---
        embeddings = model.encode(
            words,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=True
        )

        # --- Compute semantic similarity matrix ---
        similarity_matrix = util.cos_sim(embeddings, embeddings)

        # Full similarity matrix BEFORE thresholding
        similarity_full = similarity_matrix.cpu().numpy()
        np.fill_diagonal(similarity_full, 0)

        # Thresholded adjacency matrix
        adjacency_matrix = similarity_full.copy()
        adjacency_matrix[adjacency_matrix < SIMILARITY_THRESHOLD] = 0

        # -----------------------------
        # BEFORE connecting components
        # -----------------------------
        G_before = nx.from_numpy_array(adjacency_matrix)

        components_before = list(nx.connected_components(G_before))
        num_components_before = len(components_before)

        giant_before = max(components_before, key=len)
        giant_size_before = len(giant_before)
        frac_before = giant_size_before / G_before.number_of_nodes()

        print("Before connecting:")
        print("Number of nodes:", G_before.number_of_nodes())
        print("Number of edges:", G_before.number_of_edges())
        print("Number of components:", num_components_before)
        print("Giant component size:", giant_size_before)
        print("Fraction in giant component:", frac_before)

        # -----------------------------
        # Connect components to giant
        # -----------------------------
        connected_adjacency_matrix, added_edges = connect_components_to_giant(
            adjacency_matrix,
            similarity_full
        )

        # -----------------------------
        # AFTER connecting components
        # -----------------------------
        G_after = nx.from_numpy_array(connected_adjacency_matrix)

        components_after = list(nx.connected_components(G_after))
        num_components_after = len(components_after)

        giant_after = max(components_after, key=len)
        giant_size_after = len(giant_after)
        frac_after = giant_size_after / G_after.number_of_nodes()

        print("\nAfter connecting:")
        print("Number of nodes:", G_after.number_of_nodes())
        print("Number of edges:", G_after.number_of_edges())
        print("Number of components:", num_components_after)
        print("Giant component size:", giant_size_after)
        print("Fraction in giant component:", frac_after)
        print("Added bridge edges:", len(added_edges))

        print("\nSample bridge edges:")
        for i, j, similarity in added_edges[:10]:
            print(f"{words[i]} <-> {words[j]} | similarity = {similarity:.3f}")

        # Store results
        fracs_before.append(frac_before)
        fracs_after.append(frac_after)

        giant_sizes_before.append(giant_size_before)
        giant_sizes_after.append(giant_size_after)

        num_components_before_list.append(num_components_before)
        num_components_after_list.append(num_components_after)

        num_edges_before_list.append(G_before.number_of_edges())
        num_edges_after_list.append(G_after.number_of_edges())

        added_edge_counts.append(len(added_edges))


    # --- Save summary results ---
    summary_df = pd.DataFrame({
        "N_WORDS": N_WORDS,
        "giant_size_before": giant_sizes_before,
        "giant_size_after": giant_sizes_after,
        "fraction_in_giant_before": fracs_before,
        "fraction_in_giant_after": fracs_after,
        "num_components_before": num_components_before_list,
        "num_components_after": num_components_after_list,
        "num_edges_before": num_edges_before_list,
        "num_edges_after": num_edges_after_list,
        "added_bridge_edges": added_edge_counts
    })

    summary_path = r"C:\Users\lewis\OneDrive\Documents\LanguageApp\Language_Phrases\giant_component_summary.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    print("\nSaved summary to:", summary_path)

    # --- Plot fraction in giant component ---
    plt.plot(N_WORDS, fracs_before, marker="o", label="Before connecting")
    plt.plot(N_WORDS, fracs_after, marker="o", label="After connecting")
    plt.xscale("log")
    plt.xlabel("Number of Words")
    plt.ylabel("Fraction in Giant Component")
    plt.title(f"Giant Component Before and After Semantic Bridging, threshold={SIMILARITY_THRESHOLD}")
    plt.grid(True)
    plt.legend()
    plt.show()

    # --- Plot number of added edges ---
    plt.plot(N_WORDS, added_edge_counts, marker="o")
    plt.xscale("log")
    plt.xlabel("Number of Words")
    plt.ylabel("Number of Added Bridge Edges")
    plt.title("Number of Bridge Edges Needed to Connect the Graph")
    plt.grid(True)
    plt.show()

def connect_components_randomly(adjacency_matrix, similarity_full, min_similarity=0.0, random_seed=42):
    """
    Randomly connect disconnected components until the graph is connected.

    Edge weights are still the real semantic similarities from similarity_full.
    """
    rng = np.random.default_rng(random_seed)

    new_adj = adjacency_matrix.copy()
    G = nx.from_numpy_array(new_adj)

    added_edges = []

    while nx.number_connected_components(G) > 1:
        components = list(nx.connected_components(G))

        # Pick two different components randomly
        comp_a_idx, comp_b_idx = rng.choice(len(components), size=2, replace=False)

        comp_a = list(components[comp_a_idx])
        comp_b = list(components[comp_b_idx])

        found_edge = False

        # Try random word pairs between these two components
        for _ in range(1000):
            i = rng.choice(comp_a)
            j = rng.choice(comp_b)

            similarity = similarity_full[i, j]

            if similarity >= min_similarity:
                new_adj[i, j] = similarity
                new_adj[j, i] = similarity

                G.add_edge(i, j, weight=similarity)

                added_edges.append((i, j, similarity))
                found_edge = True
                break

        # Fallback: if no random pair met min_similarity,
        # use the strongest edge between those two chosen components
        if not found_edge:
            best_i = None
            best_j = None
            best_similarity = -1

            for i in comp_a:
                for j in comp_b:
                    similarity = similarity_full[i, j]

                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_i = i
                        best_j = j

            new_adj[best_i, best_j] = best_similarity
            new_adj[best_j, best_i] = best_similarity

            G.add_edge(best_i, best_j, weight=best_similarity)

            added_edges.append((best_i, best_j, best_similarity))

    return new_adj, added_edges

def connect_randomly():
    # --- Load frequency table ---
    freq_path = r"C:\Users\lewis\OneDrive\Documents\LanguageApp\Language_Phrases\spanish_frequency_table.csv"
    freq_df = pd.read_csv(freq_path)

    # --- Settings ---
    N_WORDS = 10000
    SIMILARITY_THRESHOLD = 0.85
    MIN_RANDOM_BRIDGE_SIMILARITY = 0.2
    RANDOM_SEED = 42

    # --- Output paths for website cache ---
    output_dir = r"C:\Users\lewis\OneDrive\Documents\LanguageApp\Language_Phrases"

    nodes_path = output_dir + r"\spanish_nodes_10000.csv"
    edges_path = output_dir + r"\spanish_edges_10000_random.csv"
    bridge_edges_path = output_dir + r"\spanish_bridge_edges_10000_random.csv"
    metadata_path = output_dir + r"\spanish_network_metadata_10000_random.json"

    # --- Load model ONCE ---
    model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

    print("\n==============================")
    print(f"Processing top {N_WORDS} words")
    print("==============================")

    nodes_df = freq_df.head(N_WORDS).copy()
    nodes_df["node_id"] = range(len(nodes_df))

    words = nodes_df["Token"].astype(str).tolist()

    # --- Create word embeddings ---
    embeddings = model.encode(
        words,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=True
    )

    # --- Compute semantic similarity matrix ---
    similarity_matrix = util.cos_sim(embeddings, embeddings)

    # Full similarity matrix BEFORE thresholding
    similarity_full = similarity_matrix.cpu().numpy()
    np.fill_diagonal(similarity_full, 0)

    # Thresholded adjacency matrix
    adjacency_matrix = similarity_full.copy()
    adjacency_matrix[adjacency_matrix < SIMILARITY_THRESHOLD] = 0

    # -----------------------------
    # BEFORE random connection
    # -----------------------------
    G_before = nx.from_numpy_array(adjacency_matrix)

    components_before = list(nx.connected_components(G_before))
    num_components_before = len(components_before)

    giant_before = max(components_before, key=len)
    giant_size_before = len(giant_before)
    frac_before = giant_size_before / G_before.number_of_nodes()

    print("Before random connection:")
    print("Number of nodes:", G_before.number_of_nodes())
    print("Number of edges:", G_before.number_of_edges())
    print("Number of components:", num_components_before)
    print("Giant component size:", giant_size_before)
    print("Fraction in giant component:", frac_before)

    # -----------------------------
    # Randomly connect components
    # -----------------------------
    connected_adjacency_matrix, added_edges = connect_components_randomly(
        adjacency_matrix=adjacency_matrix,
        similarity_full=similarity_full,
        min_similarity=MIN_RANDOM_BRIDGE_SIMILARITY,
        random_seed=RANDOM_SEED
    )

    # -----------------------------
    # AFTER random connection
    # -----------------------------
    G_after = nx.from_numpy_array(connected_adjacency_matrix)

    components_after = list(nx.connected_components(G_after))
    num_components_after = len(components_after)

    giant_after = max(components_after, key=len)
    giant_size_after = len(giant_after)
    frac_after = giant_size_after / G_after.number_of_nodes()

    if len(added_edges) > 0:
        avg_added_similarity = float(np.mean([edge[2] for edge in added_edges]))
    else:
        avg_added_similarity = 0.0

    print("\nAfter random connection:")
    print("Number of nodes:", G_after.number_of_nodes())
    print("Number of edges:", G_after.number_of_edges())
    print("Number of components:", num_components_after)
    print("Giant component size:", giant_size_after)
    print("Fraction in giant component:", frac_after)
    print("Added random bridge edges:", len(added_edges))
    print("Average added edge similarity:", avg_added_similarity)

    print("\nSample random bridge edges:")
    for i, j, similarity in added_edges[:10]:
        print(f"{words[i]} <-> {words[j]} | similarity = {similarity:.3f}")

    # -----------------------------
    # Cache nodes
    # -----------------------------
    nodes_df.to_csv(nodes_path, index=False, encoding="utf-8-sig")

    # -----------------------------
    # Cache all edges as edge list
    # -----------------------------
    edges = []

    bridge_edge_set = {
        tuple(sorted((int(i), int(j))))
        for i, j, _ in added_edges
    }

    for i, j, data in G_after.edges(data=True):
        similarity = float(data.get("weight", connected_adjacency_matrix[i, j]))

        edge_type = "random_bridge" if tuple(sorted((i, j))) in bridge_edge_set else "threshold"

        edges.append({
            "source_id": int(i),
            "target_id": int(j),
            "source_word": words[i],
            "target_word": words[j],
            "similarity": similarity,
            "edge_type": edge_type
        })

    edges_df = pd.DataFrame(edges)
    edges_df.to_csv(edges_path, index=False, encoding="utf-8-sig")

    # -----------------------------
    # Cache bridge edges separately
    # -----------------------------
    bridge_edges_df = pd.DataFrame([
        {
            "source_id": int(i),
            "target_id": int(j),
            "source_word": words[i],
            "target_word": words[j],
            "similarity": float(similarity),
            "edge_type": "random_bridge"
        }
        for i, j, similarity in added_edges
    ])

    bridge_edges_df.to_csv(bridge_edges_path, index=False, encoding="utf-8-sig")

    # -----------------------------
    # Cache metadata
    # -----------------------------
    metadata = {
        "language": "spanish",
        "n_words": N_WORDS,
        "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "min_random_bridge_similarity": MIN_RANDOM_BRIDGE_SIMILARITY,
        "random_seed": RANDOM_SEED,
        "num_nodes": int(G_after.number_of_nodes()),
        "num_edges_before": int(G_before.number_of_edges()),
        "num_edges_after": int(G_after.number_of_edges()),
        "num_components_before": int(num_components_before),
        "num_components_after": int(num_components_after),
        "giant_size_before": int(giant_size_before),
        "giant_size_after": int(giant_size_after),
        "fraction_in_giant_before": float(frac_before),
        "fraction_in_giant_after": float(frac_after),
        "added_random_bridge_edges": int(len(added_edges)),
        "average_added_edge_similarity": avg_added_similarity,
    }

    import json

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=4)

    print("\nCached network files:")
    print("Nodes:", nodes_path)
    print("Edges:", edges_path)
    print("Bridge edges:", bridge_edges_path)
    print("Metadata:", metadata_path)

    return nodes_df, edges_df, bridge_edges_df, metadata

connect_randomly()