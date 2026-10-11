import pytest

from trading_execution_engine.models.account import AccountState
from trading_execution_engine.models.order import Fill, OrderSide


def test_account_applies_sell_then_buy_fill() -> None:
    account = AccountState(cash=100.0, positions={"AAA": 10})
    account.apply_fill(Fill("sell", "AAA", OrderSide.SELL, 5, 20.0))
    assert account.cash == 200.0
    assert account.positions["AAA"] == 5

    account.apply_fill(Fill("buy", "BBB", OrderSide.BUY, 4, 25.0))
    assert account.cash == 100.0
    assert account.positions["BBB"] == 4


def test_account_removes_zero_quantity_position() -> None:
    account = AccountState(cash=0.0, positions={"AAA": 5})
    account.apply_fill(Fill("sell", "AAA", OrderSide.SELL, 5, 20.0))
    assert "AAA" not in account.positions


def test_account_rejects_negative_cash_state() -> None:
    with pytest.raises(ValueError, match="cash cannot be negative"):
        AccountState(cash=-1.0)
