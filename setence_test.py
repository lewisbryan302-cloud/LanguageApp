import pandas as pd
import spacy
import spacy

import sys
print("Running Python from:")
print(sys.executable)

df = pd.read_csv(
    r"C:\Users\lewis\Downloads\deu_sentences.tsv\deu_sentences.csv",
    sep="\t",
    header=None,
    names=["sentence_id", "language", "sentence"],
    encoding="utf-8"
)

german = df[df["language"] == "deu"].copy()

nlp = spacy.load("de_core_news_sm")

# --- Check lemmas ---
def sentence_contains_lemma(sentence: str, query_lemma: str) -> bool:
    doc = nlp(sentence)

    for token in doc:
        if token.lemma_.lower() == query_lemma.lower():
            return True

    return False

# --- Search by lemma word ---
def search_german_sentences_by_lemma(query_word, n=30):
    query_doc = nlp(query_word)
    query_lemma = query_doc[0].lemma_.lower()

    matches = []

    for _, row in german.iterrows():
        sentence = row["sentence"]

        if sentence_contains_lemma(sentence, query_lemma):
            matches.append({
                "sentence_id": row["sentence_id"],
                "sentence": sentence
            })

        if len(matches) >= n:
            break

    return pd.DataFrame(matches)

print(search_german_sentences_by_lemma("kalt", n=30))

def find_sentences_with_word(word, n=20):
    pattern = rf"\b{word}\b"
    matches = german[
        german["sentence"].str.contains(pattern, case=False, na=False)
    ]
    return matches.head(n)

#print(find_sentences_with_word("kalte"))