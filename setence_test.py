import pandas as pd

df = pd.read_csv(
    r"C:\Users\lewis\Downloads\deu_sentences.tsv\deu_sentences.csv",
    sep="\t",
    header=None,
    names=["sentence_id", "language", "sentence"],
    encoding="utf-8"
)

english = df[df["language"] == "eng"]

def find_sentences_with_word(word, n=20):
    pattern = rf"\b{word}\b"
    matches = english[
        english["sentence"].str.contains(pattern, case=False, na=False)
    ]
    return matches.head(n)

print(find_sentences_with_word("cold"))