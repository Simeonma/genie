# genie — GENIE SDK

**在脚本里构建 FDTD 仿真，`f.run()` 一行提交云端 GPU，结果取回本地。**

包名 `genie`；源码仓名 `genie-sdk`（本仓）。Apache-2.0。

## 安装

```bash
# GitHub 直连（若 raw.githubusercontent.com 可达）
pip install https://github.com/Simeonma/genie-sdk/raw/dist/dist/genie-<版本>-py3-none-any.whl

# CDN 镜像（国内网络推荐）：同一份 wheel，走 jsDelivr
pip install https://cdn.jsdelivr.net/gh/Simeonma/genie-sdk@dist/dist/genie-<版本>-py3-none-any.whl
```

版本清单见 [Releases](https://github.com/Simeonma/genie-sdk/releases)（wheel 同时放在
`dist` 分支）。Python ≥ 3.10，`requests / numpy / pydantic / h5py` 自动安装。

按需装 extra：

| extra | 用途 |
|---|---|
| `genie[server]` | `genie studio` 本地 GUI（fastapi / uvicorn） |
| `genie[agent]` | `genie-mcp`（MCP 工具面，给 LLM agent 用） |
| `genie[fit]` | 材料拟合（`fit_nk` / `add_from_library`，需 scipy） |
| `genie[plot]` | `SimData.plot`（matplotlib） |
| `genie[dev]` | pytest |

## 最小上手

```python
import genie

f = genie.connect("https://<你的网关>", api_key="<key>", username="<名字>")

f.domain.x_range = (-1e-6, 1e-6)
f.domain.y_range = (-1e-6, 1e-6)
f.domain.z_range = (-2e-6, 2e-6)
f.domain.total_time = 6e-14
f.mesh.dx = 2e-8

f.mat.add_const().name("sio2").eps(2.1)
f.geom.add_box().material("sio2") \
    .x_range(-5e-7, 5e-7).y_range(-5e-7, 5e-7).z_range(-1e-7, 1e-7).priority(1)
f.src.add_soft_source().freq(3e14).bandwidth(6e13).name("s0").center(0, 0, -3e-7)
f.mon.add_freq().name("sp").center(0, 0, 2e-7).field("all").freq(3e14, 1.2e14, 200)

f.run()                 # 提交云端 GPU
f.get_freq("sp")        # 取结果（numpy）
```

不想连服务也能先看模型：`genie.preview_script(源码字符串)` 零网络返回 cfg
（GUI 的 Ctrl+Enter 预览走的就是它）。

本地起 GUI：`pip install "genie[server]"` 后 `genie studio`（会话 + 浏览器界面同一进程）。

## 从哪读起

| 想知道 | 去哪 |
|---|---|
| 完整 API（逐方法：功能 / 输入 / 单位 / 约束 / 默认 / 陷阱） | 包内 `genie/docs/dialect.md` |
| 最快上手 + 可跑案例 | 包内 `genie/manual/commands/`（站点从 `index.html` 起，也可在 GUI 里点「手册」） |
| 用代码驱动 Studio（agent / console / MCP） | 包内 `genie/docs/agent.md` |
| 装好后的即时上手 | `python -c "import genie; help(genie)"` |
| 随包示例脚本 | 包内 `genie/examples/`（`manifest.json` 是索引） |

## 包内结构

```
genie/
├── models/  core/  lib/  net/  integrations/   引擎与 IO
├── studio/                                     GUI 服务端 + 前端壳（static/）
├── manual/                                     用户手册站点
├── examples/                                   示例脚本
└── docs/                                       dialect.md（API 语义）/ agent.md
```

## License

[Apache-2.0](LICENSE) —— 可自由使用、修改、再分发（含商用），附带专利授权。
开放边界：SDK 与 GUI 开源；GPU 内核、云服务与知识库闭源。
