import csv
import io
from fastapi import UploadFile

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta

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
        return import_cards_from_anki_apkg(
            deck_id=deck_id,
            file=file
        )

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

def import_cards_from_anki_apkg(deck_id: int, file: UploadFile) -> int:
    raw_bytes = file.file.read()

    with tempfile.TemporaryDirectory() as temp_dir:
        apkg_path = os.path.join(temp_dir, "deck.apkg")

        with open(apkg_path, "wb") as f:
            f.write(raw_bytes)

        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(apkg_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        collection_path = find_anki_collection_file(extract_dir)

        if not collection_path:
            raise ValueError("Could not find an Anki collection file inside the .apkg file.")

        collection_path = prepare_anki_collection_for_sqlite(
            collection_path=collection_path,
            temp_dir=temp_dir
        )

        if is_dummy_anki_update_collection(collection_path):
            raise ValueError(
                "This .apkg contains Anki's dummy update-message collection, "
                "not the real deck data. Export again from Anki with "
                "'Support older Anki versions' enabled."
            )

        media_map = load_anki_media_map(extract_dir)
        copied_media = copy_anki_media_files(extract_dir, media_map)

        anki_rows = read_anki_cards(collection_path)

        print("ANKI ROWS FOUND:", len(anki_rows))

    conn = get_connection()
    cursor = conn.cursor()

    imported_count = 0

    try:
        for row in anki_rows:
            front = replace_anki_media_references(
                row["front"],
                copied_media
            )

            back = replace_anki_media_references(
                row["back"],
                copied_media
            )

            card_type = detect_anki_card_type(
                row["model_name"],
                front,
                back
            )

            tags = row["tags"]

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
                    row["times_seen"],
                    row["times_correct"],
                    row["times_wrong"],
                    row["last_reviewed"],
                    row["next_review"],
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

    print("IMPORTED ANKI CARDS:", imported_count)

    return imported_count

def find_anki_collection_file(extract_dir: str) -> str | None:
    print("ANKI PACKAGE FILES:")
    for filename in os.listdir(extract_dir):
        print(" -", filename)

    possible_names = [
        "collection.anki21",
        "collection.anki2"
    ]

    for name in possible_names:
        path = os.path.join(extract_dir, name)

        if os.path.exists(path):
            print("ANKI COLLECTION FILE FOUND:", name)
            return path

    return None

def prepare_anki_collection_for_sqlite(
    collection_path: str,
    temp_dir: str
) -> str:
    with open(collection_path, "rb") as f:
        header = f.read(16)

    if header == b"SQLite format 3\x00":
        print("ANKI COLLECTION IS NORMAL SQLITE")
        return collection_path

    try:
        import zstandard as zstd
    except ImportError:
        raise ValueError(
            "This Anki package uses a compressed collection format. "
            "Run: pip install zstandard"
        )

    print("ANKI COLLECTION APPEARS COMPRESSED. TRYING ZSTD DECOMPRESSION.")

    with open(collection_path, "rb") as f:
        compressed_data = f.read()

    decompressed_data = zstd.ZstdDecompressor().decompress(compressed_data)

    sqlite_path = os.path.join(temp_dir, "collection_decompressed.sqlite")

    with open(sqlite_path, "wb") as f:
        f.write(decompressed_data)

    with open(sqlite_path, "rb") as f:
        decompressed_header = f.read(16)

    if decompressed_header != b"SQLite format 3\x00":
        raise ValueError(
            "Could not convert the Anki collection into a readable SQLite database."
        )

    print("ANKI COLLECTION DECOMPRESSED SUCCESSFULLY")

    return sqlite_path


def load_anki_media_map(extract_dir: str) -> dict[str, str]:
    media_path = os.path.join(extract_dir, "media")

    if not os.path.exists(media_path):
        print("No Anki media file found.")
        return {}

    try:
        with open(media_path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            print("Anki media file is empty.")
            return {}

        return json.loads(content)

    except json.JSONDecodeError as error:
        print("Could not parse Anki media file as JSON.")
        print("Media parse error:", error)
        return {}

    except UnicodeDecodeError as error:
        print("Could not decode Anki media file.")
        print("Media decode error:", error)
        return {}


def copy_anki_media_files(
    extract_dir: str,
    media_map: dict[str, str]
) -> dict[str, str]:
    upload_dir = "static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    copied_media = {}

    for anki_file_number, original_filename in media_map.items():
        source_path = os.path.join(extract_dir, anki_file_number)

        if not os.path.exists(source_path):
            continue

        safe_filename = os.path.basename(original_filename)
        unique_filename = f"anki_{datetime.now().timestamp()}_{safe_filename}"

        destination_path = os.path.join(upload_dir, unique_filename)

        shutil.copyfile(source_path, destination_path)

        copied_media[original_filename] = f"/static/uploads/{unique_filename}"

    return copied_media


def replace_anki_media_references(
    html: str,
    copied_media: dict[str, str]
) -> str:
    if not html:
        return ""

    for original_filename, new_path in copied_media.items():
        html = html.replace(
            f'src="{original_filename}"',
            f'src="{new_path}"'
        )

        html = html.replace(
            f"src='{original_filename}'",
            f"src='{new_path}'"
        )

        html = html.replace(
            original_filename,
            new_path
        )

    return html

def read_anki_cards(collection_path: str) -> list[dict]:
    conn = sqlite3.connect(collection_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    models = load_anki_models(cursor)
    collection_created = load_anki_collection_created_date(cursor)

    cursor.execute(
        """
        SELECT
            cards.id AS card_id,
            cards.nid AS note_id,
            cards.ord AS card_ord,
            cards.due AS due,
            cards.ivl AS interval_days,
            cards.reps AS reps,
            cards.lapses AS lapses,
            cards.queue AS queue,
            cards.type AS anki_type,
            notes.mid AS model_id,
            notes.flds AS fields,
            notes.tags AS tags
        FROM cards
        JOIN notes
            ON cards.nid = notes.id
        ORDER BY cards.id
        """
    )

    rows = cursor.fetchall()

    anki_cards = []

    for row in rows:
        model = models.get(str(row["model_id"]), {})
        model_name = model.get("name", "")

        fields = split_anki_fields(row["fields"])
        front, back = choose_front_back_from_anki_fields(
            fields=fields,
            card_ord=row["card_ord"],
            model=model
        )

        last_reviewed = get_last_reviewed_for_card(
            cursor,
            row["card_id"]
        )

        next_review = estimate_next_review(
            collection_created=collection_created,
            due=row["due"],
            interval_days=row["interval_days"],
            queue=row["queue"]
        )

        reps = row["reps"] or 0
        lapses = row["lapses"] or 0

        anki_cards.append(
            {
                "front": front,
                "back": back,
                "model_name": model_name,
                "tags": clean_anki_tags(row["tags"]),
                "times_seen": reps,
                "times_wrong": lapses,
                "times_correct": max(reps - lapses, 0),
                "last_reviewed": last_reviewed,
                "next_review": next_review,
            }
        )

    cursor.close()
    conn.close()

    return anki_cards

def load_anki_models(cursor) -> dict:
    cursor.execute(
        """
        SELECT models
        FROM col
        LIMIT 1
        """
    )

    row = cursor.fetchone()

    if not row:
        return {}

    return json.loads(row["models"])


def load_anki_collection_created_date(cursor) -> datetime:
    cursor.execute(
        """
        SELECT crt
        FROM col
        LIMIT 1
        """
    )

    row = cursor.fetchone()

    if not row:
        return datetime.now()

    return datetime.fromtimestamp(row["crt"])


def split_anki_fields(fields_text: str) -> list[str]:
    return fields_text.split("\x1f")


def choose_front_back_from_anki_fields(
    fields: list[str],
    card_ord: int,
    model: dict
) -> tuple[str, str]:
    model_name = model.get("name", "").lower()

    if "cloze" in model_name:
        text = fields[0] if len(fields) > 0 else ""
        extra = fields[1] if len(fields) > 1 else ""

        return text, extra

    if len(fields) == 0:
        return "", ""

    if len(fields) == 1:
        return fields[0], ""

    return fields[0], fields[1]


def clean_anki_tags(tags: str) -> str:
    if not tags:
        return ""

    return ";".join(
        tag.strip()
        for tag in tags.split()
        if tag.strip()
    )


def detect_anki_card_type(
    model_name: str,
    front: str,
    back: str
) -> str:
    model_name = model_name.lower()

    if "image occlusion" in model_name:
        return "image_occlusion"

    if "cloze" in model_name:
        return "cloze"

    if "{{c" in front or "{{c" in back:
        return "cloze"

    return "basic"


def get_last_reviewed_for_card(cursor, card_id: int):
    cursor.execute(
        """
        SELECT MAX(id) AS last_review_id
        FROM revlog
        WHERE cid = ?
        """,
        (card_id,)
    )

    row = cursor.fetchone()

    if not row or row["last_review_id"] is None:
        return None

    timestamp = row["last_review_id"]

    # Anki revlog IDs are commonly millisecond timestamps.
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000

    return datetime.fromtimestamp(timestamp)


def estimate_next_review(
    collection_created: datetime,
    due: int,
    interval_days: int,
    queue: int
):
    if due is None:
        return None

    # Review cards usually have due as a day offset from collection creation.
    if queue == 2:
        return collection_created + timedelta(days=due)

    # New or learning cards: make them available now in your app.
    if queue in [0, 1, 3]:
        return datetime.now()

    return datetime.now() + timedelta(days=max(interval_days or 0, 0))

def is_dummy_anki_update_collection(collection_path: str) -> bool:
    try:
        conn = sqlite3.connect(collection_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT flds
            FROM notes
            LIMIT 5
            """
        )

        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        for row in rows:
            fields = row["flds"]

            if "Please update to the latest Anki version" in fields:
                return True

        return False

    except Exception:
        return False