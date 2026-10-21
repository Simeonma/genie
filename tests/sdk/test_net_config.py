"""G72a/④：网关/凭据解析优先级链 + `genie connect` CLI。

链（高→低）：显式参数 > env > ~/.genie/credentials.json > DEFAULT_GATEWAY。
config 路径在测试里整体替换为 tmp（不碰真实 ~/.genie）。
"""
from __future__ import annotations

import json

import pytest

from genie.models.errors import GenieConfigError
from genie.net import config as ncfg


@pytest.fixture()
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "genie-config.json"
    monkeypatch.setattr(ncfg, "config_path", lambda: p)
    return p


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("GENIE_URL", "GENIE_API_KEY", "GENIE_USERNAME"):
        monkeypatch.delenv(k, raising=False)


def test_nothing_configured_gives_actionable_error(cfg_path):
    with pytest.raises(GenieConfigError) as ei:
        ncfg.resolve_gateway(None)
    # 报错必须带下一步动作（G72 ④ 失败即指引）
    assert "genie connect" in str(ei.value)
    assert "GENIE_URL" in str(ei.value)


def test_explicit_beats_env_beats_config(cfg_path, monkeypatch):
    ncfg.save_config(gateway="https://from-config")
    monkeypatch.setenv("GENIE_URL", "https://from-env")
    assert ncfg.resolve_gateway("https://explicit") == "https://explicit"
    assert ncfg.resolve_gateway(None) == "https://from-env"
    monkeypatch.delenv("GENIE_URL")
    assert ncfg.resolve_gateway(None) == "https://from-config"
    assert ncfg.resolve_gateway(None).endswith("/") is False  # 去尾斜杠


def test_save_config_merges_and_masks_nothing(cfg_path):
    ncfg.save_config(gateway="https://gw")
    ncfg.save_config(api_key="k1", username="majw")
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data == {"gateway": "https://gw", "api_key": "k1",
                    "username": "majw"}


def test_corrupt_config_is_empty_not_fatal(cfg_path):
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("{not json", encoding="utf-8")
    assert ncfg.load_config() == {}
    with pytest.raises(GenieConfigError):
        ncfg.resolve_gateway(None)


def test_cli_connect_writes_config_and_show(cfg_path, capsys):
    from genie.__main__ import main
    assert main(["connect", "https://gw.example",
                 "--username", "majw"]) == 0
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["gateway"] == "https://gw.example"
    assert data["username"] == "majw"
    # 无 url = show：不抛、不泄露 key 字段
    assert main(["connect"]) == 0
    out = capsys.readouterr().out
    assert "https://gw.example" in out
    assert "api_key" not in out


def test_studio_config_gateway_fallback(cfg_path, monkeypatch):
    from genie.studio import kernel_session as ks
    monkeypatch.delenv("GENIE_BACKEND", raising=False)
    monkeypatch.delenv("GENIE_INTERNAL_BACKEND", raising=False)
    assert ks.backend() == "http://127.0.0.1:9100"   # 无配置 → 本机缺省
    ncfg.save_config(gateway="https://cfg-gw")
    assert ks.backend() == "https://cfg-gw"          # config 兜底生效
    monkeypatch.setenv("GENIE_BACKEND", "http://env-beats")
    assert ks.backend() == "http://env-beats"        # env 仍是部署覆盖项


def test_connect_uses_config_gateway(cfg_path, monkeypatch):
    import genie
    ncfg.save_config(gateway="https://cfg-gw", api_key="cfg-key")
    s = genie.connect()
    assert s._client.base_url == "https://cfg-gw"    # 无参 connect 读链
