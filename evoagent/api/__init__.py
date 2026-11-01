"""EvoAgent 的 HTTP API 层。

这里集中放置认证、请求模型和 FastAPI 应用工厂；业务逻辑仍由
``services`` 包实现。导出项按需加载，导入 API 包本身不会启动服务器。
"""

from importlib import import_module as _import_module

_EXPORTS = {
    'auth': ('auth', None),
    'server': ('server', None),
    'AuthManager': ('auth', 'AuthManager'),
    'Principal': ('auth', 'Principal'),
    'create_app': ('server', 'create_app'),
    'run': ('server', 'run'),
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
