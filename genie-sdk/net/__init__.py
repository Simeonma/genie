"""genie.net — 唯一碰网络的层（framework §四）。

client：GPU 云客户端（作业提交/状态/结果/取消）。expert：专家会话
客户端（阶段 7 公共服务落地时实现）。包内其余模块（core/integrations）
不得自行发请求——网络出口收敛于此。
"""
