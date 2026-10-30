import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_loopwatch(monkeypatch):
    """the repeat search (its own process, loopwatch.py) only where a test switches it on"""
    from c64jukebox import loopwatch
    monkeypatch.setattr(loopwatch, "PYTHON", None)


@pytest.fixture(autouse=True)
def _no_github(monkeypatch):
    """the daily look for a new version never leaves the test machine (tests set their own address)"""
    from c64jukebox import core
    monkeypatch.setattr(core, "UPDATE_URL", "")
