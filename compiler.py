import ast
import os
from contextlib import contextmanager
from lark import Tree, Token

def unescape_string(token_val):
    try:
        return ast.literal_eval(token_val)
    except Exception:
        if len(token_val) >= 2 and token_val[0] in "'\"" and token_val[-1] in "'\"":
            return token_val[1:-1]
        return token_val


class XFYCompileError(Exception):
    """Compiler error with source file, line number, column, and line snippet."""

    def __init__(
        self,
        message,
        filepath=None,
        line=None,
        column=None,
        snippet=None,
        original_error=None,
    ):
        self.message = str(message)
        self.filepath = filepath
        self.line = line
        self.column = column
        self.snippet = snippet
        self.original_error = original_error

        loc_parts = []
        if filepath:
            loc_parts.append(str(filepath))
        if line is not None:
            loc_parts.append(str(line))
        if column is not None:
            loc_parts.append(str(column))

        loc_str = ":".join(loc_parts)
        if loc_str:
            if snippet:
                full_msg = f"{loc_str}: {self.message}\n  {snippet}"
            else:
                full_msg = f"{loc_str}: {self.message}"
        else:
            full_msg = self.message

        super().__init__(full_msg)


try:
    from .builder import NodeBuilder
    from .shortcuts import expand_function_shortcut
    from .logger import get_logger
    from .validation import BUILTIN_CONSTANTS, get_undefined_variable_error
    from .registry import MULTI_INPUT_NODES
except ImportError:
    from builder import NodeBuilder
    from shortcuts import expand_function_shortcut
    from logger import get_logger
    from validation import BUILTIN_CONSTANTS, get_undefined_variable_error
    from registry import MULTI_INPUT_NODES

# Initialize logger for this module

logger = get_logger()


# Helper functions for Python namespace bridge (py.*)
def is_primitive(value):
    """Check if value is a supported primitive type"""
    return isinstance(value, (int, float, bool, str, tuple, list))


def is_primitive_or_callable(value):
    """Check if value is primitive or callable"""
    return is_primitive(value) or callable(value)


def to_primitive(value):
    """Convert value to primitive for Python function call

    Raises TypeError if value is a node/socket reference
    """
    if is_primitive(value):
        return value

    raise TypeError(
        f"Cannot pass script variable to Python function. "
        f"Python functions accept only literals and py.* values."
    )


def validate_python_namespace(namespace):
    """Validate all namespace values are primitive or callable

    Raises TypeError for unsupported types (None, dict, objects, etc.)
    """
    for name, value in namespace.items():
        if value is None:
            raise TypeError(
                f"Python variable '{name}' is None. "
                f"Use int, float, bool, str, tuple, list, or functions."
            )
        if not is_primitive_or_callable(value):
            raise TypeError(
                f"Python variable '{name}' has unsupported type {type(value).__name__}. "
                f"Use int, float, bool, str, tuple, list, or functions returning these types."
            )


