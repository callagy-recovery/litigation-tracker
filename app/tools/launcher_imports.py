"""Every module the dashboard's code imports (main.py, data.py, resources.py, signups.py, insurers.py), so build.ps1
can bundle them into the launcher: the launcher itself imports none of them, so PyInstaller would not find them.

Run:  python app\\tools\\launcher_imports.py   -> one module name per line
"""
import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from launcher import APP_MODULES  # noqa: E402


def imports(folder=APP):
    found = set()
    for name in APP_MODULES:
        tree = ast.parse((Path(folder) / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module)
    return sorted(m for m in found if m.split(".")[0] not in APP_MODULES and m != "__future__")


if __name__ == "__main__":
    print("\n".join(imports()))
