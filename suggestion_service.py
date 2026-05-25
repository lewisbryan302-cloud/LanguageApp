from database import get_connection
from embedding_helper import (
    embedding_similarity,
    get_similar_words_with_translations,
    translate_word,
)
import spacy
from functools import lru_cache

@lru_cache(maxsize=1)
def get_english_nlp():
    return spacy.load("en_core_web_sm")

def get_existing_cards(deck_id: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, front, back
        FROM flashcards
        WHERE deck_id = %s;
    """, (deck_id,))

    existing_cards = cursor.fetchall()

    cursor.close()
    conn.close()

    return existing_cards


def get_deck_target_language(deck_id: int) -> str:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT target_language
        FROM decks
        WHERE id = %s;
    """, (deck_id,))

    target_language_row = cursor.fetchone()

    cursor.close()
    conn.close()

    if target_language_row:
        return target_language_row[0]

    return "de"


def get_deck_options() -> list:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name
        FROM decks
        ORDER BY id;
    """)

    decks = cursor.fetchall()

    cursor.close()
    conn.close()

    return decks


def find_similar_existing_cards(
    front: str,
    back: str,
    existing_cards: list,
    threshold: float = 0.75
) -> list:
    suggestions = []

    for card in existing_cards:
        card_id, existing_front, existing_back = card

        score_front = embedding_similarity(front, existing_front)
        score_back = embedding_similarity(back, existing_back)
        score_cross_1 = embedding_similarity(front, existing_back)
        score_cross_2 = embedding_similarity(back, existing_front)

        score = max(
            score_front,
            score_back,
            score_cross_1,
            score_cross_2
        )

        if score > threshold:
            suggestions.append(
                (
                    card_id,
                    existing_front,
                    existing_back,
                    score
                )
            )

    suggestions.sort(key=lambda x: x[3], reverse=True)

    return suggestions


def filter_existing_word_suggestions(
    raw_word_suggestions: list,
    existing_cards: list
) -> list:
    existing_pairs = {
        (existing_front.strip().lower(), existing_back.strip().lower())
        for _, existing_front, existing_back in existing_cards
    }

    word_suggestions = []

    for item in raw_word_suggestions:
        suggested_pair = (
            item["word"].strip().lower(),
            item["translation"].strip().lower()
        )

        reverse_pair = (
            item["translation"].strip().lower(),
            item["word"].strip().lower()
        )

        if (
            suggested_pair not in existing_pairs
            and reverse_pair not in existing_pairs
        ):
            word_suggestions.append(item)

    return word_suggestions

def get_smart_add_preview_data_from_query(
    deck_id: int,
    query_word: str
) -> dict:
    query_word = query_word.strip()

    existing_cards = get_existing_cards(deck_id)
    decks = get_deck_options()
    target_language = get_deck_target_language(deck_id)

    query_info = parse_english_query(query_word)

    similar_existing_cards = find_similar_existing_cards(
        front=query_word,
        back=query_word,
        existing_cards=existing_cards,
    )

    if query_info["is_infinitive_query"]:
        word_suggestions = []
    else:
        embedding_query = query_info["base_word"]

        raw_word_suggestions = get_similar_words_with_translations(
            embedding_query,
            k=10,
            threshold=0.45,
            source="en",
            target=target_language
        )

        formatted_word_suggestions = []

        for item in raw_word_suggestions:
            formatted = format_english_suggestion_word(item["word"])

            if formatted["translation_word"] == item["word"]:
                translation = item["translation"]
            else:
                translation = translate_word(
                    formatted["translation_word"],
                    source="en",
                    target=target_language
                )

            formatted_word_suggestions.append({
                "word": formatted["display_word"],
                "translation": translation,
                "pos_tag": formatted["pos_tag"],
                "raw_word": item["word"],
                "score": item.get("score"),
            })

        word_suggestions = filter_existing_word_suggestions(
            raw_word_suggestions=formatted_word_suggestions,
            existing_cards=existing_cards,
        )

    target_query_word = get_target_phrase_query(
        query_word=query_word,
        target_language=target_language
    )

    return {
        "decks": decks,
        "suggestions": similar_existing_cards[:10],
        "word_suggestions": word_suggestions,
        "deck_id": deck_id,
        "query_word": query_word,
        "target_query_word": target_query_word,
        "target_language": target_language,
        "phrase_suggestions": None,
        "phrase_query": None,
    }

def get_smart_add_preview_data(
    deck_id: int,
    front: str,
    back: str,
    add_reverse: str | None = None
) -> dict:
    existing_cards = get_existing_cards(deck_id)
    decks = get_deck_options()
    target_language = get_deck_target_language(deck_id)

    similar_existing_cards = find_similar_existing_cards(
        front=front,
        back=back,
        existing_cards=existing_cards,
    )

    raw_word_suggestions = get_similar_words_with_translations(
        front,
        k=10,
        threshold=0.45,
        source="en",
        target=target_language
    )

    word_suggestions = filter_existing_word_suggestions(
        raw_word_suggestions=raw_word_suggestions,
        existing_cards=existing_cards,
    )

    return {
        "decks": decks,
        "suggestions": similar_existing_cards[:10],
        "word_suggestions": word_suggestions,
        "deck_id": deck_id,
        "front": front,
        "back": back,
        "add_reverse": add_reverse,
    }

def card_exists(cursor, deck_id: int, front: str, back: str) -> bool:
    cursor.execute("""
        SELECT id
        FROM flashcards
        WHERE deck_id = %s
        AND front = %s
        AND back = %s;
    """, (deck_id, front, back))

    return cursor.fetchone() is not None


def insert_card_if_missing(
    cursor,
    deck_id: int,
    front: str,
    back: str
) -> bool:
    if card_exists(cursor, deck_id, front, back):
        return False

    cursor.execute("""
        INSERT INTO flashcards (deck_id, front, back)
        VALUES (%s, %s, %s);
    """, (deck_id, front, back))

    return True


def add_reverse_of_existing_card(
    cursor,
    deck_id: int,
    card_id: int
) -> None:
    cursor.execute("""
        SELECT front, back
        FROM flashcards
        WHERE id = %s AND deck_id = %s;
    """, (card_id, deck_id))

    card = cursor.fetchone()

    if not card:
        return

    old_front, old_back = card

    insert_card_if_missing(
        cursor=cursor,
        deck_id=deck_id,
        front=old_back,
        back=old_front,
    )


def create_selected_word_suggestions(
    cursor,
    deck_id: int,
    add_reverse: str | None,
    selected_suggestion_indices: list[int] | None,
    suggested_words: list[str] | None,
    suggested_translations: list[str] | None
) -> None:
    if not (
        selected_suggestion_indices
        and suggested_words
        and suggested_translations
    ):
        return

    for index in selected_suggestion_indices:
        word = suggested_words[index]
        translation = suggested_translations[index]

        insert_card_if_missing(
            cursor=cursor,
            deck_id=deck_id,
            front=word,
            back=translation,
        )

        if add_reverse == "yes":
            insert_card_if_missing(
                cursor=cursor,
                deck_id=deck_id,
                front=translation,
                back=word,
            )

def create_smart_add_cards_from_query(
    deck_id: int,
    query_word: str,
    selected_card_ids: list[int] | None = None,
    selected_suggestion_indices: list[int] | None = None,
    suggested_words: list[str] | None = None,
    suggested_translations: list[str] | None = None,
    selected_phrase_indices: list[int] | None = None,
    suggested_phrases: list[str] | None = None,
    suggested_phrase_translations: list[str] | None = None
) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    inserted_count = 0
    target_language = get_deck_target_language(deck_id)

    if selected_card_ids:
        for card_id in selected_card_ids:
            cursor.execute("""
                SELECT front, back
                FROM flashcards
                WHERE id = %s AND deck_id = %s;
            """, (card_id, deck_id))

            card = cursor.fetchone()

            if not card:
                continue

            old_front, old_back = card

            inserted = insert_card_if_missing(
                cursor=cursor,
                deck_id=deck_id,
                front=old_back,
                back=old_front,
            )

            if inserted:
                inserted_count += 1

    if selected_suggestion_indices and suggested_words and suggested_translations:
        for index in selected_suggestion_indices:
            word_front = suggested_words[index].strip()
            word_back = suggested_translations[index].strip()

            if not word_front or not word_back:
                continue

            inserted = insert_card_if_missing(
                cursor=cursor,
                deck_id=deck_id,
                front=word_front,
                back=word_back,
            )

            if inserted:
                inserted_count += 1

    # Important: this is NOT inside the word-suggestion block.
    if selected_phrase_indices and suggested_phrases:
        for index in selected_phrase_indices:
            target_phrase = suggested_phrases[index].strip()

            if not target_phrase:
                continue

            if suggested_phrase_translations:
                english_phrase = suggested_phrase_translations[index].strip()
            else:
                english_phrase = translate_word(
                    target_phrase,
                    source=target_language,
                    target="en"
                )

            inserted = insert_card_if_missing(
                cursor=cursor,
                deck_id=deck_id,
                front=english_phrase,
                back=target_phrase,
            )

            if inserted:
                inserted_count += 1

    conn.commit()
    cursor.close()
    conn.close()

    return inserted_count

def create_smart_add_cards(
    deck_id: int,
    front: str,
    back: str,
    add_reverse: str | None = None,
    selected_card_ids: list[int] | None = None,
    selected_suggestion_indices: list[int] | None = None,
    suggested_words: list[str] | None = None,
    suggested_translations: list[str] | None = None,
    selected_phrase_indices: list[int] | None = None,
    suggested_phrases: list[str] | None = None
) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    insert_card_if_missing(
        cursor=cursor,
        deck_id=deck_id,
        front=front,
        back=back,
    )

    if add_reverse == "yes":
        insert_card_if_missing(
            cursor=cursor,
            deck_id=deck_id,
            front=back,
            back=front,
        )

    if selected_card_ids:
        for card_id in selected_card_ids:
            add_reverse_of_existing_card(
                cursor=cursor,
                deck_id=deck_id,
                card_id=card_id,
            )

    create_selected_word_suggestions(
        cursor=cursor,
        deck_id=deck_id,
        add_reverse=add_reverse,
        selected_suggestion_indices=selected_suggestion_indices,
        suggested_words=suggested_words,
        suggested_translations=suggested_translations,
    )

    # Add selected phrase suggestions
    if selected_phrase_indices and suggested_phrases:
        for index in selected_phrase_indices:
            phrase_front = suggested_phrases[index].strip()

            if not phrase_front:
                continue

            phrase_back = translate_word(
                phrase_front,
                source="en",
                target="de"
            )

            insert_card_if_missing(
                cursor=cursor,
                deck_id=deck_id,
                front=phrase_front,
                back=phrase_back,
            )

            if add_reverse == "yes":
                insert_card_if_missing(
                    cursor=cursor,
                    deck_id=deck_id,
                    front=phrase_back,
                    back=phrase_front,
                )

    conn.commit()
    cursor.close()
    conn.close()

def is_likely_english_infinitive(word: str) -> bool:
    word = word.strip().lower()

    if not word:
        return False

    # Do not handle multi-word suggestions here.
    if " " in word:
        return False

    # Reject obvious non-infinitive forms.
    if word.endswith("ing"):
        return False

    if word.endswith("ed"):
        return False

    # Avoid simple third-person forms like "favours", "runs", "eats".
    # This is imperfect, but useful.
    if word.endswith("s") and len(word) > 3:
        return False

    nlp = get_english_nlp()

    # Test whether it behaves as a bare infinitive after "will".
    # Example: "I will go", "I will eat", "I will favour".
    doc = nlp(f"I will {word}")

    target_token = None

    for token in doc:
        if token.text.lower() == word:
            target_token = token
            break

    if target_token is None:
        return False

    # In Penn tags, VB means base-form verb.
    # This rejects VBD, VBN, VBG, VBZ, Noun, etc.
    if target_token.tag_ != "VB":
        return False

    # Extra safety check:
    # If spaCy strongly reads the word by itself as a noun/proper noun,
    # do not automatically add "to".
    standalone_doc = nlp(word)

    if len(standalone_doc) != 1:
        return False

    standalone_token = standalone_doc[0]

    if standalone_token.pos_ in {"NOUN", "PROPN"}:
        return False

    return True


def format_english_suggestion_word(word: str) -> dict:
    word = word.strip()

    if is_likely_english_infinitive(word):
        return {
            "display_word": f"to {word}",
            "translation_word": word,
            "pos_tag": "verb",
        }

    return {
        "display_word": word,
        "translation_word": word,
        "pos_tag": None,
    }

def parse_english_query(query_word: str) -> dict:
    query_word = query_word.strip()
    lower_query = query_word.lower()

    if lower_query.startswith("to "):
        base_word = query_word[3:].strip()

        # Only treat simple "to X" as an infinitive query.
        if base_word and " " not in base_word:
            return {
                "original_query": query_word,
                "base_word": base_word,
                "is_infinitive_query": True,
            }

    return {
        "original_query": query_word,
        "base_word": query_word,
        "is_infinitive_query": False,
    }

def get_target_phrase_query(
    query_word: str,
    target_language: str
) -> str:
    query_info = parse_english_query(query_word)

    if query_info["is_infinitive_query"]:
        base_verb = query_info["base_word"]

        # Translate in a sentence context to force verb meaning.
        translated_sentence = translate_word(
            f"I want to {base_verb}",
            source="en",
            target=target_language
        )

        try:
            from phrase_helper import get_nlp

            nlp = get_nlp(target_language)
            doc = nlp(translated_sentence)

            verb_lemmas = [
                token.lemma_.lower()
                for token in doc
                if token.pos_ in {"VERB", "AUX"}
            ]

            if verb_lemmas:
                # Usually the final verb is the actual infinitive/main verb.
                return verb_lemmas[-1]

        except Exception:
            pass

        # Fallback if spaCy extraction fails.
        return translate_word(
            base_verb,
            source="en",
            target=target_language
        )

    return translate_word(
        query_word,
        source="en",
        target=target_language
    )