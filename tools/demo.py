"""Stub ohne echten Scanner ausprobieren.

Startet einen nachgebauten Netzwerkscanner, auf dessen Glas drei erfundene Bons liegen, und
Stub selbst mit eigener Ablage in einem Wegwerf-Ordner. Der ganze Ablauf ist echt: Suche,
eSCL-Scan, Zuschnitt, Texterkennung, Analyse (mit Claude, falls angemeldet) und Ablage.

    .venv/bin/python -m tools.demo
"""
import os
import sys
import tempfile
from pathlib import Path

home = Path(tempfile.mkdtemp(prefix="stub-demo-"))
os.environ["STUB_HOME"] = str(home)
os.environ.setdefault("STUB_PORT", "8740")

from stub import config as cfg  # noqa: E402
from stub import scanner, server  # noqa: E402
from tests.fakes import CAFE, FUEL, OFFICE, FakeScanner, glass, receipt  # noqa: E402

image = home / "glas.jpg"
glass([(receipt(CAFE), (20, 20)), (receipt(FUEL, ink=165, seed=2), (115, 20)),
       (receipt(OFFICE, seed=3), (115, 200))]).save(image, quality=92)
fake = FakeScanner(image, model="Demo-Scanner (simuliert)")
scanner.discover = lambda wait=3.0: ([{"name": "Demo-Scanner (simuliert)", "addr": fake.addr}], [])
cfg.config.update(base_dir=str(home / "Belege"), multi=True, ki="--ohne-claude" not in sys.argv)
print(f"Demo-Ablage: {home / 'Belege'}")
server.main()
