"""
Indicator contract definition.

Every indicator file in jack/indicators/ must contain:
- METADATA dict with: name, display_name, params, output_columns, timeframes
- compute(df, **params) function that returns the DataFrame with new columns appended

This module exists for documentation and validation. It is not a base class
to inherit from — indicators are plain Python modules with a dict and a function.
"""

REQUIRED_METADATA_KEYS = {"name", "display_name", "params", "output_columns", "timeframes"}

REQUIRED_INPUT_COLUMNS = {"Date", "Open", "High", "Low", "Close"}


def validate_indicator_module(module) -> tuple[bool, str]:
    """
    Validate that a module conforms to the indicator contract.

    Args:
        module: An imported Python module.

    Returns:
        (True, "ok") if valid, (False, reason) if not.
    """
    # Check METADATA exists
    if not hasattr(module, "METADATA"):
        return False, "Missing METADATA dict"

    metadata = module.METADATA
    if not isinstance(metadata, dict):
        return False, "METADATA is not a dict"

    # Check required keys
    missing = REQUIRED_METADATA_KEYS - set(metadata.keys())
    if missing:
        return False, f"METADATA missing keys: {missing}"

    # Check compute function exists
    if not hasattr(module, "compute"):
        return False, "Missing compute() function"

    if not callable(module.compute):
        return False, "compute is not callable"

    return True, "ok"
