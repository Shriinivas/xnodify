"""
Validation Rules - Single Source of Truth

This module contains all validation logic used by both:
- semantic_analyzer.py (for LSP static analysis)
- compiler.py (for runtime validation during compilation)

All validation rules are defined here to ensure consistency and
eliminate code duplication.
"""

# Built-in constants that are always defined
# Maps constant name to its Python value (single source of truth)
BUILTIN_CONSTANTS = {
    "True": True,
    "False": False,
    "true": True,
    "false": False,
}


def is_variable_defined(name, symbol_table, inputs, groups):
    """
    Check if a variable name is defined in any scope.

    This is the single source of truth for variable resolution order:
    1. Built-in constants (True, False)
    2. Symbol table (local variables, assignments)
    3. Input parameters
    4. Group definitions

    Args:
        name: Variable name to check
        symbol_table: Dict of defined variables (name -> any value)
        inputs: Dict of input parameters (name -> info dict)
        groups: Dict of group definitions (name -> info)

    Returns:
        bool: True if variable is defined, False otherwise
    """
    return (
        name in BUILTIN_CONSTANTS
        or name in symbol_table
        or name in inputs
        or name in groups
    )


def get_undefined_variable_error(name, symbol_table):
    """
    Generate error message for an undefined variable.

    Single source of truth for the error message format.

    Args:
        name: The undefined variable name
        symbol_table: Current symbol table (for listing available variables)

    Returns:
        str: Error message
    """
    available = list(symbol_table.keys())
    return f"Undefined variable: '{name}'. Available variables: {available}"


def get_unused_inputs(inputs):
    """
    Find input parameters that were never used.

    Args:
        inputs: Dict of input parameters where each value has a 'used' key
                and optionally 'line' and 'column' keys for location info.

    Returns:
        list: List of tuples (name, line, column) for unused inputs.
              Line/column are 0 if not available.
    """
    unused = []
    for name, info in inputs.items():
        if not info.get("used", False):
            line = info.get("line", 0)
            column = info.get("column", 0)
            unused.append((name, line, column))
    return unused


def get_unused_input_warning(name):
    """
    Generate warning message for an unused input parameter.

    Single source of truth for the warning message format.

    Args:
        name: The unused input parameter name

    Returns:
        str: Warning message
    """
    return f"Unused input parameter: {name}"
