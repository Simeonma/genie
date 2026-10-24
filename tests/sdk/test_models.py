"""genie.models 验收锚（迁移阶段 1a；阶段 ④ 修订懒加载条目）。

覆盖四件事：
1. **expr 纯 stdlib 纪律**（子进程 + 独立文件加载锚）：``expr.py`` 自身
   零 pydantic 依赖——内核薄壳/任何纯环境可单用。阶段 ④ 心脏置换后
   ``import genie`` 必拉 pydantic（_cfg 即 SimConfig 实例，framework §四），
   原「import genie.models.expr 不拉 pydantic」的浏览器镜像纪律随镜像
   退役（阶段 ②），锚改为对 expr.py 文件本体的独立加载断言。
2. **零内核纪律**（AGENTS 铁律 3）：``import genie`` 不 import fdtd。
3. **表面锁**：``__all__`` 与 ``_wire`` 实际定义一致（防加模型忘登记，
   懒加载静默 AttributeError）；内部名（内核薄壳消费）同样可服务。
4. **语义锚**：模型守卫 + expr 正典小 golden + resolve 两段校验/幂等。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SDK = Path(__file__).resolve().parents[2]  # tests/sdk → 仓根 → genie/

BASE_CFG = {
    "domain": {"x_range": [-1e-6, 1e-6], "y_range": [-1e-6, 1e-6],
               "z_range": [-1e-6, 1e-6], "total_time": 60e-15, "cfl": 0.9},
    "mesh": {"dx": 20e-9},
    "source": [{"type": "soft_source", "freq": 300e12, "bandwidth": 60e12}],
    "run": {"gpu": 2},
}


# ---------------------------------------------------------------------------
# 1/2. 懒加载 + 零内核（子进程锚——干净解释器，防本进程已污染）
# ---------------------------------------------------------------------------

def _run_py(code: str) -> str:
    # 子进程守卫（同 conftest，同一份 _tree.py）：干净解释器里先把 genie 钉到
    # 本仓 genie-sdk/，并摘掉共享 venv 挂着的别处 editable 安装——PEP 660 按
    # 精确模块名认领（实证：搬家后 `genie._script` 被解析到另一个树的文件），
    # 不钉则子进程锚会静默测到别处的包。
    boot = (
        "import sys\n"
        f"sys.path.insert(0, {str(_SDK)!r})\n"
        "import _tree\n"
        "_tree.bind_local_genie()\n")
    r = subprocess.run([sys.executable, "-c", boot + code],
                       capture_output=True, text=True, cwd=str(_SDK.parent))
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_expr_module_is_pure_stdlib():
    """expr.py 文件本体零 pydantic（importlib 独立加载，绕开包 __init__——
    阶段 ④ 起 import genie 必拉 pydantic，浏览器镜像纪律随镜像退役）。"""
    out = _run_py(
        "import sys, importlib.util as iu\n"
        "spec = iu.spec_from_file_location("
        "'expr_standalone', %r)\n" % str(_SDK / "genie-sdk" / "models" / "expr.py")
        + "m = iu.module_from_spec(spec); spec.loader.exec_module(m)\n"
        + "assert 'pydantic' not in sys.modules, 'expr.py 混入 pydantic'\n"
        + "assert m.eval_expr('50[nm]') == 50 * 1e-9\n"
        + "print('ok')")
    assert "ok" in out


def test_models_lazy_shell_serves_attributes():
    """models/__init__ 的懒加载壳仍按需服务（SimConfig 触达才载 _wire；
    壳保留供内核薄壳与直接 import genie.models 的消费方，零成本）。"""
    out = _run_py(
        "import sys; sys.path.insert(0, %r)\n" % str(_SDK)
        + "from genie.models import SimConfig, DEFAULT_TIMEOUT_S\n"
        + "cfg = SimConfig.model_validate({\n"
        + "    'domain': {'x_range': [-1, 1], 'y_range': [-1, 1], 'z_range': [-1, 1], 'total_time': 1e-13},\n"
        + "    'mesh': {'dx': 1e-8},\n"
        + "    'source': [{'type': 'soft_source', 'freq': 3e14, 'bandwidth': 6e13}],\n"
        + "    'run': {'gpu': 1}})\n"
        + "assert cfg.run.timeout_s == DEFAULT_TIMEOUT_S\n"
        + "assert sorted('SimConfig' in d for d in [dir(__import__('genie.models', fromlist=['x']))]) == [True]\n"
        + "print('ok')")
    assert "ok" in out


def test_import_genie_never_imports_fdtd():
    out = _run_py(
        "import sys; sys.path.insert(0, %r)\n" % str(_SDK)
        + "import genie, genie.core.script\n"
        + "assert 'fdtd' not in sys.modules, '零内核纪律破坏'\n"
        + "print('ok')")
    assert "ok" in out


# ---------------------------------------------------------------------------
# 3. 表面锁：__all__ ↔ _wire 实际定义，防加模型忘登记
# ---------------------------------------------------------------------------

def test_all_matches_wire_definitions():
    import types
    from genie import models
    import genie_protocol
    from genie_protocol import _wire  # 真源（genie.models 壳只转发，2026-10-27 拆分）
    defined_public = set()
    _TYPING_IMPORTS = {"Union", "Annotated", "Literal", "Optional"}
    for n in dir(_wire):
        if n.startswith("_") or n in _TYPING_IMPORTS:
            continue
        obj = getattr(_wire, n)
        if isinstance(obj, types.ModuleType):
            continue
        # 只算 _wire 自己的表面：import 进来的函数（valid_param_name 来自
        # .expr）排除；typing/builtins 来源的是本文件定义的类型别名
        # （Range2/Vec3/Annotated union 等），算定义。
        mod = getattr(obj, "__module__", None)
        if mod not in (None, _wire.__name__, "typing", "builtins"):
            continue
        defined_public.add(n)
    assert defined_public == set(genie_protocol.__all__), (
        f"真源 _wire 与 genie_protocol.__all__ 漂移：仅一侧有 "
        f"{defined_public ^ set(genie_protocol.__all__)}")
    assert set(models.__all__) == set(genie_protocol.__all__), (
        "genie.models 壳与 genie_protocol 的 __all__ 漂移：仅一侧有 "
        f"{set(models.__all__) ^ set(genie_protocol.__all__)}")
    for n in models.__all__:
        assert getattr(models, n) is not None
    for n in ("_StrictModel", "_RangeModel", "_env_int", "_check_range"):
        assert getattr(models, n) is not None  # 内核薄壳消费的内部名


# ---------------------------------------------------------------------------
# 4a. 模型语义锚（挑代表性守卫；全量守卫归内核 golden，同源已锁）
# ---------------------------------------------------------------------------

def test_simconfig_validates_base():
    from genie.models import SimConfig
    cfg = SimConfig.model_validate(BASE_CFG)
    assert cfg.mesh.dx == 20e-9 and cfg.run.gpu == 2


def test_extra_field_forbidden():
    from pydantic import ValidationError
    from genie.models import SimConfig
    with pytest.raises(ValidationError):
        SimConfig.model_validate({**BASE_CFG, "prioraty": 1})


def test_geometry_name_optional():
    """几何显示名（2026-10-21）：可选、纯表现层、缺省 None、重名拒收。"""
    from genie.models import SimConfig
    base = {**BASE_CFG,
            "materials": [{"type": "const", "name": "sio2", "eps": 2.1}]}
    unnamed = {**base,
               "geometry": [{"type": "sphere", "material": "sio2",
                             "radius": 1e-7}]}
    assert SimConfig.model_validate(unnamed).geometry[0].name is None
    named = {**base,
             "geometry": [{"type": "box", "material": "sio2", "name": "mwj",
                           "x_range": [-1e-7, 1e-7], "y_range": [-1e-7, 1e-7],
                           "z_range": [-1e-7, 1e-7]}]}
    assert SimConfig.model_validate(named).geometry[0].name == "mwj"
    # 未知字段仍然大声报错（严格性未被兼容字段侵蚀）
    import pytest as _pytest
    from pydantic import ValidationError
    with _pytest.raises(ValidationError):
        SimConfig.model_validate({**base, "geometry": [
            {"type": "sphere", "material": "sio2", "radius": 1e-7, "nm": "x"}]})
    # 重名必须 422（未命名对象不参与查重）
    dup = {**base, "geometry": [
        {"type": "sphere", "material": "sio2", "radius": 1e-7, "name": "a"},
        {"type": "sphere", "material": "sio2", "radius": 2e-7, "name": "a"}]}
    with _pytest.raises(ValidationError, match="duplicate geometry name"):
        SimConfig.model_validate(dup)
    two_anon = {**base, "geometry": [
        {"type": "sphere", "material": "sio2", "radius": 1e-7},
        {"type": "sphere", "material": "sio2", "radius": 2e-7}]}
    assert len(SimConfig.model_validate(two_anon).geometry) == 2


def test_material_color_optional_and_normalized():
    """材料显示色（2026-10-21）：可选、归一为 #RRGGBB 大写、非法 422。"""
    import pytest as _pytest
    from pydantic import ValidationError
    from genie.models import SimConfig
    base = {**BASE_CFG,
            "materials": [{"type": "const", "name": "sio2", "eps": 2.1}]}
    # 缺省 = None（存量 payload 零扰动）
    assert SimConfig.model_validate(base).materials[0].color is None
    # 大小写/缺 # 都归一
    ok = {**BASE_CFG,
          "materials": [{"type": "const", "name": "sio2", "eps": 2.1,
                         "color": "4a7fb5"}]}
    assert SimConfig.model_validate(ok).materials[0].color == "#4A7FB5"
    # 非法色值大声报错（不静默回退）
    bad = {**BASE_CFG,
           "materials": [{"type": "const", "name": "sio2", "eps": 2.1,
                          "color": "sage"}]}
    with _pytest.raises(ValidationError, match="color"):
        SimConfig.model_validate(bad)


