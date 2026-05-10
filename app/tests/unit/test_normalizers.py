import pandas as pd
import pytest

from app.etl.transform.normalizers import (
    coerce_numeric_columns,
    drop_duplicates_stable,
    ensure_date,
    fill_numeric_nulls_with_median,
)


def test_drop_duplicates_keeps_most_recent_stable_order() -> None:
    df = pd.DataFrame(
        {"k": ["A", "A", "B"], "v": [1, 2, 3], "trade_date": [1, 2, 3]}
    ).sort_values("trade_date")
    cleaned = drop_duplicates_stable(df, subset=["k"])
    assert cleaned["v"].tolist() == [2, 3]


def test_numeric_coercion_introduces_nan() -> None:
    df = pd.DataFrame({"amt": ["1", "", "oops"]})
    coerced = coerce_numeric_columns(df, ["amt"])
    assert pd.isna(coerced.iloc[2]["amt"])


def test_fill_numeric_nulls_uses_median() -> None:
    df = pd.DataFrame({"x": [10.0, None, 20.0]})
    filled = fill_numeric_nulls_with_median(df, ["x"])
    assert filled.iloc[1]["x"] == pytest.approx(15.0)


def test_ensure_date_parses_iso_strings() -> None:
    df = pd.DataFrame({"d": ["2024-03-09", "2024-06-01"]})
    normalized = ensure_date(df, "d").dt.strftime("%Y-%m-%d")
    assert normalized.tolist() == ["2024-03-09", "2024-06-01"]
