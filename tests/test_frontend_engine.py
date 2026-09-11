"""Runs the browser label-map engine tests under Node when it is installed."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "online_annotator" / "web"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_labelmap_engine_under_node():
    result = subprocess.run(["node", "--test", str(ROOT / "tests" / "js" / "labelmap.test.mjs")],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_frontend_has_no_external_urls():
    """Intranet rule: every asset is served locally; no CDN, font or analytics URL may appear."""
    offenders = []
    for path in WEB.rglob("*"):
        if path.suffix in {".html", ".js", ".css"}:
            text = path.read_text(encoding="utf-8")
            for url in re.findall(r"(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s\"'`)]*", text):
                if not url.split("//", 1)[1].startswith("www.w3.org/"):
                    offenders.append(f"{path.relative_to(ROOT)}: {url}")
    assert offenders == []
