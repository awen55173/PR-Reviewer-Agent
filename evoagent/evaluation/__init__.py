"""代码审查评测工具包。

提供数据集校验、发现匹配、端到端评测、产品模式对比，以及受控实验和
统计汇总能力，用于验证审查器和技能演进是否带来可重复的改进。
"""

from importlib import import_module as _import_module

_EXPORTS = {
    'evaluation_harness': ('evaluation_harness', None),
    'evaluation_v2': ('evaluation_v2', None),
    'evaluation_experiments': ('evaluation_experiments', None),
    'EndToEndEvaluationHarness': ('evaluation_harness', 'EndToEndEvaluationHarness'),
    'dataset_fingerprint': ('evaluation_harness', 'dataset_fingerprint'),
    'one_to_one_match': ('evaluation_harness', 'one_to_one_match'),
    'ProductionEvaluationHarness': ('evaluation_v2', 'ProductionEvaluationHarness'),
    'FairAblationSuite': ('evaluation_v2', 'FairAblationSuite'),
    'AccuracyExperimentSuite': ('evaluation_experiments', 'AccuracyExperimentSuite'),
    'SkillEvolutionExperimentSuite': ('evaluation_experiments', 'SkillEvolutionExperimentSuite'),
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
