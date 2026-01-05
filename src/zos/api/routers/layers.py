"""Layers endpoint."""

from fastapi import APIRouter

from zos.api.dependencies import ConfigDep, LayerLoaderDep
from zos.api.models import LayersResponse, LayerSummary

router = APIRouter()


@router.get("", response_model=LayersResponse)
async def list_layers(
    config: ConfigDep,
    loader: LayerLoaderDep,
) -> LayersResponse:
    """List all registered layers.

    Returns information about all available layer definitions including
    their schedules and which layers are currently enabled.
    """
    layer_names = loader.list_layers()
    summaries = []

    for name in layer_names:
        try:
            layer = loader.load(name)
            summaries.append(
                LayerSummary(
                    name=layer.name,
                    description=layer.description,
                    schedule=layer.schedule,
                    target_categories=layer.targets.categories,
                    node_count=len(layer.pipeline.nodes),
                )
            )
        except Exception:
            # Skip invalid layers
            pass

    return LayersResponse(
        layers=summaries,
        enabled=config.enabled_layers,
    )
