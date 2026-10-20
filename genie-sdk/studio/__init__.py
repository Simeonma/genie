"""genie.studio — 随包分发的 GUI（一份代码两个宿主，framework §四）。

本地宿主：``python -m genie.studio``（本机 127.0.0.1）；云端宿主
（阶段 6）：host 包沙箱壳 serve 同一份 static/ 并把 /api/preview
指向沙箱执行——同一个 ``preview_script`` 函数。
"""
