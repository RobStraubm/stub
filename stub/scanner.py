"""Scanner im Netz finden und ueber eSCL (AirScan) scannen."""
import re
import ssl
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import config, lock, save_config

SCAN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <pwg:Version>2.63</pwg:Version>
  <scan:Intent>TextAndGraphic</scan:Intent>
  <pwg:ScanRegions><pwg:ScanRegion>
    <pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>
    <pwg:XOffset>0</pwg:XOffset><pwg:YOffset>0</pwg:YOffset>
    <pwg:Width>{width}</pwg:Width><pwg:Height>{height}</pwg:Height>
  </pwg:ScanRegion></pwg:ScanRegions>
  <pwg:InputSource>{source}</pwg:InputSource>
  <scan:ColorMode>{mode}</scan:ColorMode>
  <scan:XResolution>{dpi}</scan:XResolution>
  <scan:YResolution>{dpi}</scan:YResolution>
  <pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>
</scan:ScanSettings>"""


SCAN_TYPES = ("_uscan._tcp.local.", "_uscans._tcp.local.")    # eSCL-Scanner (AirScan)


PRINTER_TYPES = ("_ipp._tcp.local.", "_ipps._tcp.local.")     # Drucker, evtl. mit abgeschaltetem Scan


NO_TLS_CHECK = ssl._create_unverified_context()  # Drucker haben selbstsignierte Zertifikate


caps_cache = {}


class ScanError(Exception):
    pass


def scanner_url(addr):
    """'host:port' (alte Einstellung) oder volle URL -> Basis-URL der eSCL-Schnittstelle."""
    addr = (addr or "").strip().rstrip("/")
    if not re.match(r"https?://", addr):
        addr = "http://" + addr
    return addr if re.match(r"https?://[^/]+/.", addr) else addr + "/eSCL"


def scanner_label(addr=None, name=None):
    """Anzeigename: gemerkter Modellname, sonst der Hostname ohne .local."""
    if addr is None:
        addr, name = config["scanner"], config.get("scanner_name")
    if not addr:
        return "Noch kein Scanner"
    host = re.sub(r"[:/].*$", "", re.sub(r"^https?://", "", scanner_url(addr)))
    return name or re.sub(r"\.local$", "", host)


def http(url, data=None, timeout=10):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "text/xml"} if data else {})
    return urllib.request.urlopen(req, timeout=timeout, context=NO_TLS_CHECK)


def probe(addr, timeout=4):
    """HTTP-Status von ScannerStatus (200 = bereit, 503 = Scannen am Geraet abgeschaltet), None = nicht erreichbar."""
    try:
        with http(scanner_url(addr) + "/ScannerStatus", timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (OSError, ValueError):
        return None


def capabilities(base):
    """Glasgroesse, Aufloesungen und Quelle aus ScannerCapabilities (je Scanner gemerkt)."""
    if base in caps_cache:
        return caps_cache[base]
    caps = {"width": 2550, "height": 3508, "dpis": [], "source": "Platen", "model": ""}
    try:
        with http(base + "/ScannerCapabilities") as r:
            root = ET.fromstring(r.read())
        def local(el):
            return el.tag.rsplit("}", 1)[-1]

        caps["model"] = next((el.text.strip() for el in root.iter()
                              if local(el) == "MakeAndModel" and el.text), "")
        src = next((el for el in root.iter() if local(el) == "Platen"), None)
        if src is None:
            src = next((el for el in root.iter() if local(el) == "Adf"), None)
            caps["source"] = "Feeder"
        for el in (src if src is not None else root).iter():
            if local(el) == "MaxWidth":
                caps["width"] = int(el.text)
            elif local(el) == "MaxHeight":
                caps["height"] = int(el.text)
            elif local(el) == "XResolution" and el.text.strip().isdigit():
                caps["dpis"].append(int(el.text))
    except (OSError, ValueError, ET.ParseError) as e:
        print(f"ScannerCapabilities nicht lesbar ({base}): {e}", flush=True)
        return caps  # nicht merken, beim naechsten Mal neu versuchen
    caps_cache[base] = caps
    return caps


def discover(wait=3.0):
    """Sucht Scanner im Netz per Bonjour.

    Liefert (Scanner [{name, addr}], Namen von Druckern, die scannen koennten, bei denen
    das Scannen uebers Netzwerk aber abgeschaltet ist).
    """
    from zeroconf import ServiceBrowser, Zeroconf
    found = []

    class Listener:
        def add_service(self, zc, kind, name):
            found.append((kind, name))

        def update_service(self, *a):
            pass

        def remove_service(self, *a):
            pass

    zc = Zeroconf()
    scanners, printers = {}, {}
    try:
        browsers = [ServiceBrowser(zc, kind, Listener()) for kind in SCAN_TYPES + PRINTER_TYPES]
        time.sleep(wait)
        for kind, name in sorted(set(found)):
            info = zc.get_service_info(kind, name, 2000)
            if not info or not info.server:
                continue
            props = {k.decode(errors="replace"): (v or b"").decode(errors="replace")
                     for k, v in info.properties.items()}
            host = info.server.rstrip(".")
            label = props.get("ty") or name.split("._")[0]
            uid = props.get("UUID", "").lower() or host
            if kind in SCAN_TYPES:
                https = kind.startswith("_uscans")
                root = props.get("rs", "eSCL").strip("/") or "eSCL"
                addr = f"{'https' if https else 'http'}://{host}:{info.port}/{root}"
                if uid not in scanners or not https:  # unverschluesselt bevorzugen, wenn beides da ist
                    scanners[uid] = {"name": label, "addr": addr}
            else:
                printers.setdefault(uid, {"name": label, "host": host})
        del browsers
    finally:
        zc.close()
    rest = {uid: p for uid, p in printers.items() if uid not in scanners}
    with ThreadPoolExecutor(8) as ex:  # Drucker, die eSCL koennen, es aber nicht per Bonjour melden
        codes = dict(zip(rest, ex.map(lambda p: probe(f"http://{p['host']}/eSCL", 3), rest.values()), strict=True))
    off = []
    for uid, p in rest.items():
        if codes[uid] == 200:
            scanners[uid] = {"name": p["name"], "addr": f"http://{p['host']}/eSCL"}
        elif codes[uid] == 503:
            off.append(p["name"])
    return sorted(scanners.values(), key=lambda s: s["name"]), sorted(off)


def remember_scanner(addr, name):
    """Setzt den aktuellen Scanner und merkt ihn sich (zuletzt benutzte zuerst, unter lock)."""
    config["scanner"], config["scanner_name"] = addr, name
    known = [k for k in config.get("known", []) if scanner_url(k["addr"]) != scanner_url(addr)]
    config["known"] = ([{"name": name, "addr": addr}] + known)[:10]
    save_config()


def ensure_scanner():
    """Prueft den eingestellten Scanner; ist er nicht erreichbar, wird ein anderer gesucht.

    Liefert einen Hinweistext, wenn gewechselt wurde, sonst None.
    """
    if config["scanner"] and probe(config["scanner"]) == 200:
        return None
    if config["scanner"] and not config.get("auto_switch", True):
        raise ScanError(f"Scanner „{scanner_label()}“ ist nicht erreichbar. Ist er an und im selben Netz?")
    scanners, off = discover()
    known = [scanner_url(k["addr"]) for k in config.get("known", [])]
    current = scanner_url(config["scanner"])
    # bekannte Scanner zuerst (zuletzt benutzte vorn), sonst ein einzelner neu gefundener
    familiar = sorted((s for s in scanners if scanner_url(s["addr"]) in known),
                      key=lambda s: known.index(scanner_url(s["addr"])))
    for pick in familiar or (scanners if len(scanners) == 1 else []):
        if probe(pick["addr"]) != 200:
            continue
        if scanner_url(pick["addr"]) == current:
            return None  # nur kurz eingeschlafen, inzwischen wach
        with lock:
            remember_scanner(pick["addr"], pick["name"])
        return f"Scanner gewechselt: {pick['name']}"
    if config["scanner"] and probe(config["scanner"]) == 200:  # schlafender Drucker ist inzwischen aufgewacht
        return None
    if len(scanners) > 1:
        raise ChooseScanner("Hier gibt es mehrere Scanner – bitte einmal auswählen, welcher es sein soll.")
    msg = (f"„{scanner_label()}“ ist nicht erreichbar, und hier wurde kein anderer Scanner gefunden."
           if config["scanner"] else "Im Netz wurde kein Scanner gefunden. Ist der Mac im selben WLAN wie der Drucker?")
    if off:
        msg += (f" „{off[0]}“ könnte scannen, aber das Scannen übers Netzwerk (AirPrint-Scan/eSCL) ist dort"
                " ausgeschaltet – das kann der Administrator in der Druckerverwaltung einschalten.")
    raise ScanError(msg)


class ChooseScanner(ScanError):
    pass


def escl_scan(dest, dpi):
    """Scannt das Flachbett und schreibt ein JPEG nach dest. Liefert die tatsaechliche Aufloesung."""
    base = scanner_url(config["scanner"])
    caps = capabilities(base)
    if caps["dpis"] and dpi not in caps["dpis"]:
        dpi = min(caps["dpis"], key=lambda d: (d < dpi, abs(d - dpi)))  # lieber feiner als groeber
    body = SCAN_XML.format(mode="RGB24" if config["color"] else "Grayscale8", dpi=dpi, source=caps["source"],
                           width=caps["width"], height=caps["height"]).encode()
    try:
        with http(base + "/ScanJobs", data=body, timeout=30) as r:
            loc = r.headers.get("Location")
    except urllib.error.HTTPError as e:
        if e.code in (409, 503):
            raise ScanError("Der Scanner ist gerade beschäftigt. Kurz warten und nochmal versuchen.") from e
        raise ScanError(f"Scanner meldet Fehler {e.code}.") from e
    except OSError as e:
        raise ScanError(f"Scanner „{scanner_label()}“ nicht erreichbar. Ist er an und im selben Netz? [{e}]") from e
    if not loc:
        raise ScanError("Scanner hat keinen Scanauftrag angelegt.")
    path = re.sub(r"^https?://[^/]+", "", loc).rstrip("/")  # Hostnamen der Einstellung behalten
    job = (re.match(r"https?://[^/]+", base).group(0) + path) if path.startswith("/") else f"{base}/{path}"
    last = None
    for _ in range(20):
        try:
            with http(job + "/NextDocument", timeout=180) as r:
                Path(dest).write_bytes(r.read())
            return dpi
        except urllib.error.HTTPError as e:
            last = e
            if e.code != 503:
                break
            time.sleep(1)
        except OSError as e:
            last = e
            break
    raise ScanError(f"Scan konnte nicht abgeholt werden: {last}")
