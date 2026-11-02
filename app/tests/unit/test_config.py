from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_fx_targets_are_parsed_and_normalized(make_settings) -> None:
    settings = make_settings(FX_TARGET_CURRENCIES=" brl,eur , ,gbp")
    assert settings.fx_targets == ("BRL", "EUR", "GBP")


def test_empty_report_history_means_full_history(make_settings) -> None:
    assert make_settings(REPORT_HISTORY_DAYS="").report_history_days is None
    assert make_settings(REPORT_HISTORY_DAYS="30").report_history_days == 30


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
