#!/usr/bin/env python3
"""
LSP server for XFY (XNodify) files.
Provides diagnostics and autocomplete by reusing existing parser and registry.
"""

import sys
import os
from pathlib import Path

# Add xnodify directory and vendor to path to import parser
repo_dir = Path(__file__).parent.parent.parent
vendor_dir = repo_dir / "vendor"
if vendor_dir.exists() and str(vendor_dir) not in sys.path:
    sys.path.insert(0, str(vendor_dir))
if str(repo_dir) not in sys.path:
    sys.path.insert(0, str(repo_dir))

import re
from lsprotocol.types import (
    CompletionItem,
    CompletionItemKind,
    CompletionList,
    CompletionParams,
    DefinitionParams,
    Diagnostic,
    DiagnosticSeverity,
    Hover,
    HoverParams,
    Location,
    MarkupContent,
    MarkupKind,
    ParameterInformation,
    Position,
    Range,
    SignatureHelp,
    SignatureHelpParams,
    SignatureInformation,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_CHANGE,
    TEXT_DOCUMENT_DID_SAVE,
    TEXT_DOCUMENT_COMPLETION,
    TEXT_DOCUMENT_DEFINITION,
    TEXT_DOCUMENT_HOVER,
    TEXT_DOCUMENT_SIGNATURE_HELP,
    TextDocumentSyncKind,
    TextDocumentSyncOptions,
)
from pygls.lsp.server import LanguageServer
from pygls.workspace import TextDocument

# Import our existing parser and semantic analyzer (single source of truth!)
from parser import parse
from semantic_analyzer import SemanticAnalyzer
from shortcuts import FUNCTION_SHORTCUTS
from registry import NodeRegistry
import hashlib

# Cache for source maps to avoid expensive rebuilding
# Key: (file_uri, content_hash) -> source_map
_source_map_cache = {}
from common_attributes import (
    COMMON_ATTRIBUTES,
    INTERNAL_PROPERTIES,
    get_user_facing_properties,
    get_valid_values,
)

# Debounce infrastructure for validation
import threading
_validation_timers = {}  # uri -> Timer
_validation_lock = threading.Lock()
DEBOUNCE_DELAY = 0.3  # 300ms debounce


