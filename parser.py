import os
import re
import types
import hashlib
from lark import Lark

GRAMMAR_PATH = os.path.join(os.path.dirname(__file__), 'grammar.lark')

# Parser cache for performance (avoids rebuilding Lark parser on every parse)
# Only rebuilt when grammar file changes
_parser_cache = None
_grammar_hash = None

def _get_cached_parser():
    """
    Get cached Lark parser, rebuilding only if grammar changed.
    
    This is critical for LSP performance - parser construction is expensive (~200ms)
    and was previously done on every keystroke.
    """
    global _parser_cache, _grammar_hash
    
    # Read grammar and compute hash
    with open(GRAMMAR_PATH, 'rb') as f:
        grammar_bytes = f.read()
    current_hash = hashlib.md5(grammar_bytes).hexdigest()
    
    # Rebuild parser if hash changed or first time
    if _parser_cache is None or _grammar_hash != current_hash:
        grammar = grammar_bytes.decode('utf-8')
        _parser_cache = Lark(
            grammar, 
            start='start', 
            parser='earley', 
            cache=False,  # Lark's internal cache doesn't help here
            propagate_positions=True
        )
        _grammar_hash = current_hash
    
    return _parser_cache

# Magic comment to mark Python blocks as deferred (run after script compilation)
DEFER_MARKER = '#defer'


def is_deferred_block(code: str) -> bool:
    """
    Check if a Python block is marked as deferred.
    
    A deferred block starts with '#defer' (with optional trailing content on same line).
    Example:
        ```#defer
        # This runs AFTER script compilation
        ```
    
    Args:
        code: The Python code content (with ``` markers stripped)
        
    Returns:
        True if block should be deferred, False otherwise
    """
    stripped = code.strip()
    # Check for #defer at start (case-insensitive)
    return stripped.lower().startswith(DEFER_MARKER.lower())


