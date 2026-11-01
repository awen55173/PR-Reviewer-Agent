"""任务、审查结果、技能版本和运行轨迹的持久化后端。

提供零配置 SQLite 存储以及可选的 PostgreSQL 存储，并以相同的任务存储
接口供服务层选择。数据库连接和表初始化都在实际访问后端时进行。
"""

from importlib import import_module as _import_module

_EXPORTS = {
    'store': ('store', None),
    'postgres_store': ('postgres_store', None),
    'TaskStore': ('store', 'TaskStore'),
    'utc_now': ('store', 'utc_now'),
    'PostgresTaskStore': ('postgres_store', 'PostgresTaskStore'),
    'create_store': ('postgres_store', 'create_store'),
}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    """按需加载公开模块或对象，并缓存已解析的导出项。"""
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, symbol = _EXPORTS[name]
    module = _import_module(f"{__name__}.{module_name}")
    value = module if symbol is None else getattr(module, symbol)
    globals()[name] = value
    return value
