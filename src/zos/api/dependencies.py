"""FastAPI dependency injection."""

from typing import Annotated

from fastapi import Depends

from zos.config import ZosConfig, get_config
from zos.db import Database, get_db
from zos.insights import InsightRepository
from zos.layer import LayerLoader
from zos.salience.repository import SalienceRepository
from zos.scheduler.repository import RunRepository


def get_zos_config() -> ZosConfig:
    """Get global config."""
    return get_config()


def get_database() -> Database:
    """Get global database."""
    return get_db()


def get_insight_repository(
    db: Annotated[Database, Depends(get_database)],
) -> InsightRepository:
    """Create insight repository."""
    return InsightRepository(db)


def get_run_repository(
    db: Annotated[Database, Depends(get_database)],
) -> RunRepository:
    """Create run repository."""
    return RunRepository(db)


def get_salience_repository(
    db: Annotated[Database, Depends(get_database)],
) -> SalienceRepository:
    """Create salience repository."""
    return SalienceRepository(db)


def get_layer_loader(
    config: Annotated[ZosConfig, Depends(get_zos_config)],
) -> LayerLoader:
    """Create layer loader."""
    return LayerLoader(config.layers_dir)


# Type aliases for use in route functions
ConfigDep = Annotated[ZosConfig, Depends(get_zos_config)]
DatabaseDep = Annotated[Database, Depends(get_database)]
InsightRepoDep = Annotated[InsightRepository, Depends(get_insight_repository)]
RunRepoDep = Annotated[RunRepository, Depends(get_run_repository)]
SalienceRepoDep = Annotated[SalienceRepository, Depends(get_salience_repository)]
LayerLoaderDep = Annotated[LayerLoader, Depends(get_layer_loader)]
