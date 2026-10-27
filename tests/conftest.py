import os
import tempfile
import time

import pytest

# vor dem ersten Import von stub: Einstellungen und Arbeitskopien in einen Wegwerf-Ordner
os.environ["STUB_HOME"] = tempfile.mkdtemp(prefix="stub-test-")

from stub import config as cfg  # noqa: E402
from stub import filing, session  # noqa: E402


@pytest.fixture
def ablage(tmp_path, monkeypatch):
    """Frische Sitzung mit eigener Ablage; geloeschte PDFs landen nicht im echten Papierkorb."""
    monkeypatch.setitem(cfg.config, "base_dir", str(tmp_path / "Belege"))
    monkeypatch.setattr(filing, "trash", lambda path: os.path.exists(path) and os.remove(path))
    session.receipts.clear()
    session.scans.clear()
    yield tmp_path / "Belege"
    wait_for_analysis()
    session.receipts.clear()
    session.scans.clear()


def wait_for_analysis(timeout=20):
    end = time.time() + timeout
    while any(r["status"] == "analyzing" for r in session.receipts):
        assert time.time() < end, "Analyse wurde nicht fertig"
        time.sleep(0.05)
