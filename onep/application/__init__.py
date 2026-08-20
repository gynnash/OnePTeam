"""Shared application entry points for CLI and Web."""

from onep.application.capabilities import Capability, CapabilityRegistry
from onep.application.service import ApplicationService, RequestContext

__all__ = [
    "ApplicationService",
    "Capability",
    "CapabilityRegistry",
    "RequestContext",
]
