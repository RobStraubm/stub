"""Lokaler HTTP-Server (127.0.0.1) fuer die Oberflaeche im Browser."""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import filing, scanner, session
from .config import (
    EMPTY_FIELDS,
    IDLE_EXIT,
    PORT,
    STATIC,
    WORK,
    config,
    lock,
    save_config,
)

last_seen = time.time()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global last_seen
        last_seen = time.time()
        if self.path == "/":
            return self.send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/icon.png" and (STATIC / "icon.png").exists():
            return self.send(200, (STATIC / "icon.png").read_bytes(), "image/png")
        if self.path.startswith("/api/state"):
            with lock:
                return self.send(200, {"config": config, "scanning": session.scanning,
                                       "scanner_label": scanner.scanner_label(),
                                       "today": dt.date.today().isoformat(),
                                       "receipts": [session.public(r) for r in session.receipts]})
        m = re.match(r"/raw/([\d-]+)(\?|$)", self.path)
        if m:
            with lock:
                scan = session.scans.get(m.group(1))
            if scan and os.path.exists(scan["raw"]):
                return self.send(200, Path(scan["raw"]).read_bytes(), "image/jpeg")
        m = re.match(r"/img/(\d+)/(\d+)", self.path)
        if m:
            with lock:
                rec = next((r for r in session.receipts if r["id"] == int(m.group(1))), None)
                n = int(m.group(2))
                p = rec["pages"][n] if rec and n < len(rec["pages"]) else None
            if p and os.path.exists(p):
                return self.send(200, Path(p).read_bytes(), "image/jpeg")
        self.send(404, {"error": "nicht gefunden"})

    def do_POST(self):
        global last_seen
        last_seen = time.time()
        # nur Anfragen von der eigenen Seite annehmen
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self.send(403, {"error": "verboten"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            data = {}
        try:
            self.send(200, self.route(self.path, data))
        except scanner.ScanError as e:
            self.send(200, {"error": str(e), "choose": isinstance(e, scanner.ChooseScanner)})
        except Exception as e:  # Fehler im Browser anzeigen statt Verbindung abbrechen
            self.send(200, {"error": f"{type(e).__name__}: {e}"})

    def route(self, path, data):
        rec = None
        if "id" in data:
            with lock:
                rec = next((r for r in session.receipts if r["id"] == data["id"]), None)
            if not rec:
                return {"error": "Beleg nicht gefunden."}

        if path == "/api/scan":
            recs, info = session.do_scan(data.get("append_to"))
            return {"ids": [r["id"] for r in recs], "info": info}

        if path == "/api/discover":
            scanners, off = scanner.discover()
            with lock:
                known = {scanner.scanner_url(k["addr"]): k["name"] for k in config.get("known", [])}
                cur = scanner.scanner_url(config["scanner"])
                listed = {scanner.scanner_url(sc["addr"]) for sc in scanners}
                # bekannte, gerade nicht sichtbare Scanner (z.B. der daheim) bleiben waehlbar
                rows = [dict(sc, found=True) for sc in scanners] + [
                    {"name": n or scanner.scanner_label(a), "addr": a, "found": False}
                    for a, n in known.items() if a not in listed]
                for row in rows:
                    row["current"] = scanner.scanner_url(row["addr"]) == cur
                    row["known"] = scanner.scanner_url(row["addr"]) in known
            return {"scanners": rows, "off": off}

        if path == "/api/update" and rec:
            with lock:
                for k in EMPTY_FIELDS:
                    if k in data:
                        rec["fields"][k] = str(data[k]).strip()
                rec["edited"] = True
                filing.rename(rec)
                return session.public(rec)

        if path == "/api/confirm" and rec:
            with lock:
                rec["confirmed"] = True
                return session.public(rec)

        if path == "/api/reanalyse" and rec:
            with lock:
                rec["edited"] = False
                rec["status"] = "analyzing"
                rec["version"] += 1
                v = rec["version"]
            threading.Thread(target=session.analyse, args=(rec, v), daemon=True).start()
            return session.public(rec)

        if path == "/api/delete" and rec:
            with lock:
                session.remove_receipt(rec)
            return {"ok": True}

        if path == "/api/crop_info" and rec:
            with lock:
                n = int(data.get("page", 0))
                if not 0 <= n < len(rec["src"]):
                    return {"error": "Seite nicht gefunden."}
                stamp = rec["src"][n]["scan"]
                scan = session.scans.get(stamp)
                if not scan or not os.path.exists(scan["raw"]):
                    return {"error": "Der Originalscan ist nicht mehr vorhanden."}
                slots = session.scan_slots(stamp)
                return {"stamp": stamp, "w": scan["w"], "h": scan["h"], "auto": scan["auto"],
                        "boxes": [r["src"][i]["box"] for r, i in slots],
                        "single": any(i > 0 for _, i in slots)}

        if path == "/api/recrop":
            return {"ids": session.recrop(str(data.get("stamp", "")),
                                          data.get("boxes") or [])}

        if path == "/api/config":
            with lock:
                if data.get("base_dir"):
                    config["base_dir"] = str(data["base_dir"]).strip()
                addr = str(data.get("scanner") or "").strip()
                if addr and scanner.scanner_url(addr) != scanner.scanner_url(config["scanner"]):
                    known = {scanner.scanner_url(k["addr"]): k["name"] for k in config.get("known", [])}
                    name = data.get("scanner_name") or known.get(scanner.scanner_url(addr), "")
                    scanner.remember_scanner(addr, str(name))
                if "dpi" in data and int(data["dpi"]) in (150, 200, 300, 400, 600):
                    config["dpi"] = int(data["dpi"])
                for k in ("color", "ki", "multi", "auto_switch"):
                    if k in data:
                        config[k] = bool(data[k])
                save_config()
            return config

        if path == "/api/choose_folder":
            r = subprocess.run(["osascript", "-e", 'tell application "System Events" to activate',
                                "-e", 'POSIX path of (choose folder with prompt "Ablageordner für Belege wählen")'],
                               capture_output=True, text=True)
            p = r.stdout.strip()
            if p:
                with lock:
                    config["base_dir"] = p.rstrip("/")
                    save_config()
            return config

        if path == "/api/open_folder":
            day = Path(config["base_dir"]).expanduser() / dt.date.today().isoformat()
            target = day if day.exists() else Path(config["base_dir"]).expanduser()
            target.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(target)])
            return {"ok": True}

        if path == "/api/quit":
            threading.Timer(0.3, os._exit, [0]).start()
            return {"ok": True}

        return {"error": "Unbekannte Aktion."}


def idle_watchdog():
    """Beendet den Dienst, wenn laenger kein Browserfenster mehr offen ist."""
    while True:
        time.sleep(30)
        if not session.scanning and time.time() - last_seen > IDLE_EXIT:
            os._exit(0)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    for p in WORK.glob("*.jpg"):  # alte Arbeitskopien aufraeumen
        if time.time() - p.stat().st_mtime > 3 * 86400:
            p.unlink(missing_ok=True)
    url = f"http://127.0.0.1:{PORT}"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print("Stub läuft schon – öffne Browser.")
        webbrowser.open(url)
        return
    print(f"Stub läuft: {url}   (Beenden mit Ctrl+C)")
    threading.Thread(target=idle_watchdog, daemon=True).start()
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
