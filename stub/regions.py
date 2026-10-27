"""Belege im Rohscan finden und zuschneiden."""
import numpy as np
from PIL import Image

from .config import config


def box_count(a, r):
    """Anzahl gesetzter Zellen im (2r+1)x(2r+1)-Fenster um jede Zelle."""
    k = 2 * r + 1
    c = np.pad(a.astype(np.int32), ((r + 1, r), (r + 1, r))).cumsum(0).cumsum(1)
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def find_regions(img, dpi, multi):
    """Liefert die bedruckten Bereiche des Scans als [(Pixel-Box mit Rand, liegt_am_Glasrand)].

    Die Maske nimmt je 4x4-Block das dunkelste Pixel und vergleicht es mit dem Papierweiss,
    damit auch duenner, verblasster Thermodruck und Kugelschreiber erhalten bleiben.
    multi=False: ein Bereich um alles. multi=True: getrennt an breiten weissen
    Luecken (XY-Schnitt), damit mehrere Belege einzeln herauskommen.
    """
    f = 4
    g = np.asarray(img.convert("L"), dtype=np.int16)
    gh, gw = g.shape[0] // f * f, g.shape[1] // f * f
    small = g[:gh, :gw].reshape(gh // f, f, gw // f, f).min(axis=(1, 3))
    paper = np.percentile(small, 90)
    a = box_count(small < paper - 40, 2) >= 5  # einzelne Staubkoerner fallen weg
    mm = dpi / 25.4 / f
    b = max(1, int(3 * mm))  # Schatten an den Glaskanten ignorieren
    a[:b] = a[-b:] = False
    a[:, :b] = a[:, -b:] = False

    def bbox(x0, y0, x1, y1):
        sub = a[y0:y1, x0:x1]
        cols, rows = np.flatnonzero(sub.any(axis=0)), np.flatnonzero(sub.any(axis=1))
        if not len(cols):
            return None
        return x0 + cols[0], y0 + rows[0], x0 + cols[-1] + 1, y0 + rows[-1] + 1

    def segments(profile, min_gap):
        idx = np.flatnonzero(profile)
        segs, start, prev = [], idx[0], idx[0]
        for i in idx[1:]:
            if i - prev > min_gap:
                segs.append((start, prev + 1))
                start = i
            prev = i
        return segs + [(start, prev + 1)]

    def cut(box):
        box = bbox(*box)
        if not box:
            return []
        x0, y0, x1, y1 = box
        sub = a[y0:y1, x0:x1]
        segs = segments(sub.any(axis=0), 10 * mm)   # nebeneinander: ab 10 mm Abstand
        if len(segs) > 1:
            return [r for s, e in segs for r in cut((x0 + s, y0, x0 + e, y1))]
        segs = segments(sub.any(axis=1), 30 * mm)   # uebereinander: ab 30 mm Abstand
        if len(segs) > 1:
            return [r for s, e in segs for r in cut((x0, y0 + s, x1, y0 + e))]
        return [box]

    h, w = a.shape
    # Kleinteile (Staub, Fusseln) fallen weg; im Einzelmodus ein Rahmen um alle Belege
    boxes = [r for r in cut((0, 0, w, h)) if r[2] - r[0] > 15 * mm and r[3] - r[1] > 10 * mm]
    if boxes and not multi:
        x0s, y0s, x1s, y1s = zip(*boxes, strict=True)
        boxes = [(min(x0s), min(y0s), max(x1s), max(y1s))]
    m, tol = int(5 * mm), b + int(2 * mm)
    return [((int(max(0, x0 - m) * f), int(max(0, y0 - m) * f),
              int(min(img.width, (x1 + m) * f)), int(min(img.height, (y1 + m) * f))),
             bool(x0 <= tol or y0 <= tol or x1 >= w - tol or y1 >= h - tol))
            for x0, y0, x1, y1 in boxes]


def crop_page(img, box, dest):
    img.crop(box).save(dest, "JPEG", quality=72, optimize=True)


def open_scan(path):
    img = Image.open(path)
    img.load()
    return img if config["color"] else img.convert("L")


def split_scan(raw, dpi, multi):
    """Sucht die Belege im Rohscan. Liefert ([(Box, am_Rand)], etwas_gefunden)."""
    img = open_scan(raw)
    regions = [r for r in find_regions(img, dpi, multi) if r[0][2] - r[0][0] > 50 and r[0][3] - r[0][1] > 50]
    return img, (regions or [((0, 0, img.width, img.height), False)]), bool(regions)
