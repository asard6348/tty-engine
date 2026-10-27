_NAME = "ttyengine"


def _pyproject_version():
    import re
    from pathlib import Path

    table = re.compile(r"^\s*\[+\s*([^\[\]]+?)\s*\]+\s*(?:#.*)?$")
    field = re.compile(r"""^\s*(name|version)\s*=\s*(?:"([^"]*)"|'([^']*)')\s*(?:#.*)?$""")
    try:
        with open(Path(__file__).resolve().parent.parent / "pyproject.toml", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    fields = {}
    current = None
    for line in lines:
        header = table.match(line)
        if header:
            current = header.group(1)
            continue
        found = field.match(line) if current == "project" else None
        if found:
            fields[found.group(1)] = found.group(2) if found.group(2) is not None else found.group(3)
    return fields.get("version") if fields.get("name") == _NAME else None


def _installed_version():
    try:
        from importlib.metadata import version
        return version(_NAME)
    except Exception:
        return None


__version__ = _installed_version() or _pyproject_version() or "0+unknown"

__all__ = ["Session", "World", "Simulation", "start", "net", "__version__"]


def __getattr__(name):
    if name in ("Session", "World", "Simulation", "start"):
        from . import launcher
        return getattr(launcher, name)
    if name == "net":
        from . import net
        return net
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
