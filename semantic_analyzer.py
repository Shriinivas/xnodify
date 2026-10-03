"""
Semantic analyzer for XFY scripts.

Performs Blender-independent semantic analysis:
- Symbol table management
- Undefined variable detection
- Unused parameter detection
- Type tracking and compatibility checking
- Output validation

Uses validation.py as the single source of truth for validation rules.
This analyzer is used by both the LSP server and the Blender compiler.
"""

from lark import Tree, Token

from validation import (
    is_variable_defined,
    get_undefined_variable_error,
    get_unused_inputs,
    get_unused_input_warning,
)
from common_attributes import (
    COMMON_ATTRIBUTES,
    PREPROCESSOR_ATTRIBUTES,
    get_user_facing_properties,
    is_valid_attribute,
)

from registry import NodeRegistry, MULTI_INPUT_NODES
from shortcuts import FUNCTION_SHORTCUTS

# Nodes with mode-dependent inputs (registry only captures one mode)
# Skip type validation for these as the registry is incomplete
MODE_DEPENDENT_NODES = {
    # Math nodes with operation modes
    'math', 'vector_math', 'mix', 'map_range', 'clamp',
    'boolean_math', 'compare', 'switch', 'random_value',
    'menu_switch', 'menuswitch', 'index_switch',
    # Attribute nodes with type modes
    'accumulate_field', 'sample_index', 'sample_nearest',
    'sample_nearest_surface', 'raycast', 'store_named_attribute',
    'input_named_attribute', 'blur_attribute', 'capture_attribute',
    # Geometry nodes with flexible positional arguments
    'curve_primitive_circle', 'curve_primitive_arc', 'curve_primitive_line',
    'mesh_cone', 'mesh_cylinder', 'mesh_grid', 'mesh_uv_sphere', 'uvsphere',
    'transform', 'set_position', 'offset_point_in_curve',
    'align_rotation_to_vector', 'set_shade_smooth',
    'sample_curve', 'curve_to_mesh', 'fill_curve', 'extrude_mesh',
    'set_material', 'set_grease_pencil_depth', 'curves_to_grease_pencil',
    'geometry_to_instance', 'join_geometry', 'curve_spline_type',
}


