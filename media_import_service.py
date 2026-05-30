# media_import_service.py

import re
from collections import Counter

from database import get_connection

from deep_translator import GoogleTranslator

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    RequestBlocked,
    IpBlocked,
)
from urllib.parse import urlparse, parse_qs

def translate_media_word(
    word: str,
    source_language: str,
    user_language: str = "en"
) -> str:
    if not word:
        return ""

    if source_language == user_language:
        return word

    try:
        return GoogleTranslator(
            source=source_language,
            target=user_language
        ).translate(word)

    except Exception as error:
        print("MEDIA IMPORT TRANSLATION ERROR:", error)
        return ""

def normalise_word(word: str) -> str:
    return word.strip().lower()


def extract_1grams_from_text(text: str) -> list[str]:
    """
    First simple version:
    Extract alphabetic words, including accented characters.
    Good enough for Spanish/French/German/Italian first pass.
    """

    if not text:
        return []

    raw_words = re.findall(
        r"[A-Za-zÀ-ÖØ-öø-ÿñÑüÜáéíóúÁÉÍÓÚ]+",
        text.lower()
    )

    words = []

    for word in raw_words:
        word = normalise_word(word)

        if len(word) < 2:
            continue

        words.append(word)

    return words


def get_existing_deck_words(deck_id: int) -> set[str]:
    """
    First version assumes the target-language word is usually on the front.
    This avoids English translations on the back blocking Spanish/French/etc words.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT front
        FROM flashcards
        WHERE deck_id = %s;
        """,
        (deck_id,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    existing_words = set()

    for row in rows:
        front = row[0]

        if not front:
            continue

        front = normalise_word(front)

        if " " in front:
            continue

        existing_words.add(front)

    return existing_words


def extract_unknown_1grams_for_deck(
    deck_id: int,
    text: str,
    source_language: str,
    user_language: str = "en",
    minimum_count: int = 1,
    max_results: int = 100
) -> list[dict]:
    extracted_words = extract_1grams_from_text(text)

    existing_words = get_existing_deck_words(deck_id)

    counts = Counter(extracted_words)

    candidates = []

    for word, count in counts.items():
        if count < minimum_count:
            continue

        if word in existing_words:
            continue

        translation = translate_media_word(
            word=word,
            source_language=source_language,
            user_language=user_language
        )

        candidates.append({
            "word": word,
            "translation": translation,
            "count": count
        })

    candidates.sort(
        key=lambda item: (
            -item["count"],
            item["word"]
        )
    )

    return candidates[:max_results]

def extract_youtube_video_id(url: str) -> str | None:
    if not url:
        return None

    url = url.strip()
    parsed_url = urlparse(url)

    hostname = parsed_url.hostname or ""

    if hostname in ["www.youtube.com", "youtube.com", "m.youtube.com"]:
        if parsed_url.path == "/watch":
            query_params = parse_qs(parsed_url.query)
            return query_params.get("v", [None])[0]

        if parsed_url.path.startswith("/shorts/"):
            return parsed_url.path.split("/shorts/")[-1].split("/")[0]

    if hostname == "youtu.be":
        return parsed_url.path.strip("/") or None

    return None


def get_youtube_transcript_text(
    youtube_url: str,
    language: str
) -> str:
    video_id = extract_youtube_video_id(youtube_url)

    if not video_id:
        raise ValueError("Could not find a valid YouTube video ID.")

    try:
        api = YouTubeTranscriptApi()

        transcript = api.fetch(
            video_id,
            languages=[language, "en"]
        )

        return " ".join(
            snippet.text
            for snippet in transcript
            if snippet.text
        )

    except NoTranscriptFound:
        raise ValueError(
            "No transcript was found in the deck language or English. "
            "Try a different video, or paste the transcript manually."
        )

    except TranscriptsDisabled:
        raise ValueError(
            "Transcripts are disabled for this video."
        )

    except VideoUnavailable:
        raise ValueError(
            "This video is unavailable."
        )

    except (RequestBlocked, IpBlocked):
        raise ValueError(
            "YouTube blocked the transcript request from this connection. "
            "For now, paste the transcript manually, or we can add a fallback transcript provider later."
        )

    except Exception as error:
        raise ValueError(
            f"Could not fetch transcript: {error}"
        )
    
def debug_available_youtube_transcripts(youtube_url: str) -> str:
    video_id = extract_youtube_video_id(youtube_url)

    if not video_id:
        return "Could not find a valid YouTube video ID."

    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        lines = []

        for transcript in transcript_list:
            lines.append(
                f"language={transcript.language}, "
                f"language_code={transcript.language_code}, "
                f"generated={transcript.is_generated}, "
                f"translatable={transcript.is_translatable}"
            )

        if not lines:
            return "No transcript options were returned."

        return "\n".join(lines)

    except Exception as error:
        return f"Could not list transcripts: {error}"