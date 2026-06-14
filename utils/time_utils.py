```python
"""
Module: utils/time_utils.py

This module provides utility functions for handling time-related operations.

Functions:
    get_utc_timestamp() -> str: Returns the current UTC time as an ISO 8601 string.
"""

import datetime
from typing import Union

def get_utc_timestamp() -> str:
    """
    Returns the current UTC time as an ISO 8601 string.

    Returns:
        str: The current UTC time in ISO 8601 format.
    """
    # Get the current UTC time
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    # Format the time as an ISO 8601 string
    return utc_now.isoformat()

# Example usage
if __name__ == "__main__":
    try:
        timestamp = get_utc_timestamp()
        print(f"Current UTC timestamp: {timestamp}")
    except Exception as e:
        print(f"Failed to get UTC timestamp: {e}")
```