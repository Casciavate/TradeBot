from __future__ import annotations

from fastapi.testclient import TestClient

from monitoring.alerts import AlertKind, AlertRouter, AlertSeverity
from monitoring.audit_log import AuditLog
from monitoring.status_dashboard import build_status_app
from risk_gate.models import PortfolioState, Position


def _portfolio() -> PortfolioState:
    return PortfolioState(
        equity=98_000,
        peak_equity=100_000,
        cash=80_000,
        positions={"SPY": Position("SPY", 20, 12_000, "Broad Market")},
        realized_pnl_today=-1_200,
        unrealized_pnl_today=400,
    )


def _client(base_config, **kwargs) -> TestClient:
    app = build_status_app(base_config, portfolio_provider=_portfolio, **kwargs)
    return TestClient(app)


def test_page_shows_positions_pnl_and_risk_headroom(base_config):
    response = _client(base_config).get("/")

    assert response.status_code == 200
    body = response.text
    assert "SPY" in body
    assert "-800.00" in body
    assert "largest position" in body
    assert "Risk limit headroom" in body


def test_page_warns_when_the_kill_switch_is_engaged(base_config, kill_switch):
    kill_switch.engage("manual test")

    body = _client(base_config, kill_switch=kill_switch).get("/").text

    assert "KILL SWITCH ENGAGED" in body
    assert "manual test" in body


def test_page_warns_when_the_circuit_breaker_is_tripped(base_config, circuit_breaker):
    circuit_breaker.trip("daily loss 3.1% breached the 2.50% circuit breaker")

    body = _client(base_config, circuit_breaker=circuit_breaker).get("/").text

    assert "CIRCUIT BREAKER TRIPPED" in body
    assert "circuit_breaker_cli.py reset" in body


def test_page_reports_all_clear_when_nothing_is_halted(base_config):
    """The default _portfolio() deliberately breaches the position cap, so
    all-clear is checked against a portfolio that is within every limit."""
    within_limits = PortfolioState(
        equity=100_000,
        peak_equity=100_000,
        cash=95_000,
        positions={"SPY": Position("SPY", 10, 5_000, "Broad Market")},
    )
    app = build_status_app(base_config, portfolio_provider=lambda: within_limits)

    body = TestClient(app).get("/").text

    assert "Trading not halted" in body


def test_a_position_over_the_cap_is_flagged_on_the_page(base_config):
    """_portfolio() holds $12k of SPY against an $8k cap."""
    body = _client(base_config).get("/").text

    assert "risk limit(s) at or over the cap" in body
    assert "largest position" in body


def test_page_lists_recent_alerts(base_config, tmp_path):
    router = AlertRouter(audit_log=AuditLog(tmp_path / "alerts.log"), throttle_seconds=0)
    router.alert(AlertKind.ORDER_REJECTED, AlertSeverity.CRITICAL, "Order REJECTED by IBKR: BUY 10 SPY")

    body = _client(base_config, alert_router=router).get("/").text

    assert "Order REJECTED by IBKR: BUY 10 SPY" in body


def test_placeholder_account_size_is_called_out(base_config):
    body = _client(base_config).get("/").text

    assert "Placeholder account size" in body


def test_json_endpoint_exposes_the_same_numbers(base_config):
    payload = _client(base_config).get("/api/status").json()

    assert payload["equity"] == 98_000
    assert payload["daily_pnl"] == -800
    assert payload["positions"][0]["symbol"] == "SPY"
    names = [item["name"] for item in payload["risk_usage"]]
    assert "largest position" in names
    assert "drawdown from peak" in names


def test_dashboard_exposes_no_state_changing_routes(base_config):
    """This page must stay read-only -- approving a trade happens only on
    the approval dashboard."""
    app = build_status_app(base_config, portfolio_provider=_portfolio)

    methods = set()
    for route in app.routes:
        methods |= getattr(route, "methods", set())

    assert methods <= {"GET", "HEAD"}, f"status dashboard must be read-only, found {methods}"


class TestDemoNotice:
    """demo_notice exists so a deployment with no real kill switch or
    circuit breaker wired in never lets the page assert "trading not
    halted" -- a claim it has no basis to make."""

    def test_demo_notice_is_rendered_prominently(self, base_config):
        app = build_status_app(
            base_config, portfolio_provider=_portfolio, demo_notice="Read-only preview, not connected to a live system."
        )
        body = TestClient(app).get("/").text

        assert "Read-only preview, not connected to a live system." in body

    def test_demo_notice_suppresses_the_all_clear_banner(self, base_config):
        within_limits = PortfolioState(equity=100_000, peak_equity=100_000, cash=100_000)
        app = build_status_app(
            base_config, portfolio_provider=lambda: within_limits, demo_notice="demo only"
        )

        body = TestClient(app).get("/").text

        assert "Trading not halted" not in body

    def test_no_demo_notice_keeps_the_existing_all_clear_banner(self, base_config):
        """Regression guard: real deployments (run_status_dashboard.py,
        run_control_center.py) must keep behaving exactly as before."""
        within_limits = PortfolioState(equity=100_000, peak_equity=100_000, cash=100_000)
        app = build_status_app(base_config, portfolio_provider=lambda: within_limits)

        body = TestClient(app).get("/").text

        assert "Trading not halted" in body

    def test_demo_notice_is_exposed_on_the_json_endpoint(self, base_config):
        app = build_status_app(base_config, portfolio_provider=_portfolio, demo_notice="demo only")

        payload = TestClient(app).get("/api/status").json()

        assert payload["demo_notice"] == "demo only"

    def test_json_endpoint_reports_null_when_no_notice_is_set(self, base_config):
        app = build_status_app(base_config, portfolio_provider=_portfolio)

        payload = TestClient(app).get("/api/status").json()

        assert payload["demo_notice"] is None
