"""Insights storage module.

Provides persistent storage for reflection outputs with source tracking
and privacy scope enforcement.
"""

from zos.insights.models import Insight
from zos.insights.repository import InsightRepository

__all__ = ["Insight", "InsightRepository"]
