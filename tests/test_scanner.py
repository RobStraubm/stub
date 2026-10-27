import pytest

from stub import config as cfg
from stub import scanner
from tests.fakes import FakeScanner, glass


@pytest.fixture
def fake(tmp_path):
    image = tmp_path / "glas.jpg"
    glass([], dust=0).save(image)
    scanner.caps_cache.clear()
    fs = FakeScanner(image)
    yield fs
    fs.close()


@pytest.fixture
def settings(monkeypatch):
    for key, value in {"scanner": "", "scanner_name": "", "known": [], "auto_switch": True}.items():
        monkeypatch.setitem(cfg.config, key, value)
    monkeypatch.setattr(scanner, "save_config", lambda: None)
    return cfg.config


@pytest.mark.parametrize("addr, url, label", [
    ("drucker.local:8080", "http://drucker.local:8080/eSCL", "drucker"),
    ("https://10.0.0.7/eSCL/", "https://10.0.0.7/eSCL", "10.0.0.7"),
    ("http://scan.local:80/airscan", "http://scan.local:80/airscan", "scan"),
])
def test_addresses(addr, url, label):
    assert scanner.scanner_url(addr) == url
    assert scanner.scanner_label(addr, "") == label


def test_label_without_scanner(settings):
    assert scanner.scanner_label() == "Noch kein Scanner"


def test_probe(fake):
    assert scanner.probe(fake.addr) == 200
    fake.status = 503  # Scannen am Geraet abgeschaltet
    assert scanner.probe(fake.addr) == 503
    assert scanner.probe("http://127.0.0.1:9/eSCL", timeout=1) is None


def test_capabilities_are_read(fake):
    caps = scanner.capabilities(fake.addr)
    assert caps == {"width": 2480, "height": 3507, "dpis": [150, 300, 600], "source": "Platen",
                    "model": "Testscanner X1"}


def test_scan_uses_scanner_limits_and_own_host(fake, settings, tmp_path, monkeypatch):
    settings["scanner"] = fake.addr
    monkeypatch.setitem(settings, "dpi", 400)
    dest = tmp_path / "roh.jpg"
    assert scanner.escl_scan(dest, 400) == 600  # nicht angeboten -> lieber feiner als groeber
    assert dest.read_bytes() == fake.image_path.read_bytes()
    xml = fake.posted[0]
    assert "<pwg:Width>2480</pwg:Width>" in xml and "<pwg:Height>3507</pwg:Height>" in xml
    assert "<scan:XResolution>600</scan:XResolution>" in xml


def test_reachable_scanner_is_kept(fake, settings, monkeypatch):
    settings["scanner"] = fake.addr
    monkeypatch.setattr(scanner, "discover", lambda: pytest.fail("darf nicht suchen"))
    assert scanner.ensure_scanner() is None


def test_switches_to_known_scanner(fake, settings, monkeypatch):
    settings.update(scanner="http://127.0.0.1:9/eSCL",
                    known=[{"name": "Daheim", "addr": "http://127.0.0.1:9/eSCL"}, {"name": "Büro", "addr": fake.addr}])
    monkeypatch.setattr(scanner, "probe", lambda addr, timeout=4: 200 if addr == fake.addr else None)
    monkeypatch.setattr(scanner, "discover", lambda: ([{"name": "Fremd", "addr": "http://fremd/eSCL"},
                                                      {"name": "Büro", "addr": fake.addr}], []))
    assert scanner.ensure_scanner() == "Scanner gewechselt: Büro"
    assert settings["scanner"] == fake.addr
    assert [k["name"] for k in settings["known"]] == ["Büro", "Daheim"]


def test_first_run_takes_the_only_scanner(fake, settings, monkeypatch):
    monkeypatch.setattr(scanner, "discover", lambda: ([{"name": "Testscanner X1", "addr": fake.addr}], []))
    assert scanner.ensure_scanner() == "Scanner gewechselt: Testscanner X1"


def test_several_unknown_scanners_ask_the_user(settings, monkeypatch):
    monkeypatch.setattr(scanner, "discover", lambda: ([{"name": "A", "addr": "http://a/eSCL"},
                                                      {"name": "B", "addr": "http://b/eSCL"}], []))
    with pytest.raises(scanner.ChooseScanner):
        scanner.ensure_scanner()


def test_printer_with_scanning_switched_off_is_explained(settings, monkeypatch):
    monkeypatch.setattr(scanner, "discover", lambda: ([], ["Bürodrucker MFP"]))
    with pytest.raises(scanner.ScanError, match="Bürodrucker MFP.*ausgeschaltet"):
        scanner.ensure_scanner()


def test_no_switching_when_disabled(settings, monkeypatch):
    settings.update(scanner="http://127.0.0.1:9/eSCL", auto_switch=False)
    monkeypatch.setattr(scanner, "probe", lambda addr, timeout=4: None)
    monkeypatch.setattr(scanner, "discover", lambda: pytest.fail("darf nicht suchen"))
    with pytest.raises(scanner.ScanError, match="nicht erreichbar"):
        scanner.ensure_scanner()
