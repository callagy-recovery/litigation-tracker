"""The dashboard launcher (app/launcher.py): runs the shared code, falls back to its built-in copy when that fails."""
import sys

import pytest

import launcher


@pytest.fixture
def clean_modules():
    """The tests import fake dashboards named main/data: put the real ones (and sys.path) back afterwards."""
    saved = {m: sys.modules.get(m) for m in launcher.APP_MODULES}
    path = list(sys.path)
    yield
    for m, mod in saved.items():
        if mod is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = mod
    sys.path[:] = path


def dashboard(folder, who, extra=""):
    folder.mkdir()
    (folder / "main.py").write_text(f"import data\nWHO = '{who}'\n{extra}\ndef main():\n    return WHO\n", encoding="utf-8")
    (folder / "data.py").write_text(f"WHO = '{who}'\n", encoding="utf-8")
    return folder


def test_the_shared_code_runs_when_it_loads(tmp_path, clean_modules):
    live, backup = dashboard(tmp_path / "live", "live"), dashboard(tmp_path / "backup", "backup")
    main, source, reason = launcher.choose(live, backup)
    assert (main.WHO, sys.modules["data"].WHO, source, reason) == ("live", "live", "shared folder", "")


def test_a_broken_shared_file_falls_back_to_the_backup(tmp_path, clean_modules):
    live, backup = dashboard(tmp_path / "live", "live"), dashboard(tmp_path / "backup", "backup")
    (live / "data.py").write_text("WHO = 'half saved", encoding="utf-8")  # a half-written file
    main, source, reason = launcher.choose(live, backup)
    assert main.WHO == "backup" and sys.modules["data"].WHO == "backup"  # nothing of the broken copy is mixed in
    assert source == "backup copy in the launcher" and "could not be loaded (SyntaxError" in reason


def test_a_missing_library_says_to_rebuild_the_launcher(tmp_path, clean_modules):
    live = dashboard(tmp_path / "live", "live", extra="import a_library_the_launcher_lacks")
    backup = dashboard(tmp_path / "backup", "backup")
    main, source, reason = launcher.choose(live, backup)
    assert main.WHO == "backup" and "a_library_the_launcher_lacks" in reason and "rebuild the launcher" in reason


def test_the_build_bundles_every_library_the_dashboard_imports(monkeypatch):
    from conftest import ROOT
    monkeypatch.syspath_prepend(str(ROOT / "app" / "tools"))
    import launcher_imports
    found = launcher_imports.imports()
    assert {"openpyxl", "openpyxl.styles", "docx", "pypdf", "PIL", "http.server", "html.parser", "urllib.request"} <= set(found)
    assert not set(found) & set(launcher.APP_MODULES)  # the dashboard's own code is read from the share, not bundled
