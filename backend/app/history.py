import json

from .storage import connect


def initialize_history() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS explorations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                sources TEXT NOT NULL,
                explorer TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                decision TEXT NOT NULL,
                reasons_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(explorations)"
            )
        }

        if "reasons_json" not in columns:
            connection.execute(
                """
                ALTER TABLE explorations
                ADD COLUMN reasons_json TEXT NOT NULL DEFAULT '[]'
                """
            )


def save_exploration(
    query: str,
    sources: str,
    explorer: str,
    reviewer: str,
    decision: str,
    reasons: list[str] | None = None,
) -> int:
    initialize_history()

    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO explorations
                (query, sources, explorer, reviewer,
                 decision, reasons_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                query,
                sources,
                explorer,
                reviewer,
                decision,
                json.dumps(reasons or [], ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid)


def list_explorations(limit: int = 20) -> list[dict]:
    initialize_history()

    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, query, sources, explorer, reviewer,
                   decision, reasons_json, created_at
            FROM explorations
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    explorations = []

    for row in rows:
        item = dict(row)
        item["reasons"] = json.loads(item.pop("reasons_json"))
        explorations.append(item)

    return explorations