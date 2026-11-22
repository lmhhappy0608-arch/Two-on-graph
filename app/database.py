"""Read-only SQLite access for the curriculum database."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "curriculum.sqlite"

REQUIRED_TABLES = (
    "courses",
    "course_aliases",
    "class_sections",
    "graph_edges",
    "major_rules",
    "major_rule_items",
    "major_rule_constraints",
)

_READ_PREFIXES = ("select", "with", "pragma")


class DatabaseError(RuntimeError):
    """The curriculum database cannot be used."""


class DatabaseUnavailable(DatabaseError):
    """The database file is missing or is not a readable SQLite file."""


class SchemaError(DatabaseError):
    """A required table is missing."""


class WriteRejected(DatabaseError):
    """A statement would modify the database."""


def default_db_path() -> Path:
    return DEFAULT_DB_PATH


def source_stamp(path: Path | None = None) -> tuple[int, int]:
    """File version used as a cache key. It is not a course-offering forecast."""
    target = path or DEFAULT_DB_PATH
    stat = target.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _is_read_statement(sql: str) -> bool:
    stripped = sql.lstrip().lstrip("(").strip().lower()
    return stripped.startswith(_READ_PREFIXES)


class Database:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else DEFAULT_DB_PATH

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise DatabaseUnavailable(f"Database file not found: {self.path}")
        try:
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise DatabaseUnavailable(f"Unable to open database: {exc}") from exc
        try:
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA query_only = ON")
                connection.execute("PRAGMA foreign_keys = ON")
                self.require_schema(connection)
            except SchemaError:
                raise
            except sqlite3.Error as exc:
                raise DatabaseUnavailable(f"Unable to read database: {exc}") from exc
            yield connection
        finally:
            connection.close()

    def require_schema(self, connection: sqlite3.Connection) -> None:
        found = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = [name for name in REQUIRED_TABLES if name not in found]
        if missing:
            raise SchemaError("Missing required database tables: " + ", ".join(missing))

    def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        if not _is_read_statement(sql):
            raise WriteRejected("The read-only data layer rejected a write or schema-change statement.")
        with self.connect() as connection:
            cursor = connection.execute(sql, params)
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return [{key: row[key] for key in row.keys()} for row in rows]
