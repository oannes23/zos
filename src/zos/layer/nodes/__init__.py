"""Pipeline nodes for layer execution.

This module provides the node factory and all node implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zos.exceptions import LayerValidationError
from zos.layer.nodes.base import BaseNode, NodeResult
from zos.layer.nodes.fetch_insights import FetchInsightsNode
from zos.layer.nodes.fetch_messages import FetchMessagesNode
from zos.layer.nodes.llm_call import LLMCallNode
from zos.layer.nodes.output import OutputNode
from zos.layer.nodes.reduce import ReduceNode
from zos.layer.nodes.store_insight import StoreInsightNode

if TYPE_CHECKING:
    from zos.layer.schema import AnyNodeConfig

__all__ = [
    "BaseNode",
    "NodeResult",
    "FetchMessagesNode",
    "FetchInsightsNode",
    "LLMCallNode",
    "ReduceNode",
    "StoreInsightNode",
    "OutputNode",
    "create_node",
]

# Registry of node types to classes
_NODE_REGISTRY: dict[str, type[BaseNode]] = {
    "fetch_messages": FetchMessagesNode,
    "fetch_insights": FetchInsightsNode,
    "llm_call": LLMCallNode,
    "reduce": ReduceNode,
    "store_insight": StoreInsightNode,
    "output": OutputNode,
}


def create_node(config: AnyNodeConfig) -> BaseNode:
    """Create a node instance from configuration.

    Args:
        config: Node configuration from layer YAML.

    Returns:
        Configured node instance.

    Raises:
        LayerValidationError: If node type is unknown.
    """
    node_class = _NODE_REGISTRY.get(config.type)

    if node_class is None:
        raise LayerValidationError(f"Unknown node type: {config.type}")

    return node_class(config=config)


def get_registered_node_types() -> list[str]:
    """Get list of registered node types.

    Returns:
        List of node type identifiers.
    """
    return list(_NODE_REGISTRY.keys())
