from deep_translator import GoogleTranslator
from wordfreq import top_n_list
from sentence_transformers import SentenceTransformer, util


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_model = None


def get_model():
    global _model

    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)

    return _model

words = top_n_list("en", 5000)
embeddings = get_model().encode(words, convert_to_tensor=True)


def get_similar_words(query: str, k: int = 20, threshold: float = 0.55):
    query_embedding = get_model().encode(query, convert_to_tensor=True)

    scores = util.cos_sim(query_embedding, embeddings)[0]
    top_results = scores.topk(k=k)

    results = []

    for score, idx in zip(top_results.values, top_results.indices):
        score = float(score)

        if score >= threshold:
            results.append({
                "word": words[int(idx)],
                "score": score
            })

    return results

def translate_word(word: str, source: str = "en", target: str = "de") -> str:
    return GoogleTranslator(source=source, target=target).translate(word)

def get_similar_words_with_translations(
    query: str,
    k: int = 20,
    threshold: float = 0.75,
    source: str = "en",
    target: str = "de"
):
    similar_words = get_similar_words(query, k=k, threshold=threshold)

    results = []

    for item in similar_words:
        word = item["word"]

        try:
            translation = translate_word(word, source=source, target=target)
        except Exception:
            translation = ""

        results.append({
            "word": word,
            "translation": translation,
            "score": item["score"]
        })

    return results

#print(get_similar_words("happy"))

embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")


def embedding_similarity(a: str, b: str) -> float:
    embedding_a = embedding_model.encode(a, convert_to_tensor=True)
    embedding_b = embedding_model.encode(b, convert_to_tensor=True)

    similarity = util.cos_sim(embedding_a, embedding_b)

    return float(similarity[0][0])