def preprocess_python_macros(text, parent_chain=None, skip_python=False, extra_namespaces=None, current_file=None, source_map=None):
    """
    Preprocess py!.* macro substitutions and separate deferred blocks.

    This function:
    1. Extracts Python blocks (``` ... ```)
    2. Separates normal blocks from deferred blocks (#defer marker)
    3. Executes ONLY normal blocks to build namespace
    4. Replaces py!.varname patterns with values from namespace
    5. Returns deferred blocks for execution after script compilation

    Args:
        text: The script text to preprocess
        parent_chain: Default parent chain for untagged blocks [direct_parent, ..., root]
        skip_python: If True, skip Python block execution (for syntax-only validation)
        extra_namespaces: Optional list of namespace dicts to merge into the scope
        current_file: Path to current file being processed
        source_map: SourceMap tracking line transformations

    Returns:
        Tuple of (modified_text, python_namespace, deferred_blocks) where:
        - modified_text: Text with py!.* macros replaced
        - python_namespace: Dict of variables from normal Python blocks
        - deferred_blocks: List of (code, parent_chain) tuples to execute after compilation

    Note:
        This is RAW TEXT SUBSTITUTION with NO type checking.
        Use py.* (without !) for type-safe value substitution at compile time.
    """
    if parent_chain is None:
        parent_chain = []

    def _format_error_with_loc(err, prep_line, default_msg=None):
        orig_file = current_file
        orig_line = prep_line
        if source_map and prep_line:
            m_file, m_line = source_map.get_original_location(prep_line)
            if m_file:
                orig_file = m_file
                orig_line = m_line
        snippet = ""
        if orig_file and os.path.exists(orig_file) and orig_line:
            try:
                with open(orig_file, "r", encoding="utf-8") as f:
                    f_lines = f.read().splitlines()
                if 0 < orig_line <= len(f_lines):
                    snippet = f_lines[orig_line - 1].strip()
            except Exception:
                pass
        loc_parts = []
        if orig_file:
            loc_parts.append(str(orig_file))
        if orig_line is not None:
            loc_parts.append(str(orig_line))
        loc = ":".join(loc_parts)
        msg = default_msg if default_msg else str(err)
        if loc:
            if snippet:
                return f"{loc}: {msg}\n  {snippet}"
            return f"{loc}: {msg}"
        return msg

    # Pattern to match parent chain tags followed by Python blocks
    # Match: # __XNODIFY_PARENTS__: [...]\n```...```
    tagged_block_pattern = r'# __XNODIFY_PARENTS__: (.*?)\n(```[\s\S]*?```)'

    # Find all tagged blocks and their parent chains
    tagged_matches = list(re.finditer(tagged_block_pattern, text))

    # Find all Python blocks (tagged and untagged)
    all_blocks = list(re.finditer(r'```[\s\S]*?```', text))

    if not all_blocks:
        return text, {}, []  # No Python blocks to process
    
    # If skipping Python execution, comment out lines with py!. macros
    if skip_python:
        # Comment out any line containing py!. to avoid parse errors
        # This allows syntax validation without Python execution
        lines = text.split('\n')
        processed_lines = []
        for line in lines:
            if 'py!.' in line:
                # Comment out this line
                processed_lines.append('# ' + line)
            else:
                processed_lines.append(line)
        return '\n'.join(processed_lines), {}, []

    # Build set of tagged block positions
    tagged_positions = {match.start(2) for match in tagged_matches}

    # Separate tagged and untagged blocks, further separating deferred blocks
    # All blocks will be categorized into: normal_tagged, normal_untagged, deferred
    normal_tagged_blocks = []  # List of (parent_chain, code, code_start_line) tuples
    normal_untagged_blocks = []  # List of (code, code_start_line) tuples
    deferred_blocks = []  # List of (code, parent_chain) tuples

    def strip_defer_marker(code):
        """Remove #defer marker from code, preserving the rest"""
        lines = code.split('\n')
        if lines and lines[0].strip().lower().startswith(DEFER_MARKER.lower()):
            # Remove the #defer line
            return '\n'.join(lines[1:]).strip()
        return code

    for block_match in all_blocks:
        block_start = block_match.start()
        block_text = block_match.group(0)
        # Calculate line in preprocessed text
        block_line_in_text = text[:block_start].count('\n') + 1
        # Extract code content (strip ``` markers)
        code = block_text[3:-3].strip()
        code_offset_lines = block_text[:block_text.find(code)].count('\n') if code else 0
        code_start_line = block_line_in_text + code_offset_lines

        if block_start in tagged_positions:
            # This is a tagged block - find its tag
            for tag_match in tagged_matches:
                if tag_match.start(2) == block_start:
                    parent_chain_repr = tag_match.group(1)
                    try:
                        block_parent_chain = eval(parent_chain_repr)
                    except:
                        block_parent_chain = parent_chain
                    
                    # Check if deferred
                    if is_deferred_block(code):
                        deferred_blocks.append((strip_defer_marker(code), block_parent_chain))
                    else:
                        normal_tagged_blocks.append((block_parent_chain, code, code_start_line))
                    break
        else:
            # Untagged block - check if deferred
            if is_deferred_block(code):
                deferred_blocks.append((strip_defer_marker(code), parent_chain))
            else:
                normal_untagged_blocks.append((code, code_start_line))

    # Build global namespace by executing ONLY NORMAL Python blocks
    # Deferred blocks will be executed after script compilation
    # bpy is only available inside Blender - make it optional for LSP/validation
    try:
        import bpy
    except ModuleNotFoundError:
        bpy = None  # Running outside Blender (LSP, validation, etc.)

    namespace = {
        "bpy": bpy,
        "_selfobj": bpy.context.view_layer.objects.active if (bpy and hasattr(bpy.context, "view_layer") and bpy.context.view_layer) else None,
        "__builtins__": __builtins__,
    }

    # Merge extra namespaces (from skipped includes)
    if extra_namespaces:
        for extra_ns in extra_namespaces:
            namespace.update(extra_ns)

    # Execute each normal tagged block with its specific parent chain
    for block_parent_chain, code, code_start_line in normal_tagged_blocks:
        # Execute with this block's parent chain
        try:
            namespace['__parents__'] = block_parent_chain
            namespace['__file__'] = block_parent_chain[0] if block_parent_chain else current_file
            
            import sys, os
            namespace['__name__'] = '__main__'
            namespace['__package__'] = ''
            if namespace['__file__']:
                s_dir = os.path.dirname(os.path.abspath(namespace['__file__']))
                if s_dir not in sys.path: sys.path.insert(0, s_dir)
                
            exec(code, namespace)
        except Exception as e:
            err_line_in_code = 1
            if isinstance(e, SyntaxError) and getattr(e, 'lineno', None) is not None:
                err_line_in_code = e.lineno
            else:
                import sys
                tb = sys.exc_info()[2]
                while tb and tb.tb_next:
                    tb = tb.tb_next
                if tb:
                    err_line_in_code = tb.tb_lineno
            prep_line = code_start_line + (err_line_in_code - 1)
            err_str = _format_error_with_loc(e, prep_line, f"Error executing Python block for macro expansion: {e}")
            raise RuntimeError(err_str) from e

    # Execute each normal untagged block with default parent chain
    for code, code_start_line in normal_untagged_blocks:
        # Execute with default parent chain
        try:
            namespace['__parents__'] = parent_chain
            namespace['__file__'] = parent_chain[0] if parent_chain else current_file
            
            import sys, os
            namespace['__name__'] = '__main__'
            namespace['__package__'] = ''
            if namespace['__file__']:
                s_dir = os.path.dirname(os.path.abspath(namespace['__file__']))
                if s_dir not in sys.path: sys.path.insert(0, s_dir)
                
            exec(code, namespace)
        except Exception as e:
            err_line_in_code = 1
            if isinstance(e, SyntaxError) and getattr(e, 'lineno', None) is not None:
                err_line_in_code = e.lineno
            else:
                import sys
                tb = sys.exc_info()[2]
                while tb and tb.tb_next:
                    tb = tb.tb_next
                if tb:
                    err_line_in_code = tb.tb_lineno
            prep_line = code_start_line + (err_line_in_code - 1)
            err_str = _format_error_with_loc(e, prep_line, f"Error executing Python block for macro expansion: {e}")
            raise RuntimeError(err_str) from e

    # Filter namespace to only include user variables
    # Skip: dunder names (__x__), 'bpy', and modules
    python_namespace = {}
    for k, v in namespace.items():
        if k.startswith('__') or k == 'bpy' or isinstance(v, types.ModuleType):
            continue
        python_namespace[k] = v

    # Pattern to match py!.varname (word boundary after varname)
    macro_pattern = r'py!\.(\w+)'

    # Function to replace a single macro match
    def replace_single_macro(match_obj):
        var_name = match_obj.group(1)
        if var_name not in python_namespace:
            match_line = text[:match_obj.start()].count('\n') + 1
            err_msg = (
                f"Python macro variable 'py!.{var_name}' not found. "
                f"Available: {', '.join(sorted(python_namespace.keys()))}"
            )
            raise NameError(_format_error_with_loc(None, match_line, err_msg))
        value = python_namespace[var_name]
        return value if isinstance(value, str) else str(value)

    # Main callback for the tokenizing regex
    def tokenize_and_replace(match):
        token = match.group(0)
        
        # 1. Comment: Return unchanged (ignore macros inside)
        if match.group('comment'):
            return token
            
        # 2. String: Expand macros inside the string
        # (Macros ARE supported inside strings, e.g. attributes)
        if match.group('string') or match.group('triple'):
            # Simple recursive substitution inside the string
            # No need to worry about comments inside strings
            return re.sub(macro_pattern, replace_single_macro, token)
            
        # 3. Macro: Replace it directly
        if match.group('macro'):
            # Extract just the name part from the full match 'py!.name'
            var_name = token[4:] # strip 'py!.'
            if var_name not in python_namespace:
                match_line = text[:match.start()].count('\n') + 1
                err_msg = (
                    f"Python macro variable 'py!.{var_name}' not found. "
                    f"Available: {', '.join(sorted(python_namespace.keys()))}"
                )
                raise NameError(_format_error_with_loc(None, match_line, err_msg))
            value = python_namespace[var_name]
            return value if isinstance(value, str) else str(value)
            
        return token

    # Comprehensive Regex to tokenize the input:
    # 1. Triple-quoted strings (multi-line)
    # 2. Strings (single/double quoted, handling escapes)
    # 3. Comments
    # 4. Macros
    tokenizer_pattern = re.compile(
        r'(?P<triple>"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')|'  # Triple quoted strings
        r'(?P<string>"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\')|'  # Normal strings
        r'(?P<comment>#[^\n]*)|'  # Comments
        r'(?P<macro>py!\.\w+)'  # Macros
    )

    # Perform the replacement scan with source mapping
    output_pieces = []
    line_locations = {}
    curr_input_line = 1
    curr_output_line = 1
    
    if source_map:
        line_locations[1] = source_map.get_original_location(1)
    
    last_end = 0
    for match in tokenizer_pattern.finditer(text):
        # 1. Unmatched text before this match
        unmatched = text[last_end:match.start()]
        if unmatched:
            output_pieces.append(unmatched)
            if source_map:
                for char in unmatched:
                    if char == '\n':
                        curr_input_line += 1
                        curr_output_line += 1
                        line_locations[curr_output_line] = source_map.get_original_location(curr_input_line)

        # 2. Replacement for this match
        replacement = tokenize_and_replace(match)
        output_pieces.append(replacement)
        
        if source_map:
            match_text = match.group(0)
            n_match_newlines = match_text.count('\n')
            match_orig_loc = source_map.get_original_location(curr_input_line)
            
            for char in replacement:
                if char == '\n':
                    curr_output_line += 1
                    line_locations[curr_output_line] = match_orig_loc
            
            curr_input_line += n_match_newlines

        last_end = match.end()

    # Trailing unmatched text
    trailing = text[last_end:]
    if trailing:
        output_pieces.append(trailing)
        if source_map:
            for char in trailing:
                if char == '\n':
                    curr_input_line += 1
                    curr_output_line += 1
                    line_locations[curr_output_line] = source_map.get_original_location(curr_input_line)

    modified_text = "".join(output_pieces)

    if source_map and line_locations:
        # Reconstruct source_map.mappings from line_locations
        new_mappings = []
        total_out_lines = curr_output_line
        
        range_start = 1
        range_file, range_orig_start = line_locations.get(1, (None, 1))
        
        for out_line in range(2, total_out_lines + 1):
            curr_file, curr_orig = line_locations.get(out_line, (None, out_line))
            expected_orig = range_orig_start + (out_line - range_start)
            
            if curr_file == range_file and curr_orig == expected_orig:
                # Contiguous linear range continues
                continue
            else:
                # End previous range
                new_mappings.append((range_start, out_line, range_file, range_orig_start))
                range_start = out_line
                range_file, range_orig_start = curr_file, curr_orig
        
        new_mappings.append((range_start, total_out_lines + 1, range_file, range_orig_start))
        source_map.mappings = new_mappings

    # Return modified text, namespace, AND deferred blocks for post-compilation execution
    return modified_text, python_namespace, deferred_blocks

