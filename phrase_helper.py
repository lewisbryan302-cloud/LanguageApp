import pandas as pd
import spacy
from collections import Counter, defaultdict
from functools import lru_cache

from phrase_config import LANGUAGE_CORPORA

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
        disable=["ner"]
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


def get_query_lemma(query_word: str, target_language: str) -> str:
    nlp = get_nlp(target_language)
    doc = nlp(query_word)
    return doc[0].lemma_.lower()


def is_clean_token(token) -> bool:
    return not token.is_space and not token.is_punct


def normalise_phrase(text: str) -> str:
    return " ".join(text.split()).strip()


def is_good_phrase(phrase: str) -> bool:
    words = phrase.split()

    if len(words) < 2:
        return False

    if len(words) > 7:
        return False

    return True


def extract_linguistic_phrases_from_doc(doc, query_lemma: str):
    phrases = set()

    # 1. Noun chunks containing the query word.
    # Example: "das alte Haus", "ein wildes Tier"
    for chunk in doc.noun_chunks:
        if any(token.lemma_.lower() == query_lemma for token in chunk):

            if not is_bare_det_noun_phrase(chunk):
                phrase = normalise_phrase(chunk.text)

                if is_good_phrase(phrase):
                    phrases.add(phrase)

            # Try to include a preceding preposition.
            # Example: "in dem Haus", "mit dem Tier", "zu Hause"
            start = chunk.start

            if start > 0:
                previous = doc[start - 1]

                if previous.pos_ == "ADP":
                    prep_phrase = normalise_phrase(
                        doc[previous.i : chunk.end].text
                    )

                    if is_good_phrase(prep_phrase):
                        phrases.add(prep_phrase)

    # 2. Prepositional phrases around the query token.
    # This catches phrases noun_chunks may miss.
    for token in doc:
        if token.lemma_.lower() != query_lemma:
            continue

        # If the token is attached to a preposition, collect prep + subtree.
        if token.head.pos_ == "ADP":
            subtree_tokens = sorted(
                list(token.head.subtree),
                key=lambda t: t.i
            )

            phrase = normalise_phrase(
                " ".join(t.text for t in subtree_tokens if is_clean_token(t))
            )

            if is_good_phrase(phrase):
                phrases.add(phrase)

        # If the token has a preposition child, collect that phrase.
        for child in token.children:
            if child.pos_ == "ADP":
                subtree_tokens = sorted(
                    list(child.subtree),
                    key=lambda t: t.i
                )

                phrase = normalise_phrase(
                    " ".join(t.text for t in subtree_tokens if is_clean_token(t))
                )

                if is_good_phrase(phrase):
                    phrases.add(phrase)

    return list(phrases)


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
        phrases = extract_linguistic_phrases_from_doc(
            doc=doc,
            query_lemma=query_lemma
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

def is_bare_det_noun_phrase(span) -> bool:
    clean_tokens = [
        token
        for token in span
        if is_clean_token(token)
    ]

    if len(clean_tokens) != 2:
        return False

    return (
        clean_tokens[0].pos_ == "DET"
        and clean_tokens[1].pos_ in {"NOUN", "PROPN"}
    )