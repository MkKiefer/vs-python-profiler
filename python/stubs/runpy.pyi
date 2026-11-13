"""Stubs for ``runpy`` including the private helper ``python -m`` itself uses."""

def run_path(
    path_name: str, init_globals: dict[str, object] | None = None, run_name: str | None = None
) -> dict[str, object]: ...
def run_module(
    mod_name: str,
    init_globals: dict[str, object] | None = None,
    run_name: str | None = None,
    alter_sys: bool = False,
) -> dict[str, object]: ...
def _run_module_as_main(mod_name: str, alter_argv: bool = True) -> dict[str, object]: ...
