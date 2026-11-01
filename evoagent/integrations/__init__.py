"""外部系统集成与运行观测。

包含 GitHub API/App 签名验证、指标采集、OpenTelemetry 观测和告警能力。
这些适配器保持独立，核心审查流程可在没有外部服务时运行。
"""

from importlib import import_module as _import_module

_EXPORTS = {
    'github': ('github', None),
    'metrics': ('metrics', None),
    'observability': ('observability', None),
    'GitHubClient': ('github', 'GitHubClient'),
    'GitHubAppAuthenticator': ('github', 'GitHubAppAuthenticator'),
    'verify_signature': ('github', 'verify_signature'),
    'Metrics': ('metrics', 'Metrics'),
    'Observability': ('observability', 'Observability'),
    'AlertManager': ('observability', 'AlertManager'),
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