class SemanticAnalyzer:
    """
    Analyzes XFY AST for semantic errors without requiring Blender.

    Phase 1.5: Extracts Blender-independent validation logic from compiler.
    Future: Will be used by both LSP and compiler (single source of truth).
    """

    def __init__(self, registry=None):
        # Symbol table: var_name -> {type, value, defined_at}
        # Predefined variables for compatibility
        self.symbol_table = {
            "_specialchars": {
                "type": "ARRAY",
                "value": ["\n"],
                "defined_at": None,
                "referenced": True
            }
        }

        # Input parameters: name -> {type, display_name, default, used}
        self.inputs = {}

        # Output parameters: name -> {type, display_name, assigned}
        self.outputs = {}

        # Group definitions: name -> {ast, inputs, outputs, compiled}
        self.groups = {}

        # Current group being analyzed (for nested context)
        self.current_group = None

        # Collected errors and warnings
        # Each entry is a tuple: (message, line, column)
        # Line/column are 0-based for LSP compatibility
        self.errors = []
        self.warnings = []

        # Node registry for attribute validation
        # Lazy-load to avoid import issues when registry isn't needed
        self.registry = registry
        
        # Python namespace from embedded Python blocks
        # Variables defined in py blocks are accessible via py.varname
        self.py_namespace = {}



    def reset(self):
        """Reset state for reuse (avoids recreating instance each time)."""
        self.symbol_table = {
            "_specialchars": {
                "type": "ARRAY",
                "value": ["\n"],
                "defined_at": None,
                "referenced": True
            }
        }
        self.inputs = {}
        self.outputs = {}
        self.groups = {}
        self.current_group = None
        self.errors = []
        self.warnings = []
        self.py_namespace = {}



    def analyze(self, ast):
        """
        Analyze an XFY AST and return semantic errors and warnings.

        Args:
            ast: Parsed AST from parser.parse()

        Returns:
            (errors, warnings): Tuple of error and warning message lists
        """
        # Clear previous results
        self.errors = []
        self.warnings = []

        # Process all top-level statements
        if ast.data == 'start':
            for statement in ast.children:
                self._process_statement(statement)

        # Post-processing checks
        self._check_unused_inputs()
        self._check_hanging_nodes()

        return self.errors, self.warnings

    def _process_statement(self, stmt):
        """
        Process a single statement from the AST.

        This is the main dispatcher for different statement types.
        Note: The AST has 'statement' wrapper nodes that need to be unwrapped.
        """
        if isinstance(stmt, Tree):
            # Unwrap wrapper nodes
            if stmt.data == "statement":
                if stmt.children:
                    self._process_statement(stmt.children[0])
                return
            
            # Unwrap group_statement wrapper nodes (inside group definitions)
            if stmt.data == "group_statement":
                if stmt.children:
                    self._process_statement(stmt.children[0])
                return

            stmt_type = stmt.data

            if stmt_type == 'input_decl':
                self._process_input_decl(stmt)
            elif stmt_type == 'output_decl':
                self._process_output_decl(stmt)
            elif stmt_type == 'group_input':
                # Handle group input declarations (same structure as input_decl)
                self._process_input_decl(stmt)
            elif stmt_type == 'group_output':
                # Handle group output declarations
                self._process_output_decl(stmt)
            elif stmt_type == 'assignment':
                self._process_assignment(stmt)
            elif stmt_type == 'group_def':
                self._process_group_def(stmt)
            elif stmt_type == 'repeat':
                self._process_repeat(stmt)
            elif stmt_type == 'foreach':
                self._process_foreach(stmt)
            elif stmt_type == 'simulation':
                self._process_simulation(stmt)
            elif stmt_type == 'closure':
                self._process_closure(stmt)
            # TODO: Add other statement types (frames, etc.)

    def _process_input_decl(self, stmt):
        """
        Process input declaration: input name: type "Display" = default

        Grammar: input_decl: "input" NAME ":" type STRING? ("=" value)?

        Tracks input parameters for later unused parameter detection.
        """
        name_token = stmt.children[0]
        var_name = name_token.value
        type_node = stmt.children[1]
        if isinstance(type_node, Token):
            type_name = type_node.value
        elif hasattr(type_node, "data"):
            if type_node.data == "closure_signature" or (type_node.data == "type_spec" and hasattr(type_node.children[0], "data") and type_node.children[0].data == "closure_signature"):
                type_name = "CLOSURE"
            elif type_node.data == "type_spec" and isinstance(type_node.children[0], Token):
                type_name = type_node.children[0].value
            else:
                type_name = "CLOSURE"
        else:
            type_name = "FLOAT"

        # Get line number from token (Lark uses 1-based, convert to 0-based)
        line = getattr(name_token, 'line', 1) - 1
        column = getattr(name_token, 'column', 1) - 1

        # Optional display name (STRING) and default value
        display_name = None
        default_value = None

        if len(stmt.children) > 2:
            for child in stmt.children[2:]:
                if isinstance(child, Token) and child.type == "STRING":
                    display_name = child.value[1:-1]  # Remove quotes
                elif isinstance(child, Tree):
                    # This is the default value expression
                    # For now, just note that a default exists
                    default_value = "<expression>"  # We don't evaluate it yet

        if not display_name:
            display_name = var_name.capitalize()

        # Store input information with location for unused warning
        self.inputs[var_name] = {
            "type": type_name.upper(),  # FLOAT, VECTOR, GEOMETRY, etc.
            "display_name": display_name,
            "default": default_value,
            "used": False,  # Will be set to True when referenced
            "line": line,
            "column": column,
        }

    def _process_output_decl(self, stmt):
        """
        Process output declaration: output name

        Grammar: output_decl: "output" NAME

        Tracks output parameters for later validation.
        """
        name = stmt.children[0].value

        # Store output information
        self.outputs[name] = {
            "type": None,  # Will be inferred from assignment
            "display_name": name.capitalize(),
            "assigned": False,  # Will be set to True when assigned
        }

    def _process_assignment(self, stmt):
        """
        Process assignment: var = expression

        Grammar: assignment: NAME "=" expression

        Tracks variables in symbol table and checks for undefined references.
        """
        left_side = stmt.children[0]
        right_side = stmt.children[1]

        # IMPORTANT: Check right-side expression BEFORE adding left-side to symbol table
        # This catches errors like: x = foo(x) where x is undefined
        self._check_expression_references(right_side)

        # Get variable name
        if hasattr(left_side, "data") and left_side.data == "tuple_target":
            # Tuple unpacking: (a, b, c) = expr
            # For now, just track each variable
            var_names = []
            for child in left_side.children:
                if hasattr(child, "data") and child.data == "tuple_target_item":
                    if child.children and hasattr(child.children[0], "value"):
                        var_names.append(child.children[0].value)
                elif hasattr(child, "value"):
                    var_names.append(child.value)
            for var_name in var_names:
                self.symbol_table[var_name] = {
                    "type": "UNKNOWN",  # TODO: Infer from expression
                    "value": None,
                    "defined_at": None,  # TODO: Add line number tracking
                }
        else:
            # Simple assignment: var = expr
            var_name = left_side.value

            # Mark input as used if assigning an input variable
            if var_name in self.inputs:
                self.inputs[var_name]["used"] = True

            # Mark output as assigned if it's a declared output
            if var_name in self.outputs:
                self.outputs[var_name]["assigned"] = True

            # Add to symbol table AFTER checking right-side
            # Infer type from right_side expression
            rhs_type = self._infer_expression_type(right_side)
            
            # Check if we are overwriting an unused variable
            if var_name in self.symbol_table:
                existing_info = self.symbol_table[var_name]
                if not existing_info.get("referenced", False) and not existing_info.get("type") == "UNKNOWN":
                    # Variable was defined but never used before being overwritten
                    line = existing_info.get("defined_at")
                    if line:
                        line = line - 1
                    else:
                        line = 0
                    
                    self.warnings.append((
                        f"Variable '{var_name}' is overwritten without being used. "
                        f"The previous value creates a disconnected node.",
                        line,
                        0
                    ))

            self.symbol_table[var_name] = {
                "type": rhs_type,
                "value": None,
                "defined_at": getattr(left_side, 'line', None),
                "referenced": False,  # Track usage for hanging node detection
            }



    def _process_group_def(self, stmt):
        """
        Process group definition: group Name { ... }

        Grammar: group_def: "group" NAME STRING? group_statement*

        Stores group definition and analyzes the body for semantic errors.
        """
        child_offset = 0
        explicit_tree_type = None
        if len(stmt.children) > 0 and isinstance(stmt.children[0], Tree):
            if stmt.children[0].data in ("material_domain", "geometry_domain"):
                explicit_tree_type = "ShaderNodeTree" if stmt.children[0].data == "material_domain" else "GeometryNodeTree"
                child_offset = 1
            elif stmt.children[0].data == "domain_type":
                domain_val = stmt.children[0].children[0].value.lower() if stmt.children[0].children else ""
                explicit_tree_type = "ShaderNodeTree" if domain_val in ("shader", "material", "world") else "GeometryNodeTree"
                child_offset = 1

        group_name = stmt.children[child_offset].value
        child_offset += 1

        # Check for optional display name
        display_name = None
        if (
            len(stmt.children) > child_offset
            and isinstance(stmt.children[child_offset], Token)
            and stmt.children[child_offset].type == "STRING"
        ):
            display_name = stmt.children[child_offset].value[1:-1]  # Strip quotes
            child_offset += 1

        # Store group definition (AST body for later analysis if needed)
        self.groups[group_name] = {
            "display_name": display_name or group_name,
            "tree_type": explicit_tree_type,
            "body_ast": stmt,  # Store full AST for potential future analysis
            "inputs": [],
            "outputs": [],
            "compiled": False,
        }

        # Save current state and create new scope for group analysis
        saved_inputs = self.inputs.copy()
        saved_outputs = self.outputs.copy()
        saved_symbol_table = self.symbol_table.copy()
        self.current_group = group_name

        # Reset for group scope (keep groups reference for recursive calls)
        self.inputs = {}
        self.outputs = {}
        # Keep symbol table entries but mark a new scope

        # Process all statements inside the group body
        for child in stmt.children[child_offset:]:
            if isinstance(child, Tree):
                self._process_statement(child)

        # Check for unused inputs and hanging nodes within the group scope
        self._check_unused_inputs()
        self._check_hanging_nodes()

        # Restore previous state
        self.inputs = saved_inputs
        self.outputs = saved_outputs
        self.symbol_table = saved_symbol_table
        self.current_group = None
    
    def _process_state_clause(self, state_clause_node):
        """
        Process state clause: state=(var1, var2:type, ...)
        
        Returns set of state variable names.
        Handles:
        1. Checking referenced variables (if no type)
        2. Defining new variables (if type is present)
        """
        state_vars = set()
        
        for item in state_clause_node.children:
            name = None
            type_name = None
            token = None
            
            if hasattr(item, 'data') and item.data == 'state_item':
                # Typed declaration or untyped wrapper: NAME (: TYPE)?
                name = item.children[0].value
                token = item.children[0]
                
                if len(item.children) > 1 and hasattr(item.children[1], 'type') and item.children[1].type == 'TYPE':
                    type_name = item.children[1].value
                    
            elif isinstance(item, Token) and item.type == 'NAME':
                # Legacy direct NAME token
                name = item.value
                token = item
            
            if name:
                state_vars.add(name)
                
                if type_name:
                    # Typed declaration - defines/redefines variable
                    # Even if it didn't exist, it now exists for the loop initialization
                    self.symbol_table[name] = {
                        "type": type_name.upper(),
                        "value": None,
                        "defined_at": getattr(token, 'line', None),
                        "referenced": True
                    }
                else:
                    # Reference to existing variable
                    if is_variable_defined(name, self.symbol_table, self.inputs, self.groups):
                        if name in self.symbol_table:
                            self.symbol_table[name]["referenced"] = True
                        elif name in self.inputs:
                            self.inputs[name]["used"] = True
                    else:
                        line = getattr(token, 'line', 1) - 1
                        col = getattr(token, 'column', 1) - 1
                        error_msg = get_undefined_variable_error(name, self.symbol_table)
                        self.errors.append((error_msg, line, col))
                        
        return state_vars

    def _process_repeat(self, stmt):
        """
        Process repeat loop: repeat iterations, geometry, state=(vars):loop_vars { body }(results)
        
        Tracks:
        1. Loop variables from output_vars_clause (:var1, var2) - available inside loop
        2. Variables defined in the output clause - available after loop
        """
        # Check input references (iterations, geometry, state inputs)
        state_vars = set()
        for child in stmt.children:
            if isinstance(child, Tree):
                if child.data == 'state_clause':
                    state_vars = self._process_state_clause(child)
                    continue

                if child.data in ('output_vars_clause', 'output_clause', 'statement'):
                    continue
                self._check_expression_references(child)
            elif isinstance(child, Token):
                self._check_expression_references(child)

        # First, parse output_vars_clause to track loop variables available inside the loop

        for child in stmt.children:

            if isinstance(child, Tree) and child.data == 'output_vars_clause':
                # Parse loop variables: :idx, geo (or whatever names are used)
                for item in child.children:
                    if isinstance(item, Tree) and item.data == 'output_var_item':
                        # output_var_item is NAME?
                        if item.children:
                            var_name = item.children[0].value
                            # Add loop variable to symbol table
                            self.symbol_table[var_name] = {
                                "type": "UNKNOWN",
                                "value": None,
                                "defined_at": None,
                            }
        
        # Process loop body statements (now that loop vars are defined)
        for child in stmt.children:
            if isinstance(child, Tree) and child.data == 'statement':
                self._process_statement(child)
        
        # Finally, parse output_clause to track variables defined from loop outputs


        for child in stmt.children:
            if isinstance(child, Tree) and child.data == 'output_clause':
                # Parse output_clause: (output_item, output_item, ...)
                # output_item can be: NAME=NAME (rename), NAME (pass through), or empty
                for item in child.children:
                    if isinstance(item, Tree) and item.data == 'output_item':
                        # Extract variable name from output_item
                        var_name = None
                        if len(item.children) == 2:
                            # NAME = NAME (renaming: result=geom means 'result' is available)
                            # First child is the new name, second is the source
                            var_name = item.children[0].value
                        elif len(item.children) == 1:
                            # NAME (no renaming, same name passed through)
                            var_name = item.children[0].value
                        # else: empty slot, skip
                        
                        if var_name:
                            # Mark the source variable as referenced if different from var_name
                            # The source is usually the same name (pass-through) or renaming (source=var_name)
                            # Actually, if renaming: new_name = source_name
                            
                            source_name = None
                            if len(item.children) == 2:
                                # new_name = source_name
                                source_name = item.children[1].value
                            elif len(item.children) == 1:
                                # source_name (implicit pass-through)
                                source_name = item.children[0].value
                            
                            if source_name:
                                # Mark as referenced in the loop scope
                                if source_name in self.symbol_table:
                                    self.symbol_table[source_name]["referenced"] = True

                            # Add to symbol table (available after loop)

                            self.symbol_table[var_name] = {
                                "type": "UNKNOWN",
                                "value": None,
                                "defined_at": None,
                                "referenced": var_name in state_vars, 
                            }



    def _process_foreach(self, stmt):
        """
        Process foreach loop: foreach{...} geometry, selection, state=(vars):loop_vars { body }(input_items:output_items)
        
        Tracks:
        1. Loop variables from output_vars_clause (:idx, elems) - available inside loop
        2. Variables defined in output_items part of output clause - available after loop
        """
        # Check input references (geometry, selection, state inputs)
        state_vars = set()
        for child in stmt.children:
            if isinstance(child, Tree):
                if child.data == 'state_clause':
                    state_vars = self._process_state_clause(child)
                    continue
                            
                if child.data in ('output_vars_clause', 'foreach_output_clause', 'statement', 'attributes'):
                    continue
                self._check_expression_references(child)
            elif isinstance(child, Token):
                self._check_expression_references(child)

        # First, parse output_vars_clause to track loop variables available inside the loop

        for child in stmt.children:


            if isinstance(child, Tree) and child.data == 'output_vars_clause':
                # Parse loop variables: :idx, elems (or whatever names are used)
                for item in child.children:
                    if isinstance(item, Tree) and item.data == 'output_var_item':
                        # output_var_item is NAME?
                        if item.children:
                            var_name = item.children[0].value
                            # Add loop variable to symbol table
                            self.symbol_table[var_name] = {
                                "type": "UNKNOWN",
                                "value": None,
                                "defined_at": None,
                            }
        
        # Process loop body statements (now that loop vars are defined)
        for child in stmt.children:
            if isinstance(child, Tree) and child.data == 'statement':
                self._process_statement(child)
        
        # Finally, parse foreach_output_clause to track variables from output_items (after colon)


        for child in stmt.children:
            if isinstance(child, Tree) and child.data == 'foreach_output_clause':
                # Find output_item_list (after the colon)
                for subchild in child.children:
                    if isinstance(subchild, Tree) and subchild.data == 'output_item_list':
                        # Parse output items
                        for item in subchild.children:
                            if isinstance(item, Tree) and item.data == 'output_item':
                                # Extract variable name from output_item
                                var_name = None
                                if len(item.children) == 2:
                                    # NAME = NAME (renaming: result=geom means 'result' is available)
                                    var_name = item.children[0].value
                                elif len(item.children) == 1:
                                    # NAME (no renaming, same name passed through)
                                    var_name = item.children[0].value
                                # else: empty slot, skip
                                
                                if var_name:
                                    # Mark source variable as referenced
                                    source_name = None
                                    if len(item.children) == 2:
                                        source_name = item.children[1].value
                                    elif len(item.children) == 1:
                                        source_name = item.children[0].value
                                    
                                    if source_name and source_name in self.symbol_table:
                                        self.symbol_table[source_name]["referenced"] = True

                                    # Add to symbol table (available after loop)

                                    self.symbol_table[var_name] = {
                                        "type": "UNKNOWN",
                                        "value": None,
                                        "defined_at": None,
                                        "referenced": var_name in state_vars, 


                                    }


    def _process_simulation(self, stmt):
        """
        Process simulation zone: simulation{...} geometry, state=(vars):delta_time, geometry { body }(results)
        
        Same pattern as _process_repeat - tracks:
        1. Loop variables from output_vars_clause (:delta_time, geometry) - available inside simulation
        2. Variables defined in the output clause - available after simulation
        """
        # Check input references (geometry, state inputs)
        state_vars = set()
        for child in stmt.children:
            if isinstance(child, Tree):
                if child.data == 'state_clause':
                    state_vars = self._process_state_clause(child)
                    continue
                            
                if child.data in ('output_vars_clause', 'output_clause', 'statement', 'attributes'):
                    continue
                self._check_expression_references(child)
            elif isinstance(child, Token):
                self._check_expression_references(child)


        # First, parse output_vars_clause to track variables available inside the simulation



        for child in stmt.children:
            if isinstance(child, Tree) and child.data == 'output_vars_clause':
                # Parse loop variables: :dt, geom (or whatever names are used)
                for item in child.children:
                    if isinstance(item, Tree) and item.data == 'output_var_item':
                        # output_var_item is NAME?
                        if item.children:
                            var_name = item.children[0].value
                            # Add to symbol table
                            self.symbol_table[var_name] = {
                                "type": "UNKNOWN",
                                "value": None,
                                "defined_at": None,
                            }
        
        # Process simulation body statements (now that loop vars are defined)
        for child in stmt.children:
            if isinstance(child, Tree) and child.data == 'statement':
                self._process_statement(child)
        
        # Finally, parse output_clause to track variables defined from simulation outputs


        for child in stmt.children:
            if isinstance(child, Tree) and child.data == 'output_clause':
                # Parse output_clause: (output_item, output_item, ...)
                for item in child.children:
                    if isinstance(item, Tree) and item.data == 'output_item':
                        # Extract variable name from output_item
                        var_name = None
                        if len(item.children) == 2:
                            var_name = item.children[0].value
                        elif len(item.children) == 1:
                            var_name = item.children[0].value
                        
                        if var_name:

                            # Mark source variable as referenced
                            source_name = None
                            if len(item.children) == 2:
                                source_name = item.children[1].value
                            elif len(item.children) == 1:
                                source_name = item.children[0].value
                            
                            if source_name and source_name in self.symbol_table:
                                self.symbol_table[source_name]["referenced"] = True

                            # Add to symbol table (available after simulation)

                        elif len(item.children) == 1:
                            # NAME (no renaming, same name passed through)
                            var_name = item.children[0].value
                        # else: empty slot, skip
                        
                        if var_name:
                            # Mark source variable as referenced
                            source_name = None
                            if len(item.children) == 2:
                                source_name = item.children[1].value
                            elif len(item.children) == 1:
                                source_name = item.children[0].value
                            
                            if source_name and source_name in self.symbol_table:
                                self.symbol_table[source_name]["referenced"] = True

                            # Add to symbol table (available after simulation)
                            self.symbol_table[var_name] = {

                                "type": "UNKNOWN",
                                "value": None,
                                "defined_at": None,
                                "referenced": var_name in state_vars, 


                            }

    def _process_closure(self, stmt):
        """
        Process closure zone: closure(inputs) { body }(outputs)
        """
        # Parse closure_inputs to register parameters inside closure body
        for child in stmt.children:
            if isinstance(child, Tree) and child.data == 'closure_inputs':
                for param in child.children:
                    if isinstance(param, Tree) and param.data == 'closure_param':
                        if param.children:
                            param_name = param.children[0].value
                            self.symbol_table[param_name] = {
                                "type": "UNKNOWN",
                                "value": None,
                                "defined_at": None,
                            }

        # Process statements in closure body
        for child in stmt.children:
            if isinstance(child, Tree) and child.data == 'statement':
                self._process_statement(child)

        # Process output clause
        for child in stmt.children:
            if isinstance(child, Tree) and child.data == 'output_clause':
                for item in child.children:
                    if isinstance(item, Tree) and item.data == 'output_item':
                        if len(item.children) == 2:
                            out_name = item.children[0].value
                            self.symbol_table[out_name] = {
                                "type": "CLOSURE",
                                "value": None,
                                "defined_at": None,
                            }

    def _check_expression_references(self, expr):
        """
        Recursively check if all variables/functions referenced in an expression are defined.

        Checks against:
        - symbol_table (assigned variables)
        - inputs (declared input parameters)
        - groups (defined groups)
        - Built-in constants (True, False, etc.)

        Adds errors for undefined references.
        """
        if isinstance(expr, Token):
            # Check if this is a NAME token (variable reference)
            if expr.type == "NAME":
                name = expr.value

                # Use shared validation function (single source of truth)
                if is_variable_defined(name, self.symbol_table, self.inputs, self.groups):
                    # Mark variable as referenced
                    if name in self.symbol_table:
                        self.symbol_table[name]["referenced"] = True


                else:

                    # Get line/column from token (Lark uses 1-based, convert to 0-based)
                    line = getattr(expr, 'line', 1) - 1
                    column = getattr(expr, 'column', 1) - 1
                    error_msg = get_undefined_variable_error(name, self.symbol_table)
                    self.errors.append((error_msg, line, column))

                # Mark input as used if it's referenced
                if name in self.inputs:
                    self.inputs[name]["used"] = True

        elif isinstance(expr, Tree):
            # Handle function calls specially
            if expr.data == "function_call":
                # First child is the function name
                func_name = None
                if expr.children:
                    func_name_token = expr.children[0]
                    if isinstance(func_name_token, Token):
                        func_name = func_name_token.value

                        # Validate that function/node exists
                        # Check against: defined groups, closure variables, input parameters, shortcuts, or registry nodes
                        if (
                            func_name not in self.groups
                            and func_name not in self.symbol_table
                            and func_name not in self.inputs
                        ):
                            # Not a group or local closure - check if it's a shortcut or registry node
                            if self.registry:
                                # Resolve shortcut to actual node name
                                actual_node = func_name
                                if func_name in FUNCTION_SHORTCUTS:
                                    shortcut_info = FUNCTION_SHORTCUTS[func_name]
                                    actual_node = shortcut_info[0] if isinstance(shortcut_info, tuple) else shortcut_info
                                
                                # Check if node exists in registry
                                node_def = self.registry.get_node_def(actual_node) or self.registry.get_node_def(func_name)
                                if not node_def:
                                    from asset_loader import is_known_asset
                                    if is_known_asset(actual_node) or is_known_asset(func_name):
                                        # Valid built-in asset group (e.g. Combine Spherical, Array, etc.)
                                        pass
                                    else:
                                        line = getattr(func_name_token, 'line', 1) - 1
                                        col = getattr(func_name_token, 'column', 1) - 1
                                        # Quoted names might be group labels or built-in assets
                                        if func_name.startswith('"') or func_name.startswith("'"):
                                            # Warning instead of error for quoted labels
                                            self.warnings.append((
                                                f"Node '{func_name}' not in registry (may be a group label or built-in asset)",
                                                line,
                                                col
                                            ))
                                        else:
                                            self.errors.append((
                                                f"Unknown node type: '{func_name}'. Not found in registry or defined groups.",
                                                line,
                                                col
                                            ))
                                else:
                                    # Use canonical name for validation if resolved
                                    resolved_name = self.registry.get_canonical_name(node_def.get("bl_idname")) or actual_node
                                    # Validate argument types against socket types
                                    self._validate_argument_types(expr, resolved_name, func_name_token)
                                    
                                    # Special check for multi-input nodes using comma instead of tilde
                                    # Use centralized definition from registry
                                    is_multi_input = False
                                    
                                    # Check by canonical name if possible, or bl_idname
                                    if self.registry:
                                        bl_idname = self.registry.get_bl_idname(actual_node)
                                        if bl_idname:
                                            # Check bl_idname against the set
                                            if bl_idname in MULTI_INPUT_NODES:
                                                is_multi_input = True
                                    
                                    # Fallback: check if the name itself is in the set (unlikely but safe)
                                    if not is_multi_input and actual_node in MULTI_INPUT_NODES:
                                        is_multi_input = True
                                        
                                    if is_multi_input:
                                        # Parse arguments to count them
                                        arg_count = 0

                                        for child in expr.children:
                                            if isinstance(child, Tree) and child.data == "arguments":
                                                for arg in child.children:
                                                    if isinstance(arg, Tree) and arg.data == "argument":
                                                        arg_count += 1
                                        
                                        if arg_count > 1:
                                            line = getattr(func_name_token, 'line', 1) - 1
                                            col = getattr(func_name_token, 'column', 1) - 1
                                            self.warnings.append((
                                                f"Function '{func_name}' has {arg_count} arguments. Did you mean to use '~' to join them? "
                                                f"Example: {func_name}(a ~ b)",
                                                line,
                                                col
                                            ))


                    # Check arguments and validate attributes
                    for child in expr.children[1:]:
                        if isinstance(child, Tree) and child.data == "attributes":
                            # Validate attribute keys for this function
                            self._validate_attributes(func_name, child)
                        self._check_expression_references(child)

            elif expr.data == "kwarg":
                # Named argument: kwarg -> [NAME (param name), value]
                # Skip the first child (parameter name), only check the value
                if len(expr.children) > 1:
                    self._check_expression_references(expr.children[1])

            elif expr.data == "attributes":
                # Attributes block: {key:value, key2:value2}
                # Each child is an 'attribute' node
                for child in expr.children:
                    self._check_expression_references(child)

            elif expr.data == "attribute":
                # Single attribute: NAME ":" value
                # First child is the key (skip it), rest are values
                # Only check values that could be variable references
                for child in expr.children[1:]:
                    self._check_expression_references(child)

            elif expr.data == "attr_access":
                # attr_access: primary "." NAME
                # Only check references in primary, not the attribute NAME
                if expr.children:
                    self._check_expression_references(expr.children[0])

            elif expr.data == "py_access":
                # py.varname - access to Python namespace
                # Always valid - variables are populated from embedded Python blocks
                # No need to check since we can't statically analyze Python execution
                pass

            else:
                # Recursively check all children
                for child in expr.children:
                    self._check_expression_references(child)

    def _validate_attributes(self, func_name: str, attributes_node):
        """
        Validate attribute keys in a function call.

        Checks that each attribute key is a valid property for the node.

        Args:
            func_name: The function/node name being called
            attributes_node: The 'attributes' AST node containing attribute children
        """
        if not func_name:
            return

        # Resolve shortcut to actual node name
        actual_node = func_name
        if func_name in FUNCTION_SHORTCUTS:
            shortcut_info = FUNCTION_SHORTCUTS[func_name]
            actual_node = shortcut_info[0] if isinstance(shortcut_info, tuple) else shortcut_info

        # Get valid properties for this node
        valid_props = set(COMMON_ATTRIBUTES.keys())  # Always allow common attributes
        valid_props.update(PREPROCESSOR_ATTRIBUTES)  # Also allow preprocessor attributes

        if self.registry:
            node_info = self.registry.nodes.get(actual_node)
            if node_info:
                # Add user-facing properties
                if "properties" in node_info:
                    user_props = get_user_facing_properties(node_info["properties"])
                    valid_props.update(user_props)
                
                # Add input socket names as valid attributes (for MENU sockets etc.)
                # Attributes can set socket default values via {socket_name:'VALUE'}
                if "inputs" in node_info:
                    for socket_name in node_info["inputs"].keys():
                        # Convert to snake_case for attribute matching
                        snake_name = socket_name.lower().replace(' ', '_').replace('-', '_')
                        valid_props.add(snake_name)

        # Check each attribute
        for attr_child in attributes_node.children:
            if isinstance(attr_child, Tree) and attr_child.data == "attribute":
                # First child is the attribute key (NAME or ATTR_NAME token)
                if attr_child.children:
                    key_token = attr_child.children[0]
                    if isinstance(key_token, Token) and key_token.type in ("NAME", "ATTR_NAME"):
                        attr_key = key_token.value
 
                        # Split by dot to validate nested property paths (e.g., color_ramp.interpolation)
                        parts = attr_key.split('.')
                        base_key = parts[0]
 
                        if base_key not in valid_props:
                            line = getattr(key_token, 'line', 1) - 1
                            column = getattr(key_token, 'column', 1) - 1
                            self.errors.append((
                                f"Unknown attribute '{attr_key}' for node '{actual_node}'",
                                line,
                                column
                            ))
                        elif len(parts) > 1:
                            # Validate nested parts against node_info["properties"]
                            current_props = node_info.get("properties", {}).get(base_key) if node_info else None
                            valid_path = True
                            
                            for part in parts[1:]:
                                struct_def = current_props.get("default") if isinstance(current_props, dict) else None
                                if isinstance(struct_def, dict) and struct_def.get("type") == "STRUCT":
                                    current_props = struct_def.get("properties", {}).get(part)
                                    if current_props is None:
                                        valid_path = False
                                        break
                                else:
                                    valid_path = False
                                    break
                                    
                            if not valid_path:
                                line = getattr(key_token, 'line', 1) - 1
                                column = getattr(key_token, 'column', 1) - 1
                                self.errors.append((
                                    f"Unknown nested attribute '{attr_key}' for node '{actual_node}'",
                                    line,
                                    column
                                ))

    def _validate_argument_types(self, func_call_expr, node_name: str, func_name_token):
        """
        Validate that positional argument types match expected socket types.
        
        Args:
            func_call_expr: The function_call AST node
            node_name: Resolved node name (from registry)
            func_name_token: Token with function name (for line info)
        """
        if not self.registry:




            return
        
        # Skip type validation for mode-dependent nodes (registry incomplete)
        if node_name in MODE_DEPENDENT_NODES:
            return
        
        node_info = self.registry.nodes.get(node_name)
        if not node_info or "inputs" not in node_info:
            return
        
        # Get sockets sorted by index
        inputs = node_info.get("inputs", {})
        sockets = []
        for socket_name, socket_info in inputs.items():
            if node_name == "store_named_attribute":
                print(f"STORE_NAMED_ATTR: Found socket {socket_name} with info: {socket_info}")
            if "index" in socket_info and "type" in socket_info:

                sockets.append((socket_info["index"], socket_name, socket_info["type"]))
        sockets.sort(key=lambda x: x[0])
        
        # Extract positional arguments from function call
        # Function call structure: NAME, {attributes}?, (arguments)?
        arguments = []
        for child in func_call_expr.children:
            if isinstance(child, Tree) and child.data == "arguments":
                for arg_child in child.children:
                    if isinstance(arg_child, Tree) and arg_child.data == "argument":
                        arguments.append(arg_child)
        
        # For nodes with no sockets in registry, skip validation
        # (registry may be incomplete for mode-dependent nodes)
        if len(sockets) == 0:
            return
        
        # Check each positional argument against expected socket type
        for i, arg in enumerate(arguments):
            if i >= len(sockets):
                # More args than sockets - check if it's a multi-input node
                # If it's multi-input (like join_strings or join_geometry), we might allow excess args?
                # But they should use `~` operator.
                # If we are here, it means we have comma separated arguments.
                
                # We already warn about this in _check_expression_references for known multi-input nodes.
                # For regular nodes, this is definitely wrong.
                
                line = getattr(func_name_token, 'line', 1) - 1
                col = getattr(func_name_token, 'column', 1) - 1
                
                # Check if node supports variadic inputs? But registry doesn't specify.
                # Assuming fixed inputs as per registry unless it's a special node.
                
                self.warnings.append((
                    f"Too many arguments for '{node_name}': expected {len(sockets)}, got {len(arguments)}",
                    line,
                    col
                ))
                continue
            
            # Skip empty arguments (they don't have children)
            if not arg.children:
                continue
            
            # Skip kwargs (named arguments use different mechanism)
            arg_expr = arg.children[0]
            if isinstance(arg_expr, Tree) and arg_expr.data == "kwarg":
                continue
            
            # Infer argument type
            arg_type = self._infer_expression_type(arg_expr)
            if arg_type == "UNKNOWN":
                continue  # Can't validate unknown types
            
            # Get expected socket type
            _, socket_name, expected_type = sockets[i]
            
            # Check type compatibility
            if not self._types_compatible(arg_type, expected_type):
                # Get line info from argument if possible
                line = getattr(func_name_token, 'line', 1) - 1
                col = getattr(func_name_token, 'column', 1) - 1
                
                self.errors.append((
                    f"Type mismatch in '{node_name}': argument {i+1} has type {arg_type} "
                    f"but socket '{socket_name}' expects {expected_type}",
                    line,
                    col
                ))

    def _infer_expression_type(self, expr) -> str:
        """
        Infer the type of an expression for type checking.
        
        Returns type string: VALUE, INT, STRING, BOOLEAN, VECTOR, GEOMETRY, MENU, UNKNOWN
        """
        if isinstance(expr, Token):
            if expr.type == "NUMBER" or expr.type == "SIGNED_NUMBER":
                # Check if integer or float
                val = expr.value
                if "." in val:
                    return "VALUE"  # Float
                else:
                    return "INT"
            elif expr.type == "STRING":
                return "STRING"
            elif expr.type == "BOOL":
                return "BOOLEAN"
            elif expr.type == "NAME":
                # Variable - check symbol table for type
                var_name = expr.value
                if var_name in self.symbol_table:
                    stored_type = self.symbol_table[var_name].get("type", "UNKNOWN")
                    if stored_type != "UNKNOWN":
                        return stored_type
                if var_name in self.inputs:
                    return self.inputs[var_name].get("type", "UNKNOWN")
                return "UNKNOWN"
        
        elif isinstance(expr, Tree):
            if expr.data == "tuple_or_group":
                # Could be vector (3-tuple) or color (4-tuple)
                if len(expr.children) == 3:
                    return "VECTOR"
                elif len(expr.children) == 4:
                    return "RGBA"
                return "UNKNOWN"
            
            elif expr.data == "function_call":
                # Try to get return type from registry
                if expr.children:
                    func_name_token = expr.children[0]
                    if isinstance(func_name_token, Token):
                        func_name = func_name_token.value
                        
                        # Skip inference for mode-dependent nodes (registry output types unreliable)
                        if func_name in MODE_DEPENDENT_NODES:
                            return "UNKNOWN"

                        actual_node = func_name
                        if func_name in FUNCTION_SHORTCUTS:
                            shortcut_info = FUNCTION_SHORTCUTS[func_name]
                            actual_node = shortcut_info[0] if isinstance(shortcut_info, tuple) else shortcut_info
                        
                        if self.registry:
                            node_info = self.registry.get_node_def(actual_node) or self.registry.get_node_def(func_name)
                            if node_info and "outputs" in node_info:
                                outputs = node_info["outputs"]
                                # Return first output type (primary output)
                                if outputs:
                                    first_output = min(outputs.values(), 
                                                      key=lambda x: x.get("index", 0))
                                    return first_output.get("type", "UNKNOWN")
                return "UNKNOWN"
            
            elif expr.data == "index_access":
                # Result of indexing (e.g., func()[0], func()[-1])
                base_expr = expr.children[0]
                index_child = expr.children[1]
                idx = None
                if isinstance(index_child, Token) and index_child.type == "NUMBER":
                    try:
                        idx = int(float(index_child.value))
                    except ValueError:
                        pass
                elif hasattr(index_child, "data") and index_child.data == "unary_op":
                    if len(index_child.children) >= 2:
                        op = getattr(index_child.children[0], "value", str(index_child.children[0]))
                        num = index_child.children[1]
                        if op == "-" and isinstance(num, Token) and num.type == "NUMBER":
                            try:
                                idx = -int(float(num.value))
                            except ValueError:
                                pass

                if idx is not None and hasattr(base_expr, "data") and base_expr.data == "function_call":
                    func_name = str(base_expr.children[0])
                    actual_node = func_name
                    if func_name in FUNCTION_SHORTCUTS:
                        shortcut_info = FUNCTION_SHORTCUTS[func_name]
                        actual_node = shortcut_info[0] if isinstance(shortcut_info, tuple) else shortcut_info
                    if self.registry:
                        node_info = self.registry.get_node_def(actual_node) or self.registry.get_node_def(func_name)
                        if node_info and "outputs" in node_info:
                            outputs = list(sorted(node_info["outputs"].values(), key=lambda x: x.get("index", 0)))
                            if outputs:
                                if idx < 0:
                                    idx = len(outputs) + idx
                                if 0 <= idx < len(outputs):
                                    return outputs[idx].get("type", "UNKNOWN")
                return "UNKNOWN"

            elif expr.data == "closure":
                self._process_closure(expr)
                return "CLOSURE"

            elif expr.data == "ternary_op":
                # ternary_op: condition true_val false_val
                if len(expr.children) > 2:
                    t_type = self._infer_expression_type(expr.children[1])
                    f_type = self._infer_expression_type(expr.children[2])
                    if t_type == f_type and t_type != "UNKNOWN":
                        return t_type
                    elif {t_type, f_type} <= {"INT", "VALUE", "FLOAT"}:
                        return "VALUE"
                    elif t_type != "UNKNOWN":
                        return t_type
                    else:
                        return f_type
                return "UNKNOWN"

            # Boolean operations
            elif expr.data in ("logical_or", "logical_xor", "logical_and", "logical_nand_nor", "comparison"):
                return "BOOLEAN"

            # Concatenation operator (multi-input lists, string join, bundle join)
            elif expr.data == "concat":
                if expr.children:
                    return self._infer_expression_type(expr.children[0])
                return "UNKNOWN"

            # Math operations
            elif expr.data in ("add_sub", "mul_div", "power"):
                # Infer type from children
                # Priority: VECTOR > VALUE > INT
                has_vector = False
                has_float = False
                
                # Check children (skip operators)
                for child in expr.children:
                    if isinstance(child, Tree) or (isinstance(child, Token) and child.type == "NAME"):
                         child_type = self._infer_expression_type(child) 
                         if child_type == "VECTOR":
                             has_vector = True
                         elif child_type == "VALUE" or child_type == "FLOAT":
                             has_float = True
                
                if has_vector:
                    return "VECTOR"
                if has_float:
                    return "VALUE"
                return "INT"

            # Unary operations
            elif expr.data == "unary_op":
                 # Check operator
                 op = expr.children[0]
                 if isinstance(op, Token) and op.type == "NOT_OP":
                     return "BOOLEAN"
                 # Propagate type from operand
                 return self._infer_expression_type(expr.children[1])

            # Fallback for wrapper nodes (expression, term, factor, etc.)
            if expr.children:
                return self._infer_expression_type(expr.children[0])
        
        return "UNKNOWN"

    def _types_compatible(self, arg_type: str, socket_type: str) -> bool:
        """
        Check if an argument type is compatible with a socket type.
        
        Some types are compatible:
        - INT and VALUE are interchangeable (Blender converts automatically)
        - STRING can go to MATERIAL sockets (material name lookup)
        - CUSTOM/VIRTUAL sockets accept any type
        
        Returns True if types are compatible, False otherwise.
        """
        if arg_type == socket_type:
            return True
        
        # Virtual / Custom dynamic sockets accept any type
        if socket_type in ("CUSTOM", "VIRTUAL") or arg_type in ("CUSTOM", "VIRTUAL"):
            return True
        
        # INT, FLOAt, and VALUE are interchangeable
        if {arg_type, socket_type} <= {"INT", "VALUE", "FLOAT"}:
            return True
            
        # MAT maps to MATERIAL
        if arg_type == "MAT" and socket_type == "MATERIAL":
            return True
        
        # STRING can be used as MATERIAL/OBJECT/COLLECTION reference by name
        if arg_type == "STRING" and socket_type in ("MATERIAL", "OBJECT", "COLLECTION", "IMAGE", "TEXTURE"):
            return True
        
        # VECTOR and RGBA are somewhat compatible (Blender handles conversion)
        if {arg_type, socket_type} <= {"VECTOR", "RGBA"}:
            return True
            
        # Stricter Check: GEOMETRY is NOT compatible with math types
        if arg_type == "GEOMETRY" and socket_type in ("VALUE", "INT", "FLOAT", "VECTOR", "RGBA", "STRING", "BOOLEAN"):
            return False
            
        if socket_type == "GEOMETRY" and arg_type in ("VALUE", "INT", "FLOAT", "VECTOR", "RGBA", "STRING", "BOOLEAN"):
            return False
        
        # All other mismatches are errors
        return False

    def _check_hanging_nodes(self):
        """
        Check for variables that are defined but never referenced.
        This indicates a disconnected branch of the node graph (hanging nodes).
        """
        for var_name, info in self.symbol_table.items():
            # Skip internal/special variables
            if var_name.startswith("_"):
                continue
                
            # If variable is not referenced and not an output parameter
            if not info.get("referenced", False) and var_name not in self.outputs:
                line = info.get("defined_at")
                if line:
                    line = line - 1 # Convert to 0-based
                else:
                    line = 0
                    
                self.warnings.append((
                    f"Variable '{var_name}' is defined but never used. "
                    f"This branch may be disconnected from the final output.",
                    line,
                    0
                ))

    def _check_unused_inputs(self):
        """
        Check for input parameters that were never used.

        Uses shared validation functions (single source of truth).
        Adds warnings for unused inputs with line information.
        """
        unused = get_unused_inputs(self.inputs)
        for name, line, column in unused:
            warning_msg = get_unused_input_warning(name)
            self.warnings.append((warning_msg, line, column))
