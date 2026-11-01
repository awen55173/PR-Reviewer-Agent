"""审查发现的修复、补丁应用与验证。

该包提供安全修复器、统一 diff 补丁解析/应用和修复后验证器；默认支持
建议模式，只有明确配置时才执行受控的仓库修改。
"""

from importlib import import_module as _import_module

_EXPORTS = {
    'fixer': ('fixer', None),
    'patching': ('patching', None),
    'verifier': ('verifier', None),
    'SafeFixer': ('fixer', 'SafeFixer'),
    'VerifiedPatchFixer': ('patching', 'VerifiedPatchFixer'),
    'SuggestionOnlyFixer': ('patching', 'SuggestionOnlyFixer'),
    'FilePatch': ('patching', 'FilePatch'),
    'parse_unified_patch': ('patching', 'parse_unified_patch'),
    'RepairVerifier': ('verifier', 'RepairVerifier'),
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
