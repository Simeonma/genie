"""net/expert.py — 专家会话客户端（framework §四/§六：骨架转正，阶段 7⑤）。

终态职责（framework §六「问 / 托 分离」）：对接公共服务的专家会话端点——**SDK
用户与云 GUI 用户收敛于同一公共服务**（对称原则：同一份客户端代码、
同一组端点）::

    f = genie.connect(PUBLIC_URL, api_key=…)
    f.expert.ask("设计一个 1550nm 滤波器")       # 问：秒级~分钟级咨询
    f.expert.delegate(cfg=cfg, steps=800)        # 托：长任务（过预算闸）

服务端（cloud/services/experts/orchestrator）：design/simulation/
validation 三专家 + knowledge（干净区）；ask = 咨询结论（结构化），
delegate = 提交→等结果→验证判读（复合结论）。GPU 费与 LLM 费均计量
到调用者账户（billing 台账）。
"""
from __future__ import annotations

from typing import Any


class ExpertSession:
    """专家会话句柄（由 ``Simulation.expert`` 属性到达，不直接构造）。"""

    def __init__(self, client):
        self._client = client

    def _post(self, path: str, body: dict) -> dict:
        return self._client.expert_post(path, body)

    def ask(self, question: str) -> dict:
        """问：咨询（秒级~分钟级）→ 结构化结论（design/validation 专家）。"""
        if not question or not question.strip():
            raise ValueError("question 须非空")
        return self._post("/expert/ask", {"question": question})

    def delegate(self, cfg: dict | None = None, *, task: str = "",
                 steps: int = 800) -> dict:
        """托：委托仿真作业（过预算闸）→ 复合结论（仿真 + 验证判读）。

        ``cfg``：SimConfig JSON（如 ``f.to_config()``——表单/脚本编辑
        后的当前活动配置）；``steps``：仿真步数（默认 800）。"""
        if cfg is None and not task:
            raise ValueError("delegate 需要 cfg（或明确 task 描述）")
        return self._post("/expert/delegate",
                          {"cfg": cfg, "task": task, "steps": int(steps)})

    def close(self) -> None:
        """会话结束（当前公共服务无状态会话——保留接口对称性）。"""


__all__ = ["ExpertSession"]
