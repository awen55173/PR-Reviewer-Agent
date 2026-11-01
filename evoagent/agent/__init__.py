"""代理运行时与审查智能体实现。

本包负责多角色审查编排、上下文管理、工具调用、记忆、技能加载、模型
客户端和执行遥测。导出项采用惰性加载，以便只使用规则审查时不必配置
LLM 或其他外部服务。
"""

from importlib import import_module as _import_module

_EXPORTS = {
    'agentic_core': ('agentic_core', None),
    'context_manager': ('context_manager', None),
    'harness': ('harness', None),
    'llm': ('llm', None),
    'memory': ('memory', None),
    'repository_tools': ('repository_tools', None),
    'runtime': ('runtime', None),
    'skills': ('skills', None),
    'telemetry': ('telemetry', None),
    'AgenticReviewer': ('agentic_core', 'AgenticReviewer'),
    'ContextManager': ('context_manager', 'ContextManager'),
    'ReviewHarness': ('harness', 'ReviewHarness'),
    'JsonChatClient': ('llm', 'JsonChatClient'),
    'MemoryManager': ('memory', 'MemoryManager'),
    'RepositoryToolSuite': ('repository_tools', 'RepositoryToolSuite'),
    'AgentRuntime': ('runtime', 'AgentRuntime'),
    'ToolRegistry': ('runtime', 'ToolRegistry'),
    'AgentSkill': ('skills', 'AgentSkill'),
    'SkillRegistry': ('skills', 'SkillRegistry'),
    'ExecutionLedger': ('telemetry', 'ExecutionLedger'),
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
