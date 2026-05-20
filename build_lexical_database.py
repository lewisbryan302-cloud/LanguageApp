from wordfreq import top_n_list, zipf_frequency
import spacy
import pandas as pd
from collections import defaultdict
from names_dataset import NameDataset


# --- CONFIGURATION ---
LANGUAGE = "en"
N_WORDS = 20000
MIN_WORD_LENGTH = 3
MIN_ZIPF_FREQUENCY = 2.5

ALLOWED_POS = {
    "NOUN",
    "VERB",
    "ADJ",
    "ADV",
    "AUX",
    "ADP",
    "DET",
    "PRON",
    "NUM"
}

BAD_WORDS = {
    "gen",
    "di",
    "ii",
    "iii",
    "iv",
    "etc"
}

COMMON_WORD_WHITELIST = {
    "may",
    "march",
    "orange",
    "english",
    "china",
    "turkey"
}


# --- LOAD TOOLS ---
nlp = spacy.load("en_core_web_sm")
name_data = NameDataset()


# --- HELPER FUNCTIONS ---
def is_likely_name(word: str) -> bool:
    word = word.lower().strip()

    if word in COMMON_WORD_WHITELIST:
        return False

    result = name_data.search(word)

    if not result:
        return False

    first_name = result.get("first_name")
    last_name = result.get("last_name")

    return bool(first_name or last_name)


def is_good_surface_word(word: str) -> bool:
    word = word.lower().strip()

    if len(word) < MIN_WORD_LENGTH:
        return False

    if not word.isalpha():
        return False

    if word in BAD_WORDS:
        return False

    frequency = zipf_frequency(word, LANGUAGE)

    if frequency < MIN_ZIPF_FREQUENCY:
        return False

    if is_likely_name(word):
        return False

    return True


# --- BUILD WORD LIST ---
words = top_n_list(LANGUAGE, N_WORDS)

lemma_groups = defaultdict(list)

for word in words:

    if not is_good_surface_word(word):
        continue

    doc = nlp(word)

    if len(doc) != 1:
        continue

    token = doc[0]

    lemma = token.lemma_.lower().strip()
    pos = token.pos_

    if not lemma:
        continue

    if pos not in ALLOWED_POS:
        continue

    if lemma in BAD_WORDS:
        continue

    if is_likely_name(lemma):
        continue

    frequency = zipf_frequency(word, LANGUAGE)

    key = (lemma, pos)

    lemma_groups[key].append({
        "form": word,
        "frequency": frequency,
        "morphology": str(token.morph)
    })


# --- CONVERT TO TABLES ---
lemma_rows = []
form_rows = []

lemma_id = 1

for (lemma, pos), forms in lemma_groups.items():

    combined_frequency = sum(
        form["frequency"]
        for form in forms
    )

    most_common_form = max(
        forms,
        key=lambda item: item["frequency"]
    )["form"]

    lemma_rows.append({
        "lemma_id": lemma_id,
        "lemma": lemma,
        "pos": pos,
        "most_common_form": most_common_form,
        "combined_frequency": combined_frequency,
        "number_of_forms": len(forms)
    })

    for form in forms:
        form_rows.append({
            "lemma_id": lemma_id,
            "lemma": lemma,
            "pos": pos,
            "form": form["form"],
            "form_frequency": form["frequency"],
            "morphology": form["morphology"]
        })

    lemma_id += 1


lemmas_df = pd.DataFrame(lemma_rows)
forms_df = pd.DataFrame(form_rows)

lemmas_df = lemmas_df.sort_values(
    "combined_frequency",
    ascending=False
)

forms_df = forms_df.sort_values(
    ["lemma_id", "form_frequency"],
    ascending=[True, False]
)


# --- SAVE ---
lemmas_df.to_csv("lemmas.csv", index=False)
forms_df.to_csv("word_forms.csv", index=False)

print("Done.")
print(f"Input words: {len(words)}")
print(f"Lemmas: {len(lemmas_df)}")
print(f"Forms: {len(forms_df)}")
print("Saved:")
print("- lemmas.csv")
print("- word_forms.csv")