"""genie.models.sweep_expand — 兼容薄壳：真源已迁 genie_protocol.sweep_expand（本仓 protocol/ 子目录，2.0.0a9 起）。"""
import genie_protocol.sweep_expand as _impl

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
__all__ = list(getattr(_impl, "__all__", ()))