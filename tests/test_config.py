from janus.config import Settings


def test_defaults(monkeypatch):
    for key in (
        "JANUS_LABEL_PREFIX",
        "JANUS_DEFAULT_INTERVAL",
        "JANUS_STOP_TIMEOUT",
        "JANUS_MAX_CONCURRENT_UPDATES",
        "JANUS_LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)

    s = Settings.from_env()
    assert s.label_prefix == "janus.autoupdate"
    assert s.default_interval == 300
    assert s.stop_timeout == 10
    assert s.max_concurrent_updates == 1
    assert s.log_level == "INFO"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("JANUS_LABEL_PREFIX", "myapp.update")
    monkeypatch.setenv("JANUS_DEFAULT_INTERVAL", "60")
    monkeypatch.setenv("JANUS_STOP_TIMEOUT", "30")
    monkeypatch.setenv("JANUS_MAX_CONCURRENT_UPDATES", "4")
    monkeypatch.setenv("JANUS_LOG_LEVEL", "debug")

    s = Settings.from_env()
    assert s.label_prefix == "myapp.update"
    assert s.default_interval == 60
    assert s.stop_timeout == 30
    assert s.max_concurrent_updates == 4
    assert s.log_level == "DEBUG"  # uppercased by from_env
