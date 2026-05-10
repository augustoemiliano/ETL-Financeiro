import pandas as pd
import pytest

from app.etl.transform.schema import SCHEMA_PIPELINE_OUTPUT, SchemaValidationError, assert_schema


def test_assert_schema_raises_on_missing_column() -> None:
    df = pd.DataFrame({"symbol": ["X"]})
    with pytest.raises(SchemaValidationError):
        assert_schema(df, SCHEMA_PIPELINE_OUTPUT)


def test_assert_schema_raises_on_required_null() -> None:
    df = pd.DataFrame(
        [
            {
                "symbol": "SYM",
                "metric_date": None,
                "metric_type": "T",
                "currency": "BRL",
                "amount": 1.0,
                "source_system": "fixture",
                "load_batch_id": None,
                "extras": None,
            }
        ]
    )
    with pytest.raises(SchemaValidationError):
        assert_schema(df, SCHEMA_PIPELINE_OUTPUT)