def test_pole_requires_gamma():
    from pydantic import ValidationError
    from genie.models import SimConfig
    bad = {**BASE_CFG,
           "materials": [{"type": "lorentz", "name": "m",
                          "poles": [{"kind": "lorentz", "omega_0": 1e15}]}]}
    with pytest.raises(ValidationError, match="gamma"):
        SimConfig.model_validate(bad)


def test_boundary_periodic_needs_pair():
    from pydantic import ValidationError
    from genie.models import SimConfig
    bad = {**BASE_CFG, "domain": {**BASE_CFG["domain"],
           "boundary": {"z_min": {"kind": "periodic"}}}}
    with pytest.raises(ValidationError, match="must be paired"):
        SimConfig.model_validate(bad)


def test_wire_constants():
    from genie.models import (DEFAULT_TIMEOUT_S, FACES, MAX_SWEEP_AXES,
                              MAX_SWEEP_POINTS)
    assert DEFAULT_TIMEOUT_S == 3600
    assert MAX_SWEEP_AXES == 32 and MAX_SWEEP_POINTS == 512
    assert FACES == ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")


# ---------------------------------------------------------------------------
# 4b. expr 正典小 golden（全量语料 = 内核 expr_golden.json，同源同实现）
# ---------------------------------------------------------------------------

