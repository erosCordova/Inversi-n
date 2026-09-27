import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

DB_PATH = Path(
    os.getenv(
        "REPLIKERS_DB_PATH",
        str(Path(__file__).resolve().parent.parent / "replikers.db"),
    )
).expanduser().resolve()

if not DB_PATH.parent.is_dir():
    raise RuntimeError(
        f"No existe el directorio de la base de datos: {DB_PATH.parent}"
    )

SALDO_INICIAL = 1000.0


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(
                exc_type,
                exc_value,
                traceback,
            )
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(
        DB_PATH,
        timeout=10,
        factory=ManagedConnection,
    )
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS investments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount > 0),
                returned_amount REAL,
                status TEXT NOT NULL DEFAULT 'abierta'
                    CHECK (status IN ('abierta', 'cerrada')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                closed_at TEXT
            )
            """
        )

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(investments)"
            )
        }

        if "origin" not in columns:
            connection.execute(
                """
                ALTER TABLE investments
                ADD COLUMN origin TEXT NOT NULL DEFAULT 'manual'
                """
            )


def _portfolio(connection: sqlite3.Connection) -> dict:
    rows = connection.execute(
        """
        SELECT id, name, amount, returned_amount, status,
               created_at, closed_at, origin
        FROM investments
        ORDER BY id DESC
        """
    ).fetchall()

    investments = [dict(row) for row in rows]
    open_investments = []
    gains = []
    losses = []

    for investment in investments:
        if investment["status"] == "abierta":
            open_investments.append(investment)
            continue

        difference = (
            investment["returned_amount"]
            - investment["amount"]
        )

        if difference > 0:
            gains.append({
                **investment,
                "gain": round(difference, 2),
            })
        elif difference < 0:
            losses.append({
                **investment,
                "loss": round(-difference, 2),
            })

    invested = sum(
        item["amount"]
        for item in open_investments
    )
    total_gains = sum(
        item["gain"]
        for item in gains
    )
    total_losses = sum(
        item["loss"]
        for item in losses
    )

    agent_open = [
        item for item in open_investments
        if item["origin"] == "agent"
    ]
    agent_gains = [
        item for item in gains
        if item["origin"] == "agent"
    ]
    agent_losses = [
        item for item in losses
        if item["origin"] == "agent"
    ]

    manual_open = [
        item for item in open_investments
        if item["origin"] == "manual"
    ]
    manual_gains = [
        item for item in gains
        if item["origin"] == "manual"
    ]
    manual_losses = [
        item for item in losses
        if item["origin"] == "manual"
    ]

    return {
        "currency": "PEN",
        "initial_balance": SALDO_INICIAL,
        "available": round(
            SALDO_INICIAL
            - invested
            + total_gains
            - total_losses,
            2,
        ),
        "invested": round(invested, 2),
        "total_gains": round(total_gains, 2),
        "total_losses": round(total_losses, 2),
        "open_investments": open_investments,
        "gains": gains,
        "losses": losses,
        "agent_open_investments": agent_open,
        "agent_gains": agent_gains,
        "agent_losses": agent_losses,
        "manual_open_investments": manual_open,
        "manual_gains": manual_gains,
        "manual_losses": manual_losses,
    }


def get_portfolio() -> dict:
    initialize_database()

    with connect() as connection:
        return _portfolio(connection)


def open_investment(name: str, amount: float) -> dict:
    """Registra una operación manual de prueba."""
    if not name.strip():
        raise ValueError(
            "El nombre no puede estar vacío."
        )

    if amount <= 0:
        raise ValueError(
            "El importe debe ser mayor que cero."
        )

    initialize_database()

    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        available = _portfolio(connection)["available"]

        if amount > available:
            raise ValueError(
                f"Saldo insuficiente. "
                f"Disponible: S/ {available:.2f}."
            )

        cursor = connection.execute(
            """
            INSERT INTO investments (
                name, amount, origin
            )
            VALUES (?, ?, 'manual')
            """,
            (
                name.strip(),
                round(amount, 2),
            ),
        )
        investment_id = cursor.lastrowid

    return {
        "id": investment_id,
        "portfolio": get_portfolio(),
    }


def close_investment(
    investment_id: int,
    returned_amount: float,
) -> dict:
    """Cierra únicamente operaciones manuales."""
    if returned_amount < 0:
        raise ValueError(
            "El importe recuperado no puede ser negativo."
        )

    initialize_database()

    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")

        row = connection.execute(
            """
            SELECT id, status, origin
            FROM investments
            WHERE id = ?
            """,
            (investment_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                "La inversión no existe."
            )

        if row["origin"] != "manual":
            raise ValueError(
                "Esta operación pertenece al agente."
            )

        if row["status"] != "abierta":
            raise ValueError(
                "La inversión ya está cerrada."
            )

        connection.execute(
            """
            UPDATE investments
            SET returned_amount = ?,
                status = 'cerrada',
                closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                round(returned_amount, 2),
                investment_id,
            ),
        )

    return get_portfolio()