class Compiler:
    """
    Compiler that processes parsed AST and generates Blender nodes.
    Uses manual iteration instead of Visitor pattern to avoid duplicate node creation.
    """

    def __init__(
        self,
        builder: NodeBuilder,
        modifier=None,
        parent_chain=None,
        python_namespace=None,
        source_map=None,
        filepath=None,
        source_text=None,
    ):
        self.builder = builder
        if self.builder is not None:
            self.builder.compiler = self
        self.modifier = (
            modifier  # Optional: geometry nodes modifier (for setting defaults)
        )
        # Parent chain for __parents__ variable in Python blocks
        self.parent_chain = parent_chain if parent_chain is not None else []
        # Precomputed Python namespace from parse() - avoids re-executing blocks
        self.python_namespace = python_namespace if python_namespace is not None else {}
        self.source_map = source_map
        self.filepath = filepath
        self.source_lines = (
            source_text.split("\n")
            if (source_text and isinstance(source_text, str))
            else []
        )
        self._statement_stack = []
        self._file_lines_cache = {}
        # Predefined variables for compatibility with old XNodify
        self.symbol_table = {
            "_specialchars": ["\n"]  # Special characters array, index 0 is newline
        }  # Maps variable names to (node, socket_index)
        self.inputs = {}
        self.outputs = {}
        self.output_socket_names = {}
        self.frame_stack = []  # Stack of current frame nodes
        self.groups = {}  # Maps group names to group info
        self.current_group = None  # Current group being compiled
        self.iteration_var = None  # For loops: the iteration variable name
        self.deferred_menu_defaults = []  # Store menu input defaults to set after compilation
        self.pending_materials = []  # Store (socket, mat_name) for deferred material resolution
        self.closure_signatures = {}  # Store variable/input closure signatures: {name: {"inputs": [...], "outputs": [...]}}
        self.bundle_signatures = {}  # Store variable/input bundle signatures: {name: {"fields": [...]}}
        # Note: python_namespace is initialized from parser at line 75 - don't overwrite here
        self.python_blocks_source = []  # Source code of Python blocks (for debugging)

    @contextmanager
    def location_context(self, node):
        """Context manager to track the active AST node/statement for accurate location logging."""
        if node is not None:
            self._statement_stack.append(node)
            try:
                yield
            finally:
                if self._statement_stack:
                    self._statement_stack.pop()
        else:
            yield

    def get_ast_location_info(self, node=None):
        """
        Extract file, line, column, and line snippet for an AST node or current statement.
        Returns dict: {'file': ..., 'line': ..., 'column': ..., 'snippet': ..., 'location_str': ...}
        """
        target = node
        if target is None and self._statement_stack:
            target = self._statement_stack[-1]
        if target is None:
            target = getattr(self, "current_statement", None)

        line = None
        col = None

        def find_meta(n):
            nonlocal line, col
            if line is not None:
                return
            if hasattr(n, "meta") and getattr(n.meta, "line", None) is not None:
                line = n.meta.line
                col = getattr(n.meta, "column", 1)
                return
            if isinstance(n, Token) and getattr(n, "line", None) is not None:
                line = n.line
                col = getattr(n, "column", 1)
                return
            if hasattr(n, "children"):
                for ch in n.children:
                    find_meta(ch)

        if target is not None:
            find_meta(target)

        orig_file = None
        orig_line = line
        if line is not None and self.source_map:
            m_file, m_line = self.source_map.get_original_location(line)
            if m_file:
                orig_file = m_file
                orig_line = m_line

        eff_file = orig_file if orig_file else self.filepath
        snippet = ""

        if eff_file and os.path.exists(eff_file) and orig_line:
            if eff_file not in self._file_lines_cache:
                try:
                    with open(eff_file, "r", encoding="utf-8") as f:
                        self._file_lines_cache[eff_file] = f.read().splitlines()
                except Exception:
                    self._file_lines_cache[eff_file] = []
            f_lines = self._file_lines_cache[eff_file]
            if 0 < orig_line <= len(f_lines):
                snippet = f_lines[orig_line - 1].strip()
        elif self.source_lines and line and 0 < line <= len(self.source_lines):
            snippet = self.source_lines[line - 1].strip()

        loc_parts = []
        if eff_file:
            loc_parts.append(str(eff_file))
        if orig_line is not None:
            loc_parts.append(str(orig_line))
        if col is not None:
            loc_parts.append(str(col))

        loc_str = ":".join(loc_parts) if loc_parts else ""

        return {
            "file": eff_file,
            "line": orig_line,
            "column": col,
            "snippet": snippet,
            "location_str": loc_str,
        }

    def _format_msg(self, msg: str, node=None):
        info = self.get_ast_location_info(node)
        loc_str = info["location_str"]
        snippet = info["snippet"]
        if loc_str:
            if snippet:
                return f"{loc_str}: {msg}\n  {snippet}"
            return f"{loc_str}: {msg}"
        return msg

    def warning(self, msg: str, node=None):
        """Log a compiler warning with source location and line snippet."""
        logger.warning(self._format_msg(msg, node))

    def error(self, msg: str, node=None):
        """Log a compiler error with source location and line snippet."""
        logger.error(self._format_msg(msg, node))

    def _parse_type_spec(self, type_node):
        """Parse a type_spec, closure_signature, bundle_signature, or TYPE node and extract the base type name and optional signature."""
        if isinstance(type_node, Token):
            return type_node.value.lower(), None

        if hasattr(type_node, "data"):
            if type_node.data == "type_spec":
                child = type_node.children[0]
                return self._parse_type_spec(child)
            elif type_node.data == "bundle_signature":
                fields = []
                for child in type_node.children:
                    if not hasattr(child, "data"):
                        continue
                    if child.data == "bundle_sig_field":
                        p_name = None
                        p_type = "FLOAT"
                        if len(child.children) == 2:
                            p_name = child.children[0].value
                            p_type = child.children[1].value.upper()
                        elif len(child.children) == 1:
                            p_type = child.children[0].value.upper()
                        
                        # Normalize type enum
                        if p_type in ("INT", "INTEGER"): p_type = "INT"
                        elif p_type in ("FLOAT", "VALUE"): p_type = "FLOAT"
                        elif p_type in ("BOOL", "BOOLEAN"): p_type = "BOOLEAN"
                        elif p_type in ("COLOR", "RGBA"): p_type = "RGBA"
                        elif p_type == "VECTOR": p_type = "VECTOR"
                        elif p_type == "STRING": p_type = "STRING"
                        elif p_type == "GEOMETRY": p_type = "GEOMETRY"
                        elif p_type in ("MAT", "MATERIAL"): p_type = "MATERIAL"
                        elif p_type == "OBJECT": p_type = "OBJECT"
                        elif p_type == "COLLECTION": p_type = "COLLECTION"
                        elif p_type == "ROTATION": p_type = "ROTATION"
                        elif p_type == "MATRIX": p_type = "MATRIX"
                        elif p_type == "CLOSURE": p_type = "CLOSURE"
                        elif p_type == "BUNDLE": p_type = "BUNDLE"
                        
                        fields.append({"name": p_name, "type": p_type})
                return "bundle", {"fields": fields}
            elif type_node.data == "closure_signature":
                inputs = []
                outputs = []
                for child in type_node.children:
                    if not hasattr(child, "data"):
                        continue
                    if child.data == "closure_sig_param":
                        p_name = None
                        p_type = "FLOAT"
                        if len(child.children) == 2:
                            p_name = child.children[0].value
                            p_type = child.children[1].value.upper()
                        elif len(child.children) == 1:
                            p_type = child.children[0].value.upper()
                        inputs.append({"name": p_name, "type": p_type})
                    elif child.data == "closure_sig_return":
                        for rchild in child.children:
                            if isinstance(rchild, Token) and rchild.type == "TYPE":
                                outputs.append({"name": None, "type": rchild.value.upper()})
                            elif hasattr(rchild, "data") and rchild.data == "closure_sig_param":
                                p_name = None
                                p_type = "FLOAT"
                                if len(rchild.children) == 2:
                                    p_name = rchild.children[0].value
                                    p_type = rchild.children[1].value.upper()
                                elif len(rchild.children) == 1:
                                    p_type = rchild.children[0].value.upper()
                                outputs.append({"name": p_name, "type": p_type})

                return "closure", {"inputs": inputs, "outputs": outputs}

        return "float", None

    def resolve_pending_materials(self):
        """Resolve any pending material connections where material was created later."""
        import bpy
        if hasattr(self, "pending_materials") and self.pending_materials:
            for socket, mat_name in list(self.pending_materials):
                mat = bpy.data.materials.get(mat_name)
                if mat:
                    try:
                        socket.default_value = mat
                        logger.debug(f"Resolved pending material '{mat_name}' on socket {socket.name}")
                    except Exception as e:
                        self.error(f"Error setting pending material '{mat_name}': {e}")

    def _get_default_socket_type(self):
        """Get default socket type based on the tree type"""
        tree_type = self.builder.node_tree.bl_idname
        if tree_type == "ShaderNodeTree":
            return "NodeSocketShader"
        else:  # GeometryNodeTree or others
            return "NodeSocketGeometry"

    def compile(self, tree, source_text=None):
        """
        Compile the AST by manually iterating over top-level statements

        Args:
            tree: Parsed AST tree
            source_text: Optional source code text for logging (shows actual lines being executed)
        """
        # Store source lines for logging
        if source_text and isinstance(source_text, str):
            self.source_lines = source_text.split("\n")
        elif source_text:
            # Invalid type passed, log warning and skip
            self.warning(
                f"compile() received non-string source_text of type {type(source_text).__name__}, skipping line logging"
            )

        self.output_socket_names = {}

        # PASS 1: Execute Python blocks and build namespace
        self.execute_python_blocks(tree)

        # PASS 2: Compile statements
        # tree.data should be 'start'
        # tree.children contains all the statements
        for statement in tree.children:
            self.process_statement(statement)

        # After processing all statements, ensure all defined groups are instantiated
        # This is important for group-only scripts where groups are defined but never called
        # The groups need to exist in bpy.data.node_groups for other scripts to use them
        for group_name, group_info in list(self.groups.items()):
            if group_info["node_tree"] is None:
                # Group was defined but never instantiated - compile it now
                logger.debug(f"Compiling un-instantiated group: {group_name}")
                self._compile_group_body(group_name, group_info)

        # Process deferred menu defaults now that all nodes are created
        # and enum items have been populated
        self._set_deferred_menu_defaults()



    def extract_python_blocks(self, tree):
        """Extract all PYTHON_BLOCK tokens from AST

        Returns list of (code_content, line_number) tuples
        """
        blocks = []

        def visit(node):
            if isinstance(node, Tree):
                if node.data == "python_block" and len(node.children) >= 1:
                    code_token = node.children[0]
                    code_content = (
                        code_token.value if hasattr(code_token, "value") else str(code_token)
                    )
                    # Strip triple backticks
                    code_content = code_content.strip()
                    if code_content.startswith("```"):
                        code_content = code_content[3:]
                    if code_content.endswith("```"):
                        code_content = code_content[:-3]
                    code_content = code_content.strip()

                    # Get line number if available
                    line_num = getattr(code_token, 'line', None)
                    blocks.append((code_content, line_num))

                # Recurse into children
                for child in node.children:
                    visit(child)

        visit(tree)
        return blocks

    def execute_python_blocks(self, tree):
        """Execute all Python blocks and build namespace (Pass 1)

        If python_namespace was provided in __init__, we reuse it instead of re-executing.
        This avoids duplicate execution and maintains single source of truth.
        """
        # Check if we already have namespace from parse()
        # Note: Check against None, not truthiness (empty dict is valid!)
        if hasattr(self, 'python_namespace') and self.python_namespace is not None:
            # Already executed during parse() - reuse the namespace
            logger.info(f"✓ INFO: Python namespace ready: {len(self.python_namespace)} variable(s)/function(s)")
            return

        # Fallback: Execute blocks if no namespace provided (shouldn't normally happen)
        blocks = self.extract_python_blocks(tree)

        if not blocks:
            return  # No Python blocks

        self.python_blocks_source = blocks  # Store for debugging
        logger.info(f"ℹ️  INFO: Executing {len(blocks)} Python block(s) ({sum(len(code) for code, _ in blocks)} chars)")

        # Execute as single block
        import bpy
        namespace = {
            "bpy": bpy,
            "__builtins__": __builtins__,
            "__parents__": self.parent_chain,
        }

        # Concatenate and execute all blocks
        python_code = "\n".join(code for code, _ in blocks)
        try:
            exec(python_code, namespace)
        except Exception as e:
            self.error(f"Python block execution failed: {e}")
            import traceback
            traceback.print_exc()
            raise RuntimeError(
                f"Python block execution failed: {e}\n"
                f"Check your ``` blocks for errors."
            )

        # Extract user-defined variables (skip builtins, bpy, and modules)
        import types
        self.python_namespace = {}
        for k, v in namespace.items():
            if k.startswith('_') or k == 'bpy' or isinstance(v, types.ModuleType):
                continue
            if is_primitive_or_callable(v):
                self.python_namespace[k] = v

        # Validate all values (should pass since we already filtered)
        try:
            validate_python_namespace(self.python_namespace)
        except TypeError as e:
            self.error(str(e))
            raise

        logger.success(
            f"Python namespace ready: {len(self.python_namespace)} variable(s)/function(s)"
        )

    def _set_deferred_menu_defaults(self):
        """Set default values for menu inputs after compilation

        Menu inputs need their enum items populated before setting defaults.
        This happens when menu_switch nodes are connected to them.
        So we defer setting menu defaults until after all nodes are created.
        """
        for menu_info in self.deferred_menu_defaults:
            socket = menu_info['socket']
            value = menu_info['value']
            display_name = menu_info['display_name']

            try:
                # Initialize interface socket template from connected MenuSwitch
                if hasattr(socket, "from_socket"):
                    target_pair = self._find_menu_switch_node_and_socket(self.builder.node_tree, socket.identifier)
                    if target_pair:
                        target_node, target_socket = target_pair
                        try:
                            socket.from_socket(target_node, target_socket)
                            logger.debug(f"  → Initialized menu socket interface from {target_node.name}")
                        except Exception as fs_err:
                            logger.debug(f"  → from_socket failed: {fs_err}")

                # If value is 0 (integer index request), we need to find the actual enum string
                if value == 0 and socket.bl_socket_idname == "NodeSocketMenu":
                    resolved_value = self._find_first_menu_item(self.builder.node_tree, socket.identifier)
                    if resolved_value:
                        value = resolved_value
                        logger.debug(f"  → Resolved default index 0 to menu item '{value}'")
                    else:
                        self.warning(f"  Could not resolve default menu item for '{display_name}'")

                socket.default_value = value
                logger.debug(f"Set deferred menu default for '{display_name}': {value}")

                # Also set modifier property if we have one
                if self.modifier is not None:
                    try:
                        socket_id = socket.identifier
                        # In Blender 5.2+, inputs are under modifier.properties.inputs
                        if hasattr(self.modifier, "properties") and hasattr(self.modifier.properties, "inputs"):
                            mod_inps = self.modifier.properties.inputs
                            if hasattr(mod_inps, socket_id):
                                getattr(mod_inps, socket_id).value = value
                                logger.debug(f"  → Set menu modifier property inputs.{socket_id} = {value}")
                            else:
                                self.modifier[socket_id] = value
                        else:
                            self.modifier[socket_id] = value
                            logger.debug(f"  → Set menu modifier property '{socket_id}' = {value}")
                    except Exception as mod_err:
                        self.warning(f"   Could not set menu modifier property: {mod_err}")
            except Exception as e:
                self.warning(f"Could not set deferred menu default for '{display_name}': {e}")

    def _find_menu_switch_node_and_socket(self, node_tree, socket_identifier):
        """Recursively find the connected Menu Switch node and its Menu socket"""
        group_input_node = None
        for node in node_tree.nodes:
            if node.bl_idname == "NodeGroupInput":
                group_input_node = node
                break
        if not group_input_node:
            return None

        node_socket = None
        for out in group_input_node.outputs:
            if out.identifier == socket_identifier:
                node_socket = out
                break
        if not node_socket or not node_socket.is_linked:
            return None

        for link in node_socket.links:
            target_node = link.to_node
            target_socket = link.to_socket
            if target_node.bl_idname == "GeometryNodeMenuSwitch":
                return target_node, target_socket
            elif target_node.bl_idname == 'GeometryNodeGroup' and getattr(target_node, 'node_tree', None):
                nested = self._find_menu_switch_node_and_socket(target_node.node_tree, target_socket.identifier)
                if nested:
                    return nested
        return None

    def _find_first_menu_item(self, node_tree, socket_identifier):
        """Recursively find the first item of a connected Menu Switch node
        
        Args:
            node_tree: The node tree to search in (starts with top-level tree)
            socket_identifier: The identifier of the input socket we are tracing from
        """
        # Find the NodeGroupInput node in this tree
        group_input_node = None
        for node in node_tree.nodes:
            if node.bl_idname == "NodeGroupInput":
                group_input_node = node
                break
        
        if not group_input_node:
            return None

        # Find the specific output socket on the GroupInput node
        node_socket = None
        for out in group_input_node.outputs:
            if out.identifier == socket_identifier:
                node_socket = out
                break
        
        if not node_socket or not node_socket.is_linked:
            return None

        # Follow the link
        link = node_socket.links[0]
        target_node = link.to_node
        target_socket = link.to_socket

        # Case 1: Target is a Menu Switch
        if target_node.bl_idname == "GeometryNodeMenuSwitch":
            if len(target_node.enum_items) > 0:
                return target_node.enum_items[0].name
            return None

        # Case 2: Target is a Reroute node
        elif target_node.bl_idname == "NodeReroute":
            # Reroute only has one output (index 0), check if it's linked
            if target_node.outputs[0].is_linked:
                # Recursively follow from reroute output
                # We need to simulate this as if we are looking from the next node
                # But recursion logic here is based on "finding from input".
                # Actually, simpler to just follow the chain of nodes in the current tree first.
                # Let's handle reroutes by looping.
                pass 
                # Implementing full reroute support might be complex recursively, 
                # but standard socket tracing usually handles it.
                # Use a loop to resolve reroutes in current tree.

        # Case 3: Target is a Group Node (recursive case)
        elif target_node.bl_idname == 'GeometryNodeGroup':
            # We need to find which input socket of the group we are connected to
            # target_socket is the input socket on the group node instance
            
            # Find the index of this input socket
            socket_index = -1
            for i, inp in enumerate(target_node.inputs):
                if inp == target_socket:
                    socket_index = i
                    break
            
            if socket_index != -1 and target_node.node_tree:
                # Now go INSIDE the group
                # The input socket on the group node corresponds to an input in the inner tree interface
                inner_tree = target_node.node_tree
                
                # Get the identifier of the socket in the inner tree's interface
                # interface.items_tree contains the inputs
                # Note: inputs in interface are in order.
                # We need to match by index roughly, or better by name/identifier if possible.
                # Using index is standard for mapping group node inputs to interface.
                
                # Filter for input items in interface
                input_items = [item for item in inner_tree.interface.items_tree if item.item_type == 'SOCKET' and item.in_out == 'INPUT']
                
                if socket_index < len(input_items):
                    inner_socket_id = input_items[socket_index].identifier
                    # Recurse!
                    return self._find_first_menu_item(inner_tree, inner_socket_id)

        return None

    def sync_bundle_nodes(self):
        """Invoke bpy.ops.node.sockets_sync for bundle nodes that require it
        
        This handles post-creation sync for custom bundle nodes (NodeSeparateBundle, NodeCombineBundle)
        which may not update their sockets correctly until this operator is called.
        """
        import bpy
        
        # Check if operator exists first
        if not hasattr(bpy.ops.node, "sockets_sync"):
            return
            
        nodes_to_sync = []
        for node in self.builder.node_tree.nodes:
            # Check for bundle nodes by bl_idname
            if node.bl_idname in ("NodeSeparateBundle", "NodeCombineBundle"):
                 nodes_to_sync.append(node)
            elif "Bundle" in node.bl_idname and "Group" not in node.bl_idname:
                 nodes_to_sync.append(node)
                 
        if not nodes_to_sync:
            return
            
        logger.debug(f"Syncing {len(nodes_to_sync)} bundle node(s)...")

        # Find the Node Editor area to provide correct context
        context = bpy.context
        area = None
        region = None
        space = None
        window = context.window
        screen = context.screen
        
        # Try finding via window manager first
        if not area and context.window_manager and context.window_manager.windows:
            for w in context.window_manager.windows:
                for a in w.screen.areas:
                    if a.type == 'NODE_EDITOR':
                        window = w
                        screen = w.screen
                        area = a
                        break
                if area:
                    break
        
        # Fallback to current screen if available
        if not area and hasattr(context, 'screen') and context.screen:
             for a in context.screen.areas:
                 if a.type == 'NODE_EDITOR':
                     area = a
                     screen = context.screen
                     break

        # Setup space and region if area found
        if area:
            space = area.spaces.active
            # Ensure the space is viewing our node tree
            space.node_tree = self.builder.node_tree
            # Clear path to ensure we are at top level
            space.path.clear()
            
            for r in area.regions:
                if r.type == 'WINDOW':
                    region = r
                    break
        
        # Helper to run sync
        def run_sync(node, override_ctx=None):
            # Select and activate the node (crucial for some operators)
            try:
                # Deselect all first
                for n in self.builder.node_tree.nodes:
                    n.select = False
                
                node.select = True
                self.builder.node_tree.nodes.active = node
            except Exception as e:
                self.warning(f"  Could not select node {node.name}: {e}")

            # Try direct update functions first, as operator poll is strict
            success = False
            if hasattr(node, "socket_value_update"):
                try:
                    if override_ctx:
                         with context.temp_override(**override_ctx):
                             node.socket_value_update(context)
                             node.update()
                    else:
                         node.socket_value_update(context)
                         node.update()
                    logger.debug(f"  Called socket_value_update on {node.name}")
                    success = True
                except Exception as e:
                    self.warning(f"  Failed direct update on {node.name}: {e}")

            # Fallback to operator if needed
            if not success:
                try:
                    if override_ctx:
                        with context.temp_override(**override_ctx):
                            bpy.ops.node.sockets_sync(node_name=node.name)
                    else:
                        # Fallback (might fail in background/headless)
                        bpy.ops.node.sockets_sync(node_name=node.name)
                    logger.debug(f"  Synced {node.name} via operator")
                except Exception as e:
                    # Log warning but don't fail compilation
                     self.warning(f"  Failed to sync {node.name}: {e}")

        if area and region and space:
            # Construct override
            override = {
                'window': window,
                'screen': screen,
                'area': area,
                'region': region,
                'space_data': space,
            }
            if hasattr(context, 'active_object') and context.active_object:
                override['active_object'] = context.active_object
                override['object'] = context.active_object
            
            # Force a redraw to ensure context is fresh
            try:
                if hasattr(bpy.ops.wm, "redraw_timer"):
                    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            except:
                pass
                
            for node in nodes_to_sync:
                run_sync(node, override)
                
            # Redraw again
            try:
                if hasattr(bpy.ops.wm, "redraw_timer"):
                    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            except:
                pass
        else:
            self.warning("Could not find NODE_EDITOR area for context override. Bundle nodes might not sync correctly.")
            # Try without override just in case
            for node in nodes_to_sync:
                run_sync(node)

    def process_statement(self, tree):
        """Process a single statement based on its type"""
        # The AST has 'statement' nodes that wrap the actual statement types
        # We need to unwrap them
        if tree.data == "statement":
            # Unwrap and process the actual statement
            if tree.children:
                self.process_statement(tree.children[0])
            return

        # Log the statement being executed (INFO level) - show actual source line
        if hasattr(tree, "meta") and hasattr(tree.meta, "line") and self.source_lines:
            line_num = tree.meta.line
            # Get actual source line (line numbers are 1-indexed)
            if 0 < line_num <= len(self.source_lines):
                source_line = self.source_lines[line_num - 1]
                # Ensure it's a string (safety check)
                if isinstance(source_line, str):
                    source_line = source_line.strip()
                    # Only log non-empty lines (skip blank lines and comments)
                    if source_line and not source_line.startswith("#"):
                        # Pass group context if we're inside a group
                        logger.line(
                            source_line,
                            line_number=line_num,
                            group_context=self.current_group["name"]
                            if self.current_group
                            else None,
                        )
                else:
                    logger.debug(
                        f"Skipping non-string line at {line_num}: {type(source_line).__name__}"
                    )

        with self.location_context(tree):
            try:
                if tree.data == "input_decl":
                    self.input_decl(tree)
                elif tree.data == "output_decl":
                    self.output_decl(tree)
                elif tree.data == "assignment":
                    self.assignment(tree)
                elif tree.data == "frame_block":
                    self.frame_block(tree)
                elif tree.data == "python_block":
                    # Already executed in pass 1, skip in pass 2
                    pass
                elif tree.data == "group_def":
                    self.group_def(tree)
                elif tree.data == "function_call_statement":
                    # Process function call as a statement (result is discarded)
                    # This is for nodes with side effects like output_material(bsdf)
                    if tree.children:
                        self.evaluate_expression(tree.children[0])
                elif tree.data == "repeat":
                    self.repeat_zone(tree)
                elif tree.data == "foreach":
                    self.foreach(tree)
                elif tree.data == "simulation":
                    self.simulation_zone(tree)
                elif tree.data == "closure":
                    self.closure_zone(tree)
                elif tree.data in ("object_block", "object_block_implicit", "world_block", "scene_block"):
                    # Handled at __init__.py / sequential item level, not during compilation
                    pass
            except XFYCompileError:
                raise
            except Exception as e:
                info = self.get_ast_location_info(tree)
                raise XFYCompileError(
                    message=str(e),
                    filepath=info["file"],
                    line=info["line"],
                    column=info["column"],
                    snippet=info["snippet"],
                    original_error=e,
                ) from e

    def frame_block(self, tree):
        name_token = tree.children[0]
        frame_name = name_token.value
        if name_token.type == "STRING":
            frame_name = unescape_string(frame_name)

        frame = self.builder.create_frame(frame_name)
        self.frame_stack.append(frame)

        # Process children (statements inside frame)
        for child in tree.children[1:]:
            self.process_statement(child)

        self.frame_stack.pop()

    def python_block(self, tree):
        """Execute embedded Python code block (between triple backticks)"""
        logger.debug(f"DEBUG: python_block called with {len(tree.children)} children")
        # tree.children[0] is the PYTHON_BLOCK token containing the code
        if len(tree.children) >= 1:
            code_token = tree.children[0]
            code_content = (
                code_token.value if hasattr(code_token, "value") else str(code_token)
            )

            # Strip the triple backticks from start and end
            code_content = code_content.strip()
            if code_content.startswith("```"):
                code_content = code_content[3:]
            if code_content.endswith("```"):
                code_content = code_content[:-3]
            code_content = code_content.strip()

            if not code_content:
                print("⚠ Python block is empty after stripping backticks")
                return

            logger.debug(f"DEBUG: Executing Python code ({len(code_content)} chars)")
            logger.debug(f"DEBUG: First 100 chars: {code_content[:100]}")

            try:
                # Execute Python code with access to real bpy
                # No namespace tricks - just execute as normal Python
                import bpy

                namespace = {
                    "bpy": bpy,
                    "__builtins__": __builtins__,
                }
                exec(code_content, namespace)
                logger.success(
                    f"Executed Python code block ({len(code_content)} chars)"
                )
            except Exception as e:
                self.warning(f"Python code block execution failed: {e}")
                import traceback

                traceback.print_exc()
        else:
            logger.debug(f"DEBUG: python_block has no children!")

    def group_input(self, tree):
        """Handle group input declaration (similar to input_decl but for groups)"""
        # For now, delegate to input_decl
        # The grammar is slightly different but we can adapt
        self.input_decl(tree)

    def group_output(self, tree):
        """Handle group output declaration"""
        # Similar to output_decl
        self.output_decl(tree)

    def function_call(self, tree):
        """Override to prevent automatic visitor traversal of function calls.
        Function calls should only be processed via evaluate_expression."""
        pass

    def concat(self, tree):
        """Override to prevent automatic visitor traversal of concat expressions.
        Concatenation should only be processed via evaluate_expression."""
        pass

    def expression(self, tree):
        """Override to prevent automatic visitor traversal of expressions.
        Expressions should only be processed via evaluate_expression."""
        pass

    def term(self, tree):
        """Override to prevent automatic visitor traversal of terms.
        Terms should only be processed via evaluate_expression."""
        pass

    def primary(self, tree):
        """Override to prevent automatic visitor traversal of primary expressions.
        Primary expressions should only be processed via evaluate_expression."""
        pass

    def _ensure_socket_value(self, val, var_name=""):
        """Convert scalar constants into input nodes if needed for node linking."""
        if isinstance(val, bool):
            parent = self.frame_stack[-1] if self.frame_stack else None
            node = self.builder.create_node("input_bool", parent=parent, name=var_name)
            self.builder.set_property(node, "boolean", val)
            return (node, 0)
        elif isinstance(val, int):
            parent = self.frame_stack[-1] if self.frame_stack else None
            node = self.builder.create_node("input_int", parent=parent, name=var_name)
            self.builder.set_property(node, "integer", val)
            return (node, 0)
        elif isinstance(val, float):
            parent = self.frame_stack[-1] if self.frame_stack else None
            node = self.builder.create_node("value", parent=parent, name=var_name)
            self.builder.set_property(node, "outputs[0].default_value", val)
            return (node, 0)
        elif isinstance(val, str):
            parent = self.frame_stack[-1] if self.frame_stack else None
            node = self.builder.create_node("input_string", parent=parent, name=var_name)
            self.builder.set_property(node, "string", val)
            return (node, 0)
        elif isinstance(val, tuple) and len(val) in [2, 3, 4] and all(isinstance(v, (int, float)) for v in val):
            parent = self.frame_stack[-1] if self.frame_stack else None
            node = self.builder.create_node("input_vector", parent=parent, name=var_name)
            vec_value = list(val) + [0.0] * (3 - len(val))
            self.builder.set_property(node, "vector", vec_value[:3])
            return (node, 0)
        return val

    def _bind_output_variable(self, var_name, value):
        """Handle output connection and registration for an assigned variable."""
        if var_name == "_":
            return

        # Handle "output" as special keyword in groups / main tree
        # If assigning to "output" but "output" is not a declared output,
        # and we have other declared outputs, treat it as assigning to the first one
        actual_output_var = var_name
        if var_name == "output":
            if "output" not in self.outputs and len(self.outputs) > 0:
                actual_output_var = list(self.outputs.keys())[0]
                logger.debug(
                    f"Note: 'output' keyword maps to declared output '{actual_output_var}'"
                )

        # Auto-declare output variable if it's being assigned in main tree
        if actual_output_var == "output" and var_name not in self.outputs:
            logger.debug(f"Auto-declaring output variable '{var_name}'")
            self.outputs[var_name] = (self._get_default_socket_type(), value)

        # If this variable is declared as an output, connect it to Group Output
        if actual_output_var in self.outputs:
            output_info = self.outputs[actual_output_var]
            output_type = (
                output_info[0]
                if isinstance(output_info, tuple)
                else self._get_default_socket_type()
            )

            # Update the stored output value
            self.outputs[actual_output_var] = (output_type, value)

            # Ensure value is converted to a node output if it was a constant
            value = self._ensure_socket_value(value, actual_output_var)

            # Get or create Group Output node
            group_output = None
            for node in self.builder.node_tree.nodes:
                if node.bl_idname == "NodeGroupOutput":
                    group_output = node
                    break

            if not group_output:
                group_output = self.builder.node_tree.nodes.new("NodeGroupOutput")
                group_output.location = (400, 0)

            # Create output socket on the node tree interface
            tree_interface = self.builder.node_tree.interface

            output_socket_name = actual_output_var  # By default use variable name

            # Check if custom display name was specified for this output
            if hasattr(self, "output_socket_names") and actual_output_var in self.output_socket_names:
                output_socket_name = self.output_socket_names[actual_output_var]
            elif (
                hasattr(self, "current_group")
                and self.current_group
                and "outputs" in self.current_group
            ):
                for out_spec in self.current_group["outputs"]:
                    if out_spec["var_name"] == actual_output_var:
                        if "socket_name" in out_spec and out_spec["socket_name"]:
                            output_socket_name = out_spec["socket_name"]
                        break

            socket_exists = False
            for item in tree_interface.items_tree:
                if hasattr(item, "name") and item.name == output_socket_name:
                    socket_exists = True
                    break

            if not socket_exists:
                tree_interface.new_socket(
                    name=output_socket_name, in_out="OUTPUT", socket_type=output_type
                )

            # Now connect the value to the Group Output
            if isinstance(value, tuple) and len(value) == 2:
                from_node, from_socket = value
                output_socket_index = None
                for i, socket in enumerate(group_output.inputs):
                    if socket.name == output_socket_name:
                        output_socket_index = i
                        break

                if output_socket_index is not None:
                    self.builder.connect(
                        from_node, from_socket, group_output, output_socket_index
                    )

    def assignment(self, tree):
        left_side = tree.children[0]
        if hasattr(left_side, "value") and isinstance(left_side.value, str):
            self._current_assignment_target = left_side.value
        elif hasattr(left_side, "data") and left_side.data == "tuple_target":
            targets = []
            for child in left_side.children:
                if isinstance(child, Token):
                    targets.append(child.value)
                elif hasattr(child, "data") and child.data == "tuple_target_item":
                    targets.append(child.children[0].value)
                else:
                    targets.append(str(child))
            self._current_assignment_target = targets
        else:
            self._current_assignment_target = None

        value = self.evaluate_expression(tree.children[1])
        self._current_assignment_target = None

        # Debug comparisons
        if hasattr(left_side, "value") and "domain" in left_side.value:
            logger.debug(f"DEBUG assignment: {left_side.value} = {value}")

        assigned_pairs = []

        # Check if left side is a tuple unpacking
        if hasattr(left_side, "data") and left_side.data == "tuple_target":
            # Tuple unpacking: (a, b, c) = expr or (a: string, b: float) = expr
            var_names = []
            var_types = []
            for child in left_side.children:
                if isinstance(child, Token):
                    var_names.append(child.value)
                    var_types.append(None)
                elif hasattr(child, "data") and child.data == "tuple_target_item":
                    name = child.children[0].value
                    t = child.children[1].value.upper() if len(child.children) > 1 else None
                    if t in ("INT", "INTEGER"): t = "INT"
                    elif t in ("FLOAT", "VALUE"): t = "FLOAT"
                    elif t in ("BOOL", "BOOLEAN"): t = "BOOLEAN"
                    elif t in ("COLOR", "RGBA"): t = "RGBA"
                    elif t == "VECTOR": t = "VECTOR"
                    elif t == "STRING": t = "STRING"
                    elif t == "GEOMETRY": t = "GEOMETRY"
                    elif t in ("MAT", "MATERIAL"): t = "MATERIAL"
                    elif t == "OBJECT": t = "OBJECT"
                    elif t == "COLLECTION": t = "COLLECTION"
                    elif t == "ROTATION": t = "ROTATION"
                    elif t == "MATRIX": t = "MATRIX"
                    elif t == "CLOSURE": t = "CLOSURE"
                    elif t == "BUNDLE": t = "BUNDLE"
                    var_names.append(name)
                    var_types.append(t)
                else:
                    var_names.append(str(child))
                    var_types.append(None)

            # Check if value is already a collection of values/socket references (e.g. from multi-output closure)
            if isinstance(value, (tuple, list)) and any(isinstance(v, (tuple, list)) for v in value):
                assigned_pairs = list(zip(var_names, value))

            # Value should be a tuple (node, socket_index) for a multi-output node
            elif isinstance(value, tuple) and len(value) == 2 and hasattr(value[0], "outputs"):
                node, socket_idx = value
                # Extract all enabled non-CUSTOM outputs from this node
                # Special handling for NodeSeparateBundle unpacking
                if hasattr(node, "bl_idname") and node.bl_idname == "NodeSeparateBundle":
                    # Check how many non-virtual items we currently have
                    current_items = [item for item in node.outputs if item.identifier != "__extend__"]
                    
                    if len(current_items) < len(var_names):
                        # Helper to infer name and type from upstream node or annotations if available
                        def _get_upstream_bundle_info(idx):
                            bundle_in = node.inputs.get("Bundle") if hasattr(node, "inputs") else None
                            if bundle_in and bundle_in.links:
                                from_link = bundle_in.links[0]
                                up_node = from_link.from_node
                                from_sock = from_link.from_socket

                                # 2. Upstream node / group with bundle items (including nested bundles and GetBundleItem)
                                upstream_items = self._get_bundle_items_from_source(up_node, from_sock.name, expected_field_names=var_names)
                                if upstream_items and idx < len(upstream_items):
                                    item_name, item_type = upstream_items[idx]
                                    return item_name, item_type

                                # 3. Upstream GroupInput with bundle_signature
                                if getattr(up_node, "bl_idname", "") == "NodeGroupInput" and hasattr(self, "bundle_signatures"):
                                    sock_name = getattr(from_sock, "name", "")
                                    bsig = self.bundle_signatures.get(sock_name)
                                    if bsig and "fields" in bsig and idx < len(bsig["fields"]):
                                        fld = bsig["fields"][idx]
                                        fld_name = fld.get("name") or (var_names[idx] if idx < len(var_names) else f"Socket {idx+1}")
                                        return fld_name, fld["type"]

                            # 1. Explicit annotation or inferred type on tuple unpacking item
                            vname = var_names[idx] if idx < len(var_names) else f"Socket {idx+1}"
                            t = var_types[idx] if idx < len(var_types) and var_types[idx] else None
                            if not t:
                                if any(m in vname.lower() for m in ("mat", "material")):
                                    t = "MATERIAL"
                                elif any(s in vname.lower() for s in ("str", "string", "name", "path", "type")):
                                    t = "STRING"
                                elif any(v in vname.lower() for v in ("pos", "vec", "vector", "dir", "offset", "rot")):
                                    t = "VECTOR"
                                elif any(b in vname.lower() for b in ("bundle", "rings", "planets", "spaceobj")):
                                    t = "BUNDLE"
                                elif any(c in vname.lower() for c in ("closure", "fn", "func")):
                                    t = "CLOSURE"
                                else:
                                    t = "FLOAT"
                            return vname, t

                        needed = len(var_names) - len(current_items)
                        start_idx = len(current_items)
                        for i in range(needed):
                            var_idx = start_idx + i
                            item_name, item_type = _get_upstream_bundle_info(var_idx)
                            node.bundle_items.new(item_type, item_name)

                    if hasattr(node, "define_signature"):
                        node.define_signature = True
                
                enabled_outputs = [
                    (node, i)
                    for i, output in enumerate(node.outputs)
                    if output.enabled and output.type != "CUSTOM" and output.identifier != "__extend__"
                ]

                if len(enabled_outputs) < len(var_names):
                    raise ValueError(
                        f"Cannot unpack {len(enabled_outputs)} outputs into {len(var_names)} variables: {var_names}"
                    )
                elif len(enabled_outputs) > len(var_names):
                    self.warning(
                        f"Partial unpacking: {len(var_names)} variables for {len(enabled_outputs)} outputs (ignoring {len(enabled_outputs) - len(var_names)} trailing outputs)"
                    )
                    # Proceed with first N outputs
                    pass

                assigned_pairs = list(zip(var_names, enabled_outputs))
            elif isinstance(value, (tuple, list)):
                if len(value) < len(var_names):
                    raise ValueError(
                        f"Cannot unpack {len(value)} values into {len(var_names)} variables: {var_names}"
                    )
                assigned_pairs = list(zip(var_names, value))
            else:
                raise ValueError(
                    f"Cannot unpack value of type {type(value)} into tuple: {var_names}"
                )
        else:
            # Simple assignment: var = expr
            var_name = left_side.value
            value = self._ensure_socket_value(value, var_name)
            assigned_pairs = [(var_name, value)]

        for var_name, val in assigned_pairs:
            self.symbol_table[var_name] = val
            logger.debug(f"Assigned {var_name} = {val}")
            self._bind_output_variable(var_name, val)

    def evaluate_expression(self, tree):
        with self.location_context(tree):
            return self._evaluate_expression_impl(tree)

    def _evaluate_expression_impl(self, tree):
        from lark import Token, Tree

        if isinstance(tree, Token):
            if tree.type == "NUMBER":
                # Return raw numeric value (not a node)
                # This allows it to be used as a default value on sockets
                try:
                    return int(tree.value)
                except ValueError:
                    return float(tree.value)
            elif tree.type == "BOOL":
                return tree.value.lower() == "true"
            elif tree.type == "STRING":
                return unescape_string(tree.value)
            elif tree.type == "NAME":
                var_name = tree.value
                # Handle built-in constants (single source of truth from validation.py)
                if var_name in BUILTIN_CONSTANTS:
                    return BUILTIN_CONSTANTS[var_name]
                # Look up in symbol table
                if var_name not in self.symbol_table:
                    # Check if it's a group name - if so, instantiate it with no arguments
                    if var_name in self.groups:
                        # Auto-instantiate group with default arguments
                        logger.debug(
                            f"Auto-instantiating group '{var_name}' with no arguments"
                        )
                        # Create empty arguments node
                        empty_args = Tree("arguments", [])
                        return self.instantiate_group(var_name, empty_args, None)
                    # Use shared error message (single source of truth)
                    raise NameError(get_undefined_variable_error(var_name, self.symbol_table))
                return self.symbol_table[var_name]

        # With inline rules (?), these nodes may not exist anymore
        # Instead, we get direct structures like: add_sub -> [primary, "-", mul_div, "*", primary]

        if tree.data in (
            "add_sub",
            "mul_div",
            "power",
            "concat",
            "logical_or",
            "logical_xor",
            "logical_and",
            "logical_nand_nor",
            "comparison",
        ):
            # Handle binary operators with flattened structure
            # Children: [operand, op_token, operand, op_token, ...]
            # EXCEPT for concat which just has [operand, operand, operand, ...] with no tokens

            if len(tree.children) == 1:
                return self.evaluate_expression(tree.children[0])

            # Special handling for concat - it doesn't have operator tokens
            # Just collect all children into a list
            if tree.data == "concat":
                result = []
                for child in tree.children:
                    val = self.evaluate_expression(child)
                    # If val is already a list, extend; otherwise append
                    if isinstance(val, list):
                        result.extend(val)
                    else:
                        result.append(val)
                return result

            left = self.evaluate_expression(tree.children[0])
            i = 1
            while i < len(tree.children):
                if i + 1 >= len(tree.children):
                    break
                op_token = tree.children[i]
                # Extract operator value
                if isinstance(op_token, Token):
                    op = op_token.value
                elif isinstance(op_token, str):
                    # Direct string literal from grammar (e.g., "~")
                    op = op_token
                elif isinstance(op_token, Tree):
                    # This shouldn't happen with inline rules, but if it does,
                    # it means we got an operand instead of an operator
                    # For concat, assume ~ operator if we're in concat context
                    if tree.data == "concat":
                        op = "~"
                    else:
                        raise NotImplementedError(
                            f"Operator {op_token} not supported yet"
                        )
                else:
                    op = str(op_token)

                right = self.evaluate_expression(tree.children[i + 1])
                left = self.binary_op(op, left, right)
                i += 2
            return left

        elif tree.data == "expression":
            # expression may have comparison operators
            if len(tree.children) == 1:
                return self.evaluate_expression(tree.children[0])
            # Handle comparisons
            left = self.evaluate_expression(tree.children[0])
            i = 1
            while i < len(tree.children):
                if i + 1 >= len(tree.children):
                    break
                op_token = tree.children[i]
                if isinstance(op_token, Token):
                    op = op_token.value
                else:
                    op = str(op_token)
                right = self.evaluate_expression(tree.children[i + 1])
                left = self.binary_op(op, left, right)
                i += 2
            return left

        elif tree.data == "unary_op":
            # unary_op: (ADD_OP | SUB_OP | NOT_OP) unary
            op = tree.children[0].value  # Operator token
            operand = self.evaluate_expression(tree.children[1])
            if op == "-":
                # Handle unary minus
                if isinstance(operand, (int, float)):
                    return -operand
                # Create a multiply by -1 node
                return self.binary_op("*", -1, operand)
            elif op == "!":
                # Handle unary NOT (boolean negation)
                parent = self.frame_stack[-1] if self.frame_stack else None
                not_node = self.builder.create_node("boolean_math", parent=parent)
                not_node.operation = "NOT"

                # Connect the operand to the first input (Boolean input)
                self.connect_input(not_node, 0, operand)

                return (not_node, 0)  # Return node and output socket index
            else:
                # Unary plus - just return operand
                return operand

        elif tree.data == "ternary_op":
            # ternary_op: condition "?" true_val ":" false_val
            cond = self.evaluate_expression(tree.children[0])
            true_val = self.evaluate_expression(tree.children[1])
            false_val = self.evaluate_expression(tree.children[2])

            # Deduce input_type from operand types
            t_type = self.deduce_switch_type(true_val)
            f_type = self.deduce_switch_type(false_val)

            if t_type == f_type and t_type is not None:
                switch_type = t_type
            elif {t_type, f_type} == {"INT", "FLOAT"}:
                switch_type = "FLOAT"
            elif t_type is not None:
                switch_type = t_type
            elif f_type is not None:
                switch_type = f_type
            else:
                switch_type = "FLOAT"

            parent = self.frame_stack[-1] if self.frame_stack else None
            tree_type = getattr(self.builder.node_tree, "bl_idname", "GeometryNodeTree")
            if tree_type == "ShaderNodeTree":
                mix_type = "RGBA" if switch_type in ("RGBA", "COLOR") else ("VECTOR" if switch_type == "VECTOR" else "FLOAT")
                node = self.builder.create_node("mix", parent=parent)
                self.builder.set_property(node, "data_type", mix_type)
                self.connect_input(node, "Factor", cond)
                self.connect_input(node, "A", false_val)
                self.connect_input(node, "B", true_val)
                out_idx = next((i for i, s in enumerate(node.outputs) if getattr(s, "enabled", True)), 0)
                return (node, out_idx)

            node = self.builder.create_node("switch", parent=parent)
            self.builder.set_property(node, "input_type", switch_type)

            # Connect inputs: Switch, False, True
            self.connect_input(node, "Switch", cond)
            self.connect_input(node, "False", false_val)
            self.connect_input(node, "True", true_val)

            return (node, 0)

        elif tree.data == "closure":
            return self.closure_zone(tree)

        elif tree.data == "function_call":
            # Check if it's a py_function call
            func_name_node = tree.children[0]
            if isinstance(func_name_node, Tree) and func_name_node.data == "py_function":
                return self.evaluate_py_function_call(tree)
            return self.handle_function_call(tree)

        elif tree.data == "list":
            # list: "[" (expression ("," expression)*)? "]"
            values = []
            for child in tree.children:
                if child.data == "expression":
                    values.append(self.evaluate_expression(child))
            return values

        elif tree.data == "concat":
            # Handle concatenation - delegate to concat visitor
            return self.concat(tree)

        elif tree.data == "unary_minus":
            # Handle unary minus: -expr
            # For simple constants, return the raw negative value (not a node)
            # This allows it to be used as a default value on sockets
            child = tree.children[0]
            if isinstance(child, Token) and child.type == "NUMBER":
                # Return raw negative value
                try:
                    return -int(child.value)
                except ValueError:
                    return -float(child.value)
            else:
                # Complex expression - need to create Math node
                val = self.evaluate_expression(child)
                # If val is a raw number, return its negative
                if isinstance(val, (int, float)):
                    return -val
                # Otherwise create a multiply node with -1
                parent = self.frame_stack[-1] if self.frame_stack else None
                neg_one_node = self.builder.create_node("value", parent=parent)
                neg_one_node.outputs[0].default_value = -1.0
                return self.binary_op("*", (neg_one_node, 0), val)

        elif tree.data == "unary_plus":
            # Handle unary plus: +expr (just return the expression)
            return self.evaluate_expression(tree.children[0])

        elif tree.data == "py_access":
            # Handle py.varname - access Python namespace variable
            var_name = tree.children[0].value  # NAME token after "py."

            if var_name not in self.python_namespace:
                raise NameError(
                    f"Python variable 'py.{var_name}' not found. "
                    f"Define it in a ``` block before using it."
                )

            value = self.python_namespace[var_name]

            if callable(value):
                raise TypeError(
                    f"py.{var_name} is a function. "
                    f"Use py.{var_name}() to call it."
                )

            # Return primitive value - compiler treats as literal
            logger.debug(f"Resolved py.{var_name} = {value}")
            return value

        elif tree.data == "tuple_or_group":
            # Handle tuple expressions like (1, 0, 0) or grouped expressions like (a + b)
            # tuple_or_group: "(" expression ("," expression)* ")"

            if len(tree.children) == 1:
                # Single child - this is a grouped expression like (2 * x)
                # Evaluate and return it directly
                return self.evaluate_expression(tree.children[0])

            # Multiple children - this is a tuple like (1, 0, 0)
            # Check if all elements are numeric constants
            raw_values = []
            all_constants = True

            for child in tree.children:
                val = self.evaluate_expression(child)

                if isinstance(val, (int, float)):
                    raw_values.append(float(val))
                else:
                    all_constants = False
                    break

            # If all are numeric constants, return as raw tuple
            # The assignment handler will create appropriate constant nodes
            # When used as function args, connect_input will set as default values
            if all_constants and len(raw_values) in [2, 3, 4]:
                return tuple(raw_values)

            # For non-constant tuples, evaluate each element
            values = []
            for child in tree.children:
                val = self.evaluate_expression(child)
                values.append(val)

            # If any value is a node connection or variable, combine into vector/color node
            has_connections = any(
                (isinstance(v, tuple) and len(v) == 2 and hasattr(v[0], "bl_idname"))
                for v in values
            )
            if has_connections:
                parent = self.frame_stack[-1] if self.frame_stack else None
                if len(values) == 3:
                    combine_name = "combine_xyz"
                    combine_node = self.builder.create_node(combine_name, parent=parent)
                    for i, val in enumerate(values):
                        self.connect_input(combine_node, i, val)
                    return (combine_node, 0)
                elif len(values) == 4:
                    combine_name = "combine_color"
                    combine_node = self.builder.create_node(combine_name, parent=parent)
                    for i, val in enumerate(values):
                        self.connect_input(combine_node, i, val)
                    return (combine_node, 0)
                elif len(values) == 2:
                    combine_name = "combine_xy" if "combine_xy" in self.builder.registry.nodes else "combine_xyz"
                    combine_node = self.builder.create_node(combine_name, parent=parent)
                    for i, val in enumerate(values):
                        self.connect_input(combine_node, i, val)
                    return (combine_node, 0)

            return tuple(values)

        elif tree.data == "index_access":
            # Handle indexing like func()[0] or var[2]
            # Delegate to the index_access method
            return self.index_access(tree)

        elif tree.data == "attr_access":
            return self.attr_access(tree)

        elif tree.data == "constant_node":
            # Handle $-prefixed constants - create constant input nodes
            # $10 -> input_int, $10.5 -> value, $'text' -> input_string, $(1,2,3) -> combine_xyz
            child = tree.children[0]
            parent = self.frame_stack[-1] if self.frame_stack else None

            # Check if it's a tuple (vector constant)
            if hasattr(child, "data") and child.data == "tuple_or_group":
                # Evaluate the tuple to get raw values
                tuple_val = self.evaluate_expression(child)
                if isinstance(tuple_val, tuple) and len(tuple_val) in [2, 3, 4]:
                    # Create Combine XYZ node (lookup canonical name from bl_idname)
                    combine_xyz_name = self.builder.registry.get_canonical_name("ShaderNodeCombineXYZ")
                    combine_node = self.builder.create_node(
                        combine_xyz_name, parent=parent
                    )
                    for i, val in enumerate(tuple_val):
                        if i < 3:  # X, Y, Z
                            combine_node.inputs[i].default_value = float(val)
                    return (combine_node, 0)

            # Single value - determine type and create appropriate node
            from lark import Token

            if isinstance(child, Token):
                if child.type == "NUMBER":
                    # Check if it's an integer or float
                    try:
                        int_val = int(child.value)
                        if "." not in child.value:
                            # Integer
                            node = self.builder.create_node("input_int", parent=parent)
                            self.builder.set_property(node, "integer", int_val)
                            return (node, 0)
                    except ValueError:
                        pass
                    # Float
                    node = self.builder.create_node("value", parent=parent)
                    self.builder.set_property(
                        node, "outputs[0].default_value", float(child.value)
                    )
                    return (node, 0)
                elif child.type == "STRING":
                    # String constant
                    str_val = unescape_string(child.value)
                    node = self.builder.create_node("input_string", parent=parent)
                    self.builder.set_property(node, "string", str_val)
                    return (node, 0)
                elif child.type == "BOOL":
                    # Boolean constant
                    bool_val = child.value == "True"
                    node = self.builder.create_node("input_bool", parent=parent)
                    self.builder.set_property(node, "boolean", bool_val)
                    return (node, 0)

            # If we get here, it's an error
            raise ValueError(f"Unsupported constant node type: {child}")

        elif tree.data == "primary":
            # Handle primary expressions
            return self.evaluate_expression(tree.children[0])

        elif tree.data == "argument":
            # Handle argument nodes - unwrap to the expression inside
            if len(tree.children) > 0 and tree.children[0] is not None:
                return self.evaluate_expression(tree.children[0])
            # Empty argument
            return None

        return None

    def deduce_switch_type(self, val):
        """Deduce the switch input type enum string from operand value/node type."""
        import bpy

        # If it's a node output tuple: (node, socket_idx/socket_name)
        if isinstance(val, tuple) and len(val) == 2 and hasattr(val[0], "bl_idname"):
            node, socket_idx = val
            socket = None
            if isinstance(socket_idx, int):
                if socket_idx < len(node.outputs):
                    socket = node.outputs[socket_idx]
            elif isinstance(socket_idx, str):
                for s in node.outputs:
                    if s.name == socket_idx:
                        socket = s
                        break
            if socket:
                sock_type = socket.type
                mapping = {
                    "VALUE": "FLOAT",
                    "INT": "INT",
                    "BOOLEAN": "BOOLEAN",
                    "VECTOR": "VECTOR",
                    "RGBA": "RGBA",
                    "STRING": "STRING",
                    "SHADER": "SHADER",
                    "GEOMETRY": "GEOMETRY",
                    "MATERIAL": "MATERIAL",
                    "OBJECT": "OBJECT",
                    "COLLECTION": "COLLECTION",
                    "IMAGE": "IMAGE",
                    "TEXTURE": "TEXTURE",
                }
                if sock_type in mapping:
                    return mapping[sock_type]

        # If it's a raw Python value
        if isinstance(val, bool):
            return "BOOLEAN"
        # Since bool is a subclass of int, check bool first
        if isinstance(val, int):
            return "INT"
        if isinstance(val, float):
            return "FLOAT"
        if isinstance(val, str):
            return "STRING"
        if isinstance(val, (tuple, list)):
            if len(val) == 3:
                return "VECTOR"
            if len(val) == 4:
                return "RGBA"
        
        # Check for Blender type objects
        if hasattr(val, "rna_type"):
            rna_id = val.rna_type.identifier
            if rna_id == "Object":
                return "OBJECT"
            if rna_id == "Material":
                return "MATERIAL"
            if rna_id == "Collection":
                return "COLLECTION"
            if rna_id == "Image":
                return "IMAGE"

        return None

    def binary_op(self, op, left, right):
        """Create a binary operation node (Math, Vector Math, etc.)

        Args:
            op: The operator symbol (+, -, *, /, etc.)
            left: Left operand - can be (node, socket), raw value, or tuple
            right: Right operand - can be (node, socket), raw value, or tuple
        """
        # Comparison operators: Old XNodify uses different nodes for different comparisons:
        # - We now use the appropriate comparison node based on tree type for all comparisons
        tree_type = self.builder.node_tree.bl_idname
        compare_node = "math" if tree_type == "ShaderNodeTree" else "compare"

        # In ShaderNodeTree, math nodes lack native GREATER_EQUAL, LESS_EQUAL, and NOT_EQUAL.
        # Synthesize them using exact boolean arithmetic:
        # a >= b  <=>  1.0 - (a < b)
        # a <= b  <=>  1.0 - (a > b)
        # a != b  <=>  1.0 - (a == b)
        if tree_type == "ShaderNodeTree":
            if op == ">=":
                lt = self.binary_op("<", left, right)
                return self.binary_op("-", 1.0, lt)
            elif op == "<=":
                gt = self.binary_op(">", left, right)
                return self.binary_op("-", 1.0, gt)
            elif op == "!=":
                eq = self.binary_op("==", left, right)
                return self.binary_op("-", 1.0, eq)

        op_map = {
            "+": ("math", "ADD"),
            "-": ("math", "SUBTRACT"),
            "*": ("math", "MULTIPLY"),
            "/": ("math", "DIVIDE"),
            "%": ("math", "MODULO"),
            "**": ("math", "POWER"),
            # All comparisons use the context-aware compare_node
            ">": (compare_node, "GREATER_THAN"),
            "<": (compare_node, "LESS_THAN"),
            ">=": (compare_node, "GREATER_EQUAL"),
            "<=": (compare_node, "LESS_EQUAL"),
            "==": (compare_node, "COMPARE" if compare_node == "math" else "EQUAL"),
            "!=": (compare_node, "NOT_EQUAL"),
            # Boolean operators
            "&": ("boolean_math", "AND"),
            "|": ("boolean_math", "OR"),
            "^": ("boolean_math", "XOR"),
            "!&": ("boolean_math", "NAND"),
            "!|": ("boolean_math", "NOR"),
            "!^": ("boolean_math", "XNOR"),
            "=>": ("boolean_math", "IMPLY"),
            "!=>": ("boolean_math", "NIMPLY"),
        }

        # Handle concatenation operator ~
        if op == "~":
            # The ~ operator behaves differently based on type:
            # - For strings: use StringJoin node
            # - For geometries/nodes: create a list (for join_geometry etc.)

            # Check if we're dealing with strings or nodes
            left_is_string = isinstance(left, str)
            right_is_string = isinstance(right, str)
            left_is_node = (
                isinstance(left, tuple)
                and len(left) == 2
                and hasattr(left[0], "bl_idname")
            )
            right_is_node = (
                isinstance(right, tuple)
                and len(right) == 2
                and hasattr(right[0], "bl_idname")
            )

            # If both are strings, use string join
            if left_is_string and right_is_string:
                parent = self.frame_stack[-1] if self.frame_stack else None
                join_node = self.builder.create_node(
                    "GeometryNodeStringJoin", parent=parent
                )

                # Create string nodes for both operands
                str_node_left = self.builder.create_node(
                    "FunctionNodeInputString", parent=parent
                )
                str_node_left.string = str(left)
                self.builder.create_link(
                    str_node_left.outputs["String"], join_node.inputs["Strings"]
                )

                str_node_right = self.builder.create_node(
                    "FunctionNodeInputString", parent=parent
                )
                str_node_right.string = str(right)
                self.builder.create_link(
                    str_node_right.outputs["String"], join_node.inputs["Strings"]
                )

                return (join_node, "String")

            # Otherwise, treat as list concatenation (for geometries)
            # Convert left to list if it isn't already
            if isinstance(left, list):
                result = left
            else:
                result = [left]

            # Append right (or extend if it's a list)
            if isinstance(right, list):
                result.extend(right)
            else:
                result.append(right)

            return result

        # Type-aware operator selection for +, -, *, /
        # Detect if operands are vectors or scalars to choose between math and vector_math
        if op in ["+", "-", "*", "/"]:
            # Helper function to detect if value is a vector
            def is_vector(val):
                # Tuple of 2-4 numbers = vector constant
                if (
                    isinstance(val, tuple)
                    and len(val) in [2, 3, 4]
                    and all(isinstance(v, (int, float)) for v in val)
                ):
                    return True
                # Node output - check actual socket type
                if (
                    isinstance(val, tuple)
                    and len(val) == 2
                    and hasattr(val[0], "bl_idname")
                ):
                    node, socket_idx = val
                    # socket_idx can be either int (index) or str (name)
                    socket = None
                    if isinstance(socket_idx, int):
                        if socket_idx < len(node.outputs):
                            socket = node.outputs[socket_idx]
                    elif isinstance(socket_idx, str):
                        # Find socket by name
                        for s in node.outputs:
                            if s.name == socket_idx:
                                socket = s
                                break
                    if socket:
                        return socket.type in ["VECTOR", "RGBA"]
                return False

            def is_scalar(val):
                # Raw number = scalar
                if isinstance(val, (int, float)):
                    return True
                # Node output - check actual socket type
                if (
                    isinstance(val, tuple)
                    and len(val) == 2
                    and hasattr(val[0], "bl_idname")
                ):
                    node, socket_idx = val
                    # socket_idx can be either int (index) or str (name)
                    socket = None
                    if isinstance(socket_idx, int):
                        if socket_idx < len(node.outputs):
                            socket = node.outputs[socket_idx]
                    elif isinstance(socket_idx, str):
                        # Find socket by name
                        for s in node.outputs:
                            if s.name == socket_idx:
                                socket = s
                                break
                    if socket:
                        return socket.type in ["VALUE", "INT", "BOOLEAN"]
                return False

            left_is_vector = is_vector(left)
            right_is_vector = is_vector(right)
            left_is_scalar = is_scalar(left)
            right_is_scalar = is_scalar(right)
            
            # Determine node type based on operand types
            if left_is_vector or right_is_vector:
                # At least one operand is a vector -> use vector_math

                # Special case: vector * scalar or scalar * vector = SCALE operation
                if op == "*" and (
                    (left_is_vector and right_is_scalar)
                    or (left_is_scalar and right_is_vector)
                ):
                    parent = self.frame_stack[-1] if self.frame_stack else None
                    node = self.builder.create_node("vector_math", parent=parent)
                    self.builder.set_property(node, "operation", "SCALE")

                    # Ensure vector is first, scalar is second
                    if left_is_scalar:
                        left, right = right, left

                    # Connect vector to first input
                    self.connect_input(node, 0, left)
                    # Connect scalar to 'Scale' input
                    self.connect_input(node, "Scale", right)

                    return (node, 0)

                # Regular vector operations
                vector_op_map = {
                    "+": "ADD",
                    "-": "SUBTRACT",
                    "*": "MULTIPLY",
                    "/": "DIVIDE",
                }

                parent = self.frame_stack[-1] if self.frame_stack else None
                node = self.builder.create_node("vector_math", parent=parent)
                self.builder.set_property(node, "operation", vector_op_map[op])

                # Connect operands
                self.connect_input(node, 0, left)
                self.connect_input(node, 1, right)

                return (node, 0)

            # Both operands are scalars -> use regular math node
            # Fall through to existing op_map logic below

        if op not in op_map:
            raise NotImplementedError(f"Operator {op} not supported yet")

        # Detect operand types BEFORE creating the node
        # This is needed to set data_type on compare nodes before connecting
        left_socket_type = None
        right_socket_type = None

        if isinstance(left, tuple) and len(left) == 2 and hasattr(left[0], "bl_idname"):
            left_node, left_socket_idx = left
            if isinstance(left_socket_idx, int):
                if left_socket_idx < len(left_node.outputs):
                    left_socket_type = left_node.outputs[left_socket_idx].type
            elif isinstance(left_socket_idx, str):
                for s in left_node.outputs:
                    if s.name == left_socket_idx:
                        left_socket_type = s.type
                        break

        if (
            isinstance(right, tuple)
            and len(right) == 2
            and hasattr(right[0], "bl_idname")
        ):
            right_node, right_socket_idx = right
            if isinstance(right_socket_idx, int):
                if right_socket_idx < len(right_node.outputs):
                    right_socket_type = right_node.outputs[right_socket_idx].type
            elif isinstance(right_socket_idx, str):
                for s in right_node.outputs:
                    if s.name == right_socket_idx:
                        right_socket_type = s.type
                        break

        # Create the node
        node_type, operation = op_map[op]
        parent = self.frame_stack[-1] if self.frame_stack else None
        node = self.builder.create_node(node_type, parent=parent)
        self.builder.set_property(node, "operation", operation)

        if node_type == "math" and operation == "COMPARE":
            # Set Epsilon (input index 2) to 0.0 for exact comparison
            if len(node.inputs) > 2:
                node.inputs[2].default_value = 0.0

        # For compare nodes, set data_type BEFORE making connections
        # Changing data_type after connections may break them
        if node_type == "compare":
            # Map socket types to compare data_type
            socket_to_compare_type = {
                "VALUE": "FLOAT",
                "INT": "INT",
                "BOOLEAN": "INT",  # Compare nodes don't support BOOLEAN natively, cast to INT (0 and 1)
                "VECTOR": "VECTOR",
                "STRING": "STRING",
                "RGBA": "RGBA",
            }

            # If operand is a literal constant, infer socket type from Python type
            if left_socket_type is None:
                if isinstance(left, bool):
                    left_socket_type = "BOOLEAN"
                elif isinstance(left, int):
                    left_socket_type = "INT"
                elif isinstance(left, float):
                    left_socket_type = "VALUE"
                elif isinstance(left, str):
                    left_socket_type = "STRING"
                elif isinstance(left, (tuple, list)):
                    if len(left) == 4:
                        left_socket_type = "RGBA"
                    elif len(left) in (2, 3):
                        left_socket_type = "VECTOR"

            if right_socket_type is None:
                if isinstance(right, bool):
                    right_socket_type = "BOOLEAN"
                elif isinstance(right, int):
                    right_socket_type = "INT"
                elif isinstance(right, float):
                    right_socket_type = "VALUE"
                elif isinstance(right, str):
                    right_socket_type = "STRING"
                elif isinstance(right, (tuple, list)):
                    if len(right) == 4:
                        right_socket_type = "RGBA"
                    elif len(right) in (2, 3):
                        right_socket_type = "VECTOR"

            # Determine compare data_type from operand types
            # Handle mixed INT/VALUE comparisons: prefer FLOAT
            # (Math nodes always output VALUE, so comparing INT with math result needs FLOAT mode)
            compare_data_type = None
            left_compare_type = (
                socket_to_compare_type.get(left_socket_type)
                if left_socket_type
                else None
            )
            right_compare_type = (
                socket_to_compare_type.get(right_socket_type)
                if right_socket_type
                else None
            )

            if left_compare_type and right_compare_type:
                # Both types available - handle mixed types
                if left_compare_type == right_compare_type:
                    # Same type - use it
                    compare_data_type = left_compare_type
                elif {left_compare_type, right_compare_type} == {"INT", "FLOAT"}:
                    # Mixed INT/FLOAT - use FLOAT for compatibility
                    compare_data_type = "FLOAT"
                else:
                    # Other mixed types - use left
                    compare_data_type = left_compare_type
            elif left_compare_type:
                compare_data_type = left_compare_type
            elif right_compare_type:
                compare_data_type = right_compare_type

            if compare_data_type:
                # Blender FunctionNodeCompare only supports EQUAL and NOT_EQUAL for STRING
                if compare_data_type == "STRING" and operation not in ("EQUAL", "NOT_EQUAL"):
                    raise ValueError(
                        f"String comparison in Geometry Nodes only supports '==' and '!=', not '{op}'"
                    )
                # RGBA only supports EQUAL, NOT_EQUAL, BRIGHTER, DARKER
                if compare_data_type == "RGBA" and operation not in ("EQUAL", "NOT_EQUAL", "BRIGHTER", "DARKER"):
                    raise ValueError(
                        f"Color comparison in Geometry Nodes only supports '==' and '!=', not '{op}'"
                    )

                self.builder.set_property(node, "data_type", compare_data_type)
                # For string comparison, also set mode to ELEMENT
                if compare_data_type == "STRING":
                    self.builder.set_property(node, "mode", "ELEMENT")

        # Find the enabled input sockets for this node
        # For Compare nodes, different data_types use different socket indices
        # FLOAT: 0-1, INT: 2-3, VECTOR: 4-5, RGBA: 6-7, STRING: 8-9, etc.
        enabled_inputs = [i for i, inp in enumerate(node.inputs) if inp.enabled]

        # Use the first two enabled inputs for A and B
        input_a_idx = enabled_inputs[0] if len(enabled_inputs) > 0 else 0
        input_b_idx = enabled_inputs[1] if len(enabled_inputs) > 1 else 1

        # Handle left operand
        # If it's a raw value (int/float), set as default; if node connection, connect
        if isinstance(left, (int, float)):
            # Set as default value - check socket type to use correct conversion
            socket_a = node.inputs[input_a_idx]
            if socket_a.type == "INT":
                socket_a.default_value = int(left)
            elif socket_a.type == "VECTOR":
                socket_a.default_value = (float(left), float(left), float(left))
            elif socket_a.type == "RGBA":
                socket_a.default_value = (float(left), float(left), float(left), 1.0)
            else:
                socket_a.default_value = float(left)
        elif (
            isinstance(left, tuple) and len(left) == 2 and hasattr(left[0], "bl_idname")
        ):
            # It's a (node, socket) connection
            self.connect_input(node, input_a_idx, left)
        else:
            # Could be a vector tuple or other value - let connect_input handle it
            self.connect_input(node, input_a_idx, left)

        # Handle right operand
        if isinstance(right, (int, float)):
            # Set as default value - check socket type to use correct conversion
            socket_b = node.inputs[input_b_idx]
            if socket_b.type == "INT":
                socket_b.default_value = int(right)
            elif socket_b.type == "VECTOR":
                socket_b.default_value = (float(right), float(right), float(right))
            elif socket_b.type == "RGBA":
                socket_b.default_value = (float(right), float(right), float(right), 1.0)
            else:
                socket_b.default_value = float(right)
        elif (
            isinstance(right, tuple)
            and len(right) == 2
            and hasattr(right[0], "bl_idname")
        ):
            # It's a (node, socket) connection
            self.connect_input(node, input_b_idx, right)
        else:
            # Could be a vector tuple or other value - let connect_input handle it
            self.connect_input(node, input_b_idx, right)

        return (node, 0)  # Output is at index 0

    def create_dynamic_socket(self, node, socket_obj, value, socket_label=None):
        """Create dynamic sockets for nodes that support them (capture_attribute, etc.)

        Args:
            node: The target node
            socket_obj: The socket object (may be virtual)
            value: The value to be connected (used to determine socket type)
            socket_label: Optional label for the dynamic socket item

        Returns:
            The actual socket to use (either the original or newly created one)
        """
        # Check if this is a virtual socket that needs to be created
        if (
            hasattr(socket_obj, "bl_idname")
            and socket_obj.bl_idname == "NodeSocketVirtual"
        ):
            # Socket type mapping from Python types and node socket types
            socket_type_map = {
                bool: ("BOOLEAN", "Boolean"),
                int: ("INT", "Integer"),
                float: ("FLOAT", "Float"),
                str: ("STRING", "String"),
                tuple: ("VECTOR", "Vector"),  # For vector tuples
            }

            # Determine socket type based on value
            socket_type = None
            socket_name = "Value"

            if isinstance(value, tuple) and len(value) == 2:
                # It's a connection (node, socket)
                from_node, from_socket_idx = value
                if hasattr(from_node, "outputs"):
                    from_socket = from_node.outputs[from_socket_idx] if isinstance(from_socket_idx, int) and from_socket_idx < len(from_node.outputs) else self.builder._get_socket(from_node.outputs, from_socket_idx)
                    if from_socket:
                        from socket_types import get_bundle_type, DYNAMIC_SOCKET_TYPE_MAP
                        from_id = getattr(from_socket, "bl_idname", "")
                        from_type = getattr(from_socket, "type", "")
                        
                        bundle_type = get_bundle_type(from_id)
                        if bundle_type:
                            socket_type = (bundle_type, from_socket.name or "Item")
                        elif from_id in DYNAMIC_SOCKET_TYPE_MAP:
                            socket_type = DYNAMIC_SOCKET_TYPE_MAP[from_id]
                        elif from_type in DYNAMIC_SOCKET_TYPE_MAP:
                            socket_type = DYNAMIC_SOCKET_TYPE_MAP[from_type]
                        else:
                            # Map Blender socket types
                            blender_type_map = {
                                "VALUE": ("FLOAT", "Float"),
                                "INT": ("INT", "Integer"),
                                "BOOLEAN": ("BOOLEAN", "Boolean"),
                                "VECTOR": ("VECTOR", "Vector"),
                                "STRING": ("STRING", "String"),
                                "RGBA": ("RGBA", "Color"),
                                "GEOMETRY": ("GEOMETRY", "Geometry"),
                                "ROTATION": ("ROTATION", "Rotation"),
                                "MATRIX": ("MATRIX", "Matrix"),
                                "MATERIAL": ("MATERIAL", "Material"),
                                "OBJECT": ("OBJECT", "Object"),
                                "COLLECTION": ("COLLECTION", "Collection"),
                                "IMAGE": ("IMAGE", "Image"),
                                "BUNDLE": ("BUNDLE", "Bundle"),
                                "CUSTOM": ("BUNDLE" if "Bundle" in from_id else "FLOAT", "Custom"),
                            }
                            socket_type = blender_type_map.get(
                                from_type, ("FLOAT", "Float")
                            )
            else:
                # It's a constant value - determine type from Python type
                if isinstance(value, bool):
                    socket_type = ("BOOLEAN", "Boolean")
                elif isinstance(value, int):
                    socket_type = ("INT", "Integer")
                elif isinstance(value, float):
                    socket_type = ("FLOAT", "Float")
                elif isinstance(value, str):
                    socket_type = ("STRING", "String")
                elif isinstance(value, (tuple, list)):
                    if len(value) == 4:
                        socket_type = ("RGBA", "Color")
                    elif len(value) == 16:
                        socket_type = ("MATRIX", "Matrix")
                    else:
                        socket_type = ("VECTOR", "Vector")
                else:
                    socket_type = ("FLOAT", "Float")

            # Create the dynamic socket based on node type
            if hasattr(node, "bl_idname"):
                if node.bl_idname in ("GeometryNodeCaptureAttribute", "GeometryNodeFieldToGrid") and socket_type:
                    # Create new capture/grid item
                    type_name, default_name = socket_type
                    if node.bl_idname == "GeometryNodeFieldToGrid":
                        node.grid_items.new(type_name, default_name)
                    else:
                        node.capture_items.new(type_name, default_name)
                    # The new socket is at index -2 (before the virtual socket)
                    return node.inputs[-2]
                elif node.bl_idname == "GeometryNodeFieldToList" and socket_type:
                    type_name, default_name = socket_type
                    valid_field_types = {'FLOAT', 'INT', 'BOOLEAN', 'VECTOR', 'RGBA', 'ROTATION', 'MATRIX', 'STRING', 'MENU'}
                    if type_name not in valid_field_types:
                        type_name = 'FLOAT'
                    item_count = len(node.list_items) + 1
                    node.list_items.new(type_name, f"Field {item_count}")
                    # The new socket is at index -2 (before the virtual socket)
                    return node.inputs[-2]
                elif node.bl_idname in ("NodeClosureOutput", "NodeEvaluateClosure") and socket_type:
                    type_name, default_name = socket_type
                    if node.bl_idname == "NodeClosureOutput":
                        item_count = len(node.output_items) + 1
                        node.output_items.new(type_name, f"{default_name} {item_count}")
                    else:
                        item_count = len(node.input_items) + 1
                        node.input_items.new(type_name, f"{default_name} {item_count}")
                    # The new socket is at index -2 (before the virtual socket)
                    return node.inputs[-2]
                elif node.bl_idname == "GeometryNodeMenuSwitch" and socket_type:
                    # Create new menu item
                    node.enum_items.new("item")
                    # The new socket is at index -2 (before the virtual socket)
                    return node.inputs[-2]
                elif node.bl_idname == "NodeCombineBundle" and socket_type:
                    type_name, default_name = socket_type
                    name_to_use = socket_label or default_name or f"Item {len(node.bundle_items) + 1}"
                    if name_to_use.lower() == "type":
                        name_to_use = "Type"
                    node.bundle_items.new(type_name, name_to_use)
                    if hasattr(node, "define_signature"):
                        node.define_signature = True
                    return node.inputs[-2]
                # Add other dynamic socket nodes here as needed

        return socket_obj

    def connect_input(self, node, socket_or_name, value, socket_label=None):
        """Connect or set value for an input socket.

        Args:
            node: The target node
            socket_or_name: Either a socket object, socket name (string), or socket index (int)
            value: The value to connect/set
            socket_label: Optional label for menu switch enum items or dynamic bundle items
        """
        # Get the socket name for logging and default value setting
        if hasattr(socket_or_name, "name"):
            # It's a socket object
            socket_name = socket_or_name.name
            socket_obj = socket_or_name
            # Check if we need to create a dynamic socket
            socket_obj = self.create_dynamic_socket(node, socket_obj, value, socket_label=socket_label)
            # Update socket_name in case it changed
            if hasattr(socket_obj, "name"):
                socket_name = socket_obj.name
        elif isinstance(socket_or_name, int):
            # It's a socket index
            socket_name = f"input[{socket_or_name}]"  # For logging
            socket_obj = (
                node.inputs[socket_or_name]
                if socket_or_name < len(node.inputs)
                else None
            )

            # Special case for dynamic nodes: if socket not found, we might need to create it via builder
            # But connect_input assumes we have a socket object for create_dynamic_socket call below.
            # If socket_obj is None, we check if node supports dynamic sockets via builder.
            dynamic_nodes = [
                "NodeCombineBundle",
                "GeometryNodeIndexSwitch",
                "GeometryNodeFieldToList",
                "NodeClosureOutput",
                "NodeEvaluateClosure",
                "GeometryNodeClosureToList",
            ]
            if socket_obj is None and hasattr(node, "bl_idname") and node.bl_idname in dynamic_nodes:
                 # Pass the index directly to builder.connect later
                 pass
            if socket_obj:
                socket_obj = self.create_dynamic_socket(node, socket_obj, value)
                # Update socket_name in case it changed
                if hasattr(socket_obj, "name"):
                    socket_name = socket_obj.name
        else:
            # It's a socket name (string)
            socket_name = socket_or_name
            socket_obj = self.builder._get_socket(node.inputs, socket_or_name) if hasattr(node, "inputs") else None
            if socket_obj:
                socket_obj = self.create_dynamic_socket(node, socket_obj, value, socket_label=socket_label)
                if hasattr(socket_obj, "name"):
                    socket_name = getattr(socket_obj, "label", None) or socket_obj.name

        # Check if value is a connection (node, socket) tuple
        # vs a vector value tuple like (1.0, 0.0) or (1.0, 0.0, 0.0)
        is_connection = False
        if isinstance(value, tuple) and len(value) == 2:
            # Check if first element looks like a node
            # Nodes have 'bl_idname' attribute, numbers don't
            if hasattr(value[0], "bl_idname"):
                is_connection = True

        if is_connection:
            # Single connection: (from_node, from_socket_index)
            from_node, from_socket = value
            # Pass socket object if we have it, otherwise pass name/index
            self.builder.connect(
                from_node,
                from_socket,
                node,
                socket_obj if socket_obj else socket_or_name,
            )
        elif isinstance(value, list):
            # Multiple connections (from concatenation operator)
            # Connect each item in the list to the same input socket
            # IMPORTANT: Reverse the list because Blender appears to store variadic input links in reverse order
            # (This matches the behavior of legacy xnodify2 - see xnodify2/main.py:120)
            for item in reversed(value):
                if isinstance(item, tuple) and len(item) == 2:
                    from_node, from_socket = item
                    self.builder.connect(
                        from_node,
                        from_socket,
                        node,
                        socket_obj if socket_obj else socket_or_name,
                    )
        elif value is not None:
            # Handle constants - set as default value on the socket generically
            node_name = (
                node.get("name")
                if isinstance(node, dict)
                else getattr(node, "name", "unknown")
            )
            logger.debug(
                f"Setting default value for {node_name}.{socket_name} to {value}"
            )

            # If socket object was not found yet, try lookup by name
            if socket_obj is None and hasattr(node, "inputs") and isinstance(socket_or_name, str):
                socket_obj = self.builder._get_socket(node.inputs, socket_or_name)

            # Special case for NodeCombineBundle with literal values on new dynamic sockets
            if socket_obj is None and getattr(node, "bl_idname", None) == "NodeCombineBundle" and isinstance(socket_or_name, str) and hasattr(node, "bundle_items"):
                try:
                    if isinstance(value, bool):
                        type_enum = "BOOLEAN"
                    elif isinstance(value, int):
                        type_enum = "INT"
                    elif isinstance(value, float):
                        type_enum = "FLOAT"
                    elif isinstance(value, str):
                        type_enum = "STRING"
                    elif isinstance(value, (tuple, list)):
                        type_enum = "RGBA" if len(value) == 4 else "VECTOR"
                    else:
                        type_enum = "FLOAT"
                    name_to_use = "Type" if socket_or_name.lower() == "type" else socket_or_name
                    node.bundle_items.new(type_enum, name_to_use)
                    if hasattr(node, "define_signature"):
                        node.define_signature = True
                    socket_obj = self.builder._get_socket(node.inputs, name_to_use)
                except Exception as e:
                    self.warning(f"Failed to create bundle item '{socket_or_name}': {e}")

            if socket_obj:
                # For virtual sockets, attempt to instantiate them first
                if getattr(socket_obj, "bl_idname", None) == "NodeSocketVirtual":
                    socket_index = next((i for i, s in enumerate(node.inputs) if s == socket_obj), -1)
                    if socket_index != -1:
                        socket_obj = self.builder._create_virtual_socket(node, socket_index, None)

                if socket_obj and getattr(socket_obj, "bl_idname", None) != "NodeSocketVirtual":
                    self.builder._set_socket_value(socket_obj, value, socket_label=socket_label, node=node)
            elif isinstance(socket_or_name, str):
                # Fallback to generic property setter
                self.builder.set_property(node, socket_or_name, value)

    def evaluate_py_function_call(self, tree):
        """Handle py.func() calls

        Args:
            tree: function_call tree with py_function as first child

        Returns:
            Primitive value returned by Python function
        """
        from lark import Tree

        # Extract function name
        py_func_node = tree.children[0]  # py_function node
        func_name = py_func_node.children[0].value  # NAME token

        # Look up function
        if func_name not in self.python_namespace:
            raise NameError(
                f"Python function 'py.{func_name}' not found. "
                f"Define it in a ``` block."
            )

        func = self.python_namespace[func_name]

        if not callable(func):
            raise TypeError(
                f"py.{func_name} is not a function (it's {type(func).__name__}). "
                f"Use py.{func_name} without () to access the value."
            )

        # Evaluate arguments
        args_node = None
        attributes = None

        # Parse function_call children: [py_function, optional attributes, optional arguments]
        for child in tree.children[1:]:
            if isinstance(child, Tree):
                if child.data == "attributes":
                    attributes = child
                elif child.data == "arguments":
                    args_node = child

        # Evaluate arguments to primitives
        primitive_args = []
        if args_node:
            for arg in args_node.children:
                if arg is None:  # Empty argument (from empty parens or trailing comma)
                    continue  # Skip entirely - don't add to primitive_args
                else:
                    arg_value = self.evaluate_expression(arg)
                    if arg_value is None:  # Empty argument node with no children
                        continue  # Skip entirely
                    # Convert to primitive
                    try:
                        primitive_args.append(to_primitive(arg_value))
                    except TypeError as e:
                        self.error(f"Argument evaluation failed: arg_value={arg_value}, type={type(arg_value)}")
                        raise TypeError(
                            f"Argument to py.{func_name}() must be a literal or py.* value: {e}"
                        )

        # Call Python function
        logger.debug(f"Calling py.{func_name}({primitive_args})")

        try:
            result = func(*primitive_args)
        except Exception as e:
            self.error(f"Python function py.{func_name}() failed: {e}")
            import traceback
            traceback.print_exc()
            raise RuntimeError(
                f"Python function py.{func_name}() failed: {e}"
            )

        # Validate return type
        if not is_primitive(result):
            raise TypeError(
                f"Python function py.{func_name}() returned {type(result).__name__}. "
                f"Must return int, float, bool, str, tuple, or list."
            )

        logger.debug(f"py.{func_name}() returned {result}")
        return result

    def handle_function_call(self, tree):
        # Function name can be NAME or STRING (for group references by display name)
        func_name_token = tree.children[0]
        func_name = func_name_token.value

        # If it's a STRING token, remove the quotes
        if func_name_token.type == "STRING":
            func_name = unescape_string(func_name)

        args_node = None
        attrs_node = None

        for child in tree.children[1:]:
            if isinstance(child, Tree):
                if child.data == "arguments":
                    args_node = child
                elif child.data == "attributes":
                    attrs_node = child

        # Check if calling a closure variable: my_closure(arg1, arg2)
        if func_name in self.symbol_table:
            val = self.symbol_table[func_name]
            if isinstance(val, tuple) and len(val) == 2:
                c_node, c_sock = val
                is_closure = (
                    getattr(c_node, "bl_idname", "") == "NodeClosureOutput"
                    or c_sock == "Closure"
                    or func_name in self.closure_signatures
                )
                if not is_closure and hasattr(c_node, "outputs"):
                    sock = None
                    if isinstance(c_sock, int) and c_sock < len(c_node.outputs):
                        sock = c_node.outputs[c_sock]
                    elif isinstance(c_sock, str) and c_sock in c_node.outputs:
                        sock = c_node.outputs[c_sock]
                    if sock and getattr(sock, "bl_socket_idname", "") == "NodeSocketClosure":
                        is_closure = True

                if is_closure:
                    closure_sig = self.closure_signatures.get(func_name)
                    return self.evaluate_closure_call(val, args_node, attrs_node, closure_sig=closure_sig)

        # Check if calling evaluate_closure: evaluate_closure(closure, arg1, arg2)
        if func_name == "evaluate_closure" and args_node and args_node.children:
            first_arg = args_node.children[0]
            closure_name = None
            if hasattr(first_arg, "children") and first_arg.children:
                curr = first_arg
                while hasattr(curr, "children") and curr.children:
                    if isinstance(curr.children[0], Token) and curr.children[0].type == "NAME":
                        closure_name = curr.children[0].value
                        break
                    curr = curr.children[0]
            closure_sig = self.closure_signatures.get(closure_name) if closure_name else None
            closure_val = self.evaluate_expression(first_arg)
            remaining_args = Tree("arguments", args_node.children[1:])
            return self.evaluate_closure_call(closure_val, remaining_args, attrs_node, closure_sig=closure_sig)

        # Check if this is a group call (by identifier or display name)
        group_id = None
        if func_name in self.groups:
            group_id = func_name
        else:
            # Try to find by display name
            for gid, ginfo in self.groups.items():
                if ginfo.get("display_name") == func_name:
                    group_id = gid
                    break

        if group_id:
            return self.instantiate_group(group_id, args_node, attrs_node)

        # Check if it's a group created by Python blocks (in bpy.data.node_groups)
        # This allows wrapper scripts to use groups created by run_geo_script_file_v2()
        import bpy

        if func_name in bpy.data.node_groups:
            logger.debug(f"Found group '{func_name}' in bpy.data.node_groups")
            group_tree = bpy.data.node_groups[func_name]

            # Import metadata so we can use standard instantiate_group logic
            self._import_group_info(func_name, group_tree)

            # Now instantiate using the imported info
            return self.instantiate_group(func_name, args_node, attrs_node)
        else:
            logger.debug(f"Group NOT found in bpy.data.node_groups")

            # Try to load as built-in asset (lazy loading)
            from asset_loader import try_load_asset_if_needed
            asset_node_group = try_load_asset_if_needed(func_name)

            if asset_node_group:
                # Asset was loaded successfully - import and instantiate
                logger.debug(f"Loaded built-in asset '{func_name}'")
                self._import_group_info(func_name, asset_node_group)
                return self.instantiate_group(func_name, args_node, attrs_node)

            logger.debug(f"Available groups: {list(bpy.data.node_groups.keys())}")

        # Parse existing attributes if any
        # Parse existing attributes if any
        # For most nodes, attributes are unique (stored in dict)
        # For ColorRamp and Curves, we need to preserve duplicate 'remove'/'add' operations in order
        existing_attrs = {}
        dynamic_element_attrs = []  # List of (name, value) tuples for ColorRamp and Curve nodes
        if attrs_node:
            # Use the common parse_attributes helper, but handle ColorRamp and Curves specially
            for attr in attrs_node.children:
                attr_name = attr.children[0].value
                attr_val_node = attr.children[1]
                attr_val = self.evaluate_value_node(attr_val_node)

                # For ColorRamp and Curve operations, preserve all in order
                if attr_name in ("remove", "add"):
                    dynamic_element_attrs.append((attr_name, attr_val))
                    # Don't add to existing_attrs to avoid overwriting
                else:
                    existing_attrs[attr_name] = attr_val

        # Bundle Operations
        if func_name == "combine_bundle":
            # Map to NodeCombineBundle
            expanded_name = "NodeCombineBundle"
            merged_attrs = {}
        elif func_name == "separate_bundle":
            # Map to NodeSeparateBundle
            expanded_name = "NodeSeparateBundle"
            merged_attrs = {}
        elif func_name == "join_bundle":
            # Map to NodeJoinBundle
            expanded_name = "NodeJoinBundle"
            merged_attrs = {}
        else:
            # Expand function shortcuts (e.g., sin -> math{operation:'SINE'}, eq -> compare{operation:'EQUAL'})
            # This function needs to be defined or imported elsewhere, e.g., from a 'shortcuts' module
            expanded_name, merged_attrs = expand_function_shortcut(
                func_name, existing_attrs
            )

        # Handle 'compare' contextually:
        # - ShaderNodeTree: FunctionNodeCompare doesn't exist; use ShaderNodeMath ('math')
        # - GeometryNodeTree: use 'compare' which maps to FunctionNodeCompare, defaulting operation to EQUAL
        tree_type = self.builder.node_tree.bl_idname
        if expanded_name == "compare":
            if tree_type == "ShaderNodeTree":
                expanded_name = "math"
                # ShaderNodeMath only operates on floats and has no data_type property
                merged_attrs.pop("data_type", None)
                op = merged_attrs.get("operation")
                if not op or op == "EQUAL":
                    merged_attrs["operation"] = "COMPARE"
            else:
                op = merged_attrs.get("operation")
                if not op or op == "COMPARE":
                    merged_attrs["operation"] = "EQUAL"

        # Check if the expanded name is a known asset group and load it if needed
        from asset_loader import try_load_asset_if_needed
        asset_node_group = try_load_asset_if_needed(expanded_name)
        if asset_node_group:
            logger.debug(f"Loaded built-in asset '{expanded_name}' for shortcut '{func_name}'")
            self._import_group_info(expanded_name, asset_node_group)
            return self.instantiate_group(expanded_name, args_node, attrs_node)

        # Regular node creation
        parent = self.frame_stack[-1] if self.frame_stack else None
        node = self.builder.create_node(expanded_name, parent=parent)

        # Pop curve points attribute if present to avoid generic set_property warning
        points_attr = None
        if hasattr(node, "mapping") and hasattr(node.mapping, "curves"):
            points_attr = merged_attrs.pop("points", None)

        # Apply merged attributes (from shortcut defaults + user overrides)
        # Ensure file_path/image/font are set first so sub-objects exist
        sorted_attrs = sorted(
            merged_attrs.items(),
            key=lambda kv: 0 if kv[0] in ('file_path', 'filepath', 'font_path', 'image_path', 'image', 'font') else 1
        )
        for attr_name, attr_val in sorted_attrs:
            self.builder.set_property(node, attr_name, attr_val)

        # Process ColorRamp stop manipulations (remove/add)
        if node.bl_idname == "ShaderNodeValToRGB" and dynamic_element_attrs:
            self._process_color_ramp_operations(node, dynamic_element_attrs)

        # Process Curve node point manipulations (remove/add, points list)
        if hasattr(node, "mapping") and hasattr(node.mapping, "curves"):
            if dynamic_element_attrs or points_attr:
                self._process_curve_operations(node, dynamic_element_attrs, points_attr=points_attr)

        # Fix Compare node operation for VECTOR data_type
        # Vector comparisons only support EQUAL/NOT_EQUAL operations
        if (
            expanded_name == "compare"
            and hasattr(node, "data_type")
            and hasattr(node, "operation")
        ):
            if node.data_type == "VECTOR" and "operation" not in merged_attrs:
                # Default to EQUAL for vector comparisons
                self.builder.set_property(node, "operation", "EQUAL")

        # Process arguments
        if args_node:
            # Special handling for nodes with no input sockets that take property args (e.g. GeometryNodeInputImage, ShaderNodeAttribute)
            if hasattr(node, "inputs") and len(node.inputs) == 0 and args_node.children:
                for arg in args_node.children:
                    if arg.children:
                        if arg.children[0].data == "kwarg":
                            kw = arg.children[0]
                            kw_name = kw.children[0].value
                            val = self.evaluate_expression(kw.children[1])
                            if kw_name in ("value", "color", "val", "default_value") and hasattr(node, "outputs") and len(node.outputs) > 0 and hasattr(node.outputs[0], "default_value"):
                                self.builder._set_socket_value(node.outputs[0], val, node=node)
                            else:
                                self.builder.set_property(node, kw_name, val)
                        else:
                            val = self.evaluate_expression(arg)
                            if hasattr(node, "image"):
                                self.builder.set_property(node, "image", val)
                            elif hasattr(node, "attribute_name"):
                                self.builder.set_property(node, "attribute_name", val)
                            elif hasattr(node, "outputs") and len(node.outputs) > 0 and hasattr(node.outputs[0], "default_value"):
                                self.builder._set_socket_value(node.outputs[0], val, node=node)
                args_node = None

        if args_node:
            # PASS 1: Extract and set node properties first so dynamic sockets,
            # active/enabled states, and UI labels are updated in Blender.
            property_arg_indices = set()
            for idx, arg in enumerate(args_node.children):
                if arg.children and arg.children[0].data == "kwarg":
                    kwarg_node = arg.children[0]
                    kw_name = kwarg_node.children[0].value

                    is_prop = False
                    if hasattr(node, "bl_rna"):
                        rna_props = node.bl_rna.properties
                        if kw_name in rna_props and not rna_props[kw_name].is_readonly:
                            if kw_name not in ('name', 'label', 'location', 'width', 'height', 'color', 'use_custom_color', 'mute', 'hide', 'select', 'parent'):
                                is_prop = True
                        elif kw_name.lower() in rna_props and not rna_props[kw_name.lower()].is_readonly:
                            if kw_name.lower() not in ('name', 'label', 'location', 'width', 'height', 'color', 'use_custom_color', 'mute', 'hide', 'select', 'parent'):
                                is_prop = True

                    if not is_prop:
                        for sub_name in ('mapping', 'color_ramp', 'image_user', 'texture_mapping', 'color_mapping'):
                            sub_obj = getattr(node, sub_name, None)
                            if sub_obj and hasattr(sub_obj, "bl_rna"):
                                sub_props = sub_obj.bl_rna.properties
                                if (kw_name in sub_props and not sub_props[kw_name].is_readonly) or \
                                   (kw_name.lower() in sub_props and not sub_props[kw_name.lower()].is_readonly):
                                    is_prop = True
                                    break

                    # If it's a property and NOT an existing socket on node.inputs:
                    existing_sock = self.builder._get_socket(node.inputs, kw_name) if hasattr(node, "inputs") else None
                    if is_prop and existing_sock is None:
                        val = self.evaluate_expression(kwarg_node.children[1])
                        self.builder.set_property(node, kw_name, val)
                        property_arg_indices.add(idx)

            # PASS 2: Connect sockets and set input values
            arg_position = 0

            # Nodes that support dynamic socket creation (where sockets are added on-the-fly)
            supports_dynamic_sockets = node.bl_idname in [
                "GeometryNodeCaptureAttribute",
                "GeometryNodeMenuSwitch",
                "GeometryNodeIndexSwitch",
                "GeometryNodeRepeatInput",
                "GeometryNodeSimulationInput",
                "GeometryNodeForeachGeometryElementInput",
                "GeometryNodeForeachGeometryElementOutput",
                "NodeCombineBundle",
                "GeometryNodeCombineBundle",
                "NodeJoinBundle",
                "GeometryNodeJoinBundle",
                "GeometryNodeFieldToList",
                "NodeClosureInput",
                "NodeClosureOutput",
                "NodeEvaluateClosure",
                "GeometryNodeClosureToList",
            ]

            # For MenuSwitch nodes, clear default enum_items before adding custom ones
            if node.bl_idname == "GeometryNodeMenuSwitch":
                node.enum_items.clear()

            # Initialize visible inputs list (active, non-hidden sockets)
            visible_inputs = [inp for inp in node.inputs if not inp.hide and inp.enabled]

            for i, arg in enumerate(args_node.children):
                if i in property_arg_indices:
                    # Already handled as a node property in Pass 1; skip so it doesn't consume arg_position
                    continue

                # Refresh visible inputs as dynamic sockets or modes might have changed
                visible_inputs = [inp for inp in node.inputs if not inp.hide and inp.enabled]

                # Check if argument is empty (no children means empty argument like ,,)
                if not arg.children:
                    # Skip this input - use node default
                    arg_position += 1
                    continue

                if arg.children[0].data == "kwarg":
                    kwarg_node = arg.children[0]
                    arg_name = kwarg_node.children[0].value
                    val = self.evaluate_expression(kwarg_node.children[1])
                    self.connect_input(node, arg_name, val)
                else:
                    # It's either a labeled_arg or positional argument
                    label = None
                    if arg.children[0].data == "labeled_arg":
                        labeled_node = arg.children[0]
                        val = self.evaluate_expression(labeled_node.children[0])
                        label = labeled_node.children[1].value[1:-1]  # Strip quotes
                    else:
                        # If positional argument was a variable name, extract it as default label
                        if label is None:
                            if hasattr(arg, "children") and len(arg.children) > 0:
                                child = arg.children[0]
                                if isinstance(child, Token) and child.type == "NAME":
                                    label = child.value
                                elif hasattr(child, "data") and child.data in ("var_ref", "primary"):
                                    if len(child.children) > 0 and isinstance(child.children[0], Token) and child.children[0].type == "NAME":
                                        label = child.children[0].value
                            elif isinstance(arg, Token) and arg.type == "NAME":
                                label = arg.value

                        val = self.evaluate_expression(arg)
                        
                        # Use the stringified value as the label for dynamic menus if it's text-like
                        if isinstance(val, (str, int, float)) and not isinstance(val, bool) and node.bl_idname == "GeometryNodeMenuSwitch":
                            label = str(val)

                    # Dynamic socket processing
                    if node.bl_idname == "GeometryNodeMenuSwitch" and arg_position > 0:
                        menu_item_idx = arg_position - 1
                        
                        # Fallback label if none provided natively
                        if label is None:
                            label = f"Item {menu_item_idx}"
                            
                        # Create or rename enum_item
                        if menu_item_idx >= len(node.enum_items):
                            node.enum_items.new(label)
                        else:
                            node.enum_items[menu_item_idx].name = label
                            
                        visible_inputs = [inp for inp in node.inputs if not inp.hide and inp.enabled]

                    # Standard list unpacking for Multi-input nodes
                    support_multi_input = node.bl_idname in MULTI_INPUT_NODES
                    if support_multi_input and isinstance(val, list):
                        input_socket = visible_inputs[0] if visible_inputs else None
                        if input_socket:
                            self.connect_input(node, input_socket, val)
                        else:
                            self.warning(f" No input socket found for multi-input node {node.bl_idname}")
                        arg_position += 1
                        continue

                    # Standard connecting logic
                    kwargs = {}
                    if label:
                        kwargs['socket_label'] = label

                    if arg_position < len(visible_inputs):
                        input_socket = visible_inputs[arg_position]
                        self.connect_input(node, input_socket, val, **kwargs)
                    else:
                        # Pass by index: builder and create_dynamic_socket handles dynamic item creation for nodes lacking explicit setup
                        self.connect_input(node, arg_position, val, **kwargs)

                    arg_position += 1

        # For MenuSwitch nodes, set the Menu socket's default value to the first enum item
        if node.bl_idname == "GeometryNodeMenuSwitch" and len(node.enum_items) > 0:
            menu_socket = node.inputs[0]  # First input is the Menu socket
            if menu_socket.bl_idname == "NodeSocketMenu":
                # Set default value to the first enum item's identifier
                first_item = node.enum_items[0]
                try:
                    menu_socket.default_value = first_item.identifier
                except:
                    # If setting by identifier fails, try by name
                    try:
                        menu_socket.default_value = first_item.name
                    except:
                        pass  # Some versions may not support this
        # For NodeSeparateBundle, populate bundle items from connected upstream bundle if not already populated
        if getattr(node, "bl_idname", "") == "NodeSeparateBundle" and hasattr(node, "inputs"):
            bundle_in = node.inputs.get("Bundle")
            if bundle_in and bundle_in.is_linked:
                up_node = bundle_in.links[0].from_node
                up_sock = bundle_in.links[0].from_socket
                items = self._get_bundle_items_from_source(up_node, up_sock.name)
                if items:
                    for it_name, it_type in items:
                        if not any(b.name == it_name for b in node.bundle_items):
                            node.bundle_items.new(it_type, it_name)

        # Find the first enabled output socket
        # For multi-output nodes, ALWAYS return just the first output by default
        # Tuple unpacking will be handled in assignment() by extracting all outputs
        # Exclude virtual/custom sockets from the output list
        enabled_outputs = [
            (node, i)
            for i, output in enumerate(node.outputs)
            if output.enabled and output.type != "CUSTOM"  # Exclude virtual sockets
        ]

        if len(enabled_outputs) >= 1:
            # Return first enabled output (works for both single and multi-output nodes)
            return enabled_outputs[0]
        else:
            # No enabled outputs (shouldn't happen) - default to first output
            return (node, 0)

    def evaluate_value_node(self, node):
        """Evaluate a value node (used in defaults, attributes, etc.)"""
        from lark import Token

        # If it's a Token (terminal like STRING, NAME, NUMBER, SIGNED_NUMBER, BOOL), handle directly
        if isinstance(node, Token):
            if node.type == "STRING":
                return unescape_string(node.value)
            elif node.type == "NUMBER":
                try:
                    return int(node.value)
                except ValueError:
                    return float(node.value)
            elif node.type == "SIGNED_NUMBER":
                # Handle negative numbers (includes the minus sign)
                try:
                    return int(node.value)
                except ValueError:
                    return float(node.value)
            elif node.type == "BOOL":
                return node.value.lower() == "true"
            elif node.type == "NAME":
                return node.value
            return node.value

        # If it's a Tree node, check what type it is
        if not hasattr(node, "data"):
            return None

        # Handle 'py_access' node - look up in python_namespace
        if node.data == "py_access":
            var_name = node.children[0].value
            if var_name not in self.python_namespace:
                raise NameError(
                    f"Python variable 'py.{var_name}' not found. "
                    f"Define it in a ``` block before using it."
                )
            value = self.python_namespace[var_name]
            if callable(value):
                raise TypeError(
                    f"py.{var_name} is a function. "
                    f"Use py.{var_name}() to call it."
                )
            return value

        # Handle 'value' node - unwrap to get the actual expression
        if node.data == "value":
            if not node.children:
                return None
            # If there are multiple children, it's a tuple (e.g., vector literal like (0, 0, 1))
            if len(node.children) > 1:
                values = []
                for child in node.children:
                    val = self.evaluate_value_node(child)
                    if val is not None:
                        values.append(val)
                return tuple(values) if values else None
            # Single child - unwrap it
            return self.evaluate_value_node(node.children[0])

        # Handle 'attribute_list' node - list of values in attributes like mode:['LEFT', 'RIGHT']
        # These are used for multi-value enum properties (flags) which Blender stores as sets
        # Note: attribute_list only allows STRING | BOOL | NAME (no numbers)
        # Numeric arrays use regular tuples: (0, 0) not lists
        if node.data == "attribute_list":
            values = []
            for child in node.children:
                if isinstance(child, Token):
                    if child.type == "STRING":
                        values.append(unescape_string(child.value))  # Strip quotes
                    elif child.type == "BOOL":
                        values.append(child.value == "True")
                    elif child.type == "NAME":
                        values.append(child.value)
            # Return as Python set (Blender uses sets for multi-value enum properties)
            # If we ever need to support list properties, we can check the registry here
            return set(values) if values else set()

        # Handle 'concat' node - this is used for vector tuples like (0,0,1)
        if node.data == "concat":
            # Collect all the numeric values from the concat
            values = []
            for child in node.children:
                val = self.evaluate_value_node(child)
                if val is not None:
                    values.append(val)
            # If we got multiple values, return as tuple (for vectors)
            if len(values) > 1:
                return tuple(values)
            elif len(values) == 1:
                return values[0]
            return None

        # Handle 'term' node - unwrap to get the primary
        if node.data == "term":
            if node.children:
                return self.evaluate_value_node(node.children[0])
            return None

        # Handle 'primary' node - get the actual value
        if node.data == "primary":
            if node.children:
                child = node.children[0]
                if isinstance(child, Token):
                    if child.type == "NUMBER":
                        try:
                            return int(child.value)
                        except ValueError:
                            return float(child.value)
                    elif child.type == "STRING":
                        return unescape_string(child.value)
                return self.evaluate_value_node(child)
            return None

        # Fallback: try to get first child
        if hasattr(node, "children") and node.children:
            return self.evaluate_value_node(node.children[0])

        return None

    def _process_color_ramp_operations(self, node, operations):
        """Process ColorRamp stop manipulations (remove/add)."""
        for attr_name, attr_val in operations:
            if attr_name == "remove":
                try:
                    pos = float(attr_val)
                    remove_elem = next(
                        (e for e in node.color_ramp.elements if abs(e.position - pos) < 0.001),
                        None,
                    )
                    if remove_elem:
                        node.color_ramp.elements.remove(remove_elem)
                    else:
                        self.warning(f"No ColorRamp stop at position {pos} to remove")
                except Exception as e:
                    self.error(f"Error removing ColorRamp stop at {attr_val}: {e}")

            elif attr_name == "add":
                try:
                    parts = attr_val.split(":", 1)
                    pos = float(parts[0])
                    color_str = parts[1]

                    elem = next(
                        (e for e in node.color_ramp.elements if abs(e.position - pos) < 0.001),
                        None,
                    )
                    if elem is None:
                        elem = node.color_ramp.elements.new(pos)
                    elem.position = pos

                    if color_str.startswith("#"):
                        hex_color = color_str.lstrip("#")
                        r = int(hex_color[0:2], 16) / 255.0
                        g = int(hex_color[2:4], 16) / 255.0
                        b = int(hex_color[4:6], 16) / 255.0
                        color = (r, g, b, 1.0)
                    else:
                        color = eval(color_str)
                    elem.color = color
                except Exception as e:
                    self.error(f"Error adding ColorRamp stop '{attr_val}': {e}")

    def _parse_curve_point_spec(self, attr_val):
        """Parse a curve point specification into (x, y, handle_type, curve_idx)."""
        x, y, handle_type, curve_idx = 0.0, 0.0, "AUTO", 0
        if isinstance(attr_val, (tuple, list)):
            if len(attr_val) >= 2:
                x = float(attr_val[0])
                y = float(attr_val[1])
            if len(attr_val) >= 3:
                handle_type = str(attr_val[2]).upper()
            if len(attr_val) >= 4:
                curve_idx = attr_val[3]
            return x, y, handle_type, curve_idx

        if isinstance(attr_val, dict):
            x = float(attr_val.get("x", attr_val.get("location", [0.0, 0.0])[0]))
            y = float(attr_val.get("y", attr_val.get("location", [0.0, 0.0])[1]))
            handle_type = str(attr_val.get("handle_type", "AUTO")).upper()
            curve_idx = attr_val.get("curve", 0)
            return x, y, handle_type, curve_idx

        if isinstance(attr_val, str):
            s = attr_val.strip()
            if s.startswith("(") and s.endswith(")"):
                s = s[1:-1].strip()
            parts = [p.strip() for p in (s.split(":") if ":" in s else (s.split(",") if "," in s else s.split()))]
            if len(parts) >= 2:
                try:
                    x = float(parts[0])
                    y = float(parts[1])
                    handle_type = parts[2].upper() if len(parts) > 2 else "AUTO"
                    if len(parts) > 3:
                        curve_idx = parts[3]
                except ValueError:
                    curve_idx = parts[0]
                    x = float(parts[1])
                    y = float(parts[2])
                    handle_type = parts[3].upper() if len(parts) > 3 else "AUTO"
            return x, y, handle_type, curve_idx

        raise ValueError(f"Cannot parse curve point from {attr_val!r}")

    def _get_curve_index(self, node, curve_spec=0):
        """Get curve index for CurveMapping curves collection."""
        num_curves = len(node.mapping.curves)
        if isinstance(curve_spec, int):
            return max(0, min(curve_spec, num_curves - 1))
        if isinstance(curve_spec, str):
            c_upper = curve_spec.upper()
            if c_upper in ("C", "COMBINED"): return 0
            if c_upper in ("R", "RED", "X"): return 1 if num_curves > 1 else 0
            if c_upper in ("G", "GREEN", "Y"): return 2 if num_curves > 2 else 0
            if c_upper in ("B", "BLUE", "Z"): return 3 if num_curves > 3 else 0
            if c_upper.isdigit():
                return max(0, min(int(c_upper), num_curves - 1))
        return 0

    def _process_curve_operations(self, node, operations, points_attr=None):
        """Process Curve node point manipulations (remove/add, points list)."""
        if not (hasattr(node, "mapping") and hasattr(node.mapping, "curves")):
            return

        def norm_handle(h):
            h_up = str(h).upper().replace("-", "_")
            if h_up in ("VECTOR", "AUTO", "AUTO_CLAMPED"):
                return h_up
            if "CLAMP" in h_up:
                return "AUTO_CLAMPED"
            return "AUTO"

        def add_point(curve, x, y, handle_type):
            existing_pt = next((p for p in curve.points if abs(p.location[0] - x) < 0.001), None)
            h = norm_handle(handle_type)
            if existing_pt is not None:
                existing_pt.location = (x, y)
                existing_pt.handle_type = h
            else:
                pt = curve.points.new(x, y)
                pt.handle_type = h

        # 1. Process points list if provided
        if points_attr:
            pt_list = [points_attr] if isinstance(points_attr, (str, dict)) else points_attr
            if isinstance(pt_list, (list, tuple, set)):
                for pt_spec in pt_list:
                    try:
                        x, y, handle, c_idx = self._parse_curve_point_spec(pt_spec)
                        idx = self._get_curve_index(node, c_idx)
                        add_point(node.mapping.curves[idx], x, y, handle)
                    except Exception as e:
                        self.error(f"Error adding point from points attribute: {e}")

        # 2. Process sequential operations (add/remove)
        if operations:
            for attr_name, attr_val in operations:
                if attr_name == "add":
                    try:
                        x, y, handle, c_idx = self._parse_curve_point_spec(attr_val)
                        idx = self._get_curve_index(node, c_idx)
                        add_point(node.mapping.curves[idx], x, y, handle)
                    except Exception as e:
                        self.error(f"Error adding curve point '{attr_val}': {e}")
                elif attr_name == "remove":
                    try:
                        val_str = str(attr_val).strip()
                        c_idx = 0
                        if ":" in val_str:
                            parts = val_str.split(":", 1)
                            try:
                                float(parts[1])
                                c_idx = self._get_curve_index(node, parts[0])
                                val_str = parts[1].strip()
                            except ValueError:
                                pass
                        curve = node.mapping.curves[c_idx]
                        if len(curve.points) <= 2:
                            self.warning(f"Cannot remove curve point '{attr_val}': CurveMap requires at least 2 points")
                            continue
                        if val_str.isdigit() and int(val_str) < len(curve.points):
                            curve.points.remove(curve.points[int(val_str)])
                        else:
                            pos_x = float(val_str)
                            pt = next((p for p in curve.points if abs(p.location[0] - pos_x) < 0.001), None)
                            if pt:
                                curve.points.remove(pt)
                            else:
                                self.warning(f"No curve point found at x={pos_x} to remove")
                    except Exception as e:
                        self.error(f"Error removing curve point '{attr_val}': {e}")

        node.mapping.update()

    def get_input_name(self, node_type, index):
        """Get the input socket name for a node type at the given index"""
        node_def = self.builder.registry.get_node_def(node_type)
        if not node_def:
            return f"input_{index}"

        # Find the input socket with the matching index
        # Note: Registry may have multiple entries for the same index (e.g., 'Vector' and 'vector')
        # We want the first one which should be the correctly capitalized Blender socket name
        inputs = node_def.get("inputs", {})
        for socket_name, socket_info in inputs.items():
            if socket_info.get("index") == index:
                # Return the socket name as-is from the registry
                # This should match Blender's actual socket name
                return socket_name

        # Fallback to generic name if not found
        return f"input_{index}"

    def parse_attributes(self, attrs_node):
        """Parse an attributes block and return a dictionary of {attr_name: attr_value}.

        Used for parsing attribute blocks like {domain:'FACE'} in foreach statements.
        """
        attributes = {}
        if attrs_node:
            for attr in attrs_node.children:
                attr_name = attr.children[0].value
                attr_val_node = attr.children[1]
                attr_val = self.evaluate_value_node(attr_val_node)
                attributes[attr_name] = attr_val
        return attributes

    def _parse_range_node(self, child):
        """Parse a range AST node (range_both, range_max_only, range_min_only).

        Returns:
            (min_val, max_val, consumed_count)
        """
        from lark import Tree
        if not isinstance(child, Tree):
            return (None, None, 0)

        if child.data == "range_both":
            min_v = self.evaluate_value_node(child.children[0])
            max_v = self.evaluate_value_node(child.children[1])
            return (min_v, max_v, 1)
        elif child.data == "range_max_only":
            max_v = self.evaluate_value_node(child.children[0])
            return (None, max_v, 1)
        elif child.data == "range_min_only":
            min_v = self.evaluate_value_node(child.children[0])
            return (min_v, None, 1)
        return (None, None, 0)

    def input_decl(self, tree):
        # input_decl: hidden_modifier? "input" NAME ":" TYPE STRING? ("=" value)? range_spec? ("@" STRING)?
        from lark import Token, Tree

        is_hidden = False
        idx = 0
        if tree.children and hasattr(tree.children[idx], "data") and tree.children[idx].data == "hidden_modifier":
            is_hidden = True
            idx += 1

        var_name = tree.children[idx].value
        type_name, sig_info = self._parse_type_spec(tree.children[idx+1])
        if type_name == "closure" and sig_info:
            self.closure_signatures[var_name] = sig_info
        elif type_name == "bundle" and sig_info:
            self.bundle_signatures[var_name] = sig_info

        display_name = None
        default_value = None
        min_val = None
        max_val = None
        tooltip = None

        # Parse optional components using index-based traversal to avoid ambiguity
        i = idx + 2

        # 1. Optional Display Name (STRING)
        if (i < len(tree.children) 
            and isinstance(tree.children[i], Token) 
            and tree.children[i].type == "STRING"):
            display_name = tree.children[i].value[1:-1]
            i += 1

        if not display_name:
            display_name = var_name.capitalize()

        # 2. Optional Default Value ("=" value)
        if (i < len(tree.children) 
            and isinstance(tree.children[i], Tree) 
            and tree.children[i].data == "value"):
            default_value = self.evaluate_value_node(tree.children[i])
            i += 1

        # 3. Optional Range ([min, max], [, max], or [min, ])
        if i < len(tree.children) and isinstance(tree.children[i], Tree):
            r_min, r_max, consumed = self._parse_range_node(tree.children[i])
            if consumed > 0:
                min_val = r_min
                max_val = r_max
                i += consumed
            elif tree.children[i].data == "value":
                min_val = self.evaluate_value_node(tree.children[i])
                i += 1
                if (i < len(tree.children) 
                    and isinstance(tree.children[i], Tree) 
                    and tree.children[i].data == "value"):
                    max_val = self.evaluate_value_node(tree.children[i])
                    i += 1

        # 4. Optional Tooltip ("@" STRING)
        if (i < len(tree.children) 
            and isinstance(tree.children[i], Token) 
            and tree.children[i].type == "STRING"):
            tooltip = tree.children[i].value[1:-1]
            i += 1

        # Default to index 0 for menu inputs if not specified
        if default_value is None and type_name == "menu":
            default_value = 0

        # Map XNodify types to Blender socket types
        from socket_types import XNODIFY_TO_BLENDER
        input_type = type_name.lower()
        socket_type = XNODIFY_TO_BLENDER.get(input_type, "NodeSocketFloat")

        # Create input socket
        tree_interface = self.builder.node_tree.interface
        new_socket = tree_interface.new_socket(
            name=display_name, in_out="INPUT", socket_type=socket_type
        )

        if is_hidden:
            if hasattr(new_socket, "hide_in_modifier"):
                new_socket.hide_in_modifier = True
            if hasattr(new_socket, "hide_value"):
                new_socket.hide_value = True

        # Set tooltip/description
        if tooltip:
            new_socket.description = tooltip

        # Set min/max ranges if provided
        if hasattr(new_socket, "min_value") and min_val is not None:
            new_socket.min_value = min_val
        if hasattr(new_socket, "max_value") and max_val is not None:
            new_socket.max_value = max_val
        if default_value is not None:
            # Also set the modifier property value (important for ranges and defaults)
            if self.modifier is not None:
                try:
                    socket_id = new_socket.identifier
                    # Check if it's a menu - those expect integer index
                    if socket_type == "NodeSocketMenu":
                        # We don't have item info yet, but if it's a string, we might defer
                        pass 
                    else:
                        if hasattr(self.modifier, "properties") and hasattr(self.modifier.properties, "inputs"):
                            mod_inps = self.modifier.properties.inputs
                            if hasattr(mod_inps, socket_id):
                                getattr(mod_inps, socket_id).value = default_value
                                logger.debug(f"  → Set modifier property inputs.{socket_id} = {default_value}")
                            else:
                                self.modifier[socket_id] = default_value
                        else:
                            self.modifier[socket_id] = default_value
                            logger.debug(f"  → Set modifier property '{socket_id}' = {default_value}")
                except Exception as mod_err:
                    self.warning(f"   Could not set modifier property: {mod_err}")

            try:
                # Handle special cases for certain socket types
                if socket_type == "NodeSocketObject" and isinstance(default_value, str):
                    # Convert object name string to actual object reference
                    import bpy

                    if default_value in bpy.data.objects:
                        new_socket.default_value = bpy.data.objects[default_value]
                        logger.debug(
                            f"Set default value for input '{display_name}': {default_value} (object)"
                        )
                    else:
                        self.warning(
                            f"Object '{default_value}' not found for input '{display_name}'"
                        )
                elif socket_type == "NodeSocketMaterial" and isinstance(
                    default_value, str
                ):
                    # Convert material name string to actual material reference
                    import bpy

                    if default_value in bpy.data.materials:
                        new_socket.default_value = bpy.data.materials[default_value]
                        logger.debug(
                            f"Set default value for input '{display_name}': {default_value} (material)"
                        )
                    else:
                        self.pending_materials.append((new_socket, default_value))
                        self.warning(
                            f"Material '{default_value}' not found for input '{display_name}'"
                        )
                elif socket_type == "NodeSocketBool" and isinstance(default_value, str):
                    # Convert string boolean to actual bool
                    if default_value.lower() in ("true", "1"):
                        new_socket.default_value = True
                    elif default_value.lower() in ("false", "0"):
                        new_socket.default_value = False
                    else:
                        new_socket.default_value = default_value
                    logger.debug(
                        f"Set default value for input '{display_name}': {new_socket.default_value} (bool)"
                    )
                elif socket_type == "NodeSocketMenu":
                    # Defer setting menu defaults until after compilation
                    # when enum items are populated
                    self.deferred_menu_defaults.append({
                        'socket': new_socket,
                        'value': default_value,
                        'display_name': display_name
                    })
                    logger.debug(
                        f"Deferred menu default for '{display_name}': {default_value} (will set after compilation)"
                    )
                elif socket_type == "NodeSocketMenu":
                    new_socket.default_value = default_value
                    logger.debug(
                        f"Set default value for input '{display_name}': {default_value}"
                    )
                elif socket_type == "NodeSocketBundle":
                    # Bundles do not support default values in the same way
                    logger.debug(
                        f"Skipping default value for bundle input '{display_name}' (not supported for bundles)"
                    )
                else:
                    new_socket.default_value = default_value
                    logger.debug(
                        f"Set default value for input '{display_name}': {default_value}"
                    )

                # CRITICAL: Also set the modifier property to match the interface default
                # This makes the default value visible in the modifier panel
                # Use new_socket.default_value (converted) instead of original default_value
                # Skip menu sockets - they're handled in _set_deferred_menu_defaults
                if self.modifier is not None and socket_type != "NodeSocketMenu":
                    try:
                        socket_id = new_socket.identifier
                        # Use the converted value from the socket, not the original default_value
                        actual_value = new_socket.default_value
                        if hasattr(self.modifier, "properties") and hasattr(self.modifier.properties, "inputs"):
                            mod_inps = self.modifier.properties.inputs
                            if hasattr(mod_inps, socket_id):
                                mod_sock = getattr(mod_inps, socket_id)
                                if hasattr(mod_sock, "value"):
                                    mod_sock.value = actual_value
                                    logger.debug(
                                        f"  → Set modifier property inputs.{socket_id}.value = {actual_value}"
                                    )
                            else:
                                self.modifier[socket_id] = actual_value
                        # Handle vector/color types (lists)
                        elif isinstance(actual_value, (list, tuple)):
                            for i in range(len(actual_value)):
                                self.modifier[socket_id][i] = actual_value[i]
                            logger.debug(
                                f"  → Set modifier property '{socket_id}' = {actual_value}"
                            )
                        else:
                            self.modifier[socket_id] = actual_value
                            logger.debug(
                                f"  → Set modifier property '{socket_id}' = {actual_value}"
                            )
                    except Exception as mod_err:
                        import traceback

                        self.warning(f"   Could not set modifier property: {mod_err}")
                        traceback.print_exc()
            except Exception as e:
                self.warning(
                    f" Could not set default value for '{display_name}': {e}"
                )

        # Store the mapping from variable name to Group Input socket
        self.inputs[var_name] = display_name
        logger.debug(f"Declared input: {var_name} ({type_name}) socket={display_name}")

        # Find or create Group Input node
        group_input = None
        for node in self.builder.node_tree.nodes:
            if node.bl_idname == "NodeGroupInput":
                group_input = node
                break
        if not group_input:
            group_input = self.builder.node_tree.nodes.new("NodeGroupInput")
            group_input.name = "Group Input"

        # Store in symbol table as (node, socket_name)
        self.symbol_table[var_name] = (group_input, display_name)

    def output_decl(self, tree):
        from lark import Token
        
        is_hidden = False
        idx = 0
        if tree.children and hasattr(tree.children[idx], "data") and tree.children[idx].data == "hidden_modifier":
            is_hidden = True
            idx += 1
            
        name = tree.children[idx].value
        
        # Check for type definition
        socket_type = "NodeSocketGeometry" # Default
        
        if len(tree.children) > idx + 1:
            type_name, closure_sig = self._parse_type_spec(tree.children[idx + 1])
            from socket_types import XNODIFY_TO_BLENDER
            input_type = type_name.lower()
            socket_type = XNODIFY_TO_BLENDER.get(input_type, "NodeSocketGeometry")

        # Optional display name and tooltip
        display_name = None
        tooltip = None
        for child in tree.children[idx + 1:]:
            if isinstance(child, Token) and child.type == "STRING":
                if display_name is None:
                    display_name = child.value[1:-1]
                elif tooltip is None:
                    tooltip = child.value[1:-1]

        socket_name = display_name if display_name else name
        if not hasattr(self, "output_socket_names"):
            self.output_socket_names = {}
        self.output_socket_names[name] = socket_name
                
        tree_interface = self.builder.node_tree.interface
        socket_exists = False
        for item in tree_interface.items_tree:
            if hasattr(item, "name") and item.name == socket_name:
                socket_exists = True
                break
                
        if not socket_exists:
            new_socket = tree_interface.new_socket(
                name=socket_name, in_out="OUTPUT", socket_type=socket_type
            )
            if is_hidden:
                if hasattr(new_socket, "hide_in_modifier"):
                    new_socket.hide_in_modifier = True
                if hasattr(new_socket, "hide_value"):
                    new_socket.hide_value = True
            if tooltip and hasattr(new_socket, "description"):
                new_socket.description = tooltip
                
        logger.debug(f"Declared output: {name} ({socket_type}) socket={socket_name}")
        
        # Store initial type info - value is None until assigned
        self.outputs[name] = (socket_type, None)

    def group_def(self, tree):
        """Handle group definition: stores group metadata and body AST for later compilation"""
        child_offset = 0
        explicit_tree_type = None
        if len(tree.children) > 0 and isinstance(tree.children[0], Tree):
            if tree.children[0].data in ("material_domain", "geometry_domain"):
                explicit_tree_type = "ShaderNodeTree" if tree.children[0].data == "material_domain" else "GeometryNodeTree"
                child_offset = 1
            elif tree.children[0].data == "domain_type":
                domain_val = tree.children[0].children[0].value.lower() if tree.children[0].children else ""
                explicit_tree_type = "ShaderNodeTree" if domain_val in ("shader", "material", "world") else "GeometryNodeTree"
                child_offset = 1

        group_name = tree.children[child_offset].value
        child_offset += 1

        # Check for optional display name (STRING after NAME)
        display_name = None
        if (
            len(tree.children) > child_offset
            and isinstance(tree.children[child_offset], Token)
            and tree.children[child_offset].type == "STRING"
        ):
            display_name = tree.children[child_offset].value[1:-1]  # Strip quotes
            child_offset += 1

        logger.info(
            f"Defining group: {group_name}"
            + (f" (display: {display_name})" if display_name else "")
        )

        # Collect inputs, outputs, and body statements
        inputs = []
        outputs = []
        body_statements = []

        # Save current group context
        prev_group = self.current_group

        # Create temporary group info for input/output collection
        group_info = {
            "name": group_name,
            "display_name": display_name,  # Store display name
            "tree_type": explicit_tree_type,
            "inputs": [],
            "outputs": [],
        }
        self.current_group = group_info

        # Process group children to collect inputs/outputs and body
        for child in tree.children[child_offset:]:
            if isinstance(child, Tree):
                if child.data == "group_statement":
                    # Check what kind of statement this is
                    stmt_child = child.children[0]
                    if stmt_child.data == "group_input":
                        self.group_input(stmt_child)
                    elif stmt_child.data == "group_output":
                        self.group_output(stmt_child)
                    elif stmt_child.data == "statement":
                        # Check if this statement is actually an input/output declaration
                        # The parser sometimes nests: group_statement -> statement -> input_decl
                        if len(stmt_child.children) > 0:
                            nested = stmt_child.children[0]
                            if nested.data == "input_decl":
                                # Treat as group input
                                self.group_input(nested)
                            elif nested.data == "output_decl":
                                # Treat as group output
                                self.group_output(nested)
                            else:
                                # It's a regular body statement
                                body_statements.append(nested)
                        else:
                            body_statements.append(stmt_child)
                    else:
                        # It's a regular statement (part of the body)
                        body_statements.append(stmt_child)

        # Store complete group info with body AST
        group_info["body_ast"] = body_statements
        group_info["node_tree"] = None  # Will be created on first instantiation

        self.groups[group_name] = group_info
        self.current_group = prev_group

        logger.debug(
            f"Group .* defined with {len(group_info['inputs'])} inputs, {len(group_info['outputs'])} outputs, {len(body_statements)} body statements"
        )

    def group_input(self, tree):
        """Handle group input declaration"""
        # group_input: "input" NAME ":" type_spec (STRING)? (STRING)? ("=" value)? ("[" value "," value "]")?
        var_name = tree.children[0].value
        type_name, sig_info = self._parse_type_spec(tree.children[1])
        closure_sig = sig_info if type_name == "closure" else None
        bundle_sig = sig_info if type_name == "bundle" else None

        socket_name = None
        tooltip = None
        default = None
        min_val = None
        max_val = None

        # Parse optional components
        i = 2
        # First STRING is socket name
        if (
            i < len(tree.children)
            and isinstance(tree.children[i], Token)
            and tree.children[i].type == "STRING"
        ):
            socket_name = tree.children[i].value[1:-1]  # Strip quotes
            i += 1

        # Second STRING is tooltip
        if (
            i < len(tree.children)
            and isinstance(tree.children[i], Token)
            and tree.children[i].type == "STRING"
        ):
            tooltip = tree.children[i].value[1:-1]
            i += 1

        # Default value
        if (
            i < len(tree.children)
            and isinstance(tree.children[i], Tree)
            and tree.children[i].data == "value"
        ):
            default = self.evaluate_value_node(tree.children[i])
            i += 1

        # Default to index 0 for menu inputs if not specified
        if default is None and type_name == "menu":
            default = 0

        # Range [min, max], [, max], or [min, ]
        if i < len(tree.children) and isinstance(tree.children[i], Tree):
            r_min, r_max, consumed = self._parse_range_node(tree.children[i])
            if consumed > 0:
                min_val = r_min
                max_val = r_max
                i += consumed
            elif tree.children[i].data == "value":
                min_val = self.evaluate_value_node(tree.children[i])
                i += 1
                if (
                    i < len(tree.children)
                    and isinstance(tree.children[i], Tree)
                    and tree.children[i].data == "value"
                ):
                    max_val = self.evaluate_value_node(tree.children[i])
                    i += 1

        if socket_name is None:
            socket_name = var_name

        input_info = {
            "var_name": var_name,
            "type": type_name,
            "socket_name": socket_name,
            "tooltip": tooltip,
            "default": default,
            "min": min_val,
            "max": max_val,
            "closure_sig": closure_sig,
            "bundle_sig": bundle_sig,
            "ast_node": tree,
        }

        if self.current_group:
            self.current_group["inputs"].append(input_info)

        logger.debug(f"Group input: {var_name} ({type_name}) socket={socket_name}")

    def group_output(self, tree):
        """Handle group output declaration

        Handles both:
        - group_output: "output" NAME ":" type_spec (STRING)?
        - output_decl: "output" NAME (when called from group context)
        """
        from lark import Token

        var_name = tree.children[0].value

        # Check if this is a full group_output (with type_spec) or just output_decl (without type_spec)
        closure_sig = None
        if len(tree.children) > 1:
            type_name, closure_sig = self._parse_type_spec(tree.children[1])
            socket_name = None

            if (
                len(tree.children) > 2
                and isinstance(tree.children[2], Token)
                and tree.children[2].type == "STRING"
            ):
                socket_name = tree.children[2].value[1:-1]

            if socket_name is None:
                socket_name = var_name
        else:
            # This is an output_decl without TYPE
            # We'll infer the type later from the assigned value
            # For now, use 'geometry' as default for geometry node groups, 'shader' for shader groups
            self.warning(
                f"Group output '{var_name}' missing type, will infer from assignment",
                node=tree
            )
            type_name = (
                "geometry"  # Default to geometry, will be corrected during assignment
            )
            socket_name = var_name

        output_info = {
            "var_name": var_name,
            "type": type_name,
            "socket_name": socket_name,
            "closure_sig": closure_sig,
            "ast_node": tree,
        }

        if self.current_group:
            self.current_group["outputs"].append(output_info)

        logger.debug(f"Group output: {var_name} ({type_name}) socket={socket_name}")

    # =========================================================================
    # Zone Helper Methods - Shared logic for repeat, simulation, foreach zones
    # =========================================================================

    def _parse_zone_clauses(self, tree, zone_type='repeat'):
        """Parse common clauses from zone tree.
        
        Args:
            tree: The zone AST node
            zone_type: 'repeat', 'simulation', or 'foreach'
            
        Returns:
            dict with keys:
            - expressions: List of top-level expressions (iterations, geometry, etc.)
            - state_vars: List of state variable names from state=()
            - output_var_names: List of variable names from :output_vars clause
            - output_items: List of (output_name, var_name) from output_clause
            - statements: List of statement nodes
            - attributes: Dict of parsed attributes from {key:value}
            - input_items: (foreach only) List of input var names from foreach_output_clause
        """
        from lark import Token
        
        result = {
            'expressions': [],
            'state_vars': [],
            'output_var_names': [],
            'output_items': [],
            'statements': [],
            'attributes': {},
            'input_items': [],  # Only used by foreach
        }
        
        # Known clause node names that aren't expressions
        clause_names = {'state_clause', 'output_vars_clause', 'output_clause', 
                        'foreach_output_clause', 'statement', 'attributes'}
        
        for child in tree.children:
            if not hasattr(child, 'data'):
                # It's a Token - treat as expression
                result['expressions'].append(child)
            elif child.data == 'attributes':
                result['attributes'] = self.parse_attributes(child)
            elif child.data not in clause_names:
                # It's an expression tree node (primary, add_sub, etc.)
                result['expressions'].append(child)
            elif child.data == 'state_clause':
                for item in child.children:
                    if hasattr(item, 'data') and item.data == 'state_item':
                        # New structure: state_item -> NAME (: TYPE)?
                        name = item.children[0].value
                        type_name = None
                        if len(item.children) > 1 and hasattr(item.children[1], 'type') and item.children[1].type == 'TYPE':
                            type_name = item.children[1].value
                        
                        result['state_vars'].append({'name': name, 'type': type_name})
                    elif isinstance(item, Token) and item.type == 'NAME':
                        # Legacy structure (or direct name tokens)
                        result['state_vars'].append({'name': item.value, 'type': None})
            elif child.data == 'output_vars_clause':
                for item in child.children:
                    if hasattr(item, 'data') and item.data == 'output_var_item':
                        if item.children:
                            result['output_var_names'].append(item.children[0].value)
                        else:
                            result['output_var_names'].append(None)  # Empty position
            elif child.data == 'output_clause':
                for item in child.children:
                    if hasattr(item, 'data') and item.data == 'output_item':
                        if len(item.children) == 2:
                            result['output_items'].append((item.children[0].value, item.children[1].value))
                        elif len(item.children) == 1:
                            name = item.children[0].value
                            result['output_items'].append((name, name))
                        else:
                            result['output_items'].append((None, None))
            elif child.data == 'foreach_output_clause':
                # Foreach has input_item_list:output_item_list structure
                self._parse_foreach_output_clause(child, result)
            elif child.data == 'statement':
                result['statements'].append(child)
        
        return result

    def _parse_foreach_output_clause(self, clause, result):
        """Parse foreach's unique bidirectional output clause: (input_list:output_list)"""
        from lark import Token
        
        for subchild in clause.children:
            if not hasattr(subchild, 'data'):
                continue
            if subchild.data == 'input_item_list':
                expecting_item = True
                has_children = False
                for item in subchild.children:
                    has_children = True
                    if hasattr(item, 'data') and item.data == 'input_item':
                        val = item.children[0].value if item.children else None
                        result['input_items'].append(val)
                        expecting_item = False
                    elif isinstance(item, Token) and item.type == 'COMMA':
                        if expecting_item:
                            result['input_items'].append(None)
                        expecting_item = True
                if has_children and expecting_item:
                    result['input_items'].append(None)
            elif subchild.data == 'output_item_list':
                expecting_item = True
                has_children = False
                for item in subchild.children:
                    has_children = True
                    if hasattr(item, 'data') and item.data == 'output_item':
                        if len(item.children) == 2:
                            result['output_items'].append((item.children[0].value, item.children[1].value))
                        elif len(item.children) == 1:
                            name = item.children[0].value
                            result['output_items'].append((name, name))
                        else:
                            result['output_items'].append((None, None))
                        expecting_item = False
                    elif isinstance(item, Token) and item.type == 'COMMA':
                        if expecting_item:
                            result['output_items'].append((None, None))
                        expecting_item = True
                if has_children and expecting_item:
                    result['output_items'].append((None, None))

    def _process_zone_outputs(self, output_items, output_node, item_collection, 
                               state_initial_values, input_node, zone_type='repeat'):
        """Process output clause and connect outputs to zone output node.
        
        Shared logic for repeat, simulation, foreach zones.
        
        Args:
            output_items: List of (output_name, var_name) tuples
            output_node: The zone output node (repeat_output, simulation_output, etc.)
            item_collection: The node's item collection (repeat_items, state_items, generation_items)
            state_initial_values: Dict of state var -> initial value
            input_node: The zone input node (for connecting initial values)
            zone_type: 'repeat', 'simulation', or 'foreach'
        """
        if not output_items:
            return
            
        # Handle first position (geometry output)
        if output_items[0][1]:  # Not empty
            output_name, var_name = output_items[0]
            if var_name in self.symbol_table:
                val = self.symbol_table[var_name]
                
                # Verify it's geometry type
                if isinstance(val, tuple) and len(val) == 2:
                    from_node, from_socket_ref = val
                    if hasattr(from_node, "outputs"):
                        if isinstance(from_socket_ref, str):
                            from_socket = from_node.outputs.get(from_socket_ref)
                        else:
                            from_socket = from_node.outputs[from_socket_ref]
                        if from_socket and hasattr(from_socket, "type"):
                            if from_socket.type != "GEOMETRY":
                                raise ValueError(
                                    f"First output in {zone_type} }}(...) must be geometry type, "
                                    f"got {from_socket.type} for variable '{var_name}'"
                                )
                
                # Connect to output node's Geometry socket
                self.connect_input(output_node, "Geometry", val)
                
                # Make available after zone
                final_name = output_name if output_name else var_name
                self.symbol_table[final_name] = (output_node, "Geometry")
        
        # Handle remaining positions (custom items)
        for output_name, var_name in output_items[1:]:
            if var_name:  # Not empty
                if var_name in self.symbol_table:
                    val = self.symbol_table[var_name]
                    
                    # Infer socket type
                    socket_type = self._infer_socket_type(val)
                    
                    # Check if item already exists (for state variables)
                    item_exists = any(item.name == var_name for item in item_collection)
                    
                    if not item_exists:
                        # Create item on output node
                        item_collection.new(socket_type, var_name)
                        logger.debug(f"  Created {zone_type}_item '{var_name}' with type {socket_type}")
                        
                        # Connect initial value to input node (if it's a state var)
                        if var_name in state_initial_values:
                            self.connect_input(input_node, var_name, state_initial_values[var_name])
                    
                    # Connect to output node
                    self.connect_input(output_node, var_name, val)
                    
                    # Make available after zone
                    final_name = output_name if output_name else var_name
                    self.symbol_table[final_name] = (output_node, var_name)

    def _infer_socket_type(self, val):
        """Infer Blender socket type from a value."""
        if isinstance(val, tuple) and len(val) == 2:
            from_node, from_socket_ref = val
            if hasattr(from_node, "outputs"):
                if isinstance(from_socket_ref, str):
                    from_socket = from_node.outputs.get(from_socket_ref)
                else:
                    from_socket = from_node.outputs[from_socket_ref]
                    
                if from_socket and hasattr(from_socket, "type"):
                    blender_type_map = {
                        "VALUE": "FLOAT",
                        "INT": "INT",
                        "BOOLEAN": "BOOLEAN",
                        "VECTOR": "VECTOR",
                        "STRING": "STRING",
                        "RGBA": "RGBA",
                        "GEOMETRY": "GEOMETRY",
                        "ROTATION": "ROTATION",
                        "MATRIX": "MATRIX",
                        "CLOSURE": "CLOSURE",
                        "BUNDLE": "BUNDLE",
                        "MENU": "MENU",
                        "OBJECT": "OBJECT",
                        "COLLECTION": "COLLECTION",
                        "MATERIAL": "MATERIAL",
                        "IMAGE": "IMAGE",
                        "TEXTURE": "TEXTURE",
                        "SHADER": "SHADER",
                        "FONT": "FONT",
                        "SOUND": "SOUND",
                        "INT_VECTOR": "INT_VECTOR",
                    }
                    return blender_type_map.get(from_socket.type, "GEOMETRY")
        elif isinstance(val, (int, float)):
            return "FLOAT"
        elif isinstance(val, bool):
            return "BOOLEAN"
        return "GEOMETRY"  # Default

    def _create_loop_state_sockets(self, state_vars, input_node, output_node, item_collection):
        """Helper method to create state variable sockets for repeat/foreach loops.

        This method:
        1. Infers socket types from initial values OR uses explicit types
        2. Creates sockets on output node (which auto-creates on input node)
        3. Connects initial values to input node (if available)
        4. Updates symbol table to read from input node outputs

        Args:
            state_vars: List of state variable dicts {'name': name, 'type': type} (or just names for legacy)
            input_node: RepeatInput or ForeachInput node
            output_node: RepeatOutput or ForeachOutput node
            item_collection: The collection to add items to:
                - For repeat: repeat_output.repeat_items
                - For foreach: foreach_output.input_items

        Returns:
            dict: Mapping of state variable names to their initial values
        """
        state_initial_values = {}

        for var_info in state_vars:
            # Handle both new dict format and legacy string format
            if isinstance(var_info, str):
                var = var_info
                var_type = None
            else:
                var = var_info['name']
                var_type = var_info['type']
            
            # Check if variable exists individually
            initial_val = None
            if var in self.symbol_table:
                initial_val = self.symbol_table[var]
                state_initial_values[var] = initial_val

            # Determine socket type
            socket_type = "GEOMETRY"  # Default fallback
            
            if var_type:
                # Use explicit type from annotation
                from socket_types import XNODIFY_TO_BLENDER, BLENDER_TO_REGISTRY
                # Map 'geometry' -> 'NodeSocketGeometry' -> 'GEOMETRY'
                blender_socket_type = XNODIFY_TO_BLENDER.get(var_type, "NodeSocketGeometry")
                socket_type = BLENDER_TO_REGISTRY.get(blender_socket_type, "GEOMETRY")
            elif initial_val is not None:
                # Infer type from initial value
                if isinstance(initial_val, tuple) and len(initial_val) == 2:
                    from_node, from_socket_ref = initial_val
                    if hasattr(from_node, "outputs"):
                        if isinstance(from_socket_ref, str):
                            from_socket = from_node.outputs.get(from_socket_ref)
                        else:
                            from_socket = from_node.outputs[from_socket_ref]

                        if from_socket and hasattr(from_socket, "type"):
                            blender_type_map = {
                                "VALUE": "FLOAT",
                                "INT": "INT",
                                "BOOLEAN": "BOOLEAN",
                                "VECTOR": "VECTOR",
                                "STRING": "STRING",
                                "RGBA": "RGBA",
                                "GEOMETRY": "GEOMETRY",
                                "ROTATION": "ROTATION",
                                "MATRIX": "MATRIX",
                            }
                            socket_type = blender_type_map.get(from_socket.type, "GEOMETRY")
                elif isinstance(initial_val, (int, float)):
                    socket_type = "FLOAT"
                elif isinstance(initial_val, bool):
                    socket_type = "BOOLEAN"

            # In ForEach zones, input_items don't support GEOMETRY.
            # External geometry is simply linked implicitly from outside the zone.
            if socket_type == "GEOMETRY" and input_node.bl_idname == "GeometryNodeForeachGeometryElementInput":
                logger.debug(f"  Skipping GEOMETRY state item '{var}' (unsupported by Foreach API). Implicit linking will be used.")
                if initial_val is not None:
                    # Keep the original external node output in symbol_table so internal nodes link directly to it
                    self.symbol_table[var] = initial_val
                continue

            # Create item on output node (auto-creates corresponding socket on input node)
            try:
                item_collection.new(socket_type, var)
                logger.debug(f"  Created loop state item '{var}' with type {socket_type}")
            except Exception as e:
                # Fallback implementation if specific type fails (e.g. older blender versions)
                if socket_type != "GEOMETRY":
                    self.warning(f"  Failed to create socket type {socket_type}, falling back to GEOMETRY: {e}")
                    try:
                        item_collection.new("GEOMETRY", var)
                    except Exception as e2:
                        self.warning(f"  Fallback GEOMETRY creation also failed: {e2}")
                else:
                    self.warning(f"  Failed to create GEOMETRY socket '{var}': {e}")

            # Connect initial value to input node (if available)
            if initial_val is not None and getattr(input_node, "bl_idname", "") != "GeometryNodeForeachGeometryElementInput":
                # Only explicit connections to input_node for things with actual sockets
                self.connect_input(input_node, var, initial_val)
            elif initial_val is not None and socket_type != "GEOMETRY":
                self.connect_input(input_node, var, initial_val)
            
            # Make state vars available in loop body
            # Inside loop body, state vars READ from INPUT node outputs
            if socket_type != "GEOMETRY" or getattr(input_node, "bl_idname", "") != "GeometryNodeForeachGeometryElementInput":
                self.symbol_table[var] = (input_node, var)

        return state_initial_values

    def repeat_zone(self, tree):
        """Handle repeat zone with full syntax:
        repeat iterations, geometry_input, state=(vars):output_vars { body }(outputs)

        Example: repeat 5, mesh, state=(var1):idx, geom { ... }(result=geom, var1)
        """
        # Parse tree using shared helper
        parsed = self._parse_zone_clauses(tree, zone_type='repeat')
        expressions = parsed['expressions']
        state_vars = parsed['state_vars']
        output_var_names = parsed['output_var_names']
        statements = parsed['statements']
        output_items = parsed['output_items']

        # Evaluate expressions: [iterations, geometry_input]
        count = self.evaluate_expression(expressions[0]) if expressions else 1
        geometry_input = self.evaluate_expression(expressions[1]) if len(expressions) > 1 else None

        logger.debug(f"Repeat zone: {count} iterations, geometry_input={geometry_input is not None}, state vars: {state_vars}")

        # Create Repeat Input/Output nodes
        parent = self.frame_stack[-1] if self.frame_stack else None
        repeat_input = self.builder.create_node("repeat_input", parent=parent)
        repeat_output = self.builder.create_node("repeat_output", parent=parent)

        # Pair the nodes (CRITICAL for repeat zones to work)
        if not repeat_input.paired_output:
            repeat_input.pair_with_output(repeat_output)

        # Connect iterations
        self.connect_input(repeat_input, "Iterations", count)

        # Connect geometry input if provided
        if geometry_input:
            self.connect_input(repeat_input, "Geometry", geometry_input)

        # Create state variable sockets
        state_initial_values = self._create_loop_state_sockets(
            state_vars, repeat_input, repeat_output, repeat_output.repeat_items
        )

        # Make output variables available in loop body
        # output_var_names: [iteration_var, geometry_var, ...]
        if len(output_var_names) >= 1 and output_var_names[0]:
            self.symbol_table[output_var_names[0]] = (repeat_input, "Iteration")
        if len(output_var_names) >= 2 and output_var_names[1]:
            self.symbol_table[output_var_names[1]] = (repeat_input, "Geometry")

        # Process statements in loop body
        for stmt in statements:
            self.process_statement(stmt)

        # Process output clause using shared helper
        self._process_zone_outputs(
            output_items, repeat_output, repeat_output.repeat_items,
            state_initial_values, repeat_input, zone_type='repeat'
        )

        self.iteration_var = None

    def simulation_zone(self, tree):
        """Handle simulation zone with syntax:
        simulation{skip:expr} geometry_input, state=(vars):delta_time, geometry { body }(outputs)

        Example: simulation{skip:should_skip} mesh, state=(velocity):dt, geom { ... }(result=new_geom, velocity)
        
        Key differences from repeat_zone:
        - No iterations count
        - Has optional skip attribute (connected to SimulationOutput's Skip socket)
        - First output_var is Delta Time (VALUE), not Iteration (INT)
        - Uses state_items instead of repeat_items
        """
        # Parse tree using shared helper
        parsed = self._parse_zone_clauses(tree, zone_type='simulation')
        expressions = parsed['expressions']
        state_vars = parsed['state_vars']
        output_var_names = parsed['output_var_names']
        statements = parsed['statements']
        output_items = parsed['output_items']
        attributes = parsed['attributes']

        # Evaluate geometry input (simulation has only one optional expression)
        geometry_input = self.evaluate_expression(expressions[0]) if expressions else None

        logger.debug(f"Simulation zone: geometry_input={geometry_input is not None}, state vars: {state_vars}")

        # Create Simulation Input/Output nodes
        parent = self.frame_stack[-1] if self.frame_stack else None
        sim_input = self.builder.create_node("simulation_input", parent=parent)
        sim_output = self.builder.create_node("simulation_output", parent=parent)

        # Pair the nodes (CRITICAL for simulation zones to work)
        if not sim_input.paired_output:
            sim_input.pair_with_output(sim_output)

        # Connect Skip socket if provided in attributes
        if 'skip' in attributes:
            skip_value = attributes['skip']
            if isinstance(skip_value, str) and skip_value in self.symbol_table:
                skip_value = self.symbol_table[skip_value]
            self.connect_input(sim_output, "Skip", skip_value)
            logger.debug(f"  Connected Skip socket to: {skip_value}")

        # Connect geometry input if provided
        if geometry_input:
            self.connect_input(sim_input, "Geometry", geometry_input)

        # Create state variable sockets
        state_initial_values = self._create_loop_state_sockets(
            state_vars, sim_input, sim_output, sim_output.state_items
        )

        # Make output variables available in simulation body
        # output_var_names: [delta_time_var, geometry_var, ...]
        if len(output_var_names) >= 1 and output_var_names[0]:
            self.symbol_table[output_var_names[0]] = (sim_input, "Delta Time")
        if len(output_var_names) >= 2 and output_var_names[1]:
            self.symbol_table[output_var_names[1]] = (sim_input, "Geometry")

        # Process statements in simulation body
        for stmt in statements:
            self.process_statement(stmt)

        # Process output clause using shared helper
        self._process_zone_outputs(
            output_items, sim_output, sim_output.state_items,
            state_initial_values, sim_input, zone_type='simulation'
        )

    def foreach(self, tree):
        """Handle foreach with full syntax:
        foreach{domain:'FACE'} geometry_input, selection, state=(vars):idx, elem { body }(input_items:output_items)

        Example: foreach{domain:'FACE'} mesh, , state=(var1):idx, elem { ... }(result:out3)
        
        Input items (before :) are variables to connect TO loop end node inputs
        Output items (after :) are variables to define FROM loop end node outputs
        """
        # Parse tree using shared helper
        parsed = self._parse_zone_clauses(tree, zone_type='foreach')
        expressions = parsed['expressions']
        state_vars = parsed['state_vars']
        output_var_names = parsed['output_var_names']
        statements = parsed['statements']
        input_items = parsed['input_items']
        output_items = parsed['output_items']
        attributes = parsed['attributes']
        
        # Get domain from attributes
        domain = attributes.get('domain', 'POINT')

        # Evaluate expressions: [geometry_input, selection]
        geometry_input = self.evaluate_expression(expressions[0]) if expressions else None
        selection_input = self.evaluate_expression(expressions[1]) if len(expressions) > 1 else None

        logger.debug(f"Foreach with domain={domain}, geometry_input={geometry_input is not None}, selection={selection_input is not None}, state vars: {state_vars}")

        # Create Foreach Input/Output nodes
        parent = self.frame_stack[-1] if self.frame_stack else None
        foreach_input = self.builder.create_node("foreach_geometry_element_input", parent=parent)
        foreach_output = self.builder.create_node("foreach_geometry_element_output", parent=parent)

        # Set domain property on output node
        if hasattr(foreach_output, 'domain'):
            foreach_output.domain = domain
            logger.debug(f"  Set foreach output domain to {domain}")

        # Pair the nodes (CRITICAL for foreach to work)
        if not foreach_input.paired_output:
            foreach_input.pair_with_output(foreach_output)

        # Connect geometry input if provided
        if geometry_input:
            self.connect_input(foreach_input, "Geometry", geometry_input)

        # Connect selection input if provided
        if selection_input:
            self.connect_input(foreach_input, "Selection", selection_input)

        # Create state variable sockets
        state_initial_values = self._create_loop_state_sockets(
            state_vars, foreach_input, foreach_output, foreach_output.input_items
        )

        # Make output variables available in foreach body
        # output_var_names: [index_var, element_var, ...]
        if len(output_var_names) >= 1 and output_var_names[0]:
            self.symbol_table[output_var_names[0]] = (foreach_input, "Index")
        if len(output_var_names) >= 2 and output_var_names[1]:
            self.symbol_table[output_var_names[1]] = (foreach_input, "Element")

        # Process statements in foreach body
        for stmt in statements:
            self.process_statement(stmt)

        # Process input items: connect variables TO loop end node inputs
        # Foreach is unique: it has bidirectional input/output handling
        for idx, var_name in enumerate(input_items):
            if var_name:  # Not empty slot
                if var_name in self.symbol_table:
                    val = self.symbol_table[var_name]
                    socket_type = self._infer_socket_type(val)

                    if idx == 0:
                        # Connect to existing "Geometry" input socket
                        self.connect_input(foreach_output, "Geometry", val)
                        logger.debug(f"  Connected input_item[{idx}] '{var_name}' to ForeachOutput.Geometry")
                    else:
                        # Check if generation_item already exists
                        item_exists = any(item.name == var_name for item in foreach_output.generation_items)

                        if not item_exists:
                            foreach_output.generation_items.new(socket_type, var_name)
                            logger.debug(f"  Created generation_item '{var_name}' at index {idx} with type {socket_type}")

                        self.connect_input(foreach_output, var_name, val)
                        logger.debug(f"  Connected input_item[{idx}] '{var_name}' to ForeachOutput")

        # Process output items: define variables FROM loop end node outputs
        # Build list of enabled, non-CUSTOM output sockets
        enabled_outputs = [
            (i, output)
            for i, output in enumerate(foreach_output.outputs)
            if output.enabled and output.type != "CUSTOM"
        ]
        
        for idx, (output_name, var_name) in enumerate(output_items):
            if var_name:
                final_name = output_name if output_name else var_name
                if idx < len(enabled_outputs):
                    actual_idx, actual_socket = enabled_outputs[idx]
                    self.symbol_table[final_name] = (foreach_output, actual_idx)
                    logger.debug(f"  Defined output_item[{idx}] '{final_name}' from ForeachOutput output[{actual_idx}]")
                else:
                    self.warning(f"  Output index {idx} out of range for ForeachOutput")

        self.iteration_var = None

    def closure_zone(self, tree):
        """Handle closure zone with syntax:
        my_fn = closure(x: float, y: float) { sum = x + y }(sum)
        or
        closure(x: float, y: float) { sum = x + y }(my_fn = sum)
        """
        attributes = {}
        closure_params = []
        statements = []
        output_items = []

        for child in tree.children:
            if not hasattr(child, "data"):
                continue
            if child.data == "attributes":
                attributes = self.parse_attributes(child)
            elif child.data == "closure_inputs":
                for param_node in child.children:
                    if hasattr(param_node, "data") and param_node.data == "closure_param":
                        name = param_node.children[0].value
                        type_name = "FLOAT"
                        default_val = None
                        idx = 1
                        if idx < len(param_node.children) and hasattr(param_node.children[idx], "type") and param_node.children[idx].type == "TYPE":
                            type_name = param_node.children[idx].value.upper()
                            idx += 1
                        if idx < len(param_node.children):
                            default_val = self.evaluate_value_node(param_node.children[idx])

                        # Map type names
                        type_mapping = {
                            "INT": "INT",
                            "FLOAT": "FLOAT",
                            "VECTOR": "VECTOR",
                            "BOOL": "BOOLEAN",
                            "BOOLEAN": "BOOLEAN",
                            "STRING": "STRING",
                            "COLOR": "RGBA",
                            "RGBA": "RGBA",
                            "ROTATION": "ROTATION",
                            "MATRIX": "MATRIX",
                            "GEOMETRY": "GEOMETRY",
                            "OBJECT": "OBJECT",
                            "COLLECTION": "COLLECTION",
                            "MAT": "MATERIAL",
                            "MATERIAL": "MATERIAL",
                            "SHADER": "SHADER",
                            "IMAGE": "IMAGE",
                            "TEXTURE": "TEXTURE",
                            "MENU": "MENU",
                            "BUNDLE": "BUNDLE",
                            "CLOSURE": "CLOSURE",
                            "INT_VECTOR": "INT_VECTOR",
                        }
                        type_enum = type_mapping.get(type_name, "FLOAT")
                        closure_params.append({"name": name, "type": type_enum, "default": default_val})
            elif child.data == "statement":
                statements.append(child)
            elif child.data == "output_clause":
                for item in child.children:
                    if hasattr(item, "data") and item.data == "output_item":
                        if len(item.children) == 2:
                            output_items.append((item.children[0].value, item.children[1].value))
                        elif len(item.children) == 1:
                            name = item.children[0].value
                            output_items.append((name, name))
                        else:
                            output_items.append((None, None))

        parent = self.frame_stack[-1] if self.frame_stack else None
        c_in = self.builder.create_node("closure_input", parent=parent)
        c_out = self.builder.create_node("closure_output", parent=parent)

        if hasattr(c_in, "pair_with_output") and not c_in.paired_output:
            c_in.pair_with_output(c_out)

        # Save outer scope symbols
        outer_symbols = dict(self.symbol_table)

        try:
            # Add input items to c_out (which creates output sockets on c_in)
            for param in closure_params:
                c_out.input_items.new(param["type"], param["name"])
                self.symbol_table[param["name"]] = (c_in, param["name"])

            # Execute body statements
            for stmt in statements:
                self.process_statement(stmt)

            # Process output items
            closure_target_name = None
            for idx, (out_name, var_name) in enumerate(output_items):
                if var_name:
                    if var_name in self.symbol_table:
                        val = self.symbol_table[var_name]
                        socket_type = self._infer_socket_type(val)
                        item_name = var_name
                        if out_name and out_name != var_name:
                            closure_target_name = out_name

                        item_exists = any(item.name == item_name for item in c_out.output_items)
                        if not item_exists:
                            c_out.output_items.new(socket_type, item_name)

                        self.connect_input(c_out, item_name, val)
        finally:
            self.symbol_table = outer_symbols

        closure_ref = (c_out, "Closure")
        if closure_target_name:
            self.symbol_table[closure_target_name] = closure_ref

        return closure_ref

    def evaluate_closure_call(self, closure_val, args_node=None, attrs_node=None, closure_sig=None):
        """Evaluate a closure: instantiate NodeEvaluateClosure, connect arguments, and return output."""
        parent = self.frame_stack[-1] if self.frame_stack else None
        eval_node = self.builder.create_node("evaluate_closure", parent=parent)

        # Connect Closure input socket
        self.connect_input(eval_node, "Closure", closure_val)

        # Parse attributes (e.g. output='y' or outputs=['s', 'd'])
        attrs = self.parse_attributes(attrs_node) if attrs_node else {}

        # If closure_val is from NodeClosureOutput or IndexSwitch, copy signature items to eval_node
        c_node = None
        if isinstance(closure_val, tuple) and len(closure_val) == 2:
            c_node = closure_val[0]

        # Trace through IndexSwitch if needed
        if c_node and getattr(c_node, "bl_idname", "") == "GeometryNodeIndexSwitch":
            for inp in c_node.inputs:
                if inp.is_linked and inp.name != "Index":
                    upstream = inp.links[0].from_node
                    if getattr(upstream, "bl_idname", "") == "NodeClosureOutput":
                        c_node = upstream
                        break

        if c_node and getattr(c_node, "bl_idname", "") == "NodeClosureOutput":
            if hasattr(c_node, "input_items") and hasattr(eval_node, "input_items"):
                for item in c_node.input_items:
                    if not any(ei.name == item.name for ei in eval_node.input_items):
                        eval_node.input_items.new(item.socket_type, item.name)
            if hasattr(c_node, "output_items") and hasattr(eval_node, "output_items"):
                for item in c_node.output_items:
                    if not any(eo.name == item.name for eo in eval_node.output_items):
                        eval_node.output_items.new(item.socket_type, item.name)

        # If closure_sig is provided, populate input_items and output_items
        if closure_sig:
            for inp_item in closure_sig.get("inputs", []):
                p_name = inp_item.get("name")
                p_type = inp_item.get("type", "FLOAT")
                if p_name and hasattr(eval_node, "input_items") and not any(ei.name == p_name for ei in eval_node.input_items):
                    eval_node.input_items.new(p_type, p_name)
            for out_item in closure_sig.get("outputs", []):
                p_name = out_item.get("name")
                p_type = out_item.get("type", "FLOAT")
                if p_name and hasattr(eval_node, "output_items") and not any(eo.name == p_name for eo in eval_node.output_items):
                    eval_node.output_items.new(p_type, p_name)

        # Handle explicit output item(s) from attributes if provided
        if "output" in attrs:
            out_name = str(attrs["output"])
            default_t = "GEOMETRY" if any(g in out_name.lower() for g in ("geom", "geometry", "mesh")) else "FLOAT"
            out_type = attrs.get("output_type", default_t).upper()
            if hasattr(eval_node, "output_items") and not any(eo.name == out_name for eo in eval_node.output_items):
                eval_node.output_items.new(out_type, out_name)
        elif "outputs" in attrs and isinstance(attrs["outputs"], (list, tuple)):
            for out_item in attrs["outputs"]:
                out_name = str(out_item)
                default_t = "GEOMETRY" if any(g in out_name.lower() for g in ("geom", "geometry", "mesh")) else "FLOAT"
                if hasattr(eval_node, "output_items") and not any(eo.name == out_name for eo in eval_node.output_items):
                    eval_node.output_items.new(default_t, out_name)

        # Connect arguments to eval_node
        if args_node:
            arg_pos = 0
            for child in args_node.children:
                if not child.children:
                    arg_pos += 1
                    continue
                if child.children[0].data == "kwarg":
                    kwarg_node = child.children[0]
                    k_name = kwarg_node.children[0].value
                    k_val = self.evaluate_expression(kwarg_node.children[1])
                    if hasattr(eval_node, "input_items") and not any(ei.name == k_name for ei in eval_node.input_items):
                        val_type = self._infer_socket_type(k_val)
                        eval_node.input_items.new(val_type, k_name)
                    self.connect_input(eval_node, k_name, k_val)
                else:
                    val = self.evaluate_expression(child)
                    if hasattr(eval_node, "input_items"):
                        if arg_pos < len(eval_node.input_items):
                            item_name = eval_node.input_items[arg_pos].name
                            self.connect_input(eval_node, item_name, val)
                        else:
                            sig_inputs = closure_sig.get("inputs", []) if closure_sig else []
                            if arg_pos < len(sig_inputs) and sig_inputs[arg_pos].get("name"):
                                item_name = sig_inputs[arg_pos]["name"]
                            else:
                                item_name = f"arg_{arg_pos}"
                            val_type = self._infer_socket_type(val)
                            eval_node.input_items.new(val_type, item_name)
                            self.connect_input(eval_node, item_name, val)
                    else:
                        self.connect_input(eval_node, arg_pos + 1, val)
                    arg_pos += 1

        # Ensure there is at least one output item
        if hasattr(eval_node, "output_items") and len(eval_node.output_items) == 0:
            target = getattr(self, "_current_assignment_target", None)
            sig_outputs = closure_sig.get("outputs", []) if closure_sig else []
            if sig_outputs and sig_outputs[0].get("name"):
                eval_node.output_items.new(sig_outputs[0].get("type", "FLOAT"), sig_outputs[0]["name"])
            elif isinstance(target, str):
                inferred_type = "FLOAT"
                if any(g in target.lower() for g in ("geom", "geometry", "mesh", "curve", "instance")):
                    inferred_type = "GEOMETRY"
                elif any(v in target.lower() for v in ("pos", "vec", "vector", "dir", "offset", "rot", "rotation")):
                    inferred_type = "VECTOR"
                elif any(c in target.lower() for c in ("col", "color", "rgba")):
                    inferred_type = "RGBA"
                elif any(s in target.lower() for s in ("str", "string", "name", "path")):
                    inferred_type = "STRING"
                elif any(b in target.lower() for b in ("bool", "is_", "has_", "sel", "selection")):
                    inferred_type = "BOOLEAN"
                eval_node.output_items.new(inferred_type, target)
            elif isinstance(target, (list, tuple)):
                for t in target:
                    t_str = str(t)
                    t_type = "GEOMETRY" if any(g in t_str.lower() for g in ("geom", "geometry", "mesh")) else "FLOAT"
                    eval_node.output_items.new(t_type, t_str)
            else:
                eval_node.output_items.new("FLOAT", "result")

        # Return output socket(s)
        if hasattr(eval_node, "output_items") and len(eval_node.output_items) > 0:
            if len(eval_node.output_items) == 1:
                return (eval_node, eval_node.output_items[0].name)
            else:
                return tuple((eval_node, item.name) for item in eval_node.output_items)
        return (eval_node, 0)

    def _compile_group_body(self, group_name, group_info):
        """Compile a group's body and create it in bpy.data.node_groups

        This method is called either when a group is first instantiated, or at the end
        of compilation to ensure all defined groups exist in bpy.data.node_groups.
        """
        logger.debug(f"Compiling group '{group_name}' body...")

        # Create the NodeGroup tree
        display_name = group_info.get("display_name")
        explicit_tree_type = group_info.get("tree_type")
        group_tree = self.builder.create_group(
            group_name=group_name,
            inputs_spec=group_info["inputs"],
            outputs_spec=group_info["outputs"],
            tree_type=explicit_tree_type,
            display_name=display_name,
        )

        # Save current builder context
        prev_node_tree = self.builder.node_tree
        prev_symbol_table = self.symbol_table
        prev_inputs = self.inputs
        prev_outputs = self.outputs
        prev_output_socket_names = getattr(self, "output_socket_names", {})
        prev_current_group = (
            self.current_group if hasattr(self, "current_group") else None
        )
        prev_deferred_menu_defaults = self.deferred_menu_defaults
        prev_closure_signatures = getattr(self, "closure_signatures", {})
        prev_bundle_signatures = getattr(self, "bundle_signatures", {})

        # Switch to group tree context
        self.builder.node_tree = group_tree
        self.symbol_table = {}
        self.inputs = {}
        self.outputs = {}
        self.output_socket_names = {}
        self.deferred_menu_defaults = []
        self.closure_signatures = {}
        self.bundle_signatures = {}
        # Make group info available to assignment method for looking up socket names
        self.current_group = group_info

        # Pre-populate outputs dict with declared group outputs
        # This allows assignments to output variables to be detected and connected
        for out_spec in group_info["outputs"]:
            var_name = out_spec["var_name"]
            # Initialize with None, will be set when assigned
            self.outputs[var_name] = None

        # Map group inputs to symbol table (they come from GroupInput node)
        group_input_node = None
        for node in group_tree.nodes:
            if hasattr(node, "bl_idname") and node.bl_idname == "NodeGroupInput":
                group_input_node = node
                break

        if group_input_node:
            for i, inp_spec in enumerate(group_info["inputs"]):
                var_name = inp_spec["var_name"]
                # Reference the group input node's output socket
                self.symbol_table[var_name] = (group_input_node, i)
                if inp_spec.get("closure_sig"):
                    self.closure_signatures[var_name] = inp_spec["closure_sig"]
                if inp_spec.get("bundle_sig"):
                    self.bundle_signatures[var_name] = inp_spec["bundle_sig"]
                    # Also map under socket_name
                    if inp_spec.get("socket_name"):
                        self.bundle_signatures[inp_spec["socket_name"]] = inp_spec["bundle_sig"]

        # Bug Fix: Builder fails to set default values for Menu sockets because the
        # internal "Menu Switch" hasn't been created yet (so enum list is empty).
        # We must defer setting these defaults until AFTER the group body is compiled.
        if hasattr(group_tree, "interface"):
            # Blender 4.0+
            interface_items = [
                item
                for item in group_tree.interface.items_tree
                if item.item_type == "SOCKET" and item.in_out == "INPUT"
            ]
            
            # Match specs to interface items by index (builder creates them in order)
            if len(interface_items) == len(group_info["inputs"]):
                for i, inp_spec in enumerate(group_info["inputs"]):
                    if inp_spec.get("type") == "menu" and inp_spec.get("default") is not None:
                        socket = interface_items[i]
                        # Verify we have the right socket type just in case
                        if hasattr(socket, "bl_socket_idname") and socket.bl_socket_idname == "NodeSocketMenu":
                            self.deferred_menu_defaults.append({
                                "socket": socket,
                                "value": inp_spec["default"],
                                "display_name": inp_spec["var_name"]
                            })
                            logger.debug(f"Queued deferred default for menu '{inp_spec['var_name']}': {inp_spec['default']}")

        # Process each statement in the group body
        for stmt in group_info[
            "body_ast"
        ]:  # Changed from 'body' to 'body_ast' to match original
            self.process_statement(stmt)

        # Connect outputs to GroupOutput node
        group_output_node = None
        for node in group_tree.nodes:
            if hasattr(node, "bl_idname") and node.bl_idname == "NodeGroupOutput":
                group_output_node = node
                break

        if group_output_node:
            for i, out_spec in enumerate(group_info["outputs"]):
                var_name = out_spec["var_name"]
                if var_name in self.symbol_table:
                    val = self.symbol_table[var_name]
                    self.connect_input(group_output_node, i, val)

        # Process deferred menu defaults for this group
        # before restoring context
        self._set_deferred_menu_defaults()

        # Restore context
        self.builder.node_tree = prev_node_tree
        self.symbol_table = prev_symbol_table
        self.inputs = prev_inputs
        self.outputs = prev_outputs
        self.output_socket_names = prev_output_socket_names
        self.current_group = prev_current_group
        self.deferred_menu_defaults = prev_deferred_menu_defaults
        self.closure_signatures = prev_closure_signatures
        self.bundle_signatures = prev_bundle_signatures

        # Store the compiled group tree
        group_info["node_tree"] = group_tree
        logger.debug(f"Group .* body compiled successfully")

    def _import_group_info(self, group_name, group_tree):
        """Import group metadata from an existing Blender node group"""
        # Build inputs spec from interface to match instantiate_group expectations
        inputs = []
        if hasattr(group_tree, "interface"):
            # Blender 4.0+
            for item in group_tree.interface.items_tree:
                if item.item_type == "SOCKET" and item.in_out == "INPUT":
                    inputs.append(
                        {
                            "var_name": item.name,  # Use socket name as var name since we don't know original var val
                            "socket_name": item.name,
                            "type": "geometry",  # Dummy, type logic not strictly used for connections
                        }
                    )
        else:
            # Older Blender versions (fallback, though XNodify targets 4.0+)
            for inp in group_tree.inputs:
                inputs.append(
                    {"var_name": inp.name, "socket_name": inp.name, "type": "geometry"}
                )

        group_info = {
            "name": group_name,
            "display_name": group_name,
            "inputs": inputs,
            "outputs": [],  # Not needed for instantiation return
            "node_tree": group_tree,  # Prevents recompilation
            "body_ast": [],  # Empty body
        }
        self.groups[group_name] = group_info
        if hasattr(group_tree, "name") and group_tree.name != group_name:
            self.groups[group_tree.name] = group_info
        logger.debug(
            f"Imported external group info for '{group_name}' from Blender data"
        )

    def instantiate_group(self, group_name, args_node, attrs_node):
        """Instantiate a defined group: compile body on first use, create instance"""
        group_info = self.groups[group_name]

        # Compile group body on first instantiation
        if group_info["node_tree"] is None:
            self._compile_group_body(group_name, group_info)

        # Create group instance in current tree
        parent = self.frame_stack[-1] if self.frame_stack else None
        group_node = self.builder.instantiate_group(
            group_tree=group_info["node_tree"],
            name=group_name,  # Use group name directly (matches old xnodify behavior)
            parent=parent,
        )

        logger.debug(f"Created instance of group '{group_name}'")

        connected_indices = set()

        def _connect_by_name(arg_name, val):
            matched_idx = None
            norm_arg = arg_name.replace('_', ' ').lower().strip()
            norm_arg_nospace = arg_name.replace('_', '').replace(' ', '').lower().strip()

            # Pass 1: Exact match on var_name or socket_name
            for idx, inp_spec in enumerate(group_info["inputs"]):
                if idx in connected_indices:
                    continue
                v_name = inp_spec.get("var_name", "")
                s_name = inp_spec.get("socket_name", "")
                if v_name == arg_name or s_name == arg_name:
                    matched_idx = idx
                    break

            # Pass 2: Space & case normalized match
            if matched_idx is None:
                for idx, inp_spec in enumerate(group_info["inputs"]):
                    if idx in connected_indices:
                        continue
                    v_name = inp_spec.get("var_name", "")
                    s_name = inp_spec.get("socket_name", "")
                    if (v_name.replace('_', ' ').lower().strip() == norm_arg or
                        s_name.replace('_', ' ').lower().strip() == norm_arg):
                        matched_idx = idx
                        break

            # Pass 3: No-space & case normalized match
            if matched_idx is None:
                for idx, inp_spec in enumerate(group_info["inputs"]):
                    if idx in connected_indices:
                        continue
                    v_name = inp_spec.get("var_name", "")
                    s_name = inp_spec.get("socket_name", "")
                    if (v_name.replace('_', '').replace(' ', '').lower().strip() == norm_arg_nospace or
                        s_name.replace('_', '').replace(' ', '').lower().strip() == norm_arg_nospace):
                        matched_idx = idx
                        break

            # Pass 4: Direct socket lookup via builder
            if matched_idx is None and hasattr(group_node, "inputs"):
                target_socket = self.builder._get_socket(group_node.inputs, arg_name)
                if target_socket:
                    for idx, s in enumerate(group_node.inputs):
                        if s == target_socket and idx not in connected_indices:
                            matched_idx = idx
                            break

            if matched_idx is not None:
                self.connect_input(group_node, matched_idx, val)
                self._propagate_bundle_signature_to_group(group_info.get("node_tree"), matched_idx, val)
                connected_indices.add(matched_idx)
            else:
                self.builder.set_property(group_node, arg_name, val)

        # Handle attributes in curly braces {}
        if attrs_node:
            for attr in attrs_node.children:
                attr_name = attr.children[0].value
                attr_val_node = attr.children[1]
                attr_val = self.evaluate_value_node(attr_val_node)
                _connect_by_name(attr_name, attr_val)

        # Handle positional & keyword arguments in ()
        if args_node:
            for i, arg in enumerate(args_node.children):
                # Check if arg has children (can be empty for optional args like emission(, 5))
                if not arg.children:
                    continue

                if arg.children[0].data == "kwarg":
                    kwarg_node = arg.children[0]
                    arg_name = kwarg_node.children[0].value
                    val = self.evaluate_expression(kwarg_node.children[1])
                    _connect_by_name(arg_name, val)
                elif arg.children[0].data == "labeled_arg":
                    # Labeled argument: expression @ STRING
                    labeled_node = arg.children[0]
                    val = self.evaluate_expression(labeled_node.children[0])
                    label = labeled_node.children[1].value[1:-1]  # Strip quotes
                    if i < len(group_info["inputs"]):
                        self.connect_input(
                            group_node, i, val, socket_label=label
                        )
                        self._propagate_bundle_signature_to_group(group_info.get("node_tree"), i, val)
                        connected_indices.add(i)
                else:
                    # Positional argument
                    val = self.evaluate_expression(arg.children[0])
                    if i < len(group_info["inputs"]):
                        self.connect_input(group_node, i, val)
                        self._propagate_bundle_signature_to_group(group_info.get("node_tree"), i, val)
                        connected_indices.add(i)

        # Return the group node with first output
        return (group_node, 0)

    def _score_bundle_match(self, items, expected_field_names):
        if not items or not expected_field_names:
            return 0
        item_names = {it[0].lower() for it in items}
        exp_names = {f.lower() for f in expected_field_names if f not in ("_", "")}
        if not exp_names:
            return 0
        matches = 0
        score = 0
        for name in exp_names:
            if name in item_names:
                matches += 1
                if name in ("type", "bundle", "item"):
                    score += 1
                else:
                    score += 10
        # If fewer than half of specific fields match, reject (score = 0)
        specific_expected = [f for f in exp_names if f not in ("type", "bundle", "item")]
        if specific_expected:
            specific_matches = sum(1 for f in specific_expected if f in item_names)
            if specific_matches / len(specific_expected) < 0.5:
                return 0
        return score

    def _get_bundle_items_from_source(self, node, socket_idx_or_name=0, expected_field_names=None):
        """Recursively or directly find bundle items [(name, type), ...] from a node producing a bundle."""
        if not node:
            return None

        candidates = []

        # 1. Direct NodeCombineBundle
        if getattr(node, "bl_idname", "") == "NodeCombineBundle" and hasattr(node, "bundle_items") and len(node.bundle_items) > 0:
            items = [(it.name, it.socket_type) for it in node.bundle_items]
            score = self._score_bundle_match(items, expected_field_names)
            candidates.append((score, items))

            # Also inspect nested bundle inputs of NodeCombineBundle
            if hasattr(node, "inputs"):
                for inp in node.inputs:
                    if inp.is_linked and inp.name != "" and getattr(inp, "bl_idname", "") in ("NodeSocketBundle", "NodeSocketVirtual"):
                        nested = self._get_bundle_items_from_source(inp.links[0].from_node, inp.links[0].from_socket.name, expected_field_names)
                        if nested:
                            nested_score = self._score_bundle_match(nested, expected_field_names)
                            candidates.append((nested_score, nested))

        # 2. NodeSeparateBundle
        # (Follow the input Bundle to find what was connected to the specific output socket_idx_or_name)
        elif getattr(node, "bl_idname", "") == "NodeSeparateBundle" and hasattr(node, "inputs"):
            bundle_in = node.inputs.get("Bundle")
            if bundle_in and bundle_in.is_linked:
                outer_node = bundle_in.links[0].from_node
                outer_sock = bundle_in.links[0].from_socket
                nested = self._get_bundle_items_from_source(outer_node, socket_idx_or_name, expected_field_names)
                if nested:
                    nested_score = self._score_bundle_match(nested, expected_field_names)
                    candidates.append((nested_score, nested))

        # 3. NodeGetBundleItem
        elif getattr(node, "bl_idname", "") == "NodeGetBundleItem" and hasattr(node, "inputs"):
            bundle_in = node.inputs.get("Bundle")
            if bundle_in and bundle_in.is_linked:
                outer_node = bundle_in.links[0].from_node
                outer_sock = bundle_in.links[0].from_socket
                # Look inside outer_node inputs for nested bundles
                if hasattr(outer_node, "inputs"):
                    for inp in outer_node.inputs:
                        if inp.is_linked and inp.name != "":
                            src_node = inp.links[0].from_node
                            src_sock = inp.links[0].from_socket
                            nested = self._get_bundle_items_from_source(src_node, src_sock.name, expected_field_names)
                            if nested:
                                nested_score = self._score_bundle_match(nested, expected_field_names)
                                candidates.append((nested_score, nested))
                nested = self._get_bundle_items_from_source(outer_node, outer_sock.name, expected_field_names)
                if nested:
                    nested_score = self._score_bundle_match(nested, expected_field_names)
                    candidates.append((nested_score, nested))

        # 4. Group Node (GeometryNodeGroup, ShaderNodeGroup)
        elif hasattr(node, "node_tree") and node.node_tree:
            gt = node.node_tree
            out_socket_name = None
            if isinstance(socket_idx_or_name, int) and hasattr(node, "outputs") and socket_idx_or_name < len(node.outputs):
                out_socket_name = node.outputs[socket_idx_or_name].name
            elif isinstance(socket_idx_or_name, str):
                out_socket_name = socket_idx_or_name

            gout = next((n for n in gt.nodes if getattr(n, "bl_idname", "") == "NodeGroupOutput"), None)
            if gout:
                for inp in gout.inputs:
                    if (out_socket_name and inp.name == out_socket_name) or (not out_socket_name and inp.is_linked):
                        if inp.is_linked:
                            internal_from_node = inp.links[0].from_node
                            internal_from_sock = inp.links[0].from_socket
                            nested = self._get_bundle_items_from_source(internal_from_node, internal_from_sock.name, expected_field_names)
                            if nested:
                                nested_score = self._score_bundle_match(nested, expected_field_names)
                                candidates.append((nested_score, nested))

        # 5. NodeStoreBundleItem or NodeJoinBundle
        elif getattr(node, "bl_idname", "") in ("NodeStoreBundleItem", "NodeJoinBundle") and hasattr(node, "inputs"):
            for inp in node.inputs:
                if inp.is_linked and "bundle" in inp.name.lower():
                    nested = self._get_bundle_items_from_source(inp.links[0].from_node, inp.links[0].from_socket.name, expected_field_names)
                    if nested:
                        nested_score = self._score_bundle_match(nested, expected_field_names)
                        candidates.append((nested_score, nested))

        # 6. Fallback: Search all known group definitions in self.groups
        if hasattr(self, "groups"):
            target_str = str(socket_idx_or_name).lower().replace("_", "") if socket_idx_or_name is not None else ""
            for g_name, g_info in self.groups.items():
                tree = g_info.get("node_tree")
                if tree and hasattr(tree, "nodes"):
                    for n in tree.nodes:
                        if getattr(n, "bl_idname", "") == "NodeCombineBundle" and hasattr(n, "bundle_items"):
                            items = [(it.name, it.socket_type) for it in n.bundle_items]
                            score = self._score_bundle_match(items, expected_field_names) if expected_field_names else 0
                            g_clean = g_name.lower().replace("_", "")
                            if target_str and target_str not in ("obj", "item", "bundle", "value", "0", "1") and (target_str == g_clean or (len(target_str) >= 5 and (target_str in g_clean or g_clean in target_str))):
                                score += 30
                            if score >= 10:
                                candidates.append((score, items))

        if candidates:
            # Sort by score descending and return the best match
            candidates.sort(key=lambda x: x[0], reverse=True)
            if expected_field_names:
                # If we have expected_field_names and the best candidate has a non-zero score
                if candidates[0][0] > 0:
                    return candidates[0][1]
            return candidates[0][1]

        return None

    def _propagate_bundle_signature_to_group(self, group_tree, group_input_index, from_val):
        """Automatically refresh group bundle signature when a bundle is plugged into a group input."""
        if not group_tree or not hasattr(group_tree, "nodes") or not from_val:
            return

        # Extract bundle_items from from_val
        bundle_items = None
        if isinstance(from_val, tuple) and len(from_val) == 2 and hasattr(from_val[0], "outputs"):
            from_node = from_val[0]
            from_sock = from_val[1]
            bundle_items = self._get_bundle_items_from_source(from_node, from_sock)

        if not bundle_items:
            return

        # Find Group Input node in group_tree
        group_input_node = next((n for n in group_tree.nodes if getattr(n, "bl_idname", "") == "NodeGroupInput"), None)
        if not group_input_node or group_input_index >= len(group_input_node.outputs):
            return

        in_socket = group_input_node.outputs[group_input_index]
        if not in_socket.is_linked:
            return

        from socket_types import get_bundle_type

        # Propagate bundle types to all connected NodeSeparateBundle nodes
        for link in in_socket.links:
            to_node = link.to_node
            if getattr(to_node, "bl_idname", "") == "NodeSeparateBundle" and hasattr(to_node, "bundle_items"):
                for i, b_item in enumerate(bundle_items):
                    target_name = getattr(b_item, "name", None) or (b_item[0] if isinstance(b_item, (tuple, list)) else f"Item {i+1}")
                    target_type = getattr(b_item, "socket_type", None) or (b_item[1] if isinstance(b_item, (tuple, list)) else "FLOAT")
                    if i < len(to_node.bundle_items):
                        to_node.bundle_items[i].name = target_name
                        to_node.bundle_items[i].socket_type = target_type
                    else:
                        to_node.bundle_items.new(target_type, target_name)

                # Propagate downstream from to_node outputs to connected NodeCombineBundle nodes
                for out_sock in to_node.outputs:
                    if out_sock.is_linked:
                        for out_link in out_sock.links:
                            downstream_node = out_link.to_node
                            downstream_socket = out_link.to_socket
                            if getattr(downstream_node, "bl_idname", "") == "NodeCombineBundle" and hasattr(downstream_node, "bundle_items"):
                                from_type = get_bundle_type(getattr(out_sock, "bl_idname", "")) or getattr(out_sock, "type", "FLOAT")
                                for cb_item in downstream_node.bundle_items:
                                    if cb_item.name == downstream_socket.name and from_type:
                                        cb_item.socket_type = from_type

    def index_access(self, tree):
        """Handle array/list indexing: expr[index]

        Used for:
        - Socket selection: object_info()[1] - select output socket 1
        - Negative socket index: extrude_mesh()[-1] - select last output socket
        - Python list / tuple indexing: py.my_list[-1]

        Returns: (node, socket_index) tuple or indexed element
        """
        base = self.evaluate_expression(tree.children[0])
        index_expr = self.evaluate_expression(tree.children[1])

        # Extract numeric index
        if isinstance(index_expr, (int, float)):
            idx = int(index_expr)
        elif isinstance(index_expr, Token) and index_expr.type == "NUMBER":
            idx = int(float(index_expr.value))
        else:
            # Can't determine index, return base unchanged
            self.warning(f" Non-constant index in array access: {index_expr}")
            return base

        # If base is a (node, socket) tuple
        if isinstance(base, tuple) and len(base) == 2 and hasattr(base[0], "outputs"):
            node, socket_idx = base

            valid_outputs = [
                i for i, output in enumerate(node.outputs)
                if output.identifier != "__extend__" and getattr(output, "type", "") != "CUSTOM"
            ]
            if not valid_outputs:
                valid_outputs = list(range(len(node.outputs)))

            total_valid = len(valid_outputs)

            # Support python-style negative indexing
            if idx < 0:
                resolved_pos = total_valid + idx
            else:
                resolved_pos = idx

            if 0 <= resolved_pos < total_valid:
                actual_idx = valid_outputs[resolved_pos]
                return (node, actual_idx)
            else:
                self.warning(
                    f" Socket index {idx} (resolved to {resolved_pos}) out of range for {node.name} (has {total_valid} valid outputs)"
                )
                return (node, idx)

        # Handle indexing on general Python sequences (list, tuple)
        if isinstance(base, (list, tuple)):
            try:
                return base[idx]
            except IndexError:
                self.warning(f" Index {idx} out of range for sequence of length {len(base)}")
                return base

        # Otherwise return base unchanged
        return base

    def attr_access(self, tree):
        """Handle attribute selection: node.field mapped to node outputs.
        
        Used for:
        - Named socket selection: raycast().hit_position
        
        Returns: (node, socket_index) tuple matching the field name.
        """
        base = self.evaluate_expression(tree.children[0])
        attr_name = getattr(tree.children[1], "value", str(tree.children[1]))

        # Only handle node output tuple accesses
        if isinstance(base, tuple) and len(base) == 2:
            node = base[0]

            key_norm = attr_name.replace('_', ' ').lower().strip()
            key_nospace = attr_name.replace('_', '').replace(' ', '').lower().strip()

            def matches_name(cand):
                if not cand:
                    return False
                c_norm = cand.replace('_', ' ').lower().strip()
                c_nospace = cand.replace('_', '').replace(' ', '').lower().strip()
                return cand.lower() == attr_name.lower() or c_norm == key_norm or c_nospace == key_nospace

            # 1. Prefer enabled outputs matching label
            for i, out in enumerate(node.outputs):
                out_label = getattr(out, 'label', '')
                if out_label and matches_name(out_label) and getattr(out, 'enabled', True):
                    return (node, i)

            # 2. Prefer enabled outputs matching name or identifier
            for i, out in enumerate(node.outputs):
                out_name = getattr(out, 'name', '')
                out_id = getattr(out, 'identifier', '')
                if (matches_name(out_name) or (out_id and matches_name(out_id))) and getattr(out, 'enabled', True):
                    return (node, i)

            # 3. Fallback to any matching output
            for i, out in enumerate(node.outputs):
                out_label = getattr(out, 'label', '')
                out_name = getattr(out, 'name', '')
                out_id = getattr(out, 'identifier', '')
                if (out_label and matches_name(out_label)) or matches_name(out_name) or (out_id and matches_name(out_id)):
                    return (node, i)

            self.warning(
                f"Output socket '{attr_name}' not found for node '{node.name}'. Available: {[getattr(o, 'label', None) or o.name for o in node.outputs]}"
            )
            return base

        # Fallback if not a node output tuple
        return base

    def concat(self, tree):
        """Handle concatenation operator: expr ~ expr ~ expr

        Creates a list of all concatenated items.
        Used primarily with multi-input functions like _joingeom.

        Also handles tuple expressions like (1, 0, 0) for vectors.

        Example: a ~ b ~ c returns [a, b, c]
        Example: (1, 0, 0) creates a vector constant node
        """
        items = []

        # Collect all terms in the concatenation
        for child in tree.children:
            if child.data == "term":
                val = self.evaluate_expression(child)
                items.append(val)

        # If only one item, return it directly (not as list)
        if len(items) == 1:
            return items[0]

        # Check if all items are numeric constants (not node references)
        # If so, this is a vector tuple like (1, 0, 0) and we should create a vector constant node
        all_numeric = all(isinstance(item, (int, float)) for item in items)

        if all_numeric and len(items) in [2, 3, 4]:  # Vector2, Vector3, or Vector4
            # Create a vector constant node
            # Lookup canonical name from bl_idname (stable Blender identifier)
            parent = self.frame_stack[-1] if self.frame_stack else None
            combine_xyz_name = self.builder.registry.get_canonical_name("ShaderNodeCombineXYZ")
            node = self.builder.create_node(combine_xyz_name, parent=parent)

            # Set the vector components
            vector_value = tuple(items)
            if len(vector_value) >= 1:
                node.inputs[0].default_value = vector_value[0]  # X
            if len(vector_value) >= 2:
                node.inputs[1].default_value = vector_value[1]  # Y
            if len(vector_value) >= 3:
                node.inputs[2].default_value = vector_value[2]  # Z

            # Return (node, socket) tuple
            return (node, 0)

        # Return list of items (for concatenation operator ~)
        return items