def test_expr_mini_golden():
    from genie.models.expr import ExprError, eval_expr
    assert eval_expr("1 + 2*3") == 7
    assert eval_expr("sqrt(4) + max(1, 2)") == 4
    assert eval_expr("50[nm]") == 50 * 1e-9        # 与内核 e2e 同款字面量
    assert eval_expr("1[µm]") == 1e-6              # Unicode 别名
    assert eval_expr("a*2", {"a": 21}) == 42
    for expr, kind in [("1 +", "syntax"), ("b", "unknown_name"),
                       ("1[ly]", "unknown_unit"), ("__import__('os')", "illegal_node"),
                       ("1/0", "math"), ('"s"', "nonatomic")]:
        with pytest.raises(ExprError) as ei:
            eval_expr(expr)
        assert ei.value.kind == kind, (expr, ei.value.kind)


# ---------------------------------------------------------------------------
# 4c. resolve：表达式槽 + 幂等 + guard 档错误指路
# ---------------------------------------------------------------------------

def test_resolve_parameters_slots_and_idempotent():
    from genie.models.resolve import resolve_parameters
    raw = {**BASE_CFG, "parameters": {"d": "50[nm]"},
           "mesh": {"dx": "d"}}
    out = resolve_parameters(raw)
    assert out["mesh"]["dx"] == 50 * 1e-9
    assert resolve_parameters(BASE_CFG) == BASE_CFG   # 幂等锚（零扰动）


def test_validate_resolved_expr_guard_kind():
    from genie.models.expr import ExprError
    from genie.models.resolve import resolve_parameters_detailed, validate_resolved
    raw = {**BASE_CFG, "parameters": {"bad": "-1[nm]"},
           "mesh": {"dx": "bad"}}
    resolved, expr_at = resolve_parameters_detailed(raw)
    with pytest.raises(ExprError) as ei:
        validate_resolved(resolved, expr_at)
    assert ei.value.kind == "guard" and "mesh.dx" in ei.value.msg


# ---------------------------------------------------------------------------
# 4d. validate_for_ui：设计态预检的唯一实现（/api/validate 与 agent 工具共用）
# ---------------------------------------------------------------------------

def test_validate_for_ui_ok_and_shape():
    from genie.models.resolve import validate_for_ui
    assert validate_for_ui(BASE_CFG) == []
    assert validate_for_ui("not-a-dict")[0]["loc"] == ""


def test_validate_for_ui_catches_bad_param_name():
    """参数键名检查必须在**所有**入口生效（收口前 agent 路径漏掉它）。"""
    from genie.models.resolve import validate_for_ui
    raw = {**BASE_CFG, "parameters": {"1bad": 1}}
    errs = validate_for_ui(raw)
    assert errs and "parameter name" in errs[0]["msg"]


def test_validate_for_ui_carries_config_path():
    from genie.models.resolve import validate_for_ui
    raw = {**BASE_CFG, "mesh": {"dx": -1.0}}
    errs = validate_for_ui(raw)
    assert errs and errs[0]["loc"] == "mesh.dx"


def test_validate_for_ui_expr_error_kind_prefix():
    from genie.models.resolve import validate_for_ui
    raw = {**BASE_CFG, "mesh": {"dx": "nope*2"}}
    errs = validate_for_ui(raw)
    assert errs and errs[0]["msg"].startswith("unknown_name:")


def test_submit_precheck_uses_same_verdict():
    """提交前预检与 UI 预检同判定：同一份坏配置两边都要拒。"""
    from genie.core.simulate import _validate_for_submit
    from genie.models.errors import GenieConfigError
    raw = {**BASE_CFG, "parameters": {"1bad": 1}}
    with pytest.raises(GenieConfigError) as ei:
        _validate_for_submit(raw)
    assert "parameter name" in str(ei.value)
