"""FastAPI dependency injection for Zos API.

Provides access to shared resources via app.state.
"""

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from zos.chattiness import ImpulseEngine
    from zos.config import Config
    from zos.salience import SalienceLedger


def get_config(request: Request) -> "Config":
    """Get config from app state.

    Args:
        request: FastAPI request object.

    Returns:
        Application configuration.
    """
    return request.app.state.config


def get_db(request: Request) -> "Engine":
    """Get database engine from app state.

    Args:
        request: FastAPI request object.

    Returns:
        SQLAlchemy engine instance.
    """
    return request.app.state.db


def get_ledger(request: Request) -> "SalienceLedger":
    """Get salience ledger from app state.

    Args:
        request: FastAPI request object.

    Returns:
        SalienceLedger instance.
    """
    return request.app.state.ledger


def get_impulse_engine(request: Request) -> "ImpulseEngine | None":
    """Get impulse engine from app state, if available.

    Returns None when chattiness is disabled.
    """
    return getattr(request.app.state, "impulse_engine", None)