def tag_python_blocks_with_parents(text, parent_chain):
    """
    Tag Python blocks with their parent chain metadata.

    Inserts a special comment before each Python block indicating its parent chain.
    This allows preprocess_python_macros() to inject the correct __parents__ value
    for each block when all blocks are executed together.

    Args:
        text: Text containing Python blocks
        parent_chain: Parent chain for these blocks

    Returns:
        Text with tagged Python blocks
    """
    # Pattern to match Python code blocks
    python_block_pattern = r'(```[\s\S]*?```)'

    # Tag function to add parent chain comment before each block
    parent_chain_repr = repr(parent_chain)
    def add_tag(match):
        block = match.group(1)
        # Add special comment marker before the block
        return f"# __XNODIFY_PARENTS__: {parent_chain_repr}\n{block}"

    return re.sub(python_block_pattern, add_tag, text)


def preprocess_includes(text, base_path=None, include_stack=None, already_included=None, parent_chain=None, source_map=None, current_file=None):
    """
    Preprocess include statements recursively.

    Args:
        text: The script text to preprocess
        base_path: Base directory for resolving relative paths
        include_stack: Set of files currently being processed (for circular detection)
        already_included: Set of files already fully included (for duplicate skip)
        parent_chain: List of parent file paths [direct_parent, ..., root]
        source_map: SourceMap instance to track line transformations
        current_file: Path to current file being processed

    Returns:
        Tuple of (preprocessed_text, parent_chain, source_map, already_included)
    """
    from source_map import SourceMap
    
    if include_stack is None:
        include_stack = set()
    if already_included is None:
        already_included = {}  # Map path -> namespace
    if parent_chain is None:
        parent_chain = []
    if source_map is None:
        source_map = SourceMap()
    
    # List of namespaces from skipped includes to merge into current scope
    extra_namespaces = []

    # Pattern to match: include <path>
    # Supports: include ./file.xfy, include file.xfy, include /abs/path/file.xfy
    include_pattern = r'^\s*include\s+(.+?)\s*$'

    # Hide multi-line constructs (Python blocks and triple-quoted strings)
    # so that 'include' directives inside them are skipped.
    # We preserve exactly the number of newlines to keep source maps aligned.
    hidden_blocks = {}
    
    def hide_block_preserve_lines(match):
        idx = len(hidden_blocks)
        marker = f"__XFY_HIDDEN_{idx}__"
        block_text = match.group(0)
        newlines = block_text.count('\n')
        hidden_blocks[marker] = block_text
        return marker + ('\n' * newlines)
        
    hide_pattern = re.compile(
        r'(?P<python>```+[\s\S]*?```+)|'
        r'(?P<triple>"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')'
    )
    
    masked_text = hide_pattern.sub(hide_block_preserve_lines, text)
    original_lines = masked_text.split('\n')

    result_lines = []
    preprocessed_line_num = 1  # Track current line in preprocessed output
    
    for original_line_num, line in enumerate(original_lines, start=1):
        match = re.match(include_pattern, line)

        if match:
            # Extract the include path
            include_path = match.group(1).strip()
            
            # Remove optional quotes to support spaces
            if (include_path.startswith('"') and include_path.endswith('"')) or \
               (include_path.startswith("'") and include_path.endswith("'")):
                include_path = include_path[1:-1]

            # Resolve relative paths
            if not os.path.isabs(include_path):
                if base_path:
                    include_path = os.path.join(base_path, include_path)
                else:
                    # No base path - use current working directory
                    include_path = os.path.abspath(include_path)
            else:
                include_path = os.path.abspath(include_path)
            
            # Normalize path for consistent comparison
            include_path = os.path.normpath(include_path)

            # Check for circular includes (file is currently being processed)
            if include_path in include_stack:
                raise RuntimeError(
                    f"Circular include detected: {include_path}\n"
                    f"Include chain: {' -> '.join(include_stack)}"
                )
            
            # Check for duplicate includes (file already fully processed)
            if include_path in already_included:
                # Capture the namespace from the skipped include so we can use its variables
                skipped_namespace = already_included[include_path]
                if skipped_namespace:
                    extra_namespaces.append(skipped_namespace)
                    
                result_lines.append(f"# --- Already included: {include_path} (skipped) ---")
                preprocessed_line_num += 1
                continue

            include_stack.add(include_path)

            # Read the included file
            with open(include_path, 'r') as f:
                included_content = f.read()

            # Get the directory of the included file for nested includes
            included_dir = os.path.dirname(include_path)

            # Build parent chain for included file: [include_path, ...current_parents]
            # The included file sees its direct parent first
            included_parent_chain = [include_path] + parent_chain

            # Recursively preprocess the included file with new source map
            from source_map import SourceMap
            included_source_map = SourceMap()
            preprocessed_content, _, included_source_map, already_included, included_extras = preprocess_includes(
                included_content,
                included_dir,
                include_stack,
                already_included,
                included_parent_chain,
                included_source_map,
                include_path
            )
            
            # Done processing this file - remove from stack
            include_stack.discard(include_path)

            # Propagate skipped namespaces from children to parent
            if included_extras:
                extra_namespaces.extend(included_extras)

            # IMPORTANT: Expand py! macros for THIS file BEFORE merging
            # This ensures each file's py!.var patterns use only that file's namespace,
            # preventing variable collisions (e.g., both files defining 'op')
            # Pass any extra namespaces collected within the included file
            preprocessed_content, included_namespace, _ = preprocess_python_macros(
                preprocessed_content,
                parent_chain=included_parent_chain,
                skip_python=False,
                extra_namespaces=included_extras,
                current_file=include_path,
                source_map=included_source_map
            )
            
            # Mark as fully included with its namespace
            already_included[include_path] = included_namespace

            # Tag Python blocks in the included content with their parent chain
            # This allows preprocess_python_macros() to inject the correct __parents__
            # for each block when they're all executed together later
            preprocessed_content = tag_python_blocks_with_parents(preprocessed_content,  included_parent_chain)

            # Add the preprocessed content (with a comment showing the include)
            result_lines.append(f"# --- Included from {include_path} ---")
            preprocessed_line_num += 1  # Comment line
            
            # Add included content and track source map
            included_lines = preprocessed_content.split('\n')
            for included_line_idx, included_line_text in enumerate(included_lines):
                result_lines.append(included_line_text)
                # Map this line back through the included file's source map
                orig_file, orig_line = included_source_map.get_original_location(included_line_idx + 1)
                if orig_file is None:
                    # No mapping in included file, map to the included file itself
                    orig_file = include_path
                    orig_line = included_line_idx + 1
                # Add mapping from current preprocessed line to original location
                source_map.add_range(preprocessed_line_num, preprocessed_line_num + 1, orig_file, orig_line)
                preprocessed_line_num += 1
            
            result_lines.append(f"# --- End include from {include_path} ---")
            preprocessed_line_num += 1  # Comment line
        else:
            # Regular line (not an include)
            result_lines.append(line)
            # Map this line to current file
            if current_file:
                source_map.add_range(preprocessed_line_num, preprocessed_line_num + 1, current_file, original_line_num)
            preprocessed_line_num += 1

    # Restore hidden multi-line constructs
    result_text = '\n'.join(result_lines)
    for marker, content in hidden_blocks.items():
        newlines = content.count('\n')
        placeholder = marker + ('\n' * newlines)
        result_text = result_text.replace(placeholder, content)

    return (result_text, parent_chain, source_map, already_included, extra_namespaces)

