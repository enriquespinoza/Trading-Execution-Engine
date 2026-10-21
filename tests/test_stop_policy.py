import pytest

from trading_execution_engine.execution_policy.stop_policy import (
    ProtectiveStopType,
    StopPolicy,
    recommend_protective_stop,
)


def test_stop_limit_recommendation_is_deterministic() -> None:
    result = recommend_protective_stop(
        symbol="abc",
        quantity=25,
        reference_price=100.0,
        policy=StopPolicy(
            stop_type=ProtectiveStopType.STOP_LIMIT,
            stop_distance_pct=8.0,
            stop_limit_buffer_bps=50.0,
        ),
    )

    assert result.symbol == "ABC"
    assert result.quantity == 25
    assert result.reference_price == 100.0
    assert result.stop_price == 92.0
    assert result.stop_limit_price == 91.54
    assert result.review_only is True
    assert result.broker_submission_permitted is False


def test_plain_stop_has_no_limit_price() -> None:
    result = recommend_protective_stop(
        symbol="ABC",
        quantity=5,
        reference_price=50.0,
        policy=StopPolicy(
            stop_type=ProtectiveStopType.STOP,
            stop_distance_pct=10.0,
            stop_limit_buffer_bps=0.0,
        ),
    )

    assert result.stop_price == 45.0
    assert result.stop_limit_price is None


def test_stop_quantity_must_be_positive_whole_shares() -> None:
    policy = StopPolicy()

    for quantity in (0, -1):
        with pytest.raises(
            ValueError,
            match="quantity",
        ):
            recommend_protective_stop(
                symbol="ABC",
                quantity=quantity,
                reference_price=100.0,
                policy=policy,
            )


def test_invalid_stop_configuration_fails_closed() -> None:
    with pytest.raises(ValueError):
        StopPolicy(stop_distance_pct=0)

    with pytest.raises(ValueError):
        StopPolicy(stop_distance_pct=100)

    with pytest.raises(ValueError):
        StopPolicy(stop_limit_buffer_bps=-1)

    with pytest.raises(ValueError):
        StopPolicy(
            stop_type=ProtectiveStopType.STOP,
            stop_limit_buffer_bps=50,
        )
