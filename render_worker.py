"""
render_worker.py - runs Schemdraw code in a separate process and saves the picture.

Usage:  python render_worker.py <code_file> <output_dir>

Why a separate process?  Code written by an AI (or typed into the app) should
never be able to freeze or crash the app.  The app starts this worker with a
time limit; if anything goes wrong only the worker dies and the error text is
sent back (and, if AI is on, fed back to the AI for another try).

The code must create a variable called `d` that is a schemdraw.Drawing.
"""
import builtins
import json
import os
import sys
import traceback

os.environ.setdefault("MPLBACKEND", "Agg")

ALLOWED_IMPORT_ROOTS = {"schemdraw", "math"}
SAFE_BUILTINS = [
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "int", "isinstance",
    "len", "list", "map", "max", "min", "pow", "print", "range", "repr", "reversed", "round", "set",
    "sorted", "str", "sum", "tuple", "zip", "True", "False", "None", "ValueError", "Exception",
]


def _limited_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] not in ALLOWED_IMPORT_ROOTS:
        raise ImportError(f"import of '{name}' is not allowed in drawing code")
    return builtins.__import__(name, globals, locals, fromlist, level)


def run(code: str, backend: str):
    import schemdraw
    schemdraw.use(backend)
    env = {name: getattr(builtins, name) for name in SAFE_BUILTINS if hasattr(builtins, name)}
    env["__import__"] = _limited_import
    scope = {"__builtins__": env, "__name__": "__circuit__"}
    exec(compile(code, "<drawing code>", "exec"), scope)
    d = scope.get("d")
    if not isinstance(d, schemdraw.Drawing):
        raise RuntimeError("The code must create a variable named `d` that is a schemdraw.Drawing")
    return d


def render_files(code: str, out_dir: str) -> dict:
    """Run the drawing code and write diagram.svg / .png / .pdf into out_dir.

    Returns {"ok": True} or {"ok": False, "error": ..., "line": ...}.  Used by the
    subprocess entry point below, and called directly when the app runs in the
    browser (stlite / Pyodide), where there are no subprocesses.
    """
    try:
        # pass 1: native SVG backend -> labels stay real, editable text
        d = run(code, "svg")
        with open(os.path.join(out_dir, "diagram.svg"), "wb") as f:
            f.write(d.get_imagedata("svg"))
        # pass 2: Matplotlib backend -> PNG and PDF without any extra system libraries
        d = run(code, "matplotlib")
        d.save(os.path.join(out_dir, "diagram.png"), transparent=False, dpi=220)
        d.save(os.path.join(out_dir, "diagram.pdf"), transparent=False)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001 - we want every error reported back
        tb = traceback.extract_tb(sys.exc_info()[2])
        line = next((fr.lineno for fr in reversed(tb) if fr.filename == "<drawing code>"), None)
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "line": line}


def main() -> int:
    code_file, out_dir = sys.argv[1], sys.argv[2]
    code = open(code_file, encoding="utf-8").read()
    info = render_files(code, out_dir)
    print(json.dumps(info))
    return 0 if info["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
