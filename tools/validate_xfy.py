#!/usr/bin/env python3
"""
Unified validator for XFY files with fast and comprehensive modes.

Fast mode (default): Lightweight syntax and semantic validation without Blender.
Comprehensive mode (--blender): Full validation via headless Blender including compilation and runtime checks.

Usage:
    # Fast validation (syntax + semantics, no Blender required)
    python validate_xfy.py path/to/script.xfy
    
    # Comprehensive validation (compile in Blender, check runtime issues)
    python validate_xfy.py --blender path/to/script.xfy
    
    # Batch validate
    python validate_xfy.py tests/**/*.xfy
"""

import sys
import os
from pathlib import Path
import argparse
import glob

# Add addon directory and vendor to path
addon_dir = Path(__file__).parent.parent
vendor_dir = addon_dir / "vendor"
if vendor_dir.exists() and str(vendor_dir) not in sys.path:
    sys.path.insert(0, str(vendor_dir))
if str(addon_dir) not in sys.path:
    sys.path.insert(0, str(addon_dir))

from parser import parse
from semantic_analyzer import SemanticAnalyzer
from registry import NodeRegistry


def validate_file(filepath: str, verbose: bool = False, strict: bool = False) -> tuple[list, list]:
    """
    Validate a single XFY file.
    
    Args:
        filepath: Path to .xfy file
        verbose: Enable verbose output
        strict: If False (default), suppress errors related to missing Blender modules.
                If True, report all errors including bpy import failures.
    
    Returns:
        (errors, warnings): Lists of (message, line, column) tuples
    """
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except Exception as e:
        return [(f"Failed to read file: {e}", 0, 0)], []
    
    errors = []
    warnings = []
    
    source_map = None
    errors = []
    warnings = []
    
    try:
        # Parse the file
        if verbose:
            print(f"  Parsing {filepath}...")
        
        # In lenient mode, skip Python execution to avoid bpy errors
        # This allows syntax-only validation
        skip_python = not strict
        
        parse_result = parse(content, filepath=filepath, skip_python=skip_python)
        if isinstance(parse_result, tuple) and len(parse_result) >= 4:
            ast = parse_result[0]
            source_map = parse_result[3]  # Fourth element is source map
        elif isinstance(parse_result, tuple)  and len(parse_result) >= 1:
            ast = parse_result[0]
            source_map = None  # Older parse() version without source map
        else:
            ast = parse_result
            source_map = None
        
        # Run semantic analysis
        if verbose:
            print(f"  Running semantic analysis...")
        # Determine target version from filepath
        target_version = None
        if filepath:
            filepath_str = str(filepath).replace('\\', '/')
            if 'ver_5.0' in filepath_str:
                target_version = '5.0'
            elif 'ver_5.1' in filepath_str:
                target_version = '5.1'
            elif 'ver_5.2' in filepath_str:
                target_version = '5.2'
            elif 'ver_4.x' in filepath_str:
                target_version = '4.2'
            elif 'ver_3.x' in filepath_str:
                target_version = '3.3'
        registry = NodeRegistry(include_material_nodes=True, target_version=target_version)
        analyzer = SemanticAnalyzer(registry=registry)
        errors, warnings = analyzer.analyze(ast)
        
    except Exception as e:
        # Parse error (syntax error in XFY code)
        error_msg = str(e)
        line = getattr(e, 'line', 1)
        col = getattr(e, 'column', 1)
        
        # Translate line number using source map if available
        # For parse errors, we need to build source map from preprocessing
        if source_map is None:
            # Parse failed before we got source map, try to build it from preprocessing only
            try:
                from source_map import SourceMap
                from parser import preprocess_includes
                
                preprocessed_source_map = SourceMap()
                _, _, preprocessed_source_map = preprocess_includes(
                    content, 
                    base_path=os.path.dirname(os.path.abspath(filepath)) if filepath else None,
                    source_map=preprocessed_source_map,
                    current_file=os.path.abspath(filepath) if filepath else None
                )
                source_map = preprocessed_source_map
            except:
                # If preprocessing fails too, just use original line number
                pass
        
        # Translate error line number
        orig_file = filepath
        orig_line = line - 1  # Convert to 0-indexed
        if source_map:
            trans_file, trans_line = source_map.get_original_location(line)
            if trans_file:
                orig_file = trans_file
                orig_line = trans_line - 1  # Back to 0-indexed
                # Also update the error message to replace the preprocessed line number
                # Error messages from Lark contain "at line X col Y"
                import re
                error_msg = re.sub(r'at line (\d+)', f'at line {trans_line}', error_msg)
       
        # In lenient mode, treat Python module errors as warnings (runtime-only issues)
        is_python_module_error = "No module named" in error_msg or "Error executing Python block" in error_msg
        if not strict and is_python_module_error:
            warnings.append((error_msg, orig_line, col, orig_file))
        else:
            errors.append((error_msg, orig_line, col, orig_file))
    
    # Translate error/warning line numbers using source map (for semantic errors)
    if source_map and errors:
        translated_errors = []
        for error_data in errors:
            if len(error_data) == 4:
                # Already has filepath from parse error handling
                translated_errors.append(error_data)
            else:
                message, line, col = error_data
                orig_file, orig_line = source_map.get_original_location(line + 1)  # Convert to 1-indexed
                if orig_file:
                    translated_errors.append((message, orig_line - 1, col, orig_file))  # Back to 0-indexed
                else:
                    translated_errors.append((message, line, col, filepath))
        errors = translated_errors
    elif not source_map and errors:
        # No source map - add filepath to all errors that don't have it
        new_errors = []
        for e in errors:
            if len(e) == 3:
                msg, line, col = e
                new_errors.append((msg, line, col, filepath))
            else:
                new_errors.append(e)
        errors = new_errors
    
    if source_map and warnings:
        translated_warnings = []
        for warning_data in warnings:
            if len(warning_data) == 4:
                translated_warnings.append(warning_data)
            else:
                message, line, col = warning_data
                orig_file, orig_line = source_map.get_original_location(line + 1)
                if orig_file:
                    translated_warnings.append((message, orig_line - 1, col, orig_file))
                else:
                    translated_warnings.append((message, line, col, filepath))
        warnings = translated_warnings
    elif warnings:
        new_warnings = []
        for w in warnings:
            if len(w) == 3:
                msg, line, col = w
                new_warnings.append((msg, line, col, filepath))
            else:
                new_warnings.append(w)
        warnings = new_warnings
    
    return errors, warnings


