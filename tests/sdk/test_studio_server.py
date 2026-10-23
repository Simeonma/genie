"""v2 静态服务的锁测试：health / index / vendor / 路径守卫 / 门面转发。"""
from __future__ import annotations

import json
import os
import pathlib

from fastapi.testclient import TestClient




class FakeSession:
    """会话客户端的测试替身：记录调用、返回罐头。

    只服务"Studio 门面把它转给了会话、参数对不对、状态码穿不穿透"这类
    断言；**真会话语义**（attach/重放/session 隔离）在
    test_session_service.py 与 test_kernel_session.py 里用真进程验。
    """

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.gateway_reply = (200, b'{"ok": true}', "application/json")

    def _rec(self, name, **kw):
        self.calls.append((name, kw))

    def of(self, name):
        return [kw for n, kw in self.calls if n == name]

    # 会话面
    def exec(self, code, **kw):
        self._rec("exec", code=code, **kw)
        return {"id": 7}

    def output(self, **kw):
        self._rec("output", **kw)
        return {"lines": [], "busy": False, "phase": "idle", "cfg": None,
                "cfg_seq": 0}

    def stop(self, **kw):
        self._rec("stop", **kw)
        return {"stopped": False}

    def load_config(self, cfg, **kw):
        self._rec("load_config", cfg=cfg, **kw)
        return {"ok": True}

    def patch(self, ops, **kw):
        self._rec("patch", ops=ops, **kw)
        return {"id": 8}

    def replace(self, model, **kw):
        self._rec("replace", model=model, **kw)
        return {"id": 9}

    def attach(self, **kw):
        self._rec("attach", **kw)
        return {"session_id": kw.get("session_id"), "key_changed": True,
                "alive": True}

    def result_meta(self, **kw):
        self._rec("result_meta", **kw)
        return {"ok": True, "monitors": []}

    def result_series(self, **kw):
        self._rec("result_series", **kw)
        return {"ok": True}

    def health(self):
        return {"ok": True, "upstream": "http://stub", "sdk_version": "x"}

    # 网关面
    def gateway(self, method, path, **kw):
        self._rec("gateway", method=method, path=path, **kw)
        return self.gateway_reply


# 旧形态靠 `genie.studio.server:app` 的模块级实例（它的会话地址默认指向
# 已退役的 :8123）。现在必须先有会话：这里注入 FakeSession，与本地
# `genie studio` 显式注入 LocalSessionHost 同构。
from genie.studio.server import create_app  # noqa: E402

client = TestClient(create_app(mount_session=True, session=FakeSession()))


def _app(**kw):
    """带替身会话的 Studio（测试统一入口，绝不碰真 :8123）。"""
    from genie.studio.server import create_app
    fake = kw.pop("session", None) or FakeSession()
    return TestClient(create_app(mount_session=True, session=fake, **kw)), fake


def test_health_reports_auth_requirement():
    """health 必须告诉前端"要不要登录"——免登录启动时 auth_required=False。"""
    j = client.get("/api/health").json()
    assert "auth_required" in j
    assert j["auth_required"] is False     # conftest 设了 GENIE_STUDIO_OPEN=1


def test_require_auth_gates_every_local_capability():
    """站长裁决 2026-10-21：未登录什么都不给做——本地能力一律 401。"""
    from genie.studio.server import create_app
    c = TestClient(create_app(require_auth=True, mount_session=True,
                              session=FakeSession()))
    assert c.get("/api/health").json()["auth_required"] is True
    assert c.get("/api/health").status_code == 200      # health 永远开放

    # 本地能力：validate / drafts / scripts / workspace / sim /
    # 会话面（O2：attach 也在闸内——没凭据的 attach 没有意义）
    # （G50 已删 /api/preview 与 /api/scripts 列表/save 两个孤儿路由）
    cases = [
        ("post", "/api/validate", {"cfg": {}}),
        ("get", "/api/scripts/read?name=x.py", None),
        ("get", "/api/workspace/files", None),
        ("post", "/api/sim/export", {}),
        ("post", "/api/session/attach", None),
        ("post", "/api/exec", {"code": "1"}),
        ("get", "/api/exec/output", None),
    ]
    for method, path, body in cases:
        r = (c.post(path, json=body) if method == "post" else c.get(path))
        assert r.status_code == 401, f"{path} 未登录应 401，实际 {r.status_code}"
        assert "未登录" in r.json()["detail"]


