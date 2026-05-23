import pandas as pd
import spacy
from collections import Counter, defaultdict
from functools import lru_cache

from phrase_config import LANGUAGE_CORPORA

TSV_PATH = r"C:\Users\lewis\Downloads\deu_sentences.tsv\deu_sentences.tsv"

nlp = spacy.load("de_core_news_sm", disable=["parser", "ner"])


@lru_cache(maxsize=None)
def get_language_config(target_language: str) -> dict:
    if target_language not in LANGUAGE_CORPORA:
        raise ValueError(f"No phrase corpus configured for language: {target_language}")

    return LANGUAGE_CORPORA[target_language]


@lru_cache(maxsize=None)
def get_nlp(target_language: str):
    config = get_language_config(target_language)

    return spacy.load(
        config["spacy_model"],
        disable=["parser", "ner"]
    )


@lru_cache(maxsize=None)
def load_sentences(target_language: str):
    config = get_language_config(target_language)

    df = pd.read_csv(
        config["tsv_path"],
        sep="\t",
        header=None,
        names=["sentence_id", "language", "sentence"],
        encoding="utf-8"
    )

    sentences = df[df["language"] == config["tatoeba_code"]].copy()

    return sentences


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
    target_language: str,
    max_candidates: int = 10000,
    max_matches: int = 1000,
    window: int = 2,
    top_n: int = 10,
    batch_size: int = 200
):
    query_word = query_word.strip()

    if not query_word:
        return []

    sentences_df = load_sentences(target_language)
    nlp = get_nlp(target_language)

    query_doc = nlp(query_word)
    query_lemma = query_doc[0].lemma_.lower()

    phrase_counter = Counter()
    example_sentences = defaultdict(list)

    rough_matches = sentences_df[
        sentences_df["sentence"].str.contains(
            query_word,
            case=False,
            na=False,
            regex=False
        )
    ].head(max_candidates)

    rough_sentences = rough_matches["sentence"].dropna().tolist()

    matched_sentences = 0

    for doc, sentence in zip(
        nlp.pipe(rough_sentences, batch_size=batch_size),
        rough_sentences
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