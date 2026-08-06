import pytest

from app import reset_demo_data


def test_rejects_when_app_env_is_production(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_SEED", "true")

    with pytest.raises(SystemExit) as exc_info:
        reset_demo_data.main()

    assert exc_info.value.code == 1
    assert "production" in capsys.readouterr().err


def test_rejects_when_demo_seed_is_not_true(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("DEMO_SEED", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        reset_demo_data.main()

    assert exc_info.value.code == 1
    assert "DEMO_SEED=true" in capsys.readouterr().err
