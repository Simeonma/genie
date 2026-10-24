"""genie.models.resolve — 兼容薄壳：真源已迁 genie_protocol.resolve（本仓 protocol/ 子目录，2.0.0a9 起）。"""
import genie_protocol.resolve as _impl

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
__all__ = list(getattr(_impl, "__all__", ()))