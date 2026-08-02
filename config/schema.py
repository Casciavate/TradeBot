"""Typed config schema. Every tunable risk/account/universe/strategy parameter
lives here and in the YAML files under config/ -- never hardcoded in
risk_gate, signal_layer, or execution_layer."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AccountConfig(BaseModel):
    starting_capital_usd: float = Field(..., gt=0)
    is_placeholder: bool = False
    account_type: Literal["cash", "margin_no_leverage", "margin_with_leverage"]
    base_currency: str = "USD"


class RiskLimitsConfig(BaseModel):
    max_position_pct_of_equity: float = Field(..., gt=0, le=1)
    max_sector_concentration_pct: float = Field(..., gt=0, le=1)
    max_single_order_notional_usd: float = Field(..., gt=0)
    max_daily_loss_pct: float = Field(..., gt=0, le=1)
    max_drawdown_pct: float = Field(..., gt=0, le=1)
    max_orders_per_minute: int = Field(..., gt=0)
    max_orders_per_hour: int = Field(..., gt=0)
    max_leverage: float = Field(..., ge=1.0)


class UniverseConfig(BaseModel):
    allowed_asset_classes: list[Literal["ETF"]]
    min_avg_dollar_volume_usd: float = Field(..., gt=0)
    min_price_usd: float = Field(..., ge=0)
    max_price_usd: float | None = None
    exclude_symbols: list[str] = Field(default_factory=list)
    include_symbols_only: list[str] | None = None


class StrategyConfig(BaseModel):
    enabled: bool
    params: dict = Field(default_factory=dict)


class StrategiesConfig(BaseModel):
    momentum: StrategyConfig
    mean_reversion: StrategyConfig
    breakout: StrategyConfig


class ApprovalConfig(BaseModel):
    proposal_expiry_minutes: int = Field(..., gt=0)
    allow_bulk_approve: bool = False


class ConnectionConfig(BaseModel):
    host: str = "127.0.0.1"
    paper_port: int = 7497
    live_port: int = 7496
    client_id: int = 7
    account_id: str | None = None


class AppConfig(BaseModel):
    account: AccountConfig
    risk_limits: RiskLimitsConfig
    universe: UniverseConfig
    strategies: StrategiesConfig
    approval: ApprovalConfig
    connection: ConnectionConfig

    @model_validator(mode="after")
    def _leverage_matches_account_type(self) -> "AppConfig":
        if self.account.account_type != "margin_with_leverage" and self.risk_limits.max_leverage != 1.0:
            raise ValueError(
                "max_leverage must be 1.0 unless account.account_type is "
                "'margin_with_leverage' -- refusing to load a config that "
                "implies leverage on a cash/no-leverage account"
            )
        return self
