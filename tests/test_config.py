"""Tests for configuration loading and persistence."""
from pdffiller.config import LLMConfig, save_to_env


def test_timeout_from_env(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "180")
    cfg = LLMConfig.from_env()
    assert cfg.timeout == 180.0


def test_timeout_default(monkeypatch):
    monkeypatch.delenv("LLM_TIMEOUT", raising=False)
    cfg = LLMConfig.from_env()
    assert cfg.timeout == 180.0


def test_save_to_env_writes_timeout(tmp_path):
    cfg = LLMConfig(api_key="test-key", timeout=180.0, verify_ssl=False)
    env_path = tmp_path / ".env"
    save_to_env(cfg, env_path)
    text = env_path.read_text(encoding="utf-8")
    assert "LLM_TIMEOUT=180.0" in text
    assert "LLM_SSL_VERIFY=false" in text


def test_ensure_direct_connection_clears_inherited_proxies(monkeypatch):
    import os

    from pdffiller.config import ensure_direct_connection

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.corp:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp:8080")
    monkeypatch.setenv("http_proxy", "http://proxy.corp:8080")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.corp:8080")
    ensure_direct_connection()
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        assert os.environ.get(var) is None
