__version__ = "0.1.0"

__all__ = ["Session", "World", "__version__"]


def __getattr__(name):
    if name in ("Session", "World"):
        from . import launcher
        return getattr(launcher, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
