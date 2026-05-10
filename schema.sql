CREATE TABLE IF NOT EXISTS decks (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flashcards (
    id SERIAL PRIMARY KEY,
    deck_id INTEGER REFERENCES decks(id),
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    times_seen INTEGER DEFAULT 0,
    times_correct INTEGER DEFAULT 0,
    times_wrong INTEGER DEFAULT 0,
    last_reviewed TIMESTAMP,
    next_review TIMESTAMP DEFAULT NOW()
);