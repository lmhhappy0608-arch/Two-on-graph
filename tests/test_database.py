import sqlite3
from pathlib import Path

import pytest

from app.database import (
    Database,
    DatabaseUnavailable,
    SchemaError,
    WriteRejected,
    source_stamp,
)


def test_select_returns_named_fields():
    rows = Database().query("SELECT course_id, course_name FROM courses WHERE course_id = ?", ("MATH206",))
    assert rows == [{"course_id": "MATH206", "course_name": "Probability and Statistics"}]


def test_write_statement_is_rejected():
    with pytest.raises(WriteRejected):
        Database().query("DELETE FROM courses")


def test_query_only_rejects_insert():
    with Database().connect() as connection:
        with pytest.raises(sqlite3.Error):
            connection.execute(
                "INSERT INTO source_notes (field, value) VALUES ('step2', 'no')"
            )


def test_missing_file_has_clear_error(tmp_path: Path):
    with pytest.raises(DatabaseUnavailable, match="Database file not found"):
        Database(tmp_path / "missing.sqlite").query("SELECT 1")


def test_corrupt_file_has_clear_error(tmp_path: Path):
    path = tmp_path / "broken.sqlite"
    path.write_text("this is not sqlite", encoding="utf-8")
    with pytest.raises(DatabaseUnavailable):
        Database(path).query("SELECT 1")


def test_missing_table_names_the_table(tmp_path: Path):
    path = tmp_path / "partial.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE courses (course_id TEXT)")
    connection.commit()
    connection.close()
    with pytest.raises(SchemaError, match="class_sections"):
        Database(path).query("SELECT 1")


def test_source_stamp_uses_the_given_file(tmp_path: Path):
    path = tmp_path / "stamp.sqlite"
    path.write_bytes(b"abc")
    first = source_stamp(path)
    path.write_bytes(b"abcd")
    assert source_stamp(path) != first
