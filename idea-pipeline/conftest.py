"""Root conftest: make app/ importable as idea_pipeline and shared/ importable."""

import sys
from pathlib import Path

# The Docker build copies app/ -> idea_pipeline/. Locally we add a sys.path
# entry so that "import idea_pipeline.xxx" resolves to app/xxx.
_app_dir = Path(__file__).parent / "app"

# Add project root to sys.path so 'shared' package is importable locally
# (in Docker, shared/ is copied into WORKDIR).
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# We need the *parent* of the package on sys.path, and the package dir must be
# named idea_pipeline. Use a symlink-free approach: just alias via sys.modules.
if "idea_pipeline" not in sys.modules:
    import importlib

    spec = importlib.util.spec_from_file_location(
        "idea_pipeline", _app_dir / "__init__.py",
        submodule_search_locations=[str(_app_dir)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["idea_pipeline"] = mod
    spec.loader.exec_module(mod)
