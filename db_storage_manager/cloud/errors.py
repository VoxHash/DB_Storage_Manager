"""Cloud-managed database integration errors."""

from __future__ import annotations


class CloudSDKMissingError(ImportError):
    """Raised when an optional cloud SDK is not installed."""


class CloudNotConfiguredError(RuntimeError):
    """Raised when cloud credentials or required settings are missing."""


class CloudProviderError(RuntimeError):
    """Raised when a cloud provider API call fails."""
