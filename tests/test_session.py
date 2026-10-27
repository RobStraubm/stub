import shutil
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from stub import analysis, scanner, session
from stub import config as cfg
from tests.conftest import wait_for_analysis
from tests.fakes import CAFE, FUEL, MM, glass, receipt

OCR = {"cafe": ("Café Lindenblatt\n14.10.2026\nSUMME EUR 22,90", [], True),
       "fuel": ("Tankstelle am See\n09.10.2026\nGESAMT EUR 71,70", [], True)}


@pytest.fixture
def scan_env(ablage, tmp_path, monkeypatch):
    """Ein Scan mit Cafe- und Tankbeleg nebeneinander, ohne Netz und ohne Claude."""
    raw = tmp_path / "glas.jpg"
    glass([(receipt(CAFE), (20, 20)), (receipt(FUEL, ink=150, seed=2), (115, 20))]).save(raw)
    monkeypatch.setitem(cfg.config, "multi", True)
    monkeypatch.setitem(cfg.config, "ki", False)
    monkeypatch.setattr(scanner, "ensure_scanner", lambda: None)
    monkeypatch.setattr(scanner, "escl_scan", lambda dest, dpi: (shutil.copy(raw, dest), dpi)[1])
    monkeypatch.setattr(scanner, "capabilities", lambda base: {"model": "Testscanner X1"})
    monkeypatch.setattr(scanner, "remember_scanner", lambda addr, name: None)
    # Texterkennung nach Bildhoehe zuordnen: der Cafe-Bon ist laenger als der Tankbeleg
    monkeypatch.setattr(analysis, "run_ocr", lambda page: OCR["cafe" if _height_mm(page) > 90 else "fuel"])
    return ablage


def _height_mm(page):
    with Image.open(page) as im:
        return im.height / MM


def test_scan_files_two_named_pdfs_and_a_list(scan_env):
    recs, info = session.do_scan()
    wait_for_analysis()
    assert info is None and len(recs) == 2
    names = sorted(Path(r["pdf"]).name for r in recs)
    assert names == ["2026-10-09_Tankstelle-am-See_71,70EUR.pdf", "2026-10-14_Café-Lindenblatt_22,90EUR.pdf"]
    day = Path(recs[0]["pdf"]).parent
    assert (day.parent / f"{day.name}_Belegliste.csv").read_text(encoding="utf-8-sig").count("\n") == 3
    assert all(r["warn"] == [] for r in recs)


def test_failed_text_recognition_is_reported(scan_env, monkeypatch):
    monkeypatch.setattr(analysis, "run_ocr", lambda page: ("", [], False))
    recs, _ = session.do_scan()
    wait_for_analysis()
    assert all("Texterkennung fehlgeschlagen" in r["warn"][0] for r in recs)


def test_recrop_keeps_matched_receipts_and_drops_the_rest(scan_env):
    recs, _ = session.do_scan()
    wait_for_analysis()
    stamp = recs[0]["src"][0]["scan"]
    cafe = recs[0]
    cafe["fields"]["note"] = "von Hand ergänzt"
    cafe["edited"] = True
    x0, y0, x1, y1 = cafe["src"][0]["box"]
    ids = session.recrop(stamp, [[x0, y0, x1, y1 - 300]])  # nur den Cafe-Bon, unten etwas kuerzer
    wait_for_analysis()
    assert ids == [cafe["id"]] and session.receipts == [cafe]
    assert cafe["fields"]["note"] == "von Hand ergänzt"  # Angaben bleiben beim Zuschneiden erhalten
    with Image.open(cafe["pages"][0]) as page:
        assert page.size == (x1 - x0, y1 - 300 - y0)
    assert pymupdf.open(cafe["pdf"])[0].rect.height == pytest.approx((y1 - 300 - y0) * 72 / 300, abs=1)


def test_recrop_into_one_receipt_and_new_areas(scan_env):
    recs, _ = session.do_scan()
    wait_for_analysis()
    stamp = recs[0]["src"][0]["scan"]
    scan = session.scans[stamp]
    ids = session.recrop(stamp, [[0, 0, scan["w"], scan["h"]]])
    wait_for_analysis()
    assert len(ids) == 1 and len(session.receipts) == 1
    ids = session.recrop(stamp, [[0, 0, 1200, 1500], [1300, 0, 2400, 1500], [0, 2000, 900, 3000]])
    wait_for_analysis()
    assert len(ids) == 3 and len(session.receipts) == 3


def test_recrop_rejects_empty_or_tiny_areas(scan_env):
    recs, _ = session.do_scan()
    stamp = recs[0]["src"][0]["scan"]
    with pytest.raises(scanner.ScanError, match="mindestens einen Bereich"):
        session.recrop(stamp, [[10, 10, 20, 20]])
    with pytest.raises(scanner.ScanError, match="nicht mehr vorhanden"):
        session.recrop("19990101-000000", [[0, 0, 500, 500]])


def test_appended_page_needs_exactly_one_area(scan_env, monkeypatch):
    recs, _ = session.do_scan()
    wait_for_analysis()
    monkeypatch.setitem(cfg.config, "multi", False)
    (rec,), _ = session.do_scan(append_to=recs[0]["id"])
    wait_for_analysis()
    assert len(rec["pages"]) == 2
    stamp = rec["src"][1]["scan"]
    with pytest.raises(scanner.ScanError, match="genau einen Bereich"):
        session.recrop(stamp, [[0, 0, 900, 900], [1000, 0, 1900, 900]])


def test_delete_removes_pdf_and_list_entry(scan_env):
    recs, _ = session.do_scan()
    wait_for_analysis()
    pdf = Path(recs[0]["pdf"])
    session.remove_receipt(recs[0])
    assert not pdf.exists() and len(session.receipts) == 1
