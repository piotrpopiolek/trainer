"""Kind markers come from the directory. idor and concurrency stay explicit."""

from __future__ import annotations

from pathlib import Path

import pytest


def _disable_coverage_gate(config: pytest.Config) -> None:
    """Unit runs must not fail the full-suite 80% gate."""
    if hasattr(config.option, "no_cov"):
        config.option.no_cov = True
    plugin = config.pluginmanager.get_plugin("_cov")
    if plugin is None:
        return
    plugin.options.no_cov = True
    plugin.options.cov_fail_under = None
    plugin._disabled = True


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    markexpr = (config.getoption("markexpr") or "").strip()
    if markexpr == "unit":
        _disable_coverage_gate(config)
    nproc = getattr(config.option, "numprocesses", None)
    if nproc not in (None, 0, "0") and markexpr != "unit":
        raise pytest.UsageError(
            "pytest-xdist (-n) is only allowed with -m unit; "
            "integration and e2e stay serial on one database"
        )
    if markexpr != "unit":
        import app.models  # noqa: F401 — register ORM metadata for coverage


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    for item in items:
        path = Path(str(item.path)).as_posix()
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/tests/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
