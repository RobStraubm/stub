"""Belege dieser Sitzung: scannen, analysieren, neu zuschneiden."""
import datetime as dt
import os
import threading
import time
from pathlib import Path

from . import analysis, filing, regions, scanner
from .config import EMPTY_FIELDS, WORK, config, lock

scan_lock = threading.Lock()   # nur ein Scan gleichzeitig


receipts = []                  # Belege dieser Sitzung, neueste zuletzt


scans = {}                     # Rohscans dieser Sitzung: stamp -> {raw, dpi, w, h, auto, day}


next_id = 1


page_seq = int(time.time()) % 100000 * 100  # fuer eindeutige Seitenbild-Namen


scanning = False


def analyse(rec, version):
    with lock:
        pages = list(rec["pages"])
    results = [analysis.run_ocr(p) for p in pages]
    text = "\n".join(t for t, _, _ in results).strip()
    warn = []
    if not all(ok for _, _, ok in results):
        warn.append("Texterkennung fehlgeschlagen – das PDF ist nicht durchsuchbar.")
    fields = analysis.analyse_ki(pages, text) if config["ki"] else None
    if config["ki"] and not fields:
        warn.append("Claude-Analyse fehlgeschlagen – nur einfache Mustererkennung. „Neu analysieren“ probieren.")
    fields = fields or analysis.analyse_simple(text)
    with lock:
        if rec.get("deleted") or rec["version"] != version:
            return  # inzwischen geloescht, neu zugeschnitten oder neue Seite angehaengt
        rec["ocr"] = text
        rec["boxes"] = [b for _, b, _ in results]
        rec["warn"] = warn
        filing.write_pdf(rec)  # jetzt mit unsichtbarer Textebene -> durchsuchbar
        if not rec["edited"]:
            rec["fields"] = fields
        filing.rename(rec)
        rec["status"] = "ready"


def page_name(stamp):
    """Eindeutiger Dateiname fuer ein Seitenbild aus diesem Rohscan."""
    global page_seq
    page_seq += 1
    return str(WORK / f"{stamp}-{page_seq}.jpg")


def new_receipt(scan_id, page, box, edge, empty=False):
    """Legt einen Beleg mit einer Seite aus dem Rohscan scan_id an (unter lock)."""
    global next_id
    scan = scans[scan_id]
    rec = {"id": next_id, "pages": [page], "src": [{"scan": scan_id, "box": list(box)}],
           "boxes": [], "dpi": scan["dpi"], "edited": False, "confirmed": False,
           "empty": empty, "edge": edge, "warn": [], "fields": dict(EMPTY_FIELDS), "ocr": "",
           "version": 0, "status": "analyzing",
           "pdf": str(scan["day"] / f"Beleg_{Path(page).stem}.pdf")}
    next_id += 1
    receipts.append(rec)
    return rec


def start_analysis(recs):
    """Schreibt die PDFs vorab (noch ohne Text) und startet die Analyse (unter lock)."""
    for rec in recs:
        rec["version"] += 1
        rec["status"] = "analyzing"
        filing.write_pdf(rec)
        filing.update_list(Path(rec["pdf"]).parent, rec)
        threading.Thread(target=analyse, args=(rec, rec["version"]), daemon=True).start()


def remove_receipt(rec):
    """Beleg verwerfen: PDF in den Papierkorb, Seitenbilder loeschen (unter lock)."""
    rec["deleted"] = True
    receipts.remove(rec)
    pdf = Path(rec["pdf"])
    filing.trash(pdf)
    filing.update_list(pdf.parent, old_name=pdf.name)
    for p in rec["pages"]:
        Path(p).unlink(missing_ok=True)


def do_scan(append_to=None):
    global scanning
    if not scan_lock.acquire(blocking=False):
        raise scanner.ScanError("Es läuft bereits ein Scan.")
    scanning = True
    try:
        WORK.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dpi = int(config["dpi"])
        raw = WORK / f"{stamp}-roh.jpg"  # bleibt fuer das Zuschneiden liegen (3 Tage)
        info = scanner.ensure_scanner()
        dpi = scanner.escl_scan(raw, dpi) or dpi
        with lock:  # erfolgreich benutzten Scanner merken, Namen notfalls vom Geraet
            scanner.remember_scanner(config["scanner"], config.get("scanner_name")
                             or scanner.capabilities(scanner.scanner_url(config["scanner"]))["model"])
        with lock:
            target = next((r for r in receipts if r["id"] == append_to), None) if append_to else None
        img, areas, found = regions.split_scan(raw, dpi, config["multi"] and not target)
        day = Path(config["base_dir"]).expanduser() / dt.date.today().isoformat()
        with lock:
            scans[stamp] = {"raw": str(raw), "dpi": dpi, "w": img.width, "h": img.height,
                            "auto": [list(b) for b, _ in areas],
                            "day": Path(target["pdf"]).parent if target else day}
            pages = []
            for box, _ in areas:
                page = page_name(stamp)
                regions.crop_page(img, box, page)
                pages.append(page)
            if target:
                target["pages"].append(pages[0])
                target["src"].append({"scan": stamp, "box": list(areas[0][0])})
                target["edge"] = target["edge"] or areas[0][1]
                recs = [target]
            else:
                for r in receipts:
                    r["confirmed"] = True  # naechster Scan = vorherige Belege akzeptiert
                day.mkdir(parents=True, exist_ok=True)
                recs = [new_receipt(stamp, page, box, edge, not found)
                        for page, (box, edge) in zip(pages, areas, strict=True)]
            start_analysis(recs)
        return recs, info
    finally:
        scanning = False
        scan_lock.release()


