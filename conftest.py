"""Pytest bootstrap: isolate tests from production artifacts.

This runs before any ``ozbargain`` module is imported, which matters because
``setup_logger()`` is called at import time in several modules and the
``settings`` singleton reads the environment on import. Without this, running
``pytest`` from the repo root writes into the production ``logs/monitor.log``
and can open the real ``ozbargain.db``.
"""

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="ozbargain-tests-"))

# Never touch the real database or its directory.
os.environ["OZBARGAIN_DB_PATH"] = str(_tmp / "test.db")
# Point file logging at a throwaway dir and disable it outright.
os.environ["OZBARGAIN_LOG_DIR"] = str(_tmp / "logs")
os.environ["OZBARGAIN_DISABLE_FILE_LOG"] = "1"