class XFYLanguageServer(LanguageServer):
    """Language server for XFY files."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Load registry for autocomplete (single source of truth)
        self.registry = NodeRegistry(include_material_nodes=True)
        self.node_names = list(self.registry.nodes.keys())
        self.shortcut_names = list(FUNCTION_SHORTCUTS.keys())
        # Reusable semantic analyzer (reset state instead of recreating)
        self._analyzer = SemanticAnalyzer(registry=self.registry)

# Configure server to request full document sync from client
server = XFYLanguageServer(
    name="xfy-lsp",
    version="v0.1.0",
    text_document_sync_kind=TextDocumentSyncKind.Full
)

def make_friendly_error(error_msg: str) -> str:
    """Convert cryptic Lark errors to user-friendly messages"""
    # Common patterns
    if "No terminal matches" in error_msg:
        if "')'" in error_msg or "'('" in error_msg:
            return "Missing or mismatched parenthesis"
        elif "']'" in error_msg or "'['" in error_msg:
            return "Missing or mismatched bracket"
        elif "'}'" in error_msg or "'{'" in error_msg:
            return "Missing or mismatched brace"
        else:
            # Extract the unexpected character
            import re
            match = re.search(r"No terminal matches '(.)'", error_msg)
            if match:
                char = match.group(1)
                return f"Unexpected character: '{char}'"
            return "Unexpected character or missing operator"

    if "Unexpected token" in error_msg or "Expected" in error_msg:
        return error_msg  # These are already fairly clear

    # Default: return original but simplified
    return error_msg.split('\n')[0]  # First line only


def find_likely_error_location(text: str, reported_line: int, error_msg: str) -> tuple[int, str]:
    """
    Heuristic to find the actual error location when parser reports wrong line.

    Common case: Missing closing paren on line N, but parser reports error on line N+X
    where it encounters an unexpected character.

    Limitations:
    - Simple per-line counting (doesn't handle line continuations with backslash)
    - Doesn't strip strings or comments before counting
    - Will be replaced by proper semantic analysis in Phase 1.5

    Returns: (corrected_line_0based, corrected_message)
    """
    lines = text.splitlines()

    # If error is "unexpected character" at start of a line (col 1)
    if "Unexpected character" in error_msg and reported_line > 0:
        # Check previous non-empty, non-comment lines for unclosed parens/brackets/braces
        # Start from the line BEFORE where error was reported (reported_line - 2 in 0-based)
        for check_line_idx in range(reported_line - 2, max(-1, reported_line - 7), -1):
            if check_line_idx >= len(lines) or check_line_idx < 0:
                continue

            line_text = lines[check_line_idx].strip()

            # Skip empty lines and comments
            if not line_text or line_text.startswith('#'):
                continue

            # Count opening and closing delimiters
            open_parens = line_text.count('(') - line_text.count(')')
            open_brackets = line_text.count('[') - line_text.count(']')
            open_braces = line_text.count('{') - line_text.count('}')

            # If this line has unclosed delimiters, it's likely the culprit
            if open_parens > 0:
                return check_line_idx, f"Missing closing parenthesis ')'"
            elif open_brackets > 0:
                return check_line_idx, f"Missing closing bracket ']'"
            elif open_braces > 0:
                return check_line_idx, f"Missing closing brace '}}'"

            # If we found a complete statement, stop searching
            if open_parens == 0 and open_brackets == 0 and open_braces == 0:
                break

    # No better location found, return original
    return reported_line - 1, error_msg


def get_content_hash(text: str) -> str:
    """Get hash of content for cache key."""
    return hashlib.md5(text.encode()).hexdigest()


def get_cached_source_map(uri: str, text: str):
    """Get cached source map if available."""
    content_hash = get_content_hash(text)
    cache_key = (uri, content_hash)
    return _source_map_cache.get(cache_key)


def cache_source_map(uri: str, text: str, source_map):
    """Cache source map for given URI and content."""
    content_hash = get_content_hash(text)
    cache_key = (uri, content_hash)
    _source_map_cache[cache_key] = source_map
    
    # Limit cache size to prevent memory issues
    if len(_source_map_cache) > 100:
        # Remove oldest entries (simple FIFO)
        keys_to_remove = list(_source_map_cache.keys())[:50]
        for key in keys_to_remove:
            del _source_map_cache[key]


def validate_document(ls: XFYLanguageServer, uri: str, text: str) -> list[Diagnostic]:
    """
    Validate an XFY document and return diagnostics.

    Phase 1: Syntax validation (using parser)
    Phase 1.5: Semantic validation (using semantic_analyzer)

    Single source of truth: Reuses existing parser and semantic_analyzer
    """
    diagnostics = []

    # Get file path for proper include resolution
    file_path = uri.replace("file://", "")

    # Try to get cached source map first (fast path)
    source_map = get_cached_source_map(uri, text)
    
    try:
        # Phase 1: Parse the document
        # Parser returns (ast, parent_chain, python_namespace, source_map) tuple
        # Skip Python execution to avoid bpy dependency errors (syntax-only validation)
        parse_result = parse(text, filepath=file_path, skip_python=True)
        if isinstance(parse_result, tuple) and len(parse_result) >= 4:
            ast = parse_result[0]  # First element is the AST
            parse_source_map = parse_result[3]  # Fourth element is source_map
            # Cache the source map from successful parse
            if parse_source_map:
                cache_source_map(uri, text, parse_source_map)
                source_map = parse_source_map
        elif isinstance(parse_result, tuple):
            ast = parse_result[0]  # First element is the AST
        else:
            ast = parse_result  # Backwards compatibility

        # Phase 1.5: Semantic analysis (reuse analyzer for performance)
        ls._analyzer.reset()
        errors, warnings = ls._analyzer.analyze(ast)

        # Convert semantic errors to LSP diagnostics with source map translation
        # Errors are tuples: (message, line, column)
        for error in errors:
            if isinstance(error, tuple):
                message, line, col = error
            else:
                message, line, col = error, 0, 0  # Backwards compatibility
            
            # Translate line number using source map
            if source_map:
                orig_file, orig_line = source_map.get_original_location(line + 1)  # Convert to 1-indexed
                if orig_file and orig_file != file_path:
                    # Error is in a different file (included file)
                    # LSP can only report errors in the current file, so skip
                    continue
                elif orig_file:
                    line = orig_line - 1  # Back to 0-indexed
            
            diagnostics.append(
                Diagnostic(
                    range=Range(
                        start=Position(line=line, character=col),
                        end=Position(line=line, character=col + 20),
                    ),
                    message=message,
                    severity=DiagnosticSeverity.Error,
                    source="xfy-semantic",
                )
            )

        # Convert warnings to LSP diagnostics with source map translation
        # Warnings are tuples: (message, line, column)
        for warning in warnings:
            if isinstance(warning, tuple):
                message, line, col = warning
            else:
                message, line, col = warning, 0, 0  # Backwards compatibility
            
            # Translate line number using source map
            if source_map:
                orig_file, orig_line = source_map.get_original_location(line + 1)
                if orig_file and orig_file != file_path:
                    continue  # Skip warnings from included files
                elif orig_file:
                    line = orig_line - 1
            
            diagnostics.append(
                Diagnostic(
                    range=Range(
                        start=Position(line=line, character=col),
                        end=Position(line=line, character=col + 20),
                    ),
                    message=message,
                    severity=DiagnosticSeverity.Warning,
                    source="xfy-semantic",
                )
            )

        return diagnostics

    except Exception as e:
        # Parse error (syntax error)
        error_msg = str(e)
        friendly_msg = make_friendly_error(error_msg)

        # Extract line number from Lark error if available
        reported_line = 1
        if hasattr(e, 'line'):
            reported_line = e.line

        # Extract column if available
        col = 0
        if hasattr(e, 'column'):
            col = e.column - 1
        
        # If we don't have a cached source map, build one from preprocessing
        # This only happens once per unique file content
        if source_map is None:
            try:
                from source_map import SourceMap
                from parser import preprocess_includes
                import os
                
                preprocessed_source_map = SourceMap()
                _, _, preprocessed_source_map = preprocess_includes(
                    text,
                    base_path=os.path.dirname(os.path.abspath(file_path)) if file_path else None,
                    source_map=preprocessed_source_map,
                    current_file=os.path.abspath(file_path) if file_path else None
                )
                # Cache it for next time
                cache_source_map(uri, text, preprocessed_source_map)
                source_map = preprocessed_source_map
            except:
                pass  # If preprocessing fails, use heuristics
        
        # Translate line number using source map (if available)
        line = reported_line - 1  # LSP uses 0-based
        if source_map:
            orig_file, orig_line = source_map.get_original_location(reported_line)
            if orig_file and orig_file == file_path:
                line = orig_line - 1  # Back to 0-indexed
            elif orig_file:
                # Error in included file
                import os
                line = reported_line - 1
                friendly_msg = f"(in {os.path.basename(orig_file)}:{orig_line}) {friendly_msg}"
        else:
            # No source map available - try heuristics as fallback
            corrected_line, corrected_msg = find_likely_error_location(text, reported_line, friendly_msg)

            # If we found a better location via heuristics, use it
            if corrected_line != reported_line - 1:
                line = corrected_line
                friendly_msg = corrected_msg
                col = 0  # Point to start of line for "missing X" errors

        diagnostics.append(
            Diagnostic(
                range=Range(
                    start=Position(line=line, character=col),
                    end=Position(line=line, character=col + 50),
                ),
                message=friendly_msg,
                severity=DiagnosticSeverity.Error,
                source="xfy-parser",
            )
        )

    return diagnostics


@server.feature(TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: XFYLanguageServer, params):
    """Validate document when opened."""
    uri = params.text_document.uri
    # Use pygls workspace to get document
    doc = ls.workspace.get_text_document(uri)
    text = doc.source

    diagnostics = validate_document(ls, uri, text)
    ls.publish_diagnostics(uri, diagnostics)


def _debounced_validate(ls: XFYLanguageServer, uri: str, text: str):
    """
    Schedule debounced validation - only runs after DEBOUNCE_DELAY seconds of idle.
    
    This prevents validation from running on every keystroke, significantly
    improving performance for fast typists.
    """
    def do_validate():
        with _validation_lock:
            if uri in _validation_timers:
                del _validation_timers[uri]
        
        try:
            diagnostics = validate_document(ls, uri, text)
            ls.publish_diagnostics(uri, diagnostics)
        except Exception as e:
            # Don't crash on validation errors
            pass
    
    with _validation_lock:
        # Cancel any pending timer for this URI
        if uri in _validation_timers:
            _validation_timers[uri].cancel()
        
        # Schedule new validation
        timer = threading.Timer(DEBOUNCE_DELAY, do_validate)
        _validation_timers[uri] = timer
        timer.start()


@server.feature(TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: XFYLanguageServer, params):
    """Validate document on change (debounced for performance)."""
    uri = params.text_document.uri
    # Use pygls workspace to get updated document
    doc = ls.workspace.get_text_document(uri)
    text = doc.source

    # Use debounced validation to avoid running on every keystroke
    _debounced_validate(ls, uri, text)


@server.feature(TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: XFYLanguageServer, params):
    """Validate document when saved (immediate, no debounce)."""
    uri = params.text_document.uri
    # Use pygls workspace to get document
    doc = ls.workspace.get_text_document(uri)
    text = doc.source

    # Validate immediately on save (user expects feedback after explicit action)
    diagnostics = validate_document(ls, uri, text)
    ls.publish_diagnostics(uri, diagnostics)


# XFY language keywords and types
XFY_KEYWORDS = [
    "input", "output", "group", "loop", "repeat", "frame", "include",
    "True", "False",
]

XFY_TYPES = [
    "float", "int", "bool", "vector", "geometry", "string", "color",
    "object", "material", "mat", "image", "collection", "matrix", "rotation",
    "bundle", "closure", "menu", "font", "sound", "int_vector",
]


def get_attribute_context(text_before: str) -> tuple[str, bool] | None:
    """
    Detect if cursor is inside an attribute block {...}.

    Args:
        text_before: Text from start of line to cursor position

    Returns:
        (function_name, in_value) tuple if inside attributes, None otherwise.
        - function_name: The function/node name before the {
        - in_value: True if after "attr:", False if expecting attr name
    """
    # Count braces to determine if we're inside {}
    brace_depth = 0
    last_open_brace = -1

    for i, ch in enumerate(text_before):
        if ch == '{':
            brace_depth += 1
            last_open_brace = i
        elif ch == '}':
            brace_depth -= 1

    # Not inside {} if depth is 0 or negative
    if brace_depth <= 0 or last_open_brace < 0:
        return None

    # Extract function name before the {
    before_brace = text_before[:last_open_brace].rstrip()
    func_match = re.search(r'(\w+)\s*$', before_brace)
    if not func_match:
        return None

    func_name = func_match.group(1)

    # Check if we're after "attr:" (expecting value) or not (expecting attr name)
    inside_braces = text_before[last_open_brace + 1:]

    # After "attr:" means we're expecting a value
    # We need to handle cases like: {domain: or {domain:'EDGE', data_type:
    # Look for pattern: attr_name followed by : and no closing value yet
    in_value = bool(re.search(r'\w+\s*:\s*$', inside_braces))

    return func_name, in_value


@server.feature(TEXT_DOCUMENT_COMPLETION)
def completions(ls: XFYLanguageServer, params: CompletionParams) -> CompletionList:
    """Provide autocomplete suggestions."""
    items = []

    # Get current document and cursor position
    uri = params.text_document.uri
    doc = ls.workspace.get_text_document(uri)
    lines = doc.source.splitlines()

    # Get current line and text before cursor
    line_idx = params.position.line
    char_idx = params.position.character

    if line_idx < len(lines):
        line = lines[line_idx]
        text_before = line[:char_idx]
    else:
        text_before = ""

    # Determine context for filtering
    # After "input name:" or "output name:", suggest types
    # But only at line start, not inside function calls or attributes
    type_decl_match = re.match(r'^\s*(input|output)\s+\w+\s*:\s*$', text_before)
    if type_decl_match:
        for t in XFY_TYPES:
            items.append(CompletionItem(
                label=t,
                kind=CompletionItemKind.TypeParameter,
                detail="XFY type",
            ))
        return CompletionList(is_incomplete=False, items=items)

    # Check if inside attribute block {attr: value}
    attr_context = get_attribute_context(text_before)
    if attr_context:
        func_name, in_value = attr_context

        if in_value:
            # After "attr:" - suggest attribute values
            # Extract the attribute name
            attr_match = re.search(r'(\w+)\s*:\s*$', text_before)
            if attr_match:
                attr_name = attr_match.group(1)
                valid_values = get_valid_values(attr_name)
                if valid_values:
                    for val in valid_values:
                        items.append(CompletionItem(
                            label=f"'{val}'",
                            kind=CompletionItemKind.EnumMember,
                            detail=f"value for {attr_name}",
                            sort_text=f"0_{val}",
                        ))
                    return CompletionList(is_incomplete=False, items=items)
        else:
            # Inside {} but not after ":" - suggest attribute names
            # First, try to get node-specific attributes from registry
            actual_node = func_name
            if func_name in FUNCTION_SHORTCUTS:
                shortcut_info = FUNCTION_SHORTCUTS[func_name]
                actual_node = shortcut_info[0] if isinstance(shortcut_info, tuple) else shortcut_info

            node_info = ls.registry.nodes.get(actual_node)
            suggested_attrs = set()

            if node_info and "properties" in node_info:
                # Suggest node-specific properties
                user_props = get_user_facing_properties(node_info["properties"])
                for prop in user_props:
                    suggested_attrs.add(prop)
                    prop_info = node_info["properties"].get(prop, {})
                    prop_type = prop_info.get("type", "")
                    items.append(CompletionItem(
                        label=prop,
                        kind=CompletionItemKind.Property,
                        detail=f"{prop_type} (node property)",
                        sort_text=f"0_{prop}",
                    ))

            # Also suggest common attributes (that aren't already suggested)
            for attr_name in COMMON_ATTRIBUTES.keys():
                if attr_name not in suggested_attrs:
                    items.append(CompletionItem(
                        label=attr_name,
                        kind=CompletionItemKind.Property,
                        detail="common attribute",
                        sort_text=f"1_{attr_name}",
                    ))

            return CompletionList(is_incomplete=False, items=items)

    # Always suggest keywords (LSP client filters based on typed text)
    for kw in XFY_KEYWORDS:
        items.append(CompletionItem(
            label=kw,
            kind=CompletionItemKind.Keyword,
            detail="XFY keyword",
            sort_text=f"0_{kw}",  # Sort keywords first
        ))

    # Suggest shortcuts (high priority - these are commonly used)
    for name in ls.shortcut_names:
        shortcut_info = FUNCTION_SHORTCUTS[name]
        if isinstance(shortcut_info, tuple):
            node_type, attrs = shortcut_info
            detail = f"→ {node_type}"
            if attrs:
                detail += f" {attrs}"
        else:
            detail = f"→ {shortcut_info}"

        items.append(CompletionItem(
            label=name,
            kind=CompletionItemKind.Function,
            detail=detail,
            sort_text=f"1_{name}",  # Sort after keywords
        ))

    # Suggest node names from registry
    for name in ls.node_names:
        node_info = ls.registry.nodes.get(name, {})
        bl_label = node_info.get("bl_label", name)

        items.append(CompletionItem(
            label=name,
            kind=CompletionItemKind.Function,
            detail=bl_label,
            sort_text=f"2_{name}",  # Sort after shortcuts
        ))

    # Suggest variables defined in the document (highest priority for local context)
    variables = find_variable_definitions(doc.source)
    for var_name, (var_line, var_col, context) in variables.items():
        # Only suggest variables defined before current position
        if var_line < line_idx or (var_line == line_idx and var_col < char_idx):
            if context == "input":
                detail = "input parameter"
                kind = CompletionItemKind.Variable
            elif context == "loop_state":
                detail = "loop state variable"
                kind = CompletionItemKind.Variable
            else:
                detail = f"defined at line {var_line + 1}"
                kind = CompletionItemKind.Variable

            items.append(CompletionItem(
                label=var_name,
                kind=kind,
                detail=detail,
                sort_text=f"0_{var_name}",  # Sort first (local vars are most relevant)
            ))

    # Suggest groups defined in the document
    groups = find_group_definitions(doc.source)
    for group_name, (group_line, group_col) in groups.items():
        items.append(CompletionItem(
            label=group_name,
            kind=CompletionItemKind.Class,
            detail=f"group (line {group_line + 1})",
            sort_text=f"0_{group_name}",  # Sort first (local groups are most relevant)
        ))

    return CompletionList(is_incomplete=False, items=items)


def find_group_definitions(text: str) -> dict[str, tuple[int, int]]:
    """
    Find all group definitions in the document.
    Returns dict of group_name -> (line_0based, column_0based)
    """
    groups = {}
    for line_idx, line in enumerate(text.splitlines()):
        # Match: group GroupName "optional string" {
        match = re.match(r'^\s*group\s+(\w+)', line)
        if match:
            group_name = match.group(1)
            col = match.start(1)
            groups[group_name] = (line_idx, col)
    return groups


def find_variable_definitions(text: str) -> dict[str, tuple[int, int, str]]:
    """
    Find all variable definitions in the document.
    Returns dict of var_name -> (line_0based, column_0based, context)
    where context is 'assignment', 'input', or 'loop_state'
    """
    variables = {}
    in_python_block = False

    for line_idx, line in enumerate(text.splitlines()):
        stripped = line.strip()

        # Track python blocks (skip them)
        if stripped.startswith("```"):
            in_python_block = not in_python_block
            continue
        if in_python_block:
            continue

        # Skip comments
        if stripped.startswith("#"):
            continue

        # Match: input name: type ...
        input_match = re.match(r'^\s*input\s+(\w+)\s*:', line)
        if input_match:
            var_name = input_match.group(1)
            col = input_match.start(1)
            variables[var_name] = (line_idx, col, "input")
            continue

        # Match: name = expression (but not == comparison)
        # Avoid matching inside function calls or attributes
        assign_match = re.match(r'^\s*(\w+)\s*=(?!=)', line)
        if assign_match:
            var_name = assign_match.group(1)
            # Skip keywords that look like assignments
            if var_name not in ("input", "output", "group", "loop", "repeat", "frame", "include"):
                # Don't overwrite earlier definitions (e.g., loop_state vars)
                if var_name not in variables:
                    col = assign_match.start(1)
                    variables[var_name] = (line_idx, col, "assignment")
            continue

        # Match: loop ..., state=(var1, var2, ...)
        state_match = re.search(r'state\s*=\s*\(([^)]+)\)', line)
        if state_match:
            state_vars = state_match.group(1)
            for var in state_vars.split(','):
                var_name = var.strip()
                if var_name and var_name.isidentifier():
                    variables[var_name] = (line_idx, 0, "loop_state")

    return variables


def find_include_path(line: str, base_path: str) -> str | None:
    """
    Extract and resolve include path from a line.
    Returns absolute path or None if not an include statement.
    """
    match = re.match(r'^\s*include\s+(.+?)\s*$', line)
    if match:
        include_path = match.group(1).strip()
        # Resolve relative paths
        if not os.path.isabs(include_path):
            include_path = os.path.join(base_path, include_path)
        return os.path.abspath(include_path)
    return None


def get_word_at_position(line: str, character: int) -> str | None:
    """Get the word (identifier) at the given character position."""
    if character > len(line):
        return None

    # Find word boundaries
    start = character
    while start > 0 and (line[start - 1].isalnum() or line[start - 1] == '_'):
        start -= 1

    end = character
    while end < len(line) and (line[end].isalnum() or line[end] == '_'):
        end += 1

    if start == end:
        return None

    return line[start:end]


@server.feature(TEXT_DOCUMENT_DEFINITION)
def goto_definition(ls: XFYLanguageServer, params: DefinitionParams) -> Location | list[Location] | None:
    """Go to definition for groups and includes."""
    uri = params.text_document.uri
    doc = ls.workspace.get_text_document(uri)
    lines = doc.source.splitlines()

    line_idx = params.position.line
    char_idx = params.position.character

    if line_idx >= len(lines):
        return None

    line = lines[line_idx]
    file_path = uri.replace("file://", "")
    base_path = os.path.dirname(file_path)

    # Check if on an include statement
    include_path = find_include_path(line, base_path)
    if include_path and os.path.exists(include_path):
        return Location(
            uri=f"file://{include_path}",
            range=Range(
                start=Position(line=0, character=0),
                end=Position(line=0, character=0),
            ),
        )

    # Get word at cursor position
    word = get_word_at_position(line, char_idx)
    if not word:
        return None

    # Find group definitions in current document
    groups = find_group_definitions(doc.source)

    if word in groups:
        def_line, def_col = groups[word]
        return Location(
            uri=uri,
            range=Range(
                start=Position(line=def_line, character=def_col),
                end=Position(line=def_line, character=def_col + len(word)),
            ),
        )

    # Find variable definitions in current document
    variables = find_variable_definitions(doc.source)

    if word in variables:
        def_line, def_col, _ = variables[word]
        return Location(
            uri=uri,
            range=Range(
                start=Position(line=def_line, character=def_col),
                end=Position(line=def_line, character=def_col + len(word)),
            ),
        )

    # TODO: Search in included files for group definitions

    return None


def get_function_context(line: str, character: int) -> tuple[str | None, int]:
    """
    Get function name and parameter index at cursor position.
    Returns (function_name, param_index) or (None, 0) if not in a function call.
    """
    # Find the opening paren before cursor
    text_before = line[:character]

    # Count nested parens to find the active function call
    paren_depth = 0
    func_start = -1

    for i in range(len(text_before) - 1, -1, -1):
        ch = text_before[i]
        if ch == ')':
            paren_depth += 1
        elif ch == '(':
            if paren_depth == 0:
                func_start = i
                break
            paren_depth -= 1

    if func_start < 0:
        return None, 0

    # Extract function name (word before the paren, possibly with {} attrs)
    before_paren = text_before[:func_start].rstrip()

    # Skip attributes block if present: func{...}(
    if before_paren.endswith('}'):
        brace_depth = 1
        for i in range(len(before_paren) - 2, -1, -1):
            if before_paren[i] == '}':
                brace_depth += 1
            elif before_paren[i] == '{':
                brace_depth -= 1
                if brace_depth == 0:
                    before_paren = before_paren[:i].rstrip()
                    break

    # Extract function name
    match = re.search(r'(\w+)\s*$', before_paren)
    if not match:
        return None, 0

    func_name = match.group(1)

    # Count commas to determine parameter index
    inside_call = text_before[func_start + 1:]
    param_idx = 0
    paren_depth = 0

    for ch in inside_call:
        if ch == '(':
            paren_depth += 1
        elif ch == ')':
            paren_depth -= 1
        elif ch == ',' and paren_depth == 0:
            param_idx += 1

    return func_name, param_idx


@server.feature(TEXT_DOCUMENT_SIGNATURE_HELP)
def signature_help(ls: XFYLanguageServer, params: SignatureHelpParams) -> SignatureHelp | None:
    """Provide signature help for function calls."""
    uri = params.text_document.uri
    doc = ls.workspace.get_text_document(uri)
    lines = doc.source.splitlines()

    line_idx = params.position.line
    char_idx = params.position.character

    if line_idx >= len(lines):
        return None

    line = lines[line_idx]

    # Get function context
    func_name, param_idx = get_function_context(line, char_idx)
    if not func_name:
        return None

    # Check if it's a shortcut
    if func_name in FUNCTION_SHORTCUTS:
        shortcut_info = FUNCTION_SHORTCUTS[func_name]
        if isinstance(shortcut_info, tuple):
            actual_node, _ = shortcut_info
        else:
            actual_node = shortcut_info
        # Use the actual node name for lookup
        func_name = actual_node

    # Look up node in registry
    node_info = ls.registry.nodes.get(func_name)
    if not node_info:
        return None

    # Build parameter list from node inputs
    inputs = node_info.get("inputs", [])
    params_list = []
    param_labels = []

    for inp in inputs:
        inp_name = inp.get("name", "?")
        inp_type = inp.get("type", "")
        # Simplify type names
        type_short = inp_type.replace("NodeSocket", "").lower()
        param_str = f"{inp_name}: {type_short}"
        params_list.append(param_str)
        param_labels.append(ParameterInformation(label=param_str))

    if not params_list:
        return None

    # Build signature string
    signature_str = f"{func_name}({', '.join(params_list)})"
    bl_label = node_info.get("bl_label", func_name)

    return SignatureHelp(
        signatures=[
            SignatureInformation(
                label=signature_str,
                documentation=bl_label,
                parameters=param_labels,
            )
        ],
        active_signature=0,
        active_parameter=min(param_idx, len(param_labels) - 1) if param_labels else 0,
    )


# Keyword documentation
KEYWORD_DOCS = {
    "input": "Declare an input parameter.\n\nSyntax: `input name: type \"Display Name\" = default`",
    "output": "Declare an output.\n\nSyntax: `output name` or `output name: type \"Display Name\"`",
    "group": "Define a reusable node group.\n\nSyntax: `group Name \"Display\" { ... }`",
    "loop": "Create a repeat zone loop.\n\nSyntax: `loop iterations, geometry, state=(vars) { ... }`",
    "repeat": "Alias for loop. Create a repeat zone.\n\nSyntax: `repeat count, geo, state=(vars):idx, geo { ... }`",
    "frame": "Group nodes visually in a frame.\n\nSyntax: `frame \"Label\" { ... }`",
    "include": "Include another .xfy file.\n\nSyntax: `include ./path/to/file.xfy`",
    "state": "Declare loop state variables.\n\nUsed within loop/repeat syntax.",
    "True": "Boolean true value.",
    "False": "Boolean false value.",
}

TYPE_DOCS = {
    "float": "Floating point number (e.g., 1.5, -0.3)",
    "int": "Integer number (e.g., 1, -5, 100)",
    "bool": "Boolean value (True or False)",
    "vector": "3D vector (x, y, z)",
    "geometry": "Geometry data (mesh, curve, etc.)",
    "string": "Text string",
    "color": "RGBA color value",
    "object": "Blender object reference",
    "material": "Blender material reference",
    "image": "Blender image reference",
    "collection": "Blender collection reference",
}


def build_node_hover(node_name: str, node_info: dict) -> str:
    """Build markdown documentation for a node."""
    bl_label = node_info.get("bl_label", node_name)
    bl_idname = node_info.get("bl_idname", "")

    lines = [f"## {bl_label}", f"`{node_name}`"]

    if bl_idname:
        lines.append(f"\n*{bl_idname}*")

    # Inputs
    inputs = node_info.get("inputs", [])
    if inputs:
        lines.append("\n**Inputs:**")
        for inp in inputs:
            inp_name = inp.get("name", "?")
            inp_type = inp.get("type", "").replace("NodeSocket", "")
            lines.append(f"- `{inp_name}`: {inp_type}")

    # Outputs
    outputs = node_info.get("outputs", [])
    if outputs:
        lines.append("\n**Outputs:**")
        for out in outputs:
            out_name = out.get("name", "?")
            out_type = out.get("type", "").replace("NodeSocket", "")
            lines.append(f"- `{out_name}`: {out_type}")

    return "\n".join(lines)


@server.feature(TEXT_DOCUMENT_HOVER)
def hover(ls: XFYLanguageServer, params: HoverParams) -> Hover | None:
    """Provide hover documentation."""
    uri = params.text_document.uri
    doc = ls.workspace.get_text_document(uri)
    lines = doc.source.splitlines()

    line_idx = params.position.line
    char_idx = params.position.character

    if line_idx >= len(lines):
        return None

    line = lines[line_idx]

    # Get word at cursor
    word = get_word_at_position(line, char_idx)
    if not word:
        return None

    # Check keywords
    if word in KEYWORD_DOCS:
        return Hover(
            contents=MarkupContent(
                kind=MarkupKind.Markdown,
                value=f"**{word}**\n\n{KEYWORD_DOCS[word]}",
            )
        )

    # Check types
    if word in TYPE_DOCS:
        return Hover(
            contents=MarkupContent(
                kind=MarkupKind.Markdown,
                value=f"**{word}** (type)\n\n{TYPE_DOCS[word]}",
            )
        )

    # Check shortcuts
    if word in FUNCTION_SHORTCUTS:
        shortcut_info = FUNCTION_SHORTCUTS[word]
        if isinstance(shortcut_info, tuple):
            node_type, attrs = shortcut_info
            attr_str = ", ".join(f"{k}={v!r}" for k, v in attrs.items())
            content = f"**{word}** (shortcut)\n\n→ `{node_type}` with `{{{attr_str}}}`"
        else:
            content = f"**{word}** (shortcut)\n\n→ `{shortcut_info}`"

        # Also show the underlying node info if available
        actual_node = shortcut_info[0] if isinstance(shortcut_info, tuple) else shortcut_info
        node_info = ls.registry.nodes.get(actual_node)
        if node_info:
            content += "\n\n---\n" + build_node_hover(actual_node, node_info)

        return Hover(
            contents=MarkupContent(
                kind=MarkupKind.Markdown,
                value=content,
            )
        )

    # Check node registry
    node_info = ls.registry.nodes.get(word)
    if node_info:
        return Hover(
            contents=MarkupContent(
                kind=MarkupKind.Markdown,
                value=build_node_hover(word, node_info),
            )
        )

    # Check group definitions
    groups = find_group_definitions(doc.source)
    if word in groups:
        def_line, _ = groups[word]
        return Hover(
            contents=MarkupContent(
                kind=MarkupKind.Markdown,
                value=f"**{word}** (group)\n\nDefined at line {def_line + 1}",
            )
        )

    # Check variable definitions
    variables = find_variable_definitions(doc.source)
    if word in variables:
        var_line, var_col, context = variables[word]
        if context == "input":
            desc = "input parameter"
        elif context == "loop_state":
            desc = "loop state variable"
        else:
            desc = "variable"
        return Hover(
            contents=MarkupContent(
                kind=MarkupKind.Markdown,
                value=f"**{word}** ({desc})\n\nDefined at line {var_line + 1}",
            )
        )

    return None


def main():
    """Start the LSP server."""
    server.start_io()


if __name__ == "__main__":
    main()
