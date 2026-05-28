import csv
import io
from fastapi import UploadFile

from database import get_connection
from card_service import insert_card, set_card_tags_with_cursor


COLUMN_ALIASES = {
    "front": ["front", "question", "term", "word", "source", "q"],
    "back": ["back", "answer", "definition", "translation", "meaning", "target", "a"],
    "card_type": ["card_type", "card type", "type"],
    "tags": ["tags", "tag", "labels", "label"],
    "times_seen": ["times_seen", "times seen", "seen", "reviews", "reps"],
    "times_correct": ["times_correct", "times correct", "correct", "right"],
    "times_wrong": ["times_wrong", "times wrong", "wrong", "incorrect", "lapses"],
    "last_reviewed": ["last_reviewed", "last reviewed", "last_review"],
    "next_review": ["next_review", "next reviewed", "next review", "due", "due_date"],
}


STANDARD_COLUMNS = [
    "front",
    "back",
    "card_type",
    "tags",
    "times_seen",
    "times_correct",
    "times_wrong",
    "last_reviewed",
    "next_review",
]


def normalise_header(header: str) -> str:
    return (
        str(header)
        .strip()
        .lower()
        .replace("\ufeff", "")
        .replace("-", " ")
        .replace("_", " ")
    )


def build_alias_lookup() -> dict[str, str]:
    lookup = {}

    for standard_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            lookup[normalise_header(alias)] = standard_name

    return lookup


def decode_uploaded_file(file: UploadFile) -> str:
    raw_bytes = file.file.read()

    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252")

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Excel sometimes adds a first line like: sep=,
    lines = text.split("\n")

    if lines and lines[0].lower().startswith("sep="):
        text = "\n".join(lines[1:])

    return text


def delimiter_options(import_format: str) -> list[str]:
    if import_format == "tsv":
        return ["\t", ",", ";"]

    return [",", "\t", ";"]


def parse_rows(text: str, delimiter: str) -> list[list[str]]:
    reader = csv.reader(
        io.StringIO(text),
        delimiter=delimiter
    )

    rows = []

    for row in reader:
        cleaned_row = [
            cell.strip()
            for cell in row
        ]

        if any(cell != "" for cell in cleaned_row):
            rows.append(cleaned_row)

    return rows


def choose_rows_and_columns(text: str, import_format: str):
    alias_lookup = build_alias_lookup()

    best_rows = None
    best_delimiter = None
    best_score = -1
    best_column_map = None

    for delimiter in delimiter_options(import_format):
        rows = parse_rows(text, delimiter)

        if not rows:
            continue

        header_row = rows[0]

        column_map = {}
        score = 0

        for index, header in enumerate(header_row):
            normalised = normalise_header(header)

            if normalised in alias_lookup:
                standard_name = alias_lookup[normalised]
                column_map[standard_name] = index
                score += 1

        print("TRY DELIMITER:", repr(delimiter))
        print("FIRST ROW:", header_row)
        print("SCORE:", score)

        if score > best_score:
            best_rows = rows
            best_delimiter = delimiter
            best_score = score
            best_column_map = column_map

    if best_rows is None:
        raise ValueError("Could not read the import file.")

    print("CHOSEN DELIMITER:", repr(best_delimiter))
    print("CHOSEN SCORE:", best_score)
    print("CHOSEN COLUMN MAP:", best_column_map)

    # Header-based CSV/TSV
    if best_score > 0:
        data_rows = best_rows[1:]
        return data_rows, best_column_map

    # Headerless fallback:
    # column 1 = front, column 2 = back, column 3 = card_type, column 4 = tags, etc.
    print("No recognised header row found. Using headerless fallback.")

    fallback_column_map = {
        column_name: index
        for index, column_name in enumerate(STANDARD_COLUMNS)
    }

    return best_rows, fallback_column_map


def get_cell(row: list[str], column_map: dict[str, int], column_name: str, default: str = "") -> str:
    index = column_map.get(column_name)

    if index is None:
        return default

    if index >= len(row):
        return default

    value = row[index]

    if value is None:
        return default

    return str(value).strip()


def normalise_card_type(card_type: str | None) -> str:
    if not card_type:
        return "basic"

    card_type = card_type.strip().lower().replace(" ", "_")

    allowed_types = {
        "basic",
        "cloze",
        "image_occlusion"
    }

    if card_type in allowed_types:
        return card_type

    return "basic"


def clean_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default

        value = str(value).strip()

        if value == "":
            return default

        return int(value)

    except ValueError:
        return default


def clean_date(value):
    if value is None:
        return None

    value = str(value).strip()

    if value.lower() in ["", "none", "null", "nan", "never"]:
        return None

    return value


def import_cards_from_file(
    deck_id: int,
    import_format: str,
    file: UploadFile
) -> int:
    if import_format in ["csv", "tsv", "memrise_csv"]:
        return import_cards_from_csv_or_tsv(
            deck_id=deck_id,
            import_format=import_format,
            file=file
        )

    if import_format == "anki_apkg":
        raise ValueError("Anki .apkg import is not implemented yet.")

    raise ValueError("Unknown import format.")


def import_cards_from_csv_or_tsv(
    deck_id: int,
    import_format: str,
    file: UploadFile
) -> int:
    text = decode_uploaded_file(file)

    rows, column_map = choose_rows_and_columns(
        text=text,
        import_format=import_format
    )

    conn = get_connection()
    cursor = conn.cursor()

    imported_count = 0
    skipped_count = 0

    try:
        for row in rows:
            front = get_cell(row, column_map, "front")
            back = get_cell(row, column_map, "back")

            if not front and not back:
                skipped_count += 1
                continue

            card_type = normalise_card_type(
                get_cell(row, column_map, "card_type", "basic")
            )

            tags = get_cell(row, column_map, "tags")

            times_seen = clean_int(
                get_cell(row, column_map, "times_seen")
            )

            times_correct = clean_int(
                get_cell(row, column_map, "times_correct")
            )

            times_wrong = clean_int(
                get_cell(row, column_map, "times_wrong")
            )

            last_reviewed = clean_date(
                get_cell(row, column_map, "last_reviewed")
            )

            next_review = clean_date(
                get_cell(row, column_map, "next_review")
            )

            card_id = insert_card(
                cursor=cursor,
                deck_id=deck_id,
                front=front,
                back=back,
                card_type=card_type,
                image_path=None
            )

            cursor.execute(
                """
                UPDATE flashcards
                SET
                    times_seen = %s,
                    times_correct = %s,
                    times_wrong = %s,
                    last_reviewed = %s,
                    next_review = COALESCE(%s, next_review)
                WHERE id = %s
                """,
                (
                    times_seen,
                    times_correct,
                    times_wrong,
                    last_reviewed,
                    next_review,
                    card_id
                )
            )

            if tags.strip():
                set_card_tags_with_cursor(cursor, card_id, tags)

            imported_count += 1

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

    print("IMPORTED CARDS:", imported_count)
    print("SKIPPED ROWS:", skipped_count)

    return imported_count