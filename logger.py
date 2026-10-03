"""
Logging system for XNodify.

Provides customizable logging with emoji or glyph prefixes.

Log Levels:
- DEBUG (10): All debug details (connections, assignments, etc.)
- INFO (20): Informational messages + line-by-line execution
- WARNING (30): Warnings only
- ERROR (40): Errors only

Usage:
    from logger import get_logger
    logger = get_logger(__name__)
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
"""

import logging
import sys

# Icon sets
EMOJI_ICONS = {
    'DEBUG': '🔧',
    'INFO': 'ℹ️ ',
    'LINE': '📝',
    'SUCCESS': '✓',
    'WARNING': '⚠️ ',
    'ERROR': '❌',
    'CRITICAL': '🔥',
}

GLYPH_ICONS = {
    'DEBUG': '[D]',
    'INFO': '[I]',
    'LINE': '[L]',
    'SUCCESS': '[✓]',
    'WARNING': '[!]',
    'ERROR': '[X]',
    'CRITICAL': '[!!]',
}


class ColoredFormatter(logging.Formatter):
    """Custom formatter with icon support (emoji or glyph)."""

    def __init__(self, use_emoji=True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icons = EMOJI_ICONS if use_emoji else GLYPH_ICONS

    def format(self, record):
        # Add icon based on level
        icon = self.icons.get(record.levelname, '')

        # Special handling for line execution messages
        if hasattr(record, 'is_line_exec') and record.is_line_exec:
            icon = self.icons['LINE']

        # Special handling for success messages
        if hasattr(record, 'is_success') and record.is_success:
            icon = self.icons['SUCCESS']

        # Format: "🔧 DEBUG: message" or "📝 LINE: message"
        if icon:
            record.levelname = f"{icon} {record.levelname}"

        return super().format(record)


class XNodifyLogger:
    """Wrapper for logger with additional helper methods."""

    def __init__(self, logger):
        self._logger = logger

    def __getattr__(self, name):
        # Delegate all other methods to underlying logger
        return getattr(self._logger, name)

    def line(self, line_content, line_number=None, group_context=None):
        """
        Log a line being executed (INFO level).

        Args:
            line_content: The source line content
            line_number: Optional line number
            group_context: Optional group name (e.g., "group_name") to prefix the line
        """
        # Format: "60: statement" or "[group_name] 60: statement"
        if group_context:
            prefix = f"[{group_context}] "
        else:
            prefix = ""

        if line_number is not None:
            msg = f"{prefix}{line_number}: {line_content}"
        else:
            msg = f"{prefix}{line_content}"

        # Create log record with special flag
        record = self._logger.makeRecord(
            self._logger.name, logging.INFO, "(line)", line_number or 0,
            msg, (), None
        )
        record.is_line_exec = True
        self._logger.handle(record)

    def success(self, msg, *args, **kwargs):
        """Log a success message (INFO level with ✓ icon)."""
        record = self._logger.makeRecord(
            self._logger.name, logging.INFO, "(success)", 0,
            msg % args if args else msg, (), None
        )
        record.is_success = True
        self._logger.handle(record)


# Global logger instance
_logger = None
_use_emoji = True
_log_level = logging.INFO


def init_logger(name='xnodify', level=logging.INFO, use_emoji=True):
    """
    Initialize the global logger.

    Args:
        name: Logger name
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        use_emoji: True to use emoji icons, False for ASCII glyphs

    Returns:
        XNodifyLogger instance
    """
    global _logger, _use_emoji, _log_level

    _use_emoji = use_emoji
    _log_level = level

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # Create formatter
    formatter = ColoredFormatter(
        use_emoji=use_emoji,
        fmt='%(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)

    # Add handler
    logger.addHandler(handler)

    # Prevent propagation to root logger
    logger.propagate = False

    # Wrap in our custom logger
    _logger = XNodifyLogger(logger)

    return _logger


def get_logger(name=None):
    """
    Get the logger instance.

    If not initialized, will auto-initialize with settings from config.

    Args:
        name: Optional name for the logger (for sub-modules)

    Returns:
        XNodifyLogger instance
    """
    global _logger

    if _logger is None:
        # Auto-initialize with config settings
        try:
            from .config import LOG_LEVEL, USE_EMOJI
        except ImportError:
            from config import LOG_LEVEL, USE_EMOJI

        init_logger(level=LOG_LEVEL, use_emoji=USE_EMOJI)

    # Return the global logger (we use one logger for the whole addon)
    return _logger


def set_log_level(level):
    """
    Set the log level.

    Args:
        level: logging.DEBUG, logging.INFO, logging.WARNING, or logging.ERROR
               Can also be string: 'DEBUG', 'INFO', 'WARNING', 'ERROR'
    """
    global _logger

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    if _logger:
        _logger.setLevel(level)
        for handler in _logger.handlers:
            handler.setLevel(level)


def set_use_emoji(use_emoji):
    """
    Switch between emoji and glyph icons.

    Args:
        use_emoji: True for emoji, False for ASCII glyphs
    """
    global _logger, _use_emoji

    _use_emoji = use_emoji

    if _logger:
        # Update formatter
        for handler in _logger.handlers:
            formatter = ColoredFormatter(
                use_emoji=use_emoji,
                fmt='%(levelname)s: %(message)s',
                datefmt='%H:%M:%S'
            )
            handler.setFormatter(formatter)
