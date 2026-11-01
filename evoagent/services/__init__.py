"""应用服务层。

本包编排审查任务的完整生命周期：队列调度、审查服务、修复与反馈、
演进以及灰度发布。它连接领域模型、存储、代理和外部集成，但不定义
底层规则本身。
"""

from importlib import import_module as _import_module

_EXPORTS = {
    'review_service': ('review_service', None),
    'rollout': ('rollout', None),
    'task_queue': ('task_queue', None),
    'ReviewService': ('review_service', 'ReviewService'),
    'ReleaseManager': ('rollout', 'ReleaseManager'),
    'TaskQueue': ('task_queue', 'TaskQueue'),
    'PermanentTaskError': ('task_queue', 'PermanentTaskError'),
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
