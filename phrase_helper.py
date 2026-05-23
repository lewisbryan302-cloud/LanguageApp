import pandas as pd
import spacy
from collections import Counter, defaultdict
from functools import lru_cache

TSV_PATH = r"C:\Users\lewis\Downloads\deu_sentences.tsv\deu_sentences.tsv"

nlp = spacy.load("de_core_news_sm", disable=["parser", "ner"])


@lru_cache(maxsize=1)
def load_german_sentences():
    df = pd.read_csv(
        TSV_PATH,
        sep="\t",
        header=None,
        names=["sentence_id", "language", "sentence"],
        encoding="utf-8"
    )

    german = df[df["language"] == "deu"].copy()
    return german


def get_query_lemma(query_word: str) -> str:
    doc = nlp(query_word)
    return doc[0].lemma_.lower()


def is_clean_token(token) -> bool:
    return not token.is_space and not token.is_punct


def extract_phrases_from_doc(doc, query_lemma: str, window: int = 2):
    phrases = []

    for i, token in enumerate(doc):
        if token.lemma_.lower() == query_lemma:
            start = max(0, i - window)
            end = min(len(doc), i + window + 1)

            words = [
                t.text
                for t in doc[start:end]
                if is_clean_token(t)
            ]

            phrase = " ".join(words)

            if phrase:
                phrases.append(phrase)

    return phrases


def get_phrase_suggestions(
    query_word: str,
    max_candidates: int = 10000,
    max_matches: int = 1000,
    window: int = 2,
    top_n: int = 10,
    batch_size: int = 200
):
    """
    Return phrase suggestions for Smart Add.

    Each result has:
    - phrase
    - count
    - examples
    """
    german = load_german_sentences()
    query_lemma = get_query_lemma(query_word)

    rough_matches = german[
        german["sentence"].str.contains(
            query_word,
            case=False,
            na=False,
            regex=False
        )
    ].head(max_candidates)

    sentences = rough_matches["sentence"].dropna().tolist()

    phrase_counter = Counter()
    example_sentences = defaultdict(list)

    matched_sentences = 0

    for doc, sentence in zip(
        nlp.pipe(sentences, batch_size=batch_size),
        sentences
    ):
        phrases = extract_phrases_from_doc(
            doc=doc,
            query_lemma=query_lemma,
            window=window
        )

        if not phrases:
            continue

        for phrase in phrases:
            phrase_counter[phrase] += 1

            if len(example_sentences[phrase]) < 2:
                example_sentences[phrase].append(sentence)

        matched_sentences += 1

        if matched_sentences >= max_matches:
            break

    results = []

    for phrase, count in phrase_counter.most_common(top_n):
        results.append({
            "phrase": phrase,
            "count": count,
            "examples": example_sentences[phrase]
        })

    return results