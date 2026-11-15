import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "studio.db"

BUILTIN_VOICES = [
    ("cosette", "Cosette", "builtin", "cosette"),
    ("marius", "Marius", "builtin", "marius"),
    ("javert", "Javert", "builtin", "javert"),
    ("alba", "Alba", "builtin", "alba"),
    ("jean", "Jean", "builtin", "jean"),
    ("anna", "Anna", "builtin", "anna"),
    ("vera", "Vera", "builtin", "vera"),
    ("fantine", "Fantine", "builtin", "fantine"),
    ("charles", "Charles", "builtin", "charles"),
    ("paul", "Paul", "builtin", "paul"),
    ("eponine", "Eponine", "builtin", "eponine"),
    ("azelma", "Azelma", "builtin", "azelma"),
    ("george", "George", "builtin", "george"),
    ("mary", "Mary", "builtin", "mary"),
    ("jane", "Jane", "builtin", "jane"),
    ("michael", "Michael", "builtin", "michael"),
    ("eve", "Eve", "builtin", "eve"),
    ("bill_boerst", "Bill Boerst", "builtin", "bill_boerst"),
    ("peter_yearsley", "Peter Yearsley", "builtin", "peter_yearsley"),
    ("stuart_bell", "Stuart Bell", "builtin", "stuart_bell"),
    ("caro_davy", "Caro Davy", "builtin", "caro_davy"),
    ("giovanni", "Giovanni", "builtin", "giovanni"),
    ("lola", "Lola", "builtin", "lola"),
    ("juergen", "Juergen", "builtin", "juergen"),
    ("rafael", "Rafael", "builtin", "rafael"),
    ("daan", "Daan", "builtin", "daan"),
    ("estelle", "Estelle", "builtin", "estelle"),
]

def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row

    return connection


def initialize_database():
    with get_connection() as db:

        db.execute("""
            CREATE TABLE IF NOT EXISTS voices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                favorite INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Persistent recording numbering
        db.execute("""
            CREATE TABLE IF NOT EXISTS recording_counters (
                voice_id TEXT PRIMARY KEY,
                next_number INTEGER NOT NULL DEFAULT 1
            )
        """)

        for voice in BUILTIN_VOICES:
            db.execute("""
                INSERT OR IGNORE INTO voices
                (id, name, category, source)
                VALUES (?, ?, ?, ?)
            """, voice)


def get_voices():
    with get_connection() as db:
        rows = db.execute("""
            SELECT *
            FROM voices
            ORDER BY favorite DESC, name COLLATE NOCASE
        """).fetchall()

        return [dict(row) for row in rows]


def get_voice(voice_id):
    with get_connection() as db:
        row = db.execute(
            "SELECT * FROM voices WHERE id = ?",
            (voice_id,)
        ).fetchone()

        return dict(row) if row else None


def update_voice(voice_id, name=None, favorite=None):
    with get_connection() as db:

        voice = db.execute(
            "SELECT * FROM voices WHERE id = ?",
            (voice_id,)
        ).fetchone()

        if voice is None:
            return None

        if name is not None:
            name = name.strip()

            if not name or len(name) > 100:
                raise ValueError(
                    "Voice name must contain 1–100 characters."
                )

            db.execute(
                "UPDATE voices SET name = ? WHERE id = ?",
                (name, voice_id)
            )

        if favorite is not None:
            db.execute(
                "UPDATE voices SET favorite = ? WHERE id = ?",
                (int(favorite), voice_id)
            )

    return get_voice(voice_id)

def add_voice(
    voice_id,
    name,
    category,
    source
):
    with get_connection() as db:

        db.execute("""
            INSERT INTO voices
            (id, name, category, source)
            VALUES (?, ?, ?, ?)
        """, (
            voice_id,
            name,
            category,
            source
        ))

    return get_voice(voice_id)



def get_next_recording_number(voice_id):
    """
    Return the next persistent recording number for a voice.

    Example:
        alba -> 1
        alba -> 2
        marius -> 1
    """

    with get_connection() as db:

        row = db.execute(
            """
            SELECT next_number
            FROM recording_counters
            WHERE voice_id = ?
            """,
            (voice_id,)
        ).fetchone()

        if row is None:

            number = 1

            db.execute(
                """
                INSERT INTO recording_counters
                (voice_id, next_number)
                VALUES (?, ?)
                """,
                (voice_id, 2)
            )

        else:

            number = row["next_number"]

            db.execute(
                """
                UPDATE recording_counters
                SET next_number = ?
                WHERE voice_id = ?
                """,
                (number + 1, voice_id)
            )

    return number