import csv

import pymupdf
from PIL import Image

from stub import filing


def rec_with(fields, pdf):
    return {"fields": dict({"date": "", "merchant": "", "kind": "", "amount": "", "note": ""}, **fields),
            "pdf": str(pdf)}


def test_clean_removes_characters_finder_dislikes():
    assert filing.clean('Müller/Söhne: "Bau*markt"?') == "Müller-Söhne-Bau-markt"


def test_filename_from_fields(tmp_path):
    rec = rec_with({"date": "2026-10-09", "merchant": "Tankstelle am See", "kind": "Tanken", "amount": "71.70 €"},
                   tmp_path / "x.pdf")
    assert filing.filename_for(rec) == "2026-10-09_Tankstelle-am-See_Tanken_71,70EUR"
    assert filing.filename_for(rec_with({}, tmp_path / "x.pdf")) == "ohne-Datum_Beleg"


def test_daily_list_is_written_and_kept_in_sync(tmp_path):
    day = tmp_path / "2026-10-27"
    day.mkdir()
    pdf = day / "a.pdf"
    pdf.write_bytes(b"%PDF")
    filing.update_list(day, rec_with({"date": "2026-10-14", "merchant": "Café", "amount": "22,90",
                                      "note": "Anlass; Gäste"}, pdf))
    csv_path = tmp_path / "2026-10-27_Belegliste.csv"
    rows = list(csv.reader(open(csv_path, encoding="utf-8-sig"), delimiter=";"))
    assert rows == [["Belegdatum", "Händler", "Art", "Betrag", "Notiz", "Datei"],
                    ["14.10.2026", "Café", "", "22,90", "Anlass; Gäste", "a.pdf"]]
    pdf.unlink()
    filing.update_list(day)
    assert not csv_path.exists()  # letzte Datei weg -> Liste weg


def test_rename_follows_fields_without_overwriting(tmp_path):
    day = tmp_path / "2026-10-27"
    day.mkdir()
    (day / "2026-10-07_Papier-&-Co.pdf").write_bytes(b"belegt")
    pdf = day / "Beleg_1.pdf"
    pdf.write_bytes(b"%PDF")
    rec = rec_with({"date": "2026-10-07", "merchant": "Papier & Co"}, pdf)
    filing.rename(rec)
    assert rec["pdf"].endswith("2026-10-07_Papier-&-Co_2.pdf")
    assert (day / "2026-10-07_Papier-&-Co.pdf").read_bytes() == b"belegt"


def test_pdf_gets_invisible_searchable_text(tmp_path):
    page = tmp_path / "seite.jpg"
    Image.new("RGB", (600, 900), "white").save(page)
    rec = {"pages": [str(page)], "dpi": 300, "pdf": str(tmp_path / "beleg.pdf"),
           "boxes": [[(0.1, 0.8, 0.6, 0.04, "Lindenblatt"), (0.1, 0.5, 0.3, 0.04, "22,90")]]}
    filing.write_pdf(rec)
    doc = pymupdf.open(rec["pdf"])
    assert round(doc[0].rect.width) == 144  # 600 px bei 300 dpi = 2 Zoll = 144 pt
    text = doc[0].get_text()
    assert "Lindenblatt" in text and "22,90" in text
