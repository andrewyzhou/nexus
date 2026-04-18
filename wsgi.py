"""
WSGI entry point for production servers (gunicorn, uWSGI, etc.).

Example:
    gunicorn -w 4 -b 127.0.0.1:5001 wsgi:app

The backend/ directory is added to sys.path so its relative imports
(config, db.seed_prod, ...) resolve the same way they do when you run
`python3 backend/main.py` locally.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from main import app  # noqa: E402  (import must come after sys.path tweak)

# gunicorn expects `app` as a module-level attribute
__all__ = ["app"]
