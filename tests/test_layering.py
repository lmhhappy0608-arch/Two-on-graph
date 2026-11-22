import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_services_do_not_import_streamlit():
    sys.modules.pop("streamlit", None)
    import app.course_repository
    import app.database
    import app.graph_service
    import app.major_service
    import app.prerequisite_service

    assert "streamlit" not in sys.modules
    for module in (
        app.database,
        app.course_repository,
        app.graph_service,
        app.prerequisite_service,
        app.major_service,
    ):
        assert "streamlit" not in Path(module.__file__).read_text(encoding="utf-8")


def test_demo_no_longer_reads_the_excel_subset():
    source = (ROOT / "demo.py").read_text(encoding="utf-8")
    assert "curriculum_subset_math_cs_ds.xlsx" not in source
    assert "read_excel" not in source
    assert "sqlite3" not in source
    assert "SELECT " not in source
    assert "not a course plan" in source
    assert "not an official degree audit" in source
    assert not any("\u4e00" <= character <= "\u9fff" for character in source)
