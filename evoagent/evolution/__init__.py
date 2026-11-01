"""审查策略和 Agent Skill 的演进引擎。

本包负责回归评测、失败根因分析、提示词演进、Skill artifact 校验、
候选版本生成及发布前证明；它不直接承担 HTTP 请求或持久化实现。
"""

from importlib import import_module as _import_module

_EXPORTS = {
    'engine': ('engine', None),
    'evolution_v2': ('evolution_v2', None),
    'evolution_proof': ('evolution_proof', None),
    'skill_evolution': ('skill_evolution', None),
    'EvolutionEngine': ('engine', 'EvolutionEngine'),
    'RegressionEvaluator': ('engine', 'RegressionEvaluator'),
    'RootCauseEvolutionGenerator': ('evolution_v2', 'RootCauseEvolutionGenerator'),
    'PromptPolicyReviewer': ('evolution_proof', 'PromptPolicyReviewer'),
    'run_prompt_evolution_proof': ('evolution_proof', 'run_prompt_evolution_proof'),
    'SkillEvolutionEngine': ('skill_evolution', 'SkillEvolutionEngine'),
    'AgentSkillReplayReviewer': ('skill_evolution', 'AgentSkillReplayReviewer'),
    'validate_artifact': ('skill_evolution', 'validate_artifact'),
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
