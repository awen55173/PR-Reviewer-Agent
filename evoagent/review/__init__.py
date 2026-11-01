"""代码审查规则、审查器组合、质量门禁和报告格式化。

这里定义从本地确定性规则到 OpenAI-compatible 模型审查器的统一接口，
并负责发现去重、证据门禁以及 Markdown 报告输出。
"""

from importlib import import_module as _import_module

_EXPORTS = {
    'gates': ('gates', None),
    'report': ('report', None),
    'reviewer': ('reviewer', None),
    'review_rules': ('review_rules', None),
    'FindingGate': ('gates', 'FindingGate'),
    'GateResult': ('gates', 'GateResult'),
    'to_markdown': ('report', 'to_markdown'),
    'Reviewer': ('reviewer', 'Reviewer'),
    'LocalRuleReviewer': ('reviewer', 'LocalRuleReviewer'),
    'DomainRuleReviewer': ('reviewer', 'DomainRuleReviewer'),
    'SecurityRuleReviewer': ('reviewer', 'SecurityRuleReviewer'),
    'ReliabilityRuleReviewer': ('reviewer', 'ReliabilityRuleReviewer'),
    'OpenAICompatibleReviewer': ('reviewer', 'OpenAICompatibleReviewer'),
    'CompositeReviewer': ('reviewer', 'CompositeReviewer'),
    'ContextRuleReviewer': ('review_rules', 'ContextRuleReviewer'),
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
