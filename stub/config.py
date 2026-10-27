"""Einstellungen, Ablageorte und die gemeinsame Sperre fuer Sitzung und Einstellungen."""
import json
import os
import threading
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
STATIC = PACKAGE / "static"
# Einstellungen und Arbeitskopien liegen beim Nutzer, nicht im Code (STUB_HOME z.B. fuer Tests)
HOME = Path(os.environ.get("STUB_HOME") or Path.home() / "Library" / "Application Support" / "Stub")
WORK = HOME / "work"
CONFIG_FILE = HOME / "config.json"
PORT = int(os.environ.get("STUB_PORT") or 8737)

IDLE_EXIT = 15 * 60  # Sekunden ohne offenes Browserfenster, dann beendet sich der Dienst


DEFAULTS = {
    "base_dir": str(Path.home() / "Documents" / "Belege"),
    "scanner": "",        # leer: beim ersten Scan wird im Netz gesucht
    "scanner_name": "",
    "known": [],          # zuletzt benutzte Scanner (z.B. daheim, Buero), neueste zuerst
    "auto_switch": True,  # nicht erreichbar -> anderen Scanner im Netz suchen
    "dpi": 300,
    "color": True,
    "ki": True,      # Benennung per Claude; sonst einfache Mustererkennung
    "multi": False,  # mehrere Belege auf dem Glas automatisch trennen
}


lock = threading.RLock()       # schuetzt Belege der Sitzung und config


EMPTY_FIELDS = {"date": "", "merchant": "", "kind": "", "amount": "", "note": ""}


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text()))
        except ValueError:
            pass
    return cfg


def save_config():
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))


config = load_config()
