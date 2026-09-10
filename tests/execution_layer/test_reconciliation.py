from __future__ import annotations

from execution_layer.reconciliation import reconcile_positions


def test_no_discrepancies_when_positions_match():
    local = {"SPY": 10.0, "QQQ": 5.0}
    ibkr = {"SPY": 10.0, "QQQ": 5.0}
    assert reconcile_positions(local, ibkr) == []


def test_detects_quantity_mismatch():
    local = {"SPY": 10.0}
    ibkr = {"SPY": 8.0}
    [discrepancy] = reconcile_positions(local, ibkr)
    assert discrepancy.symbol == "SPY"
    assert discrepancy.difference == 2.0


def test_detects_position_missing_locally():
    local = {}
    ibkr = {"SPY": 10.0}
    [discrepancy] = reconcile_positions(local, ibkr)
    assert discrepancy.local_quantity == 0.0
    assert discrepancy.ibkr_quantity == 10.0


def test_detects_position_missing_at_broker():
    local = {"SPY": 10.0}
    ibkr = {}
    [discrepancy] = reconcile_positions(local, ibkr)
    assert discrepancy.ibkr_quantity == 0.0


def test_tiny_floating_point_differences_are_not_flagged():
    local = {"SPY": 10.0000001}
    ibkr = {"SPY": 10.0}
    assert reconcile_positions(local, ibkr) == []


class TestReconciliationAlerts:
    """A local-vs-IBKR mismatch is never silently patched over -- it raises
    a CRITICAL alert for a human to look at."""

    @staticmethod
    def _router(tmp_path):
        from monitoring.alerts import AlertRouter
        from monitoring.audit_log import AuditLog

        return AlertRouter(audit_log=AuditLog(tmp_path / "alerts.log"), throttle_seconds=0)

    def test_matching_positions_raise_no_alert(self, tmp_path):
        router = self._router(tmp_path)

        reconcile_positions({"SPY": 10.0}, {"SPY": 10.0}, alert_router=router)

        assert [r for r in router.audit_log.read_all() if r["event_type"] == "alert"] == []

    def test_a_mismatch_raises_a_critical_alert_naming_the_symbols(self, tmp_path):
        router = self._router(tmp_path)

        reconcile_positions({"SPY": 10.0, "QQQ": 5.0}, {"SPY": 8.0}, alert_router=router)

        [alert] = [r for r in router.audit_log.read_all() if r["event_type"] == "alert"]
        assert alert["kind"] == "position_reconciliation_mismatch"
        assert alert["severity"] == "CRITICAL"
        assert set(alert["details"]["symbols"]) == {"SPY", "QQQ"}

    def test_reconciliation_still_returns_discrepancies_without_a_router(self):
        [discrepancy] = reconcile_positions({"SPY": 10.0}, {"SPY": 8.0})

        assert discrepancy.symbol == "SPY"
