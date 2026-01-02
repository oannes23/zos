"""Layer execution engine.

This module provides the core infrastructure for executing YAML-defined
reflection layers with pipeline nodes, for_each expansion, budget
enforcement, and context passing.

Example usage:
    from zos.layer import LayerLoader, PipelineExecutor

    # Load a layer definition
    loader = LayerLoader(config.layers_dir)
    layer = loader.load("channel_digest")

    # Execute the layer
    executor = PipelineExecutor(db, llm_client, config)
    result = await executor.execute(layer, allocation_plan)
"""

from zos.layer.context import PipelineContext, TraceEntry
from zos.layer.executor import ExecutionResult, PipelineExecutor
from zos.layer.loader import LayerLoader
from zos.layer.nodes import (
    BaseNode,
    NodeResult,
    create_node,
)
from zos.layer.privacy import PrivacyEnforcer
from zos.layer.schema import (
    AnyNodeConfig,
    FetchInsightsConfig,
    FetchMessagesConfig,
    LayerDefinition,
    LLMCallConfig,
    ModelDefaults,
    OutputConfig,
    PipelineConfig,
    ReduceConfig,
    SalienceRulesConfig,
    StoreInsightConfig,
    TargetConfig,
)

__all__ = [
    # Schema models
    "LayerDefinition",
    "PipelineConfig",
    "TargetConfig",
    "SalienceRulesConfig",
    "ModelDefaults",
    "AnyNodeConfig",
    "FetchMessagesConfig",
    "FetchInsightsConfig",
    "LLMCallConfig",
    "ReduceConfig",
    "StoreInsightConfig",
    "OutputConfig",
    # Context
    "PipelineContext",
    "TraceEntry",
    # Nodes
    "BaseNode",
    "NodeResult",
    "create_node",
    # Execution
    "PipelineExecutor",
    "ExecutionResult",
    # Loader
    "LayerLoader",
    # Privacy
    "PrivacyEnforcer",
]
