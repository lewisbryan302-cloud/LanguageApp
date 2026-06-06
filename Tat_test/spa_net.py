# --- Import Modules ---
import pandas as pd
import re
import nltk
import spacy
from nltk.tokenize import word_tokenize
from collections import Counter

nltk.download("punkt")
nltk.download("punkt_tab")

nlp = spacy.load("es_core_news_sm")

# --- Load Data ---
path = r"C:\Users\lewis\OneDrive\Documents\LanguageApp\Language_Phrases\spa_sentences.tsv\spa_sentences.tsv"

df = pd.read_csv(path, sep="\t")

# --- Helper Functions ---
def clean_text(text):
    """Lowercase and remove punctuation/digits."""
    text = str(text).lower()
    text = re.sub(r"[^a-záéíóúüñ\s]", "", text)  # keep Spanish letters and spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text

def frequency_table(tokens):
    """Return a Pandas DataFrame of token frequencies."""
    freq = Counter(tokens)
    df = pd.DataFrame(freq.items(), columns=["Token", "Frequency"])
    df = df.sort_values(by="Frequency", ascending=False).reset_index(drop=True)
    return df

# --- Extract sentences ---
sentences = df.iloc[:, 2].dropna().tolist()

# Clean each sentence first, then tokenize
words = [
    word_tokenize(clean_text(sentence), language="spanish")
    for sentence in sentences
]

# Flatten list of token lists
all_tokens = [token for sublist in words for token in sublist]

# --- Create Frequency Table ---
freq_df = frequency_table(all_tokens)

#print(freq_df.head(20))

output_path = r"C:\Users\lewis\OneDrive\Documents\LanguageApp\Language_Phrases\spanish_frequency_table.csv"

freq_df.to_csv(output_path, index=False, encoding="utf-8-sig")