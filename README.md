# genie — GENIE SDK

**在脚本里构建 FDTD 仿真，`f.run()` 一行提交云端 GPU，结果取回本地。**

## 安装

```bash
# GitHub 直连（若 raw.githubusercontent.com 可达）
pip install https://github.com/Simeonma/genie-sdk/raw/dist/dist/genie-<版本>-py3-none-any.whl
# CDN 镜像（国内网络推荐）：同一份 wheel，走 jsDelivr
pip install https://cdn.jsdelivr.net/gh/Simeonma/genie-sdk@dist/dist/genie-<版本>-py3-none-any.whl
```

版本与 wheel 清单见 [Releases](https://github.com/Simeonma/genie-sdk/releases)
（源码仓名 = `genie-sdk`；包名仍是 `genie`）。Python ≥ 3.10；
`requests / numpy / pydantic / h5py` 自动安装。

## 从哪读起

| 想知道 | 去哪 |
|---|---|
| 完整 API（逐方法：功能 / 输入 / 单位 / 约束 / 默认 / 陷阱） | 包内 `genie/docs/dialect.md` |
| 最快上手 + 可跑案例 | 包内 `genie/manual/commands/`（站点从 `index.html` 起） |
| 用代码驱动 Studio（agent / console） | 包内 `genie/docs/agent.md` |
| 装好后的即时上手 | `python -c "import genie; help(genie)"` |

## License

[Apache-2.0](LICENSE) —— 可自由使用、修改、再分发（含商用），附带专利授权。
开放边界：SDK 与 GUI 开源；GPU 内核、云服务与知识库闭源。