def scan_slots(stamp):
    """Alle Seiten, die aus diesem Rohscan stammen: [(Beleg, Seitenindex)] (unter lock)."""
    return [(r, i) for r in receipts for i, s in enumerate(r["src"]) if s["scan"] == stamp]


def recrop(stamp, boxes):
    """Schneidet einen Rohscan nach den vom Nutzer gezogenen Bereichen neu zu.

    Jeder Bereich wird ein Beleg. Bisherige Belege aus diesem Scan werden dem Bereich
    mit der groessten Ueberlappung zugeordnet und behalten ihre Angaben und weiteren Seiten;
    Belege ohne Bereich werden verworfen, neue Bereiche werden neue Belege.
    """
    with lock:
        scan = scans.get(stamp)
        if not scan or not os.path.exists(scan["raw"]):
            raise scanner.ScanError("Der Originalscan ist nicht mehr vorhanden.")
        w, h = scan["w"], scan["h"]
        clean_boxes = []
        for b in boxes:
            x0, y0, x1, y1 = (int(round(float(v))) for v in b)
            x0, x1 = sorted((max(0, min(w, x0)), max(0, min(w, x1))))
            y0, y1 = sorted((max(0, min(h, y0)), max(0, min(h, y1))))
            if x1 - x0 >= 50 and y1 - y0 >= 50:
                clean_boxes.append((x0, y0, x1, y1))
        if not clean_boxes:
            raise scanner.ScanError("Bitte mindestens einen Bereich markieren.")
        slots = scan_slots(stamp)
        if any(i > 0 for _, i in slots) and len(clean_boxes) != 1:
            raise scanner.ScanError("Bei einer angehängten Seite bitte genau einen Bereich markieren.")

        def overlap(a, b):
            return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))

        pairs = sorted(((overlap(r["src"][i]["box"], b), si, bi)
                        for si, (r, i) in enumerate(slots) for bi, b in enumerate(clean_boxes)), reverse=True)
        match, used = {}, set()
        for ov, si, bi in pairs:
            if ov > 0 and si not in match and bi not in used:
                match[si] = bi
                used.add(bi)
        img = regions.open_scan(scan["raw"])
        changed, result = [], {}
        for si, (rec, i) in enumerate(slots):
            if si not in match:
                remove_receipt(rec)
                continue
            box = clean_boxes[match[si]]
            result[match[si]] = rec
            if list(box) == rec["src"][i]["box"]:
                continue
            page = page_name(stamp)
            regions.crop_page(img, box, page)
            Path(rec["pages"][i]).unlink(missing_ok=True)
            rec["pages"][i] = page
            rec["src"][i]["box"] = list(box)
            rec["edge"] = rec["empty"] = False  # vom Nutzer selbst zugeschnitten
            rec["ocr"], rec["boxes"] = "", []
            changed.append(rec)
        scan["day"].mkdir(parents=True, exist_ok=True)
        for bi, box in enumerate(clean_boxes):
            if bi not in result:
                page = page_name(stamp)
                regions.crop_page(img, box, page)
                result[bi] = new_receipt(stamp, page, box, False)
                changed.append(result[bi])
        start_analysis(changed)
        return [result[bi]["id"] for bi in range(len(clean_boxes))]


def public(rec):
    return {"id": rec["id"], "fields": rec["fields"], "status": rec["status"],
            "confirmed": rec["confirmed"], "pages": len(rec["pages"]), "version": rec["version"],
            "file": Path(rec["pdf"]).name, "folder": str(Path(rec["pdf"]).parent),
            "empty": rec.get("empty", False), "ocr": rec["ocr"],
            "warn": rec["warn"] + (["Der Beleg reicht bis an den Rand der Glasplatte – vielleicht ist etwas"
                                    " abgeschnitten. Prüfen und ggf. mit etwas Abstand neu scannen."]
                                   if rec["edge"] else [])}
