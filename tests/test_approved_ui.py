"""Ensure packaging retains the entire approved prototype, not a reconstruction."""
import hashlib
from pathlib import Path


def test_approved_ui_is_byte_identical():
    root = Path(__file__).resolve().parents[1]
    source = root.parent / "NEXUS-Design-Review/launcher-stage-1/index.html"
    packaged = root / "assets/approved-ui/index.html"
    # A standalone recovered checkout has no sibling design repository. Retain
    # the original golden digest rather than reading an absent external folder.
    expected = source.read_bytes() if source.is_file() else None
    digest = hashlib.sha256(packaged.read_bytes()).hexdigest()
    assert digest == (hashlib.sha256(expected).hexdigest() if expected else
                      "6a8dc003e790cf2abbaa2b961e57790004846a226a995437693b1d9cfaa3da83")


def test_build_includes_approved_ui_asset_tree():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging" / "specs" / "NexusNextRegistrationTest.spec").read_text(encoding="utf-8")
    assert '(str(root / "assets"), "assets")' in spec
