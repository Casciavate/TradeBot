from __future__ import annotations

from risk_gate.kill_switch import KillSwitch


def test_kill_switch_starts_disengaged(kill_switch: KillSwitch):
    assert not kill_switch.is_engaged()
    assert kill_switch.reason() is None


def test_kill_switch_engage_and_disengage(kill_switch: KillSwitch):
    kill_switch.engage("manual test halt")
    assert kill_switch.is_engaged()
    assert kill_switch.reason() == "manual test halt"

    kill_switch.disengage()
    assert not kill_switch.is_engaged()


def test_kill_switch_is_independent_of_rest_of_system(tmp_path):
    # A kill switch triggered by touching the file directly (e.g. from a
    # shell, with no Python process involved) must still be observed.
    path = tmp_path / "KILL_SWITCH"
    path.write_text("halted externally")

    ks = KillSwitch(path=path)
    assert ks.is_engaged()
    assert ks.reason() == "halted externally"


def test_disengage_when_never_engaged_is_a_no_op(kill_switch: KillSwitch):
    kill_switch.disengage()
    assert not kill_switch.is_engaged()
