"""genie.core.job — 作业生命周期的家（骨架，framework §四）。

终态职责（framework §四：「attach/list/cancel/status/log」）：把散在
``Simulation`` 方法与 ``net.client`` 上的作业生命周期收敛为独立 ``Job``
对象——按 id 附着他人作业、列账户作业、取消、查态、拉日志。

当前状态（2026-10 阶段 ④ 立骨、⑤ 去冗余）：**纯占位**。现有生命周期
已由 ``Simulation.run()/sweep()``（隐含 submit/wait）与 ``net.client``
覆盖，独立 Job 面等真实需求（多作业管理/attach，预计云宿主阶段前后）
落地——不预支实现，不装样子的空类。
"""
