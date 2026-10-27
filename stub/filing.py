"""Ablage: durchsuchbare PDFs, Dateinamen und die Belegliste (CSV) je Scantag."""
import csv
import json
import os
import re
import shutil
import time
from pathlib import Path

import pymupdf
from PIL import Image


def clean(s, maxlen=40):
    s = re.sub(r'[/\\:*?"<>|;\n\r\t]', " ", s or "")
    s = re.sub(r"\s+", "-", s.strip())
    return s[:maxlen].strip("-.")


def filename_for(rec):
    f = rec["fields"]
    parts = [f["date"] or "ohne-Datum", clean(f["merchant"]) or "Beleg", clean(f["kind"], 25)]
    amount = re.sub(r"[^\d,]", "", (f["amount"] or "").replace(".", ","))
    if amount:
        parts.append(amount + "EUR")
    return "_".join(p for p in parts if p)


def rename(rec):
    """Benennt das PDF passend zu den Feldern um (ohne Vorhandenes zu ueberschreiben)."""
    old = Path(rec["pdf"])
    stem = filename_for(rec)
    new = old.with_name(stem + ".pdf")
    n = 2
    while new != old and new.exists():
        new = old.with_name(f"{stem}_{n}.pdf")
        n += 1
    if new != old and old.exists():
        old.rename(new)
    rec["pdf"] = str(new)
    update_list(new.parent, rec, old_name=old.name)


def write_pdf(rec):
    """Schreibt das PDF: Seitenbilder plus unsichtbarer OCR-Text zum Suchen/Kopieren."""
    dpi = rec["dpi"]
    doc = pymupdf.open()
    for i, p in enumerate(rec["pages"]):
        with Image.open(p) as im:
            pw, ph = im.width * 72 / dpi, im.height * 72 / dpi
        page = doc.new_page(width=pw, height=ph)
        page.insert_image(page.rect, filename=p)
        for x, y, w, h, s in (rec["boxes"][i] if i < len(rec["boxes"]) else []):
            try:
                unit = pymupdf.get_text_length(s, fontname="helv", fontsize=1)
                if unit <= 0:
                    continue
                size = max(2, min(w * pw / unit, h * ph * 1.3))
                page.insert_text((x * pw, (1 - y) * ph - h * ph * 0.2), s,
                                 fontname="helv", fontsize=size, render_mode=3)
            except Exception:
                pass  # einzelne nicht darstellbare Zeile ueberspringen
    tmp = rec["pdf"] + ".tmp"
    doc.save(tmp, deflate=True)
    doc.close()
    os.replace(tmp, rec["pdf"])


def update_list(folder, rec=None, old_name=None):
    """Pflegt die Belegliste des Tages: <Ablage>/<Datum>_Belegliste.csv."""
    folder = Path(folder)
    idx_file = folder / ".belegliste.json"
    try:
        idx = json.loads(idx_file.read_text())
    except (OSError, ValueError):
        idx = {}
    if old_name:
        idx.pop(old_name, None)
    if rec and not rec.get("deleted"):
        idx[Path(rec["pdf"]).name] = dict(rec["fields"])
    idx = {k: v for k, v in idx.items() if (folder / k).exists()}
    idx_file.write_text(json.dumps(idx, indent=1, ensure_ascii=False))
    csv_path = folder.parent / f"{folder.name}_Belegliste.csv"
    if not idx:
        csv_path.unlink(missing_ok=True)
        return
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Belegdatum", "Händler", "Art", "Betrag", "Notiz", "Datei"])
        for name, f in sorted(idx.items(), key=lambda kv: (kv[1].get("date", ""), kv[0])):
            d = f.get("date", "")
            if d:
                d = ".".join(reversed(d.split("-")))
            w.writerow([d, f.get("merchant", ""), f.get("kind", ""), f.get("amount", ""),
                        f.get("note", ""), name])


def trash(path):
    p = Path(path)
    if p.exists():
        t = Path.home() / ".Trash" / p.name
        if t.exists():
            t = t.with_name(f"{p.stem}_{int(time.time())}{p.suffix}")
        shutil.move(str(p), str(t))
