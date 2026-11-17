"""M1 regression: FM-03 ticket_trust on C-002@11 (docs/trace_case.md)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def cases():
    from lab9.trace_case import investigate

    return {
        "bad": investigate("seeded_regression", "C-002", 11),
        "good": investigate("fixed", "C-002", 11),
    }


def test_fm03_ticket_trust_first_wrong_step(cases):
    bad, good = cases["bad"]["trial"], cases["good"]["trial"]
    assert bad["lab8_pass"] is False
    assert bad["lab8_reason"] == "status resolved != denied"
    kinds = [e.get("kind") for e in bad["events"]]
    assert "model_override" in kinds
    first_override = next(e for e in bad["events"] if e.get("kind") == "model_override")
    assert first_override["payload"].get("delay_days") == 5
    # Steps before the override must not already refund / resolve.
    override_idx = kinds.index("model_override")
    assert "reply" not in kinds[:override_idx]

    assert good["lab8_pass"] is True
    assert "model_override" not in [e.get("kind") for e in good["events"]]