def test_require_auth_accepts_any_non_empty_key():
    """闸门只认"有没有 token"（token 真伪由上游校验，本地不联网）。
    带 key 的本地能力请求不再被 401 拦下（业务错另说）。"""
    from genie.studio.server import create_app
    guarded = create_app(require_auth=True)
    c = TestClient(guarded)
    r = c.post("/api/validate", json={"cfg": {}},
               headers={"X-API-Key": "tok-xyz"})
    assert r.status_code != 401


def test_session_attach_requires_key_and_forwards():
    """O2：/api/session/attach 未登录 401；带 key 时把 (key, owner,
    session_id) 交给会话——**不带后端地址**（后端是会话的部署属性）。"""
    c, fake = _app(require_auth=True)
    assert c.post("/api/session/attach").status_code == 401

    r = c.post("/api/session/attach",
               headers={"X-API-Key": "tok-abc", "X-Session-Id": "s-42"})
    assert r.status_code == 200
    assert r.json()["session_id"] == "s-42"
    (kw,) = fake.of("attach")
    assert kw["key"] == "tok-abc"
    assert kw["owner"]                       # owner 必带（工作区按人隔离）
    assert kw["session_id"] == "s-42"
    assert "url" not in kw, "后端地址不得随请求走（O2）"


def test_session_id_defaults_to_single_session():
    """未送 X-Session-Id 的旧客户端（云宿主/旧页面）落到 "default" 单会话
    ——升级零破坏。"""
    c, fake = _app()
    c.post("/api/session/attach", headers={"X-API-Key": "k"})
    (kw,) = fake.of("attach")
    assert kw["session_id"] == "default"


def test_session_id_rejects_path_traversal():
    """session_id 会当目录名用 → 白名单（同 owner 规则）。"""
    c, _ = _app()
    r = c.post("/api/session/attach",
               headers={"X-API-Key": "k", "X-Session-Id": "../etc"})
    assert r.status_code == 422


def test_exec_and_output_forward_session_id():
    """terminal 三端点同一个 session_id——GUI 的键盘落在自己那份模型上。"""
    c, fake = _app()
    h = {"X-API-Key": "k", "X-Session-Id": "s1"}
    assert c.post("/api/exec", json={"code": "print(1)"},
                  headers=h).json() == {"id": 7}
    c.get("/api/exec/output", params={"since": 5}, headers=h)
    # 旧名 /api/exec/load_config（整份推送）→ 现在落到 replace 原语
    c.post("/api/exec/load_config", json={"cfg": {"a": 1}}, headers=h)
    # 新名：路径级增量 + 整份替换
    c.post("/api/model/patch",
           json={"ops": [{"path": "domain.cfl", "value": 0.5}]}, headers=h)
    c.post("/api/model/replace", json={"model": {"b": 2}}, headers=h)
    assert fake.of("exec")[0]["session_id"] == "s1"
    assert fake.of("output")[0]["session_id"] == "s1"
    assert fake.of("output")[0]["since"] == 5
    assert fake.of("replace")[0]["model"] == {"a": 1}
    assert fake.of("replace")[1]["model"] == {"b": 2}
    assert fake.of("patch")[0]["ops"] == [{"path": "domain.cfl", "value": 0.5}]
    assert fake.of("patch")[0]["session_id"] == "s1"


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["service"] == "genie-studio"


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "GENIE" in r.text and "Nanophotonic" in r.text
    assert 'id="code-editor"' in r.text


def test_vendor_assets_served():
    assert client.get("/vendor/three.min.js").status_code == 200
    # 阶段 ②（framework §四「Pyodide 删掉」）：镜像与 worker 已删，404 即正确
    assert client.get("/vendor/genie_sdk/manifest.json").status_code == 404
    assert client.get("/pyworker.js").status_code == 404


# （原 test_preview_endpoint_roundtrip / test_preview_endpoint_error_paths
#  已随 G50 删 /api/preview 孤儿路由而删除——preview 语义由
#  genie.preview_script() 本地函数承载，有 test_models.py 直测覆盖。）