def is_bpy_error(error_msg: str) -> bool:
    """Check if error is related to missing Blender (bpy) module."""
    bpy_indicators = [
        "No module named 'bpy'",
        "cannot import name 'bpy'",
        "ModuleNotFoundError: No module named 'bpy'",
        "Error executing Python block"
    ]
    return any(indicator in error_msg for indicator in bpy_indicators)


def validate_with_blender(filepath: str, verbose: bool = False, tree_type: str = None) -> tuple[bool, str]:
    """
    Validate file by compiling in headless Blender.
    
    Returns:
        (success, message): True if validation passed, message with details
    """
    import subprocess
    import shutil
    
    # Find Blender executable
    blender_paths = [
        'blender',  # In PATH
        '/usr/bin/blender',
        '/usr/local/bin/blender',
        '/snap/bin/blender',
        '/Applications/Blender.app/Contents/MacOS/Blender',  # macOS
    ]
    
    blender_exec = None
    for path in blender_paths:
        if shutil.which(path) if path == 'blender' else os.path.exists(path):
            blender_exec = path
            break
    
    if not blender_exec:
        return False, "Blender executable not found. Install Blender or add it to PATH."
    
    # Create a temporary validation script that will be run in Blender
    validation_script = f"""
import sys
import os
import logging
from pathlib import Path

# Add addon directory and vendor to path
addon_dir = Path(r'{str(addon_dir)}')
vendor_dir = addon_dir / "vendor"
if vendor_dir.exists() and str(vendor_dir) not in sys.path:
    sys.path.insert(0, str(vendor_dir))
if str(addon_dir.parent) not in sys.path:
    sys.path.insert(0, str(addon_dir.parent))
if str(addon_dir) not in sys.path:
    sys.path.insert(0, str(addon_dir))

import importlib
try:
    mod = importlib.import_module(addon_dir.name)
    compile_script = mod.compile_script
except Exception:
    from __init__ import compile_script

from logger import get_logger
import bpy

filepath = r'{filepath}'
tree_type = {repr(tree_type)}
    
try:
    # 1. Reset Blender first so that pre-setup Python blocks run cleanly
    bpy.ops.wm.read_homefile(use_empty=True)
    
    # Create a dummy mesh object to act as the active object for implicit blocks
    mesh = bpy.data.meshes.new("DummyMesh")
    obj = bpy.data.objects.new("DummyObject", mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Add a logging handler to capture any compilation errors
    logger = get_logger()
    class ErrorCollector(logging.Handler):
        def __init__(self):
            super().__init__()
            self.errors = []
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                self.errors.append(self.format(record))
    
    collector = ErrorCollector()
    logger.addHandler(collector)
    
    # 2. Compile using the real compile_script function
    success, message, trees = compile_script(
        content,
        "ValidationTest",
        bpy.context,
        filepath=filepath,
        clearExisting=True,
        tree_type=tree_type
    )
    
    if collector.errors:
        print("VALIDATION_ERROR: Compilation logged errors:")
        for err in collector.errors:
            print(f"  - {{err}}")
        sys.exit(1)
        
    if not success:
        print(f"VALIDATION_ERROR: {{message}}")
        sys.exit(1)
        
    # Force evaluation of depsgraph
    bpy.context.view_layer.update()
    
    # Check for modifier warning messages (like Cannot evaluate node group)
    for modifier in obj.modifiers:
        if modifier.type == 'NODES' and hasattr(modifier, 'warning') and modifier.warning:
            print(f"VALIDATION_ERROR: Modifier warning: {{modifier.warning}}")
            sys.exit(1)
            
    # Get total nodes and links across all compiled trees
    total_nodes = sum(len(t.nodes) for t in trees if hasattr(t, 'nodes'))
    total_links = sum(len(t.links) for t in trees if hasattr(t, 'links'))
    
    print(f"VALIDATION_SUCCESS: {{total_nodes}} nodes, {{total_links}} links in {{len(trees)}} trees")
    sys.exit(0)
    
except Exception as e:
    print(f"VALIDATION_ERROR: {{e}}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
"""
    
    # Write temp script
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        temp_script = f.name
        f.write(validation_script)
    
    try:
        # Run Blender in background mode
        cmd = [blender_exec, '--background', '--python', temp_script]
        if verbose:
            print(f"  Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30
        )
        
        # DEBUG: Print raw output to see order
        if verbose or result.returncode != 0:
             print("DEBUG RAW OUTPUT:")
             print(result.stdout)
             print("DEBUG END RAW OUTPUT")
        
        # Parse output
        error_lines = []
        in_error_block = False
        
        for line in result.stdout.splitlines():
            if line.startswith('VALIDATION_SUCCESS:'):
                details = line.split(':', 1)[1].strip()
                return True, f"✓ Compilation successful ({details})"
            elif line.startswith('VALIDATION_ERROR:'):
                in_error_block = True
                error = line.split(':', 1)[1].strip()
                error_lines.append(f"✗ Compilation failed: {error}")
            elif in_error_block:
                error_lines.append(line)
        
        if error_lines:
            return False, "\n".join(error_lines)
        
        # Fallback: check exit code
        if result.returncode == 0:
            return True, "✓ Compilation successful"
        else:
            return False, f"✗ Blender exited with code {result.returncode}"
            
    except subprocess.TimeoutExpired:
        return False, "✗ Validation timed out (>30s)"
    except Exception as e:
        return False, f"✗ Failed to run Blender: {e}"
    finally:
        # Clean up temp script
        try:
            os.unlink(temp_script)
        except:
            pass


