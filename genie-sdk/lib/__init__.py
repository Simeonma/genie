"""genie.lib — 结构函数库（framework §四：「普通 Python，无特殊概念」）。

站长提前写好的常用结构：参数化构件函数，改 ``f``、返回 None。用法
（函数与其模块同名，故**经子模块路径导入**——``from genie.lib import
grating`` 拿到的是模块本身，属 Python 同名语义；不做 __init__ 重导出，
重导出会被子模块导入覆写、两种绑定漂移）::

    from genie.lib.grating import grating
    from genie.lib.ring import ring
"""