# Don't create parser at module level - create fresh on each parse
# This ensures grammar changes are ALWAYS picked up
def parse(text, filepath=None, skip_python=False):
    """
    Parse text using the grammar file (reloads grammar each time)

    Args:
        text: The script text to parse
        filepath: Optional filepath for resolving include statements
        skip_python: If True, skip Python block execution (for syntax-only validation)

    Returns:
        Tuple of (ast, parent_chain, python_namespace, source_map, deferred_blocks) where:
        - ast: Parsed AST
        - parent_chain: List of parent file paths [direct_parent, ..., root]
        - python_namespace: Dict of variables from Python blocks (empty if skip_python=True)
        - source_map: SourceMap tracking line transformations
        - deferred_blocks: List of (code, parent_chain) tuples to execute after compilation
    """
    from source_map import SourceMap
    
    # Determine base path for includes
    base_path = None
    current_file = filepath
    if filepath and filepath != '<dynamic>':
        base_path = os.path.dirname(os.path.abspath(filepath))
        # Normalize filepath to absolute path for parent chain
        filepath = os.path.abspath(filepath)
        current_file = filepath

    # Initialize parent chain
    # If no filepath provided, use '<dynamic>' as identifier
    initial_parent_chain = []  # Root script has no parents

    # Step 1: Preprocess includes and build source map
    source_map = SourceMap()
    preprocessed_text, parent_chain, source_map, already_included, extra_namespaces = preprocess_includes(
        text, base_path, 
        parent_chain=initial_parent_chain,
        source_map=source_map,
        current_file=current_file
    )

    # Step 2: Preprocess Python macros (py!.* -> text substitution)
    # This must happen AFTER includes (so included files can define macros)
    # but BEFORE parsing (it's raw text substitution)
    # Also executes normal Python blocks and builds namespace for compiler to reuse
    # Deferred blocks are returned separately for post-compilation execution
    # Pass any extra namespaces collected from top-level skipped includes
    preprocessed_text, python_namespace, deferred_blocks = preprocess_python_macros(
        preprocessed_text, 
        parent_chain, 
        skip_python=skip_python,
        extra_namespaces=extra_namespaces,
        current_file=current_file,
        source_map=source_map
    )

    # Step 3: Run includes ONE MORE TIME to resolve any conditionally injected includes
    # (e.g. includes built dynamically via py!.op).
    # We pass the same already_included dictionary to prevent reloading static files.
    # Note: A new dummy source map is used here as this pass is only for resolving new includes,
    # and its mappings won't be merged into the main source_map.
    preprocessed_text, _, _, _, _ = preprocess_includes(
        preprocessed_text, base_path,
        already_included=already_included,
        parent_chain=parent_chain,
        source_map=SourceMap(), # Dummy source map for this pass
        current_file=current_file
    )

    # Use cached parser for performance (only rebuilds if grammar changes)
    parser = _get_cached_parser()
    try:
        ast = parser.parse(preprocessed_text)
    except Exception as e:
        line = getattr(e, 'line', None)
        col = getattr(e, 'column', None)
        orig_file = current_file
        orig_line = line
        if line is not None and source_map:
            m_file, m_line = source_map.get_original_location(line)
            if m_file:
                orig_file = m_file
                orig_line = m_line
        
        snippet = ""
        if orig_file and os.path.exists(orig_file) and orig_line:
            try:
                with open(orig_file, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
                if 0 < orig_line <= len(lines):
                    snippet = lines[orig_line - 1].strip()
            except Exception:
                pass
        
        loc_parts = []
        if orig_file:
            loc_parts.append(str(orig_file))
        if orig_line is not None:
            loc_parts.append(str(orig_line))
        if col is not None:
            loc_parts.append(str(col))
        loc = ":".join(loc_parts)
        
        msg = str(e).split('\n')[0] if hasattr(e, 'line') else str(e)
        if loc:
            if snippet:
                raise SyntaxError(f"{loc}: {msg}\n  {snippet}") from e
            raise SyntaxError(f"{loc}: {msg}") from e
        raise

    return ast, parent_chain, python_namespace, source_map, deferred_blocks
