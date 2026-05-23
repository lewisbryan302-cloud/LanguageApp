import pandas as pd
import spacy
from collections import Counter, defaultdict

TSV_PATH = r"C:\Users\lewis\Downloads\deu_sentences.tsv\deu_sentences.tsv"

# Disable pipeline parts we do not need.
# For lemmatisation, German spaCy normally needs tagger/morphologizer + lemmatizer,
# but we do not need parser or NER here.
nlp = spacy.load("de_core_news_sm", disable=["parser", "ner"])

df = pd.read_csv(
    TSV_PATH,
    sep="\t",
    header=None,
    names=["sentence_id", "language", "sentence"],
    encoding="utf-8"
)

german = df[df["language"] == "deu"].copy()


def get_query_lemma(query_word: str) -> str:
    """
    Convert the query word to its lemma.
    Example: 'kalte' -> 'kalt'
    """
    doc = nlp(query_word)
    return doc[0].lemma_.lower()


def is_clean_token(token) -> bool:
    """
    Decide whether a token should be included in phrase extraction.
    """
    return not token.is_space and not token.is_punct


def extract_phrases_from_doc(doc, query_lemma: str, window: int = 2):
    """
    Extract phrase windows from an already-parsed spaCy doc.

    This avoids parsing the same sentence twice.
    """
    phrases = []

    for i, token in enumerate(doc):
        if token.lemma_.lower() == query_lemma:
            start = max(0, i - window)
            end = min(len(doc), i + window + 1)

            span_tokens = [
                t.text
                for t in doc[start:end]
                if is_clean_token(t)
            ]

            phrase = " ".join(span_tokens)

            if phrase:
                phrases.append(phrase)

    return phrases


def find_common_phrases(
    query_word: str,
    max_matches: int = 1000,
    window: int = 2,
    top_n: int = 30,
    batch_size: int = 200
):
    """
    Find common short phrases containing the query word or one of its inflected forms.

    This version is faster because:
    1. Each sentence is parsed only once.
    2. nlp.pipe processes sentences in batches.
    3. parser and NER are disabled.
    """
    query_lemma = get_query_lemma(query_word)

    phrase_counter = Counter()
    example_sentences = defaultdict(list)

    sentences = german["sentence"].dropna().tolist()

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

            if len(example_sentences[phrase]) < 3:
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


if __name__ == "__main__":
    query = "kalt"

    results = find_common_phrases(
        query_word=query,
        max_matches=1000,
        window=2,
        top_n=30
    )

    for item in results:
        print(f"\nPhrase: {item['phrase']}")
        print(f"Count: {item['count']}")
        print("Examples:")
        for example in item["examples"]:
            print(f"  - {example}")