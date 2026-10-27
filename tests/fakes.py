"""Erfundene Kassenbons, eine Glasplatte zum Auflegen und ein nachgebauter eSCL-Scanner.

Alles hier ist synthetisch: Haendler, Namen und Betraege sind ausgedacht. Die Tests und die
Bildschirmfotos im README kommen so ohne echte Belege aus.
"""
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DPI = 300
MM = DPI / 25.4
GLASS = (2550, 3508)  # A4 bei 300 dpi
PAPER, LID = 253, 246

MONO = ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
HAND = ["/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
        "/System/Library/Fonts/Noteworthy.ttc", "/System/Library/Fonts/MarkerFelt.ttc"]


def font(candidates, size):
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def receipt(lines, width_mm=72, ink=45, seed=0):
    """Zeichnet einen Bon.

    lines: Text, ("gap", mm), ("rule",), ("big", Text), ("hand", Text) oder ("lr", links, rechts).
    ink: Grauwert des Drucks, 45 = frisch, ab etwa 170 = stark verblasster Thermodruck.
    """
    rnd = random.Random(seed)
    width = int(width_mm * MM)
    mono, big, hand = font(MONO, 30), font(MONO, 52), font(HAND, 54)
    pad = int(5 * MM)
    ops, y = [], pad
    for line in lines:
        kind, *args = line if isinstance(line, tuple) else ("text", line)
        if kind == "gap":
            y += int(args[0] * MM)
            continue
        if kind == "rule":
            ops.append(("rule", y + 10))
            y += 26
            continue
        f = {"big": big, "hand": hand}.get(kind, mono)
        ops.append((kind, y, args, f))
        y += int(f.size * 1.35)
    img = Image.new("L", (width, y + pad), PAPER)
    d = ImageDraw.Draw(img)
    for op in ops:
        if op[0] == "rule":
            for x in range(pad, width - pad, 16):
                d.line((x, op[1], x + 9, op[1]), fill=ink, width=2)
            continue
        kind, top, args, f = op
        if kind == "lr":
            d.text((pad, top), args[0], font=f, fill=ink)
            d.text((width - pad, top), args[1], font=f, fill=ink, anchor="ra")
        elif kind == "hand":
            d.text((pad + rnd.randint(0, 30), top), args[0], font=f, fill=(70 if ink < 120 else ink))
        else:
            d.text((width // 2, top), args[0], font=f, fill=ink, anchor="ma")
    return img


def glass(placed, dust=40, seed=1):
    """Legt Bons auf die Glasplatte: placed = [(Bild, (x_mm, y_mm))]. Liefert den Rohscan als RGB-Bild."""
    rnd = random.Random(seed)
    page = Image.new("L", GLASS, LID)
    for img, (x, y) in placed:
        page.paste(img, (int(x * MM), int(y * MM)))
    d = ImageDraw.Draw(page)
    for _ in range(dust):  # Staub und Fusseln auf dem Glas
        x, y, r = rnd.randint(60, GLASS[0] - 60), rnd.randint(60, GLASS[1] - 60), rnd.randint(1, 3)
        d.ellipse((x, y, x + r, y + r), fill=rnd.randint(60, 140))
    return page.convert("RGB")


CAFE = [("big", "Café Lindenblatt"), "Marktstraße 12", "12345 Musterstadt", ("gap", 4),
        ("lr", "14.10.2026", "12:41"), ("rule",),
        ("lr", "2 Flat White", "9,80"), ("lr", "1 Quiche Lorraine", "8,90"), ("lr", "1 Zitronenkuchen", "4,20"),
        ("rule",), ("lr", "SUMME EUR", "22,90"), ("lr", "MwSt 19% auf 19,24", "3,66"), ("gap", 6),
        "Bewirtungsaufwand-Angaben", "(§ 4 Abs. 5 Ziff. 2 EStG)", ("gap", 3),
        "Bewirtete Personen:", ("hand", "Anna Berger, Jonas Weil"), ("gap", 2),
        "Anlass der Bewirtung:", ("hand", "Projektplanung Q4"), ("gap", 8), "Vielen Dank!"]

FUEL = [("big", "Tankstelle am See"), "Uferweg 3 · 12345 Musterstadt", ("gap", 4),
        ("lr", "09.10.2026", "18:05"), ("rule",),
        ("lr", "Super E10  41,23 l", ""), ("lr", "  x 1,739 EUR/l", "71,70"), ("rule",),
        ("lr", "GESAMT EUR", "71,70"), ("lr", "darin MwSt 19%", "11,45"), ("gap", 22),
        "Kartenzahlung", "Beleg-Nr. 0815", ("gap", 4), "Gute Fahrt!"]

OFFICE = [("big", "Papier & Co"), "Bahnhofstr. 5", ("gap", 3), ("lr", "07.10.2026", "09:12"), ("rule",),
          ("lr", "Ordner A4 breit", "3,49"), ("lr", "Briefumschläge 50", "4,99"), ("rule",),
          ("lr", "SUMME", "8,48"), ("gap", 3), "Danke für Ihren Einkauf"]


class FakeScanner:
    """Minimaler eSCL-Scanner auf 127.0.0.1: Status, Faehigkeiten, Scanauftrag, Dokument."""

    def __init__(self, image_path, status=200, model="Testscanner X1", dpis=(150, 300, 600)):
        self.image_path, self.status, self.model, self.dpis = image_path, status, model, dpis
        self.posted = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, body=b"", headers=()):
                self.send_response(code)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.endswith("/ScannerStatus"):
                    return self.reply(fake.status, b"<scan:ScannerStatus/>")
                if self.path.endswith("/ScannerCapabilities"):
                    return self.reply(200, fake.capabilities())
                if self.path == "/eSCL/ScanJobs/42/NextDocument":
                    return self.reply(200, Path(fake.image_path).read_bytes())
                self.reply(404)

            def do_POST(self):
                fake.posted.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
                # absichtlich ein fremder Host: der Client muss den eigenen behalten
                self.reply(201, headers=[("Location", "http://192.0.2.9:9/eSCL/ScanJobs/42")])

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addr = f"http://127.0.0.1:{self.server.server_port}/eSCL"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def capabilities(self):
        res = "".join(f"<scan:DiscreteResolution><scan:XResolution>{d}</scan:XResolution>"
                      f"<scan:YResolution>{d}</scan:YResolution></scan:DiscreteResolution>" for d in self.dpis)
        return f"""<?xml version="1.0"?>
<scan:ScannerCapabilities xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
                          xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <pwg:MakeAndModel>{self.model}</pwg:MakeAndModel>
  <scan:Platen><scan:PlatenInputCaps>
    <scan:MaxWidth>2480</scan:MaxWidth><scan:MaxHeight>3507</scan:MaxHeight>
    <scan:SettingProfiles><scan:SettingProfile><scan:SupportedResolutions><scan:DiscreteResolutions>
      {res}
    </scan:DiscreteResolutions></scan:SupportedResolutions></scan:SettingProfile></scan:SettingProfiles>
  </scan:PlatenInputCaps></scan:Platen>
</scan:ScannerCapabilities>""".encode()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
