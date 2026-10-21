"""服务发现与本地身份配置（G72a，2026-10-23）——零配置面的机制层。

优先级链（高 → 低）::

    显式参数 > env（GENIE_URL / GENIE_API_KEY / GENIE_USERNAME）
             > ~/.genie/config.json > DEFAULT_GATEWAY

- ``config.json`` 由 ``genie connect <url>`` 写入（0600）；里面是**用户
  身份面**（gateway / api_key / username）。``~/.genie/studio.json`` 是
  本机会话门牌（会话路由），两回事，两文件不混。
- ``DEFAULT_GATEWAY`` 留空是刻意的：内网地址不得进公开面（红线）；公开
  域名定案后填常量、发一版，全体用户零感知切换（G72 方案）。
- 只在 net 层碰磁盘与 env（分层：本模块是 IO，models 之上）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

#: 缺省网关。None = 未定案：无参 connect 会得到"下一步动作"式报错而非猜测。
DEFAULT_GATEWAY: str | None = None


def config_path() -> Path:
    """身份配置文件路径（``~/.genie/config.json``）。"""
    return Path.home() / ".genie" / "config.json"


def load_config() -> dict:
    """读身份配置；缺失/损坏一律返回 {}（坏文件不当配置用，由 resolve 指路）。"""
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {}


def save_config(*, gateway: str | None = None, api_key: str | None = None,
                username: str | None = None) -> Path:
    """合并写入身份配置（None 字段不动现有值），0600。返回文件路径。"""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cfg = {**load_config(),
           **{k: v for k, v in
              (("gateway", gateway), ("api_key", api_key),
               ("username", username)) if v is not None}}
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:      # Windows FAT 等无 POSIX 权限的文件系统：尽力而为
        pass
    return p


def resolve_gateway(explicit: str | None = None) -> str:
    """按优先级链解析网关地址；解析不出 → 报错并给**下一步动作**。

    顺序：显式参数 > env ``GENIE_URL`` > config.json ``gateway``
    > ``DEFAULT_GATEWAY``。
    """
    from ..models.errors import GenieConfigError
    for cand in (explicit,
                 os.environ.get("GENIE_URL") or None,
                 load_config().get("gateway") or None,
                 DEFAULT_GATEWAY):
        if cand and str(cand).strip():
            return str(cand).strip().rstrip("/")
    raise GenieConfigError(
        "未配置网关地址。三选一：\n"
        "  ① genie connect <服务地址>      写入本机配置（推荐，一次即可）\n"
        "  ② set GENIE_URL=<服务地址>      环境变量\n"
        "  ③ genie.connect(<服务地址>)     脚本里显式传参")


def resolve_credential(explicit: str | None, env_name: str,
                       config_key: str) -> str | None:
    """凭据解析：显式参数 > env > config.json。缺省返回 None（不猜）。"""
    return (explicit
            or os.environ.get(env_name) or None
            or load_config().get(config_key) or None)
