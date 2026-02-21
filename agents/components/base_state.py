#!/usr/bin/env python3
"""
Base state interface for agent components
"""

from typing import Dict, Any, Protocol


class BaseState(Protocol):
    """Protocol for agent state to ensure generic component compatibility"""

    def get(self, key: str, default: Any = None) -> Any:
        """Get state value by key"""
        ...

    def __getitem__(self, key: str) -> Any:
        """Get state value by key using bracket notation"""
        ...

    def __setitem__(self, key: str, value: Any) -> None:
        """Set state value by key using bracket notation"""
        ...
