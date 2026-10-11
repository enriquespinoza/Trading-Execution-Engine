import json

import scripts.run_e2e_sms_approval_simulation as e2e


def test_create_and_load_scenario(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setattr(e2e, "STATE_DIR", state_dir)
    monkeypatch.setattr(e2e, "SCENARIO_PATH", state_dir / "scenario.json")
    monkeypatch.setattr(e2e, "APPROVAL_PATH", state_dir / "approvals.json")

    scenario = e2e.create_scenario()
    loaded = e2e.load_scenario()

    assert loaded == scenario
    assert scenario["symbol"] == "TEST"
    assert scenario["side"] == "BUY"
    assert scenario["quantity"] == 2.0
    assert scenario["price"] == 100.0
    assert scenario["starting_cash"] == 1000.0


def test_reset_removes_e2e_state(tmp_path, monkeypatch, capsys):
    state_dir = tmp_path / "state"
    scenario_path = state_dir / "scenario.json"
    approval_path = state_dir / "approvals.json"
    state_dir.mkdir()
    scenario_path.write_text(json.dumps({"x": 1}), encoding="utf-8")
    approval_path.write_text(json.dumps({"y": 2}), encoding="utf-8")

    monkeypatch.setattr(e2e, "STATE_DIR", state_dir)
    monkeypatch.setattr(e2e, "SCENARIO_PATH", scenario_path)
    monkeypatch.setattr(e2e, "APPROVAL_PATH", approval_path)

    e2e.command_reset()

    assert not scenario_path.exists()
    assert not approval_path.exists()
    assert "state reset" in capsys.readouterr().out.lower()
