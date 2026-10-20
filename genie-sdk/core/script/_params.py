from __future__ import annotations

"""参数节渲染 —— ``# parameters`` 块。

全表拓扑求值 → 失败逐参兜底 → 逐行声明式发射；求值正典 =
genie.models.expr（迁移阶段 1a 起单一正典），本模块只有渲染关注点。
"""
from ...models.expr import (ExprError, eval_expr,
                           resolve_parameter_table, valid_param_name)
from ._emit import _expr_to_py
from ._numfmt import _clean_num, _js_string, _json_value, py_num


def _resolve_params(params: dict, W: list) -> tuple[dict, dict]:
    """全表拓扑求值 → 失败逐参兜底。"""
    keys = list(params)
    try:
        resolved = resolve_parameter_table(params)
        env = {}
        for k in keys:
            raw = params[k]
            env[k] = (raw if isinstance(raw, (int, float)) and not isinstance(raw, bool)
                      else _clean_num(resolved[k]))
        return env, {}
    except Exception:  # noqa: BLE001 —— 全表失败即逐参兜底（镜像 JS catch-all）
        pass
    env = {}
    failed = {}
    resolved = {}
    for k in keys:
        raw = params[k]
        v = 0
        err = None
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            v = raw
        elif isinstance(raw, str):
            try:
                v = _clean_num(eval_expr(raw, resolved))
            except ExprError as e:
                err = e
                v = 0
        else:
            err = ExprError("syntax", "表达式求值器缺失")
        if err is not None:
            failed[k] = (err.kind or "syntax") + ": " + (err.msg or str(err))
            W.append(f"parameters.{k} 求值失败（{failed[k]}）——已用 0 占位")
            v = 0
        env[k] = v
        resolved[k] = v
    return env, failed

def _gen_params(cfg: dict, W: list) -> tuple[list[str], dict]:
    """``# parameters`` 块（仅参数非空时出现）。
    返回 (lines, env)——env 供字段槽求值失败检测（R2 声明式发射）。"""
    params = cfg.get("parameters")
    if not isinstance(params, dict) or not params:
        return [], {}
    all_keys = list(params)
    lines = ["# parameters"]
    valid: dict = {}
    for k in all_keys:
        if valid_param_name(k):
            valid[k] = params[k]
        else:
            W.append(f"parameters.{_js_string(k)} 名非法（须标识符 ≤64 字符）——未发射变量")
            lines.append(f"# 参数 {_json_value(k)} 名非法（须标识符 ≤64 字符）——未发射变量")
    if not valid:
        lines.append("")
        return lines, {}
    env, failed = _resolve_params(valid, W)
    for k in all_keys:
        if not valid_param_name(k):
            continue
        raw = params[k]
        f = failed.get(k)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            lit = py_num(env[k])
            tail = ""
        elif f:
            lit = "0"
            tail = f"（求值失败: {f}）"
        else:
            lit = _expr_to_py(raw)
            tail = ""
        lines.append(f"{k} = {lit}  # 原文 {_json_value(raw)}" + tail)
    lines.append("")
    return lines, env
