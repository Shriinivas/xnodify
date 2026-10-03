"""
Configuration settings for XNodify.
"""

import logging
import os

# ============================================================================
# Logging Configuration
# ============================================================================

# Log level: Controls verbosity of console output
# - logging.ERROR (40): Only errors
# - logging.WARNING (30): Warnings + errors
# - logging.INFO (20): Informational messages + warnings/errors + line-by-line execution (DEFAULT)
# - logging.DEBUG (10): All debug details + everything above
LOG_LEVEL = logging.INFO

# Use emoji icons in log output (True) or ASCII glyphs (False)
# Set to False if your terminal font doesn't support emoji
USE_EMOJI = True

# ============================================================================
# Environment Variable Overrides
# ============================================================================

# Override log level via environment variable
# Example: export XNODIFY_LOG_LEVEL=DEBUG
env_log_level = os.environ.get('XNODIFY_LOG_LEVEL', os.environ.get('GEOXNODIFY_LOG_LEVEL', '')).upper()
if env_log_level in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
    LOG_LEVEL = getattr(logging, env_log_level)

# Override emoji setting via environment variable
# Example: export XNODIFY_USE_EMOJI=0
env_use_emoji = os.environ.get('XNODIFY_USE_EMOJI', os.environ.get('GEOXNODIFY_USE_EMOJI', '')).lower()
if env_use_emoji in ('0', 'false', 'no'):
    USE_EMOJI = False
elif env_use_emoji in ('1', 'true', 'yes'):
    USE_EMOJI = True

# ============================================================================
# Programmatic Configuration (for advanced usage)
# ============================================================================

def set_log_level(level):
    """
    Set the log level programmatically.

    Args:
        level: Can be:
               - logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR
               - String: 'DEBUG', 'INFO', 'WARNING', 'ERROR'
               - Integer: 10 (DEBUG), 20 (INFO), 30 (WARNING), 40 (ERROR)

    Example:
        from config import set_log_level
        import logging
        set_log_level(logging.DEBUG)
    """
    global LOG_LEVEL

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    LOG_LEVEL = level

    # Update existing logger if already initialized
    try:
        from .logger import set_log_level as update_logger_level
        update_logger_level(level)
    except (ImportError, RuntimeError):
        pass  # Logger not initialized yet


def set_use_emoji(use_emoji):
    """
    Enable or disable emoji icons programmatically.

    Args:
        use_emoji: True to use emoji, False for ASCII glyphs

    Example:
        from config import set_use_emoji
        set_use_emoji(False)  # Use ASCII glyphs instead
    """
    global USE_EMOJI
    USE_EMOJI = use_emoji

    # Update existing logger if already initialized
    try:
        from .logger import set_use_emoji as update_logger_emoji
        update_logger_emoji(use_emoji)
    except (ImportError, RuntimeError):
        pass  # Logger not initialized yet


# ============================================================================
# Backward Compatibility
# ============================================================================

# For code that still uses the old DEBUG flag
@property
def DEBUG():
    """Backward compatibility: DEBUG is True when LOG_LEVEL is DEBUG."""
    return LOG_LEVEL == logging.DEBUG


def is_debug():
    """Backward compatibility: Check if debug mode is enabled."""
    return LOG_LEVEL == logging.DEBUG


def set_debug(enabled):
    """Backward compatibility: Enable/disable debug mode."""
    set_log_level(logging.DEBUG if enabled else logging.INFO)
