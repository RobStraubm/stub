import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from stub import server


@pytest.fixture
def base():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def call(url, data=None, origin=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json", **({"Origin": origin} if origin else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_page_and_state(base, ablage):
    status, page = call(base + "/")
    assert status == 200 and b"<title>Stub</title>" in page
    status, body = call(base + "/api/state")
    state = json.loads(body)
    assert status == 200 and state["receipts"] == [] and "scanner_label" in state


def test_foreign_pages_cannot_trigger_actions(base, ablage):
    status, body = call(base + "/api/quit", {}, origin="https://example.com")
    assert status == 403


def test_unknown_things(base, ablage):
    assert call(base + "/img/999/0")[0] == 404
    assert call(base + "/raw/19990101-000000")[0] == 404
    status, body = call(base + "/api/gibtsnicht", {})
    assert json.loads(body) == {"error": "Unbekannte Aktion."}
    assert json.loads(call(base + "/api/delete", {"id": 999})[1]) == {"error": "Beleg nicht gefunden."}