def test_examples_served():
    r = client.get("/examples/manifest.json")
    assert r.status_code == 200
    r2 = client.get("/examples/01_basic.py")
    assert r2.status_code == 200
    assert "genie.connect" in r2.text


def test_manual_served():
    """手册站点独立挂载（内容面不在 studio/static 下）——入口 URL 不变。"""
    r = client.get("/manual/commands/index.html")
    assert r.status_code == 200
    assert "GENIE SDK Documentation" in r.text
    # 手册页内的相对链接（figs/*.svg）必须同样可达
    assert client.get("/manual/commands/figs/fig-domain.svg").status_code == 200


def test_path_traversal_blocked():
    assert client.get("/../conftest.py").status_code == 404
    assert client.get("/%2e%2e/conftest.py").status_code == 404


def test_display_contract_in_ui():
    """v2 定案守卫（2026-10-10 terminal 战役修订）：主区上下分块——
    上=3D/Plot 标签卡，下=Terminal（会话命令面）；脚本编辑器=纯文本
    编辑器，运行=整体 exec 运行即生效——应用到场景/放弃编辑/脏标全部
    退场。本测试锁静态面；动态不变量由 e2e 锁。"""
    html = client.get("/").text
    for need in ("obj-tree", "config-panel", "three-container", "code-editor",
                 "term-dock", "term-in", "term-out"):
        assert need in html, f"显示链路缺 {need}"
    for gone in ("code-apply", "code-discard", "code-dirty", "model-dirty",
                 "py-run-out-wrap"):
        assert gone not in html, f"旧脚本工作流件 {gone} 应已退场"
    # G5 拆分（2026-10-14）：契约锚改为全模块拼接文本（app.js 已拆为
    # modules/*，锚的语义不变——锁的是接线行为不是文件形状）
    static = (pathlib.Path(__file__).resolve().parents[2] / "genie-sdk"
              / "studio" / "static")
    js = "\n".join((static / "modules" / f).read_text(encoding="utf-8")
                   for f in ("boot.js", "toolbar.js", "term.js"))
    assert 'addEventListener("click", runScript)' in js, \
        "run-py 必须接 runScript（脚本→Terminal 整体 exec）"
    assert 'termExec("f.run()")' in js, \
        "工具栏 Run 必须走 terminal（f.run 真提交）"
    assert "submitJob" not in js and "treeAdd(" not in js, \
        "前端不得出现提交/添加实现（编辑器官不接线定案）"


def test_drafts_roundtrip():
    """SDK→Studio 实时通道：POST /api/drafts → GET /__drafts since 增量。"""
    r = client.post("/api/drafts", json={"label": "t", "script": "import genie\n"})
    assert r.status_code == 200 and r.json()["ok"]
    seq = r.json()["seq"]
    items = client.get("/__drafts", params={"since": 0}).json()
    assert any(i["seq"] == seq and i["script"].startswith("import genie") for i in items)
    # since 增量：老 seq 之后只剩新的
    later = client.post("/api/drafts", json={"label": "t2", "script": "# x"}).json()
    items2 = client.get("/__drafts", params={"since": seq}).json()
    assert [i["seq"] for i in items2] == [later["seq"]]


def test_drafts_validation():
    assert client.post("/api/drafts", json={"label": "t", "script": ""}).status_code == 422
    assert client.post("/api/drafts", json={"label": "t", "script": "x" * 300_000}).status_code == 413


def test_scripts_read_with_workspace(tmp_path, monkeypatch):
    """脚本 read 端点（G50 后 scripts 面仅剩此路由）+ 名字校验。"""
    from genie.studio.server import create_app
    monkeypatch.setenv("GENIE_SCRIPTS_DIR", str(tmp_path / "scripts"))
    monkeypatch.delenv("GENIE_SCRIPTS_OWNER", raising=False)
    c = TestClient(create_app())
    # 经 workspace 上传创建 .py（save 端点已随 G50 删）
    c.post("/api/workspace/upload",
           files={"file": ("hello.py", b"print(1)", "text/x-python")})
    assert (tmp_path / "scripts" / "local" / "hello.py").read_text(
        encoding="utf-8") == "print(1)"
    r = c.get("/api/scripts/read", params={"name": "hello.py"})
    assert r.json() == {"name": "hello.py", "text": "print(1)"}
    # 名字校验：路径穿越拒收
    assert c.get("/api/scripts/read",
                 params={"name": "../evil"}).status_code == 422


