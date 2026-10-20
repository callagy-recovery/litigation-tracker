"""Litigation Tracker.exe: a launcher that runs the dashboard's code from app\\ on the shared folder.

The exe holds Python and the libraries the dashboard uses, plus a backup copy of the dashboard's code from when it was
built. At each start it loads main.py (and data.py, resources.py, signups.py, insurers.py) from the folder it sits in,
so a change there reaches everyone the next time they open the dashboard - no rebuild, no "everyone close it".
If that code cannot be loaded (a half-saved file, a mistake, or a library the launcher does not include), it runs the
backup copy instead and the page and the log say why. Rebuild the launcher only when the dashboard starts using a new
library (app\\tools\\build.ps1).
"""
import importlib
import os
import sys
import traceback
from pathlib import Path

APP_MODULES = ("main", "data", "resources", "signups", "insurers")


def load(folder):
    """The dashboard's main module, imported fresh from folder."""
    for name in APP_MODULES:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(folder))
    try:
        return importlib.import_module("main")
    except BaseException:
        sys.path.remove(str(folder))
        for name in APP_MODULES:
            sys.modules.pop(name, None)
        raise


def choose(live, backup):
    """(main module, which copy, why the live one was not used or ''). The live copy wins whenever it loads."""
    try:
        return load(live), "shared folder", ""
    except Exception as e:  # SyntaxError, ImportError, anything raised while importing
        missing = isinstance(e, ModuleNotFoundError) and e.name not in APP_MODULES
        reason = (f"the dashboard's code needs a library the launcher does not include ({e.name}); rebuild the launcher "
                  "with app\\tools\\build.ps1" if missing else
                  f"the dashboard's code on the shared folder could not be loaded ({type(e).__name__}: {e})")
        return load(backup), "backup copy in the launcher", reason + "\n" + traceback.format_exc(limit=3)


def run():
    exe_dir = Path(sys.executable).resolve().parent
    backup = Path(getattr(sys, "_MEIPASS", exe_dir)) / "app_backup"
    main, source, reason = choose(exe_dir / "app", backup)
    os.environ["LT_CODE"] = source  # main.py logs it and, for the backup, shows a note on the page
    if reason:
        os.environ["LT_CODE_PROBLEM"] = reason.splitlines()[0]
    try:
        main.main()
    except Exception:
        main.log.exception("Litigation Tracker stopped with an error")
        raise


if __name__ == "__main__":
    run()
