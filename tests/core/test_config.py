from __future__ import annotations

import pytest

from ecommerce_cs_agent.core.config import load_settings


def test_decision_max_concurrency_defaults_to_four(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("DECISION_MAX_CONCURRENCY", raising=False)

    assert load_settings().decision_max_concurrency == 4


def test_decision_max_concurrency_accepts_positive_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DECISION_MAX_CONCURRENCY", "7")

    assert load_settings().decision_max_concurrency == 7


@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_decision_max_concurrency_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DECISION_MAX_CONCURRENCY", value)

    with pytest.raises(ValueError, match="DECISION_MAX_CONCURRENCY must be a positive integer"):
        load_settings()