def test_scripts_owner_fn_injection(tmp_path, monkeypatch):
    """B1 owner 化锚：owner_fn 注入 → read 端点走 <根>/<owner>/。"""
    from genie.studio.server import create_app
    monkeypatch.setenv("GENIE_SCRIPTS_DIR", str(tmp_path / "scripts"))
    monkeypatch.delenv("GENIE_SCRIPTS_OWNER", raising=False)
    c = TestClient(create_app(owner_fn=lambda req: "tester"))
    c.post("/api/workspace/upload",
           files={"file": ("t.py", b"x=1", "text/x-python")})
    d = tmp_path / "scripts" / "tester"
    assert (d / "t.py").read_text(encoding="utf-8") == "x=1"
    assert c.get("/api/scripts/read",
                 params={"name": "t.py"}).json() == \
        {"name": "t.py", "text": "x=1"}
    # 缺省 owner（"local"）视角看不到 tester 的文件——按人隔离
    c2 = TestClient(create_app())
    assert c2.get("/api/scripts/read",
                  params={"name": "t.py"}).status_code == 404


def _png_bytes() -> bytes:
    """最小合法 PNG（1×1 红点）——struct+zlib 手拼，零新依赖。"""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)   # 1×1 8bit RGB
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            + chunk(b"IEND", b""))


def test_workspace_files_lifecycle(tmp_path, monkeypatch):
    """B3/B4 工作区文件面板锚：上传 png（multipart）→ 列表含 kind=image
    → raw 200 + image/png 内联（无 attachment 头）→ 删除消失。owner 化
    沿用 B1：文件落 <根>/<owner>/（owner_fn 注入）。"""
    from genie.studio.server import create_app
    monkeypatch.setenv("GENIE_SCRIPTS_DIR", str(tmp_path / "scripts"))
    monkeypatch.delenv("GENIE_SCRIPTS_OWNER", raising=False)
    c = TestClient(create_app(owner_fn=lambda req: "tester"))
    assert c.get("/api/workspace/files").json() == {"files": []}
    png = _png_bytes()
    r = c.post("/api/workspace/upload",
               files={"file": ("panel.png", png, "image/png")})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "name": "panel.png", "size": len(png)}
    assert (tmp_path / "scripts" / "tester" / "panel.png").read_bytes() == png
    assert c.get("/api/workspace/files").json() == {"files": [
        {"name": "panel.png", "size": len(png), "kind": "image"}]}
    raw = c.get("/api/workspace/raw", params={"name": "panel.png"})
    assert raw.status_code == 200
    assert raw.headers["content-type"] == "image/png"
    assert raw.content == png
    assert "attachment" not in raw.headers.get("content-disposition", "")
    assert c.post("/api/workspace/delete",
                  json={"name": "panel.png"}).json() == {"ok": True}
    assert c.get("/api/workspace/files").json() == {"files": []}
    assert c.post("/api/workspace/delete",
                  json={"name": "panel.png"}).status_code == 404


