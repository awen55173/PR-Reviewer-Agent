"""核心领域模型与基础配置。

本包定义任务状态、严重级别、审查发现和报告等稳定数据结构，并提供
统一 diff 解析、运行模式解析、配置读取及发现身份规范化工具。
"""

from importlib import import_module as _import_module

_EXPORTS = {
    'config': ('config', None),
    'diff_parser': ('diff_parser', None),
    'finding_identity': ('finding_identity', None),
    'models': ('models', None),
    'modes': ('modes', None),
    'Settings': ('config', 'Settings'),
    'load_dotenv': ('config', 'load_dotenv'),
    'ParsedDiff': ('diff_parser', 'ParsedDiff'),
    'parse_unified_diff': ('diff_parser', 'parse_unified_diff'),
    'Finding': ('models', 'Finding'),
    'ReviewReport': ('models', 'ReviewReport'),
    'TaskState': ('models', 'TaskState'),
    'Severity': ('models', 'Severity'),
    'ComponentKind': ('models', 'ComponentKind'),
    'RunMode': ('modes', 'RunMode'),
    'resolve_mode': ('modes', 'resolve_mode'),
    'canonical_identity': ('finding_identity', 'canonical_identity'),
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
