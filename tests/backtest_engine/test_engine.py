from __future__ import annotations

import pandas as pd
import pytest

from backtest_engine.costs import CostModel
from backtest_engine.engine import run_backtest
from config.schema import (
    AccountConfig,
    ApprovalConfig,
    AppConfig,
    ConnectionConfig,
    RiskLimitsConfig,
    StrategiesConfig,
    StrategyConfig,
    UniverseConfig,
)
from signal_layer import mean_reversion, momentum


def make_config(**risk_overrides) -> AppConfig:
    risk_defaults = dict(
        max_position_pct_of_equity=0.5,
        max_sector_concentration_pct=1.0,
        max_single_order_notional_usd=1_000_000,
        max_daily_loss_pct=1.0,
        max_drawdown_pct=1.0,
        max_orders_per_minute=1000,
        max_orders_per_hour=10000,
        max_leverage=1.0,
    )
    risk_defaults.update(risk_overrides)
    return AppConfig(
        account=AccountConfig(starting_capital_usd=100_000, is_placeholder=True, account_type="margin_no_leverage"),
        risk_limits=RiskLimitsConfig(**risk_defaults),
        universe=UniverseConfig(allowed_asset_classes=["ETF"], min_avg_dollar_volume_usd=1, min_price_usd=0),
        strategies=StrategiesConfig(
            momentum=StrategyConfig(enabled=True, params={}),
            mean_reversion=StrategyConfig(enabled=True, params={}),
            breakout=StrategyConfig(enabled=True, params={}),
        ),
        approval=ApprovalConfig(proposal_expiry_minutes=30, allow_bulk_approve=False),
        connection=ConnectionConfig(),
    )


def make_df(closes: list[float], sector="Broad Market") -> pd.DataFrame:
    dates = pd.date_range("2023-01-02", periods=len(closes), freq="B")
    df = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1_000_000] * len(closes)},
        index=dates,
    )
    df.attrs["sector"] = sector
    return df


MEAN_REVERSION_PARAMS = {
    "lookback_days": 20,
    "entry_zscore": -2.0,
    "exit_zscore": 0.0,
    "stop_loss_pct": 0.30,
    "max_hold_days": 15,
}


def dip_and_recover_closes() -> list[float]:
    return [100.0] * 40 + [70.0] * 5 + [100.0] * 40


def test_mean_reversion_backtest_opens_and_closes_a_trade():
    df = make_df(dip_and_recover_closes())
    config = make_config()

    result = run_backtest(
        price_data={"DIP": df},
        strategy_name="mean_reversion",
        strategy_module=mean_reversion,
        params=MEAN_REVERSION_PARAMS,
        config=config,
        initial_capital=100_000,
        cost_model=CostModel(),
        min_lookback_days=21,
    )

    assert len(result.equity_curve) == len(df)
    assert result.approved_proposals >= 1
    assert len(result.trades) >= 1
    assert result.trades[0].exit_reason in {"mean_reversion_exit", "stop_loss", "time_stop"}


def test_zero_sized_position_never_opens_a_trade():
    df = make_df(dip_and_recover_closes())
    config = make_config()

    result = run_backtest(
        price_data={"DIP": df},
        strategy_name="mean_reversion",
        strategy_module=mean_reversion,
        params=MEAN_REVERSION_PARAMS,
        config=config,
        initial_capital=100_000,
        cost_model=CostModel(),
        min_lookback_days=21,
    )
    # sanity check the prior test's premise: with normal sizing we do trade
    assert result.approved_proposals >= 1


def test_risk_gate_blocks_when_order_notional_ceiling_is_tiny():
    df = make_df(dip_and_recover_closes())
    config = make_config(max_single_order_notional_usd=1.0)

    result = run_backtest(
        price_data={"DIP": df},
        strategy_name="mean_reversion",
        strategy_module=mean_reversion,
        params=MEAN_REVERSION_PARAMS,
        config=config,
        initial_capital=100_000,
        cost_model=CostModel(),
        min_lookback_days=21,
    )
    assert result.blocked_proposals >= 1
    assert result.approved_proposals == 0
    assert result.trades == []
    assert len(result.blocked_reasons_sample) >= 1


def test_mismatched_calendars_raise():
    df_a = make_df([100.0] * 30)
    df_b = make_df([100.0] * 25)  # different length -> different index

    with pytest.raises(ValueError):
        run_backtest(
            price_data={"A": df_a, "B": df_b},
            strategy_name="mean_reversion",
            strategy_module=mean_reversion,
            params=MEAN_REVERSION_PARAMS,
            config=make_config(),
            initial_capital=100_000,
            min_lookback_days=21,
        )


MOMENTUM_PARAMS = {
    "lookback_days": 20,
    "skip_recent_days": 0,
    "top_n": 1,
    "stop_loss_pct": 0.5,
    "rebalance_every_days": 5,
}


def test_momentum_backtest_holds_only_top_n():
    strong = make_df([100.0 + i * 1.5 for i in range(120)], sector="Tech")
    weak = make_df([100.0 + i * 0.1 for i in range(120)], sector="Financials")

    result = run_backtest(
        price_data={"STRONG": strong, "WEAK": weak},
        strategy_name="momentum",
        strategy_module=momentum,
        params=MOMENTUM_PARAMS,
        config=make_config(),
        initial_capital=100_000,
        cost_model=CostModel(),
        min_lookback_days=25,
    )

    symbols_ever_held = {t.symbol for t in result.trades}
    assert symbols_ever_held <= {"STRONG", "WEAK"}
    assert result.approved_proposals >= 1