def test_workspace_limits_and_name_guard(tmp_path, monkeypatch):
    """B3 调研裁决两洞钉死 + 放宽面：①save/上传文本 256KiB 上限（413，
    上传半途失败不留 .part）②名字白名单 re.ASCII（非 ASCII 名 422）+
    路径穿越 422；.py 仍走 scripts 通道（面板 kind=script、raw=attachment），
    数据文件（h5）attachment 只下载不预览。"""
    from genie.studio.server import create_app
    monkeypatch.setenv("GENIE_SCRIPTS_DIR", str(tmp_path / "scripts"))
    monkeypatch.delenv("GENIE_SCRIPTS_OWNER", raising=False)
    c = TestClient(create_app())
    # 钉洞①：save 通道已随 G50 删——文本上限由 workspace/upload 同口径守
    assert c.post("/api/workspace/upload",
                  files={"file": ("big.py", b"x" * (256 * 1024 + 1),
                                  "text/x-python")}
                  ).status_code == 413
    # 上传文本类同口径：恰好 256KiB 放行，超 1 字节 413
    ok = c.post("/api/workspace/upload",
                files={"file": ("note.txt", b"x" * (256 * 1024),
                                "text/plain")})
    assert ok.status_code == 200
    over = c.post("/api/workspace/upload",
                  files={"file": ("big.txt", b"x" * (256 * 1024 + 1),
                                  "text/plain")})
    assert over.status_code == 413
    assert not (tmp_path / "scripts" / "local" / "big.txt.part").exists(), \
        "超限上传不得留 .part 半截"
    # 钉洞②：\w 裸用连非 ASCII 名都放行——统一钉 re.ASCII
    assert c.post("/api/workspace/upload",
                  files={"file": ("中文脚本.py", b"x",
                                  "text/x-python")}).status_code == 422
    assert c.post("/api/workspace/upload",
                  params={"name": "图片.png"},
                  files={"file": ("x.png", _png_bytes(), "image/png")},
                  ).status_code == 422
    # 名字白名单防路径穿越（三端点同一守卫）
    assert c.get("/api/workspace/raw",
                 params={"name": "../evil.png"}).status_code == 422
    assert c.post("/api/workspace/delete",
                  json={"name": "sub/evil.png"}).status_code == 422
    assert c.post("/api/workspace/upload",
                  files={"file": ("../evil.png", b"x",
                                  "application/octet-stream")},
                  ).status_code == 422
    # .py 回归：编辑/保存走 workspace 上传；面板统一可见（kind=script）
    assert c.post("/api/workspace/upload",
                  files={"file": ("hello.py", b"print(1)",
                                  "text/x-python")}).status_code == 200
    files = {f["name"]: f for f in
             c.get("/api/workspace/files").json()["files"]}
    assert files["hello.py"]["kind"] == "script"
    assert files["note.txt"]["kind"] == "other"
    raw_py = c.get("/api/workspace/raw", params={"name": "hello.py"})
    assert raw_py.status_code == 200
    assert "attachment" in raw_py.headers.get("content-disposition", "")
    # 数据文件 attachment 只下载不预览
    c.post("/api/workspace/upload",
           files={"file": ("out.h5", b"\x89HDF\r\n\x1a\n",
                           "application/x-hdf5")})
    raw_h5 = c.get("/api/workspace/raw", params={"name": "out.h5"})
    assert raw_h5.status_code == 200
    assert "attachment" in raw_h5.headers.get("content-disposition", "")


def test_gateway_forwards_auth_and_passes_status():
    """O2：账号面经**会话**转发（Studio 不再自己拨后端）。

    三个要点：路径映射（whoami 挂在网关根路径，不在 /api/auth 下）、
    体与查询参数原样、X-API-Key 随转发带上。
    """
    c, fake = _app()
    assert c.get("/api/auth/name-available",
                 params={"name": "abc"}).json() == {"ok": True}
    (kw,) = fake.of("gateway")
    assert kw["path"] == "api/auth/name-available"
    assert kw["method"] == "GET"
    assert kw["params"] == {"name": "abc"}

    c.post("/api/auth/verify", json={"email": "a@b.c", "code": "123456"})
    kw = fake.of("gateway")[-1]
    assert kw["path"] == "api/auth/verify"
    assert json.loads(kw["data"]) == {"email": "a@b.c", "code": "123456"}

    c.get("/api/auth/whoami", headers={"X-API-Key": "gt_t"})
    kw = fake.of("gateway")[-1]
    assert kw["path"] == "whoami"
    assert kw["key"] == "gt_t"


def test_gateway_passes_error_status_through():
    """上游 4xx 原样穿透（422 表单错/403 验证码错/429 限频）——GUI 直接
    显示 detail；Studio 不做二次翻译（唯一那一次在会话侧）。"""
    c, fake = _app()
    fake.gateway_reply = (422, json.dumps({"detail": "用户名或邮箱已存在"},
                                          ensure_ascii=False).encode(),
                          "application/json")
    r = c.post("/api/auth/verify", json={"email": "a@b.c"})
    assert r.status_code == 422
    assert r.json()["detail"] == "用户名或邮箱已存在"


