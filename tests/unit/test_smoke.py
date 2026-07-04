def test_package_version():
    import src

    assert src.__version__ == "0.1.0"


def test_core_modules_importable():
    from config.settings import get_settings  # noqa: F401
    from domain import AgingMetrics, ColumnMapping, QualityFlag  # noqa: F401
    from graph.agent import agentic_ai  # noqa: F401
    from graph.runner import build_preview, run_analysis, PipelineError  # noqa: F401
    from tools import compute_metrics, detect_mapping, normalize, read_workbook, validate  # noqa: F401


def test_no_llm_or_db_modules_remain():
    import importlib

    for gone in ("llm", "llm.client", "db", "db.models", "db.session", "domain.run"):
        try:
            importlib.import_module(gone)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"module {gone!r} should have been removed")
