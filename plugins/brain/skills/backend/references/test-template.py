"""Tests for a backend adapter: the conformance kit against a fake client, plus the mapping cases from the spec.

Copy to .brain/python/tests/test_<name>.py. Run with the workspace tool, for example `uv run --frozen pytest .brain/python/tests`.
Replace `FakeClient` with a stand-in that behaves like the service (same errors, same limits), and wire it into the adapter
the same way the real client is. The conformance kit does the contract checks; add tests for your own mapping rules.
"""
import sys
from pathlib import Path

import pytest

# the adapter script lives in ../scripts; import it as a module
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from brainctl.conformance import assert_conforms, iter_checks  # noqa: E402

import my_backend  # noqa: E402  (rename: the script is scripts/my_backend.py)


class FakeClient:
    """A fake of the service. Keep it small but honest: it should raise what the real client raises."""

    def __init__(self):
        self.items = {}


def make_adapter():
    adapter = my_backend.MyBackend()
    adapter.client = FakeClient()          # however your adapter takes its client (see Store in the template)
    return adapter


SETTINGS = lambda: {"project": "sandbox"}      # a callable gives every check fresh settings; use a dict if the fake is created fresh by make_adapter


def test_conforms():
    assert_conforms(make_adapter, settings=SETTINGS)


@pytest.mark.parametrize("name, run", list(iter_checks(make_adapter, settings=SETTINGS)), ids=lambda v: v if isinstance(v, str) else "")
def test_each_conformance_check(name, run):
    run()


# ---- mapping cases from the spec ------------------------------------------------------------------------------------

def test_status_mapping_matches_the_spec():
    ...  # every service state maps to the core status the spec says, and back
