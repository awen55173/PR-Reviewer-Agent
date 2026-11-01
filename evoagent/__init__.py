"""EvoAgent：面向代码审查、修复和持续评测的智能代理服务。

顶层包只维护版本信息，并通过惰性属性暴露各功能子包，避免导入包时
立即加载 Web 服务、数据库驱动或其他可选运行时依赖。
"""

from importlib import import_module as _import_module

__version__ = "0.3.0"
__all__ = ["__version__", "agent", "api", "core", "evaluation", "evolution",
           "integrations", "repair", "review", "services", "storage"]


def __getattr__(name: str):
    """按需加载功能子包。"""
    if name in __all__ and name != "__version__":
        value = _import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