def test_gateway_forwards_tools_and_jobs():
    """工具面（库清单/材料拟合）与作业面（状态/取消）同一条转发路。"""
    c, fake = _app()
    c.get("/api/tools/nk_library", params={"name": "Au"})
    kw = fake.of("gateway")[-1]
    assert kw["path"] == "api/tools/nk_library" and kw["method"] == "GET"
    c.post("/api/tools/material_fit", json={"library": "au"})
    kw = fake.of("gateway")[-1]
    assert kw["path"] == "api/tools/material_fit" and kw["method"] == "POST"
    c.post("/api/jobs/J1/cancel", headers={"X-API-Key": "gt_t"})
    kw = fake.of("gateway")[-1]
    assert kw["path"] == "api/jobs/J1/cancel" and kw["method"] == "POST"
    assert kw["key"] == "gt_t"


def test_submit_route_is_gone():
    """M2/O2：/api/submit 删除——GUI 的 Run 走会话里的 f.run()，此路由
    从来没有调用方。留断言防它被顺手加回来。"""
    c, _ = _app()
    assert c.post("/api/submit", json={}).status_code in (404, 405)


def test_host_mode_mounts_no_facades():
    """云宿主形态（mount_session=False）不带会话门面与网关门面——
    宿主用自己的 cookie 会话，升级零破坏。"""
    from genie.studio.server import create_app
    c = TestClient(create_app())
    assert c.post("/api/session/attach").status_code in (404, 405)
    assert c.get("/api/auth/whoami").status_code in (404, 405)
    assert c.get("/api/result/meta").status_code in (404, 405)


class _KernelStub:
    """记录调用的最小 kernel（O3 断言"门面直接落到对象上"用）。"""

    def __init__(self):
        self.calls: list[tuple] = []

    def attach(self, key=""):
        self.calls.append(("attach", key))
        return {"alive": True}

    def submit(self, code, mode="run", label=""):
        self.calls.append(("submit", code, mode))
        return 1

    def run(self, **kw):
        self.calls.append(("run", kw.get("gpu")))
        return 2

    def ensure(self):
        pass

    def output(self, since=0):
        self.calls.append(("output", since))
        return {"lines": [], "busy": False, "cfg_seq": 0}

    def stop(self):
        self.calls.append(("stop",))
        return True

    def load_config(self, cfg):
        self.calls.append(("load_config", cfg))


def test_local_session_host_is_in_process(monkeypatch):
    """O3：本地形态下 Studio 与它的会话之间**没有边**。

    没有 HTTP、没有端口、没有序列化——门面直接落到 kernel 对象上。这条
    锁死"不许把会话地址塞回产品路径"（同机同用户同生命周期，无边界可跨）。
    """
    from genie.studio import session_service as ss
    from genie.studio.server import create_app
    from genie.studio.session_local import LocalSessionHost

    fake = _KernelStub()
    monkeypatch.setattr(ss, "get_kernel",
                        lambda owner="user", session_id="default": fake)
    c = TestClient(create_app(mount_session=True,
                              session=LocalSessionHost()))
    r = c.post("/api/exec", json={"code": "print(1)"},
               headers={"X-Session-Id": "s9"})
    assert r.json() == {"id": 1}
    assert ("submit", "print(1)", "run") in fake.calls
    c.post("/api/session/attach", headers={"X-API-Key": "k",
                                           "X-Session-Id": "s9"})
    assert ("attach", "k") in fake.calls
    assert c.get("/api/exec/output", headers={"X-Session-Id": "s9"}
                 ).status_code == 200
    assert ("output", 0) in fake.calls


def test_share_session_mounts_endpoint_with_token(monkeypatch):
    """O3：跨进程客户端（genie console）走 GUI 端口的 /session，带口令。

    这才是"一个进程一个端口"：GUI 自己的路是函数调用，别人的路是这条
    带口令的 loopback 路由。
    """
    from genie.studio import session_service as ss
    from genie.studio.server import create_app
    from genie.studio.session_local import LocalSessionHost

    fake = _KernelStub()
    monkeypatch.setattr(ss, "get_kernel",
                        lambda owner="user", session_id="default": fake)
    monkeypatch.setattr(ss, "_TOKEN", "tok1")
    c = TestClient(create_app(mount_session=True, share_session=True,
                              session=LocalSessionHost()))
    assert c.get("/session/output?owner=local").status_code == 401
    r = c.get("/session/output?owner=local&session_id=default",
              headers={"X-Session-Token": "tok1"})
    assert r.status_code == 200 and r.json()["busy"] is False
