from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .live import LiveBridgeError, _LiveTransport


@dataclass(slots=True)
class LocatorBridgeClient(_LiveTransport):
    """Typed read-only client for Arrangement locator metadata."""

    def locators(self, *, limit: int = 256) -> dict[str, Any]:
        if limit < 1 or limit > 4096:
            raise LiveBridgeError("locator limit must be between 1 and 4096")
        self._require_method("read", "locators")
        return self._request("locators", {"limit": int(limit)})
