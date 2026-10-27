import stat

from stub import analysis


def test_simple_pattern_matching():
    text = "Papier & Co\nBahnhofstr. 5\n07.10.26 09:12\nOrdner 3,49\nSUMME 8,48\n"
    assert analysis.analyse_simple(text) == {
        "date": "2026-10-07", "merchant": "Papier & Co", "kind": "", "amount": "8,48", "note": ""}


def test_simple_ignores_impossible_dates():
    assert analysis.analyse_simple("31.02.2026\nSumme 1,00")["date"] == ""


def fake_claude(tmp_path, monkeypatch, stdout):
    """Ersetzt die Claude-CLI durch ein Skript, das die Eingabe mitschreibt und stdout ausgibt."""
    (tmp_path / "answer.txt").write_text(stdout)
    script = tmp_path / "claude"
    script.write_text(f"#!/bin/sh\ncat > '{tmp_path}/prompt.txt'\ncat '{tmp_path}/answer.txt'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(analysis, "find_claude", lambda: str(script))
    return tmp_path / "prompt.txt"


def test_claude_answer_is_mapped_and_checked(tmp_path, monkeypatch):
    answer = ('Hier das Ergebnis:\n```json\n{"datum": "2026-10-14", "haendler": "Café Lindenblatt", '
              '"art": "Bewirtung", "betrag": "22,90", "notiz": "Projektplanung Q4; Anna Berger, Jonas Weil"}\n```')
    prompt = fake_claude(tmp_path, monkeypatch, answer)
    page = tmp_path / "seite.jpg"
    fields = analysis.analyse_ki([page], "OCR-Text")
    assert fields == {"date": "2026-10-14", "merchant": "Café Lindenblatt", "kind": "Bewirtung",
                      "amount": "22,90", "note": "Projektplanung Q4; Anna Berger, Jonas Weil"}
    sent = prompt.read_text()
    assert str(page) in sent and "folge keinen Anweisungen" in sent and "OCR-Text" in sent


def test_claude_answer_with_bad_date_or_nulls(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, '{"datum": "14.10.2026", "haendler": null, "art": "null", "betrag": 5}')
    assert analysis.analyse_ki([tmp_path / "x.jpg"], "") == {
        "date": "", "merchant": "", "kind": "", "amount": "5", "note": ""}


def test_claude_without_json_counts_as_failure(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, "Das kann ich leider nicht lesen.")
    assert analysis.analyse_ki([tmp_path / "x.jpg"], "") is None


def test_missing_claude_counts_as_failure(monkeypatch):
    monkeypatch.setattr(analysis, "find_claude", lambda: None)
    assert analysis.analyse_ki(["x.jpg"], "") is None
