"""The two browser tools that take a capture.

Neither runs in this environment in anger — they run on the operator's machine,
against a page this environment cannot reach. What can be checked here is the
part everything else rests on: that the hash a browser computes is the hash the
importer recomputes. If those ever diverge, every bundle is refused and the
capture route silently stops working.
"""
import hashlib
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
COLLECTOR = ROOT / "tools" / "collector.html"
BOOKMARKLET = ROOT / "tools" / "capture-bookmarklet.js"
INSTALL_PAGE = ROOT / "tools" / "bookmarklet.html"

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

SAMPLES = [
    "",
    "a",
    "<html><body>Wyndham C266wynd gazetted 8 May 2026</body></html>",
    "x" * 1000,                                  # spans several 64-byte blocks
    "Ballarat — Ṽictoria · naïve — non-ascii",   # multi-byte utf-8
]


def _collector_sha256_source() -> str:
    html = COLLECTOR.read_text()
    js = html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    return js.split("// ------------------------------------------------- best-effort")[0]


def _bookmarklet_sha256_source() -> str:
    src = BOOKMARKLET.read_text()
    body = src[src.index("function sha256"):]
    return body[:body.index("  // --- best-effort")]


def _run_in_node(function_source: str, value: str) -> str:
    program = f"{function_source}\nconsole.log(sha256({json.dumps(value)}));"
    result = subprocess.run(["node", "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@node
@pytest.mark.parametrize("sample", SAMPLES)
def test_the_collector_hashes_exactly_as_python_does(sample):
    assert _run_in_node(_collector_sha256_source(), sample) == \
        hashlib.sha256(sample.encode("utf-8")).hexdigest()


@node
@pytest.mark.parametrize("sample", SAMPLES)
def test_the_bookmarklet_hashes_exactly_as_python_does(sample):
    assert _run_in_node(_bookmarklet_sha256_source(), sample) == \
        hashlib.sha256(sample.encode("utf-8")).hexdigest()


@node
def test_the_bookmarklet_is_valid_javascript():
    result = subprocess.run(["node", "--check", str(BOOKMARKLET)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_neither_tool_makes_a_network_request():
    """They run on a government page. Nothing should leave the browser."""
    for path in (COLLECTOR, BOOKMARKLET):
        source = path.read_text()
        for forbidden in ("fetch(", "XMLHttpRequest", "navigator.sendBeacon",
                          "WebSocket", "EventSource", "import("):
            assert forbidden not in source, f"{path.name} references {forbidden}"


def test_the_install_page_carries_the_current_bookmarklet():
    """The page ships a copy of the code; a stale copy would capture differently
    from the source everyone reviews."""
    page = INSTALL_PAGE.read_text()
    assert 'href="javascript:' in page
    for marker in ("crown-capture-panel", "sha256", "confirmed_by_operator",
                   "crown-capture-"):
        assert marker in page, f"the install page does not contain {marker}"


def test_the_install_page_names_one_amendment_per_lga():
    page = INSTALL_PAGE.read_text()
    leads = json.loads((ROOT / "seeds" / "relay_leads.json").read_text())["leads"]
    for lga in ("Wyndham", "Melton", "Hume"):
        assert lga in page
    # and it warns about the two the search relay contradicted itself on
    assert "CONTRADICTED" in page
    assert "C232melt" in page and "C272hume" in page
    assert any(l["amendment_number"] == "C266wynd" for l in leads)
