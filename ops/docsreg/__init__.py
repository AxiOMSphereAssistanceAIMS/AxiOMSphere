"""DOCSREG production certification modules."""


def __getattr__(name: str):
    """Lazy-import from docsreg_cycle_runner to avoid circular imports."""
    _exported = {"DocsregCycleRunResult", "build_docsreg_auditor", "run_docsreg_cycle"}
    if name in _exported:
        from ops.docsreg import docsreg_cycle_runner as _m  # noqa: PLC0415
        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