def format_diagnostic(filepath: str, message: str, line: int, col: int, severity: str) -> str:
    """Format a diagnostic message for display."""
    # Use 1-based line numbers for display
    return f"{filepath}:{line + 1}:{col + 1}: {severity}: {message}"


def main():
    parser = argparse.ArgumentParser(
        description="Unified XFY validator with fast and comprehensive modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fast validation (default - syntax + semantics, no Blender)
  %(prog)s script.xfy
  
  # Comprehensive validation (compile in Blender)
  %(prog)s --blender script.xfy
  
  # Validate multiple files
  %(prog)s file1.xfy file2.xfy file3.xfy
  
  # Verbose output
  %(prog)s -v script.xfy
  
  # Batch validate (using shell glob)
  %(prog)s tests/**/*.xfy
  
  # Strict mode (report bpy import errors)
  %(prog)s --strict script.xfy
        """
    )
    parser.add_argument(
        'files',
        nargs='+',
        help='XFY file(s) to validate'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    parser.add_argument(
        '--errors-only',
        action='store_true',
        help='Only show errors, hide warnings'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Strict mode: report all errors including Blender (bpy) import failures. '
             'By default, bpy-related errors are suppressed for syntax-only validation.'
    )
    parser.add_argument(
        '--blender',
        action='store_true',
        help='Comprehensive mode: validate by compiling in headless Blender. '
             'Checks compilation, socket types, runtime issues. Requires Blender installation.'
    )
    parser.add_argument(
        '-t', '--tree',
        choices=['geometry', 'shader', 'compositor'],
        default=None,
        help='Tree type to compile ("geometry", "shader", "compositor"). Defaults to geometry.'
    )
    
    args = parser.parse_args()
    
    # Expand glob patterns
    files = []
    for pattern in args.files:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            files.extend(matches)
        else:
            # Not a glob pattern, add as-is
            files.append(pattern)
    
    # Remove duplicates and filter for .xfy files
    files = sorted(set(f for f in files if f.endswith('.xfy')))
    
    if not files:
        print("No .xfy files found", file=sys.stderr)
        return 1
    
    total_errors = 0
    total_warnings = 0
    failed_files = []
    
    # If --blender mode, use different validation path
    if args.blender:
        for filepath in files:
            if args.verbose:
                print(f"\nValidating {filepath} with Blender...")
            
            if not os.path.exists(filepath):
                print(f"{filepath}: ERROR: File not found", file=sys.stderr)
                failed_files.append(filepath)
                total_errors += 1
                continue
            
            # Validate with Blender
            success, message = validate_with_blender(filepath, args.verbose, tree_type=args.tree)
            print(f"{filepath}: {message}")
            
            if not success:
                failed_files.append(filepath)
                total_errors += 1
    else:
        # Fast mode: syntax + semantic validation
        for filepath in files:
            if args.verbose:
                print(f"\nValidating {filepath}...")
            
            if not os.path.exists(filepath):
                print(f"{filepath}: ERROR: File not found", file=sys.stderr)
                failed_files.append(filepath)
                continue
            
            errors, warnings = validate_file(filepath, args.verbose, args.strict)
            
            # Display errors - now with filepath in the tuple
            for error_data in errors:
                if len(error_data) == 4:
                    message, line, col, err_file = error_data
                else:
                    # Fallback for old format
                    message, line, col = error_data
                    err_file = filepath
                print(format_diagnostic(err_file, message, line, col, "ERROR"))
                total_errors += 1
            
            # Display warnings (unless --errors-only)
            if not args.errors_only:
                for warning_data in warnings:
                    if len(warning_data) == 4:
                        message, line, col, warn_file = warning_data
                    else:
                        message, line, col = warning_data
                        warn_file = filepath
                    print(format_diagnostic(warn_file, message, line, col, "WARNING"))
                    total_warnings += 1
            
            if errors:
                failed_files.append(filepath)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Validated {len(files)} file(s)")
    print(f"Errors: {total_errors}, Warnings: {total_warnings}")
    
    if failed_files:
        print(f"\nFiles with errors ({len(failed_files)}):")
        for f in failed_files:
            print(f"  - {f}")
        return 1
    else:
        print("\n✓ All files passed validation")
        return 0


if __name__ == '__main__':
    sys.exit(main())
