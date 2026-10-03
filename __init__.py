bl_info = {
    "name": "XNodify",
    "author": "Shrinivas Kulkarni",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "Node Editor / Text Editor > Sidebar > XNodify",
    "description": "Declarative scripting language (XFY) for Blender Geometry Nodes and Shader Nodes",
    "category": "Node",
    "doc_url": "https://github.com/Shriinivas/xnodify",
    "tracker_url": "https://github.com/Shriinivas/xnodify/issues",
}

import bpy
import os
import sys
from bpy.props import StringProperty, PointerProperty, BoolProperty, EnumProperty
from bpy.types import Operator, Panel, PropertyGroup, AddonPreferences

# Add the addon directory and vendored dependencies to path
addon_dir = os.path.dirname(__file__)
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

vendor_dir = os.path.join(addon_dir, "vendor")
if os.path.exists(vendor_dir) and vendor_dir not in sys.path:
    sys.path.insert(0, vendor_dir)

# Get addon key for preferences
addon_key = __name__.split(".")[0]

# Import from the same package/directory
try:
    from .parser import parse
    from .compiler import Compiler
    from .builder import BlenderNodeBuilder
    from .registry import NodeRegistry
    from .lineupnodes import displayTree
except ImportError:
    # Fallback for standalone / script execution
    from parser import parse
    from compiler import Compiler
    from builder import BlenderNodeBuilder
    from registry import NodeRegistry
    try:
        from lineupnodes import displayTree
    except ImportError:
        displayTree = None


def get_prefs(context):
    """Get addon preferences (stores last file path)"""
    ad = context.preferences.addons.get(addon_key)
    if ad:
        return ad.preferences
    return None


class XNodifyPreferences(AddonPreferences):
    """Addon preferences to store persistent settings"""

    bl_idname = addon_key

    last_path: StringProperty(
        name="Last Script Path",
        description="Path to the last executed .xfy script file",
        subtype="FILE_PATH",
        default="",
    )

    clear_existing: BoolProperty(
        name="Clear Existing Nodes",
        description="Clear existing nodes before creating new ones",
        default=True,
    )

    arrange_nodes: BoolProperty(
        name="Auto Arrange Nodes",
        description="Automatically arrange nodes after generation",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "last_path")
        layout.prop(self, "clear_existing")
        layout.prop(self, "arrange_nodes")


def arrange_nodes(node_tree, context, include_group=True):
    """
    Arrange nodes in the tree using lineupnodes.

    Args:
        node_tree: The node tree to arrange
        context: Blender context
        include_group: Whether to recursively enter and arrange sub-groups (default True)
    """
    # Skip arrangement if displayTree is unavailable or in background mode
    if not displayTree or bpy.app.background:
        return

    try:

        # --- UI Context Switch Setup ---
        # Find a NODE_EDITOR space to hijack so Blender can compute node dimensions
        target_tree_type = getattr(node_tree, "bl_idname", "GeometryNodeTree")
        hijacked_space = None
        orig_tree_type = None
        orig_node_tree = None
        orig_pin = None
        
        for area in context.screen.areas:
            if area.type == "NODE_EDITOR":
                hijacked_space = area.spaces.active
                break
                
        if hijacked_space:
            orig_tree_type = hijacked_space.tree_type
            orig_node_tree = hijacked_space.node_tree
            orig_pin = hijacked_space.pin
            
            # Switch the UI to the correct tree type and assign our tree
            if hijacked_space.tree_type != target_tree_type:
                try:
                    hijacked_space.tree_type = target_tree_type
                except Exception:
                    pass
            try:
                hijacked_space.node_tree = node_tree
                hijacked_space.pin = True
            except Exception:
                pass

        # Force redraw to ensure node dimensions are computed
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)

        # Get lineup params if available, otherwise use defaults
        params = getattr(bpy.context.window_manager, "lineupNodeParams", None)
        inc_grp = params.includeGroup if params else include_group
        if params:
            displayTree(
                node_tree,
                params.vAlign,
                params.xOffset,
                params.yOffset,
                inc_grp,
                params.arrangeType,
                params.maxColNodes,
            )
        else:
            # Use sensible defaults
            displayTree(
                node_tree,
                vAlign="MIDDLE",
                xOffset=50,
                yOffset=50,
                includeGroup=include_group,
                arrangeType="LAST",
                maxColNodes=10,
            )
            
        # --- UI Context Switch Teardown ---
        if hijacked_space:
            try:
                hijacked_space.pin = orig_pin
                if hijacked_space.tree_type != orig_tree_type:
                    hijacked_space.tree_type = orig_tree_type
                hijacked_space.node_tree = orig_node_tree
            except Exception:
                pass
            # Final redraw to clean up
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    except ImportError:
        pass  # lineupnodes not available - skip silently
    except Exception as e:
        print(f"Node arrangement error: {e}")


def sync_nodes(node_tree, context):
    """
    Sync bundle nodes in the tree using sockets_sync operator.
    This ensures dynamic sockets are correctly created/updated.
    
    Args:
        node_tree: The node tree to sync
        context: Blender context
    """
    import bpy
    
    # Check if operator exists
    if not hasattr(bpy.ops.node, "sockets_sync"):
        return

    nodes_to_sync = []
    for node in node_tree.nodes:
        # If node already defines its signature or has bundle items created by compiler, skip sync
        if getattr(node, "define_signature", False):
            continue
        if hasattr(node, "bundle_items") and len(node.bundle_items) > 0:
            continue
        if node.bl_idname in ("NodeSeparateBundle", "NodeCombineBundle"):
            nodes_to_sync.append(node)
             
    if not nodes_to_sync:
        return
        
    # Sort nodes to sync: Process downstream (Separate) before upstream (Combine)
    # This seemingly reverse order helps when Separate loop-breaking affects Combine
    nodes_to_sync.sort(key=lambda n: 0 if n.bl_idname == "NodeSeparateBundle" else 1)

    print(f"Syncing {len(nodes_to_sync)} bundle node(s)...")

    # Find Node Editor context
    area = None
    region = None
    space = None
    window = context.window
    screen = context.screen
    
    # Try finding via window manager first
    if not area and context.window_manager and context.window_manager.windows:
        for w in context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == "NODE_EDITOR":
                    window = w
                    screen = w.screen
                    area = a
                    break
            if area:
                break
    
    # Fallback/Current context check
    if not area and hasattr(context, "screen") and context.screen:
         for a in context.screen.areas:
             if a.type == "NODE_EDITOR":
                 area = a
                 screen = context.screen
                 break

    if area:
        space = area.spaces.active
        # Ensure space is viewing our tree
        if space.node_tree != node_tree:
            # We can't easily switch the view without side effects, 
            # but for sync we might need it. 
            # Ideally we find the space that IS viewing it, or we temporarily set it.
            pass
            
        for r in area.regions:
            if r.type == "WINDOW":
                region = r
                break

    def get_links(node):
        """Store incoming links to a node."""
        links_data = []
        for input_socket in node.inputs:
            if input_socket.is_linked:
                for link in input_socket.links:
                    links_data.append({
                        "from_node": link.from_node,
                        "from_socket": link.from_socket,
                        "to_node": link.to_node,
                        "to_socket_index": list(node.inputs).index(input_socket),
                        "to_socket_name": input_socket.name
                    })
        return links_data

    def restore_links(node, links_data):
        """Restore links to a node."""
        for link_info in links_data:
            from_node = link_info["from_node"]
            from_socket = link_info["from_socket"]
            to_node = node
            
            # Try to find target socket by name first (more robust for dynamic sockets)
            to_socket = None
            if link_info["to_socket_name"] in to_node.inputs:
                to_socket = to_node.inputs[link_info["to_socket_name"]]
            # Fallback to index if name fails or socket renamed (less reliable for bundles)
            elif link_info["to_socket_index"] < len(to_node.inputs):
                to_socket = to_node.inputs[link_info["to_socket_index"]]
                
            if to_socket:
                try:
                    # Check if already connected to the correct socket
                    already_connected = False
                    if to_socket.is_linked:
                        for link in to_socket.links:
                            if link.from_socket == from_socket:
                                already_connected = True
                                break
                    
                    if not already_connected:
                        node_tree.links.new(from_socket, to_socket)
                        # print(f"  Restored link to {to_node.name}.{to_socket.name}")
                except Exception as e:
                    print(f"  Failed to restore link to {to_node.name}.{to_socket.name}: {e}")
            else:
                print(f"  Could not find target socket for restore: {link_info['to_socket_name']}")

    def get_outgoing_links(node):
        """Store outgoing links from a node."""
        links_data = []
        for output_socket in node.outputs:
            if output_socket.is_linked:
                for link in output_socket.links:
                    links_data.append({
                        "from_socket_name": output_socket.name,
                        "from_socket_index": list(node.outputs).index(output_socket),
                        "to_node": link.to_node,
                        # Store target socket index/name just in case, though object ref usually works
                        "to_socket": link.to_socket 
                    })
        return links_data

    def restore_outgoing_links(node, links_data):
        """Restore outgoing links from a node."""
        for link_info in links_data:
            to_node = link_info["to_node"]
            to_socket = link_info["to_socket"]
            
            # Find the new output socket on the synced node
            from_socket = None
            if link_info["from_socket_name"] in node.outputs:
                from_socket = node.outputs[link_info["from_socket_name"]]
            elif link_info["from_socket_index"] < len(node.outputs):
                from_socket = node.outputs[link_info["from_socket_index"]]
                
            if from_socket:
                try:
                    # Check if already connected
                    already_connected = False
                    if from_socket.is_linked:
                        for link in from_socket.links:
                            if link.to_socket == to_socket:
                                already_connected = True
                                break
                    
                    if not already_connected:
                        node_tree.links.new(from_socket, to_socket)
                        # print(f"  Restored outgoing link from {node.name}.{from_socket.name} to {to_node.name}")
                except Exception as e:
                    print(f"  Failed to restore outgoing link: {e}")
            else:
                 print(f"  Could not find source socket for restore: {link_info['from_socket_name']}")

    def run_sync(node, override_ctx=None):
        # Store links of the node itself
        node_links = get_links(node)
        
        # Also store links of connected upstream bundle nodes (specifically CombineBundle)
        # because syncing SeparateBundle might reset them
        upstream_links = {}
        if node.bl_idname == "NodeSeparateBundle":
             if "Bundle" in node.inputs and node.inputs["Bundle"].is_linked:
                 link = node.inputs["Bundle"].links[0]
                 upstream_node = link.from_node
                 if upstream_node.bl_idname == "NodeCombineBundle":
                     upstream_links[upstream_node] = get_links(upstream_node)

        # Store outgoing links (downstream connections)
        # This is crucial for SeparateBundle potentially disconnecting from Group Output during sync
        outgoing_links_data = get_outgoing_links(node)

        # Select and activate
        try:
            for n in node_tree.nodes:
                n.select = False
            node.select = True
            node_tree.nodes.active = node
        except:
            pass
            
        # 1. Try direct update (kept for completeness, though user says it fails)
        if hasattr(node, "socket_value_update"):
            try:
                if override_ctx:
                     with context.temp_override(**override_ctx):
                         node.socket_value_update(context)
                         node.update()
                else:
                     node.socket_value_update(context)
                     node.update()
            except Exception as e:
                print(f"  Direct update failed for {node.name}: {e}")
        
        # 2. Operator fallback - Always run
        try:
            if override_ctx:
                with context.temp_override(**override_ctx):
                    bpy.ops.node.sockets_sync(node_name=node.name)
            else:
                bpy.ops.node.sockets_sync(node_name=node.name)
        except Exception as e:
            print(f"  Operator sync failed for {node.name}: {e}")

        # Restore links
        if node_links:
            restore_links(node, node_links)
            
        for up_node, links in upstream_links.items():
            restore_links(up_node, links)

        if outgoing_links_data:
            restore_outgoing_links(node, outgoing_links_data)


    if area and region and space:
        override = {
            "window": window,
            "screen": screen,
            "area": area,
            "region": region,
            "space_data": space,
        }
        if hasattr(context, "active_object") and context.active_object:
            override["active_object"] = context.active_object
            override["object"] = context.active_object

        # Redraw
        try:
            if hasattr(bpy.ops.wm, "redraw_timer"):
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        except:
            pass
            
        for node in nodes_to_sync:
            run_sync(node, override)
            
        # Redraw
        try:
            if hasattr(bpy.ops.wm, "redraw_timer"):
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        except:
            pass
    else:
        print("Warning: No NODE_EDITOR context found for sync.")
        for node in nodes_to_sync:
            run_sync(node)


def extract_sequential_top_level_items(ast, default_tree_name, filepath=None, context=None, tree_type=None):
    """
    Extract top-level items from AST in exact script order of appearance:
    - material_block: object blocks representing materials
    - geometry_block: object blocks representing geometry trees or main statements
    - group_def: group definitions
    - python_block: python execution blocks
    """
    items = []
    main_stmts = []

    for stmt in ast.children:
        if hasattr(stmt, "data") and stmt.data == "statement" and stmt.children:
            inner_stmt = stmt.children[0]
            if hasattr(inner_stmt, "data"):
                if inner_stmt.data in ("object_block", "object_block_implicit"):
                    children = inner_stmt.children
                    if inner_stmt.data == "object_block":
                        object_name = children[0].value.strip("\"'")
                        idx = 1
                    else:
                        object_name = None
                        idx = 0

                    explicit_domain = None
                    tree_name = None

                    if idx < len(children) and hasattr(children[idx], "data") and children[idx].data in ("material_domain", "geometry_domain"):
                        explicit_domain = "ShaderNodeTree" if children[idx].data == "material_domain" else "GeometryNodeTree"
                        idx += 1

                    if idx < len(children) and hasattr(children[idx], "type") and children[idx].type == "STRING":
                        tree_name = children[idx].value.strip("\"'")
                        idx += 1

                    block_statements = children[idx:]

                    if explicit_domain:
                        is_material = (explicit_domain == "ShaderNodeTree")
                    else:
                        is_material = is_material_ast_block(block_statements, filepath, context=context, tree_type=tree_type)

                    kind = "material_block" if is_material else "geometry_block"
                    items.append((kind, object_name, tree_name, explicit_domain, block_statements))

                elif inner_stmt.data == "world_block":
                    children = inner_stmt.children
                    world_name = None
                    idx = 0
                    if idx < len(children) and hasattr(children[idx], "data") and children[idx].data in ("material_domain", "geometry_domain"):
                        idx += 1
                    if idx < len(children) and hasattr(children[idx], "type") and children[idx].type == "STRING":
                        world_name = children[idx].value.strip("\"'")
                        idx += 1
                    block_statements = children[idx:]
                    items.append(("world_block", None, world_name, "ShaderNodeTree", block_statements))

                elif inner_stmt.data == "scene_block":
                    children = inner_stmt.children
                    scene_name = children[0].value.strip("\"'")
                    world_name = None
                    idx = 1
                    if idx < len(children) and hasattr(children[idx], "data") and children[idx].data in ("material_domain", "geometry_domain"):
                        idx += 1
                    if idx < len(children) and hasattr(children[idx], "type") and children[idx].type == "STRING":
                        world_name = children[idx].value.strip("\"'")
                        idx += 1
                    block_statements = children[idx:]
                    items.append(("world_block", scene_name, world_name, "ShaderNodeTree", block_statements))

                elif inner_stmt.data in ("group_def", "python_block"):
                    items.append((inner_stmt.data, stmt))
                else:
                    main_stmts.append(stmt)
            else:
                main_stmts.append(stmt)
        else:
            main_stmts.append(stmt)

    if main_stmts:
        if is_world_ast_block(main_stmts):
            items.append(("world_block", None, default_tree_name, "ShaderNodeTree", main_stmts))
        elif is_material_ast_block(main_stmts, filepath, context=context, tree_type=tree_type):
            items.append(("material_block", None, default_tree_name, "ShaderNodeTree", main_stmts))
        else:
            items.append(("geometry_block", None, default_tree_name, "GeometryNodeTree", main_stmts))

    return items


def extract_object_blocks(ast, default_tree_name):
    """
    Extract object_block statements from AST.

    Returns:
        List of (object_name, tree_name, explicit_domain, block_statements) tuples.
        If no object blocks, returns empty list.
    """
    object_blocks = []
    main_stmts = []

    for stmt in ast.children:
        if hasattr(stmt, "data") and stmt.data == "statement" and stmt.children:
            inner_stmt = stmt.children[0]
            if hasattr(inner_stmt, "data"):
                if inner_stmt.data == "object_block":
                    # object_block: "object" STRING domain_type? ("as" STRING)? "{" statement* "}"
                    children = inner_stmt.children
                    object_name = children[0].value.strip("\"'")
                    
                    explicit_domain = None
                    tree_name = None
                    idx = 1
                    
                    if idx < len(children) and hasattr(children[idx], "data") and children[idx].data in ("material_domain", "geometry_domain"):
                        explicit_domain = "ShaderNodeTree" if children[idx].data == "material_domain" else "GeometryNodeTree"
                        idx += 1
                        
                    if idx < len(children) and hasattr(children[idx], "type") and children[idx].type == "STRING":
                        tree_name = children[idx].value.strip("\"'")
                        idx += 1
                        
                    block_statements = children[idx:]
                    object_blocks.append((object_name, tree_name, explicit_domain, block_statements))
                    
                elif inner_stmt.data == "object_block_implicit":
                    # object_block_implicit: "object" domain_type? ("as" STRING)? "{" statement* "}"
                    children = inner_stmt.children
                    object_name = None
                    
                    explicit_domain = None
                    tree_name = None
                    idx = 0
                    
                    if idx < len(children) and hasattr(children[idx], "data") and children[idx].data in ("material_domain", "geometry_domain"):
                        explicit_domain = "ShaderNodeTree" if children[idx].data == "material_domain" else "GeometryNodeTree"
                        idx += 1
                        
                    if idx < len(children) and hasattr(children[idx], "type") and children[idx].type == "STRING":
                        tree_name = children[idx].value.strip("\"'")
                        idx += 1
                        
                    block_statements = children[idx:]
                    object_blocks.append((object_name, tree_name, explicit_domain, block_statements))
                elif inner_stmt.data in ("group_def", "python_block"):
                    pass # Handled globally/separately
                else:
                    main_stmts.append(stmt)
            else:
                main_stmts.append(stmt)
        else:
            main_stmts.append(stmt)
            
    if main_stmts:
        # Wrap the remaining top-level statements in an implicit object block
        object_blocks.append((None, default_tree_name, None, main_stmts))

    return object_blocks


def extract_global_statements(ast):
    """
    Extract global statements (not inside object blocks).
    These include: group definitions ONLY.

    Returns:
        List of AST statement nodes.
    """
    global_stmts = []

    for stmt in ast.children:
        if hasattr(stmt, "data") and stmt.data == "statement" and stmt.children:
            inner_stmt = stmt.children[0]
            if hasattr(inner_stmt, "data") and inner_stmt.data in ("group_def",):
                global_stmts.append(stmt)

    return global_stmts

def is_world_ast_block(block_stmts):
    """
    Check if an AST block contains world shader nodes (output_world, ShaderNodeOutputWorld).
    """
    def check_world(node):
        if not hasattr(node, 'data'):
            return False
        if node.data in ("function_call", "function_call_statement") and len(node.children) > 0:
            name_node = node.children[0]
            raw_name = getattr(name_node, 'value', str(name_node)).lower()
            if raw_name in ("output_world", "world_output", "shadernodeoutputworld"):
                return True
        for child in getattr(node, 'children', []):
            if hasattr(child, 'data') or hasattr(child, 'value'):
                if check_world(child):
                    return True
        return False

    return any(check_world(stmt) for stmt in block_stmts)


def is_material_ast_block(block_stmts, filepath=None, context=None, registry=None, tree_type=None):
    """
    Check if an AST block contains material-specific nodes or was invoked from Shader Editor.
    Used to distinguish between ShaderNodeTree and GeometryNodeTree object blocks.
    """
    if is_world_ast_block(block_stmts):
        return False

    if registry is None:
        try:
            registry = NodeRegistry(include_material_nodes=True)
        except Exception:
            registry = None

    try:
        from .shortcuts import expand_function_shortcut
    except ImportError:
        from shortcuts import expand_function_shortcut

    # Nodes that the compiler remaps between tree types (e.g. compare -> math in ShaderNodeTree).
    # These work in both contexts so should not force the block to be geometry-only.
    cross_context_nodes = {"compare"}

    def check_node(node):
        if not hasattr(node, 'data'):
            return False, False

        # function_call_statement wraps a function_call Tree as its first child,
        # NOT a name Token. Delegate to children so the inner function_call is
        # processed correctly instead of stringifying the Tree as a name.
        if node.data == "function_call_statement":
            mat, geo = False, False
            for child in node.children:
                if hasattr(child, 'data') or hasattr(child, 'value'):
                    m, g = check_node(child)
                    mat = mat or m
                    geo = geo or g
            return mat, geo

        if node.data == "function_call":
            self_mat, self_geo = False, False
            if len(node.children) > 0:
                name_node = node.children[0]
                raw_name = getattr(name_node, 'value', str(name_node)).lower()
                expanded_name, _ = expand_function_shortcut(raw_name, {})

                # Skip cross-context nodes — they work in both tree types
                if raw_name not in cross_context_nodes and expanded_name not in cross_context_nodes:
                    # Check via registry if available
                    if registry:
                        self_mat = (raw_name in registry.material_nodes or expanded_name in registry.material_nodes) and (raw_name not in registry.geometry_nodes and expanded_name not in registry.geometry_nodes)
                        self_geo = (raw_name in registry.geometry_nodes or expanded_name in registry.geometry_nodes) and (raw_name not in registry.material_nodes and expanded_name not in registry.material_nodes)

                    # Fallback heuristics (only when registry gave no answer)
                    if not self_mat and not self_geo:
                        self_mat = raw_name.startswith(("tex_", "bsdf_", "shader_")) or any(m in raw_name for m in ["output_material", "mix_shader", "emission", "_matoutput", "glass", "glossy", "subsurface", "sheen", "fresnel", "ambient_occlusion"])
                        self_geo = raw_name.startswith(("mesh_", "curve_", "instance_")) or any(g in raw_name for g in ["join_geometry", "transform_geometry", "set_position", "extrude_mesh", "subdivide_mesh", "store_named_attribute", "capture_attribute", "set_material", "icosphere"])

            # Always recurse into children (arguments may contain nested
            # function calls like tex_coord() inside separate_xyz(tex_coord()))
            for child in node.children:
                if hasattr(child, 'data') or hasattr(child, 'value'):
                    m, g = check_node(child)
                    self_mat = self_mat or m
                    self_geo = self_geo or g
            return self_mat, self_geo

        mat, geo = False, False
        for child in node.children:
            m, g = False, False
            if hasattr(child, 'data') or hasattr(child, 'value'):
                m, g = check_node(child)
            mat = mat or m
            geo = geo or g
        return mat, geo

    has_mat = False
    has_geo = False
    for stmt in block_stmts:
        m, g = check_node(stmt)
        has_mat = has_mat or m
        has_geo = has_geo or g

    if has_geo:
        return False
    if has_mat:
        return True

    # Explicit tree_type argument override (when AST nodes are ambiguous)
    if tree_type:
        tt_lower = str(tree_type).lower()
        if tt_lower in ("shader", "shadernodetree", "material"):
            return True
        elif tt_lower in ("geometry", "geometrynodetree"):
            return False

    # Fallback to filepath and context when AST nodes are ambiguous
    if filepath and ("/material/" in str(filepath).replace("\\", "/") or str(filepath).endswith("_mat.xfy")):
        return True
    if filepath and ("/geometry/" in str(filepath).replace("\\", "/") or str(filepath).endswith("_geo.xfy")):
        return False

    if context:
        space = getattr(context, "space_data", None)
        if space and getattr(space, "type", None) == "NODE_EDITOR":
            tt = getattr(space, "tree_type", None)
            if tt == "ShaderNodeTree":
                return True
            elif tt == "GeometryNodeTree":
                return False
        area = getattr(context, "area", None)
        if area and getattr(area, "ui_type", None) == "ShaderNodeTree":
            return True

        # Check screen for active NODE_EDITOR when run from Text Editor or other spaces
        screen = getattr(context, "screen", None)
        if screen:
            for a in screen.areas:
                if a.type == "NODE_EDITOR":
                    sp = getattr(getattr(a, "spaces", None), "active", None)
                    tt = getattr(sp, "tree_type", None) or getattr(a, "ui_type", None)
                    if tt == "ShaderNodeTree":
                        return True
                    elif tt == "GeometryNodeTree":
                        return False

    return False


def is_material_group_def(
    stmt,
    registry=None,
    filepath=None,
    context=None,
    tree_type=None,
    top_level_items=None,
):
    """Check if a group_def AST node defines a shader/material node group."""
    group_node = stmt.children[0] if (hasattr(stmt, "children") and stmt.children) else stmt
    if not (hasattr(group_node, "children") and group_node.children):
        return False

    first = group_node.children[0]
    if hasattr(first, "data"):
        if first.data == "material_domain":
            return True
        if first.data == "geometry_domain":
            return False
        if first.data == "domain_type" and hasattr(first, "children") and first.children:
            d = str(first.children[0].value).lower()
            if d in ("material", "shader"):
                return True
            if d == "geometry":
                return False

    # Extract group name to check if any material/world block calls it
    name_idx = 0
    if hasattr(first, "data") and first.data in ("material_domain", "geometry_domain", "domain_type"):
        name_idx = 1
    group_name = None
    if name_idx < len(group_node.children):
        name_tok = group_node.children[name_idx]
        group_name = getattr(name_tok, "value", str(name_tok))

    # Helper to check if AST tree has a call to group_name
    def ast_has_call(node, func_name):
        if not hasattr(node, "data"):
            return False
        if node.data == "function_call" and len(node.children) > 0:
            call_name = getattr(node.children[0], "value", str(node.children[0]))
            if call_name == func_name:
                return True
        if hasattr(node, "children"):
            for child in node.children:
                if hasattr(child, "data") and ast_has_call(child, func_name):
                    return True
        return False

    # Check AST statements inside group for geometry-only or material-only nodes
    if registry is None:
        try:
            registry = NodeRegistry(include_material_nodes=True)
        except Exception:
            registry = None

    try:
        from .shortcuts import expand_function_shortcut
    except ImportError:
        from shortcuts import expand_function_shortcut

    cross_context_nodes = {"compare"}

    def check_node(node):
        if not hasattr(node, "data"):
            return False, False
        if node.data == "function_call_statement":
            m, g = False, False
            for child in node.children:
                if hasattr(child, "data") or hasattr(child, "value"):
                    cm, cg = check_node(child)
                    m = m or cm
                    g = g or cg
            return m, g
        if node.data == "function_call":
            sm, sg = False, False
            if len(node.children) > 0:
                name_node = node.children[0]
                raw_name = getattr(name_node, "value", str(name_node)).lower()
                expanded_name, _ = expand_function_shortcut(raw_name, {})
                if raw_name not in cross_context_nodes and expanded_name not in cross_context_nodes:
                    if registry:
                        sm = (raw_name in registry.material_nodes or expanded_name in registry.material_nodes) and (raw_name not in registry.geometry_nodes and expanded_name not in registry.geometry_nodes)
                        sg = (raw_name in registry.geometry_nodes or expanded_name in registry.geometry_nodes) and (raw_name not in registry.material_nodes and expanded_name not in registry.material_nodes)
                    if not sm and not sg:
                        sm = raw_name.startswith(("tex_", "bsdf_", "shader_")) or any(m in raw_name for m in ["output_material", "mix_shader", "emission", "_matoutput", "glass", "glossy", "subsurface", "sheen", "fresnel", "ambient_occlusion"])
                        sg = raw_name.startswith(("mesh_", "curve_", "instance_")) or any(g in raw_name for g in ["join_geometry", "transform_geometry", "set_position", "extrude_mesh", "subdivide_mesh", "store_named_attribute", "capture_attribute", "set_material", "icosphere"])
            for child in node.children:
                if hasattr(child, "data") or hasattr(child, "value"):
                    cm, cg = check_node(child)
                    sm = sm or cm
                    sg = sg or cg
            return sm, sg
        m, g = False, False
        for child in node.children:
            if hasattr(child, "data") or hasattr(child, "value"):
                cm, cg = check_node(child)
                m = m or cm
                g = g or cg
        return m, g

    has_mat = False
    has_geo = False
    for child in group_node.children:
        cm, cg = check_node(child)
        has_mat = has_mat or cm
        has_geo = has_geo or cg

    # If it contains geometry-only nodes, it CANNOT be a material group
    if has_geo:
        return False
    # If it contains material-only nodes, it IS a material group
    if has_mat:
        return True

    # If group is neutral (e.g. math/vector operations), check if any material_block or world_block calls it
    if group_name and top_level_items:
        for item in top_level_items:
            if item[0] in ("material_block", "world_block"):
                block_stmts = item[4]
                if any(ast_has_call(s, group_name) for s in block_stmts):
                    return True

    # Check explicit tree_type argument override
    if tree_type:
        tt_lower = str(tree_type).lower()
        if tt_lower in ("shader", "shadernodetree", "material"):
            return True
        elif tt_lower in ("geometry", "geometrynodetree"):
            return False

    # Check filepath heuristics
    if filepath and ("/material/" in str(filepath).replace("\\", "/") or str(filepath).endswith("_mat.xfy")):
        return True
    if filepath and ("/geometry/" in str(filepath).replace("\\", "/") or str(filepath).endswith("_geo.xfy")):
        return False

    # Check if top_level_items indicates a purely material/world script (no geometry blocks)
    if top_level_items:
        has_mat_or_world = any(item[0] in ("material_block", "world_block") for item in top_level_items)
        has_geom = any(item[0] == "geometry_block" for item in top_level_items)
        if has_mat_or_world and not has_geom:
            return True

    # Check editor / UI context
    if context:
        space = getattr(context, "space_data", None)
        if space and getattr(space, "type", None) == "NODE_EDITOR":
            tt = getattr(space, "tree_type", None)
            if tt == "ShaderNodeTree":
                return True
            elif tt == "GeometryNodeTree":
                return False
        area = getattr(context, "area", None)
        if area and getattr(area, "ui_type", None) == "ShaderNodeTree":
            return True

        screen = getattr(context, "screen", None)
        if screen:
            for a in screen.areas:
                if a.type == "NODE_EDITOR":
                    sp = getattr(getattr(a, "spaces", None), "active", None)
                    tt = getattr(sp, "tree_type", None) or getattr(a, "ui_type", None)
                    if tt == "ShaderNodeTree":
                        return True
                    elif tt == "GeometryNodeTree":
                        return False

    return False


def compile_object_block(
    object_name,
    tree_name_hint,
    block_statements,
    context,
    registry,
    python_namespace,
    parent_chain,
    shared_compiler,
    clearExisting,
    deferred_blocks,
    is_material=False,
    source_map=None,
    filepath=None,
    source_text=None,
):
    """
    Compile a single object block to a node tree and apply to the specified object.

    Args:
        object_name: Name of the Blender object to apply to
        tree_name_hint: Optional tree name from 'as' clause, or None
        block_statements: List of statement AST nodes for this block
        context: Blender context
        registry: NodeRegistry instance (shared)
        python_namespace: Python namespace (shared)
        parent_chain: Parent chain for Python blocks
        shared_compiler: Compiler with shared groups (for group lookup)
        clearExisting: Whether to clear existing nodes
        deferred_blocks: Deferred blocks specific to this object block
        is_material: Whether this is a material node tree
        source_map: SourceMap instance for error location mapping
        filepath: Filepath of the source script
        source_text: Full source code text for logging and line context

    Returns:
        (success, message, tree)
    """
    # Look up the object - fail fast if not found
    if object_name:
        obj = bpy.data.objects.get(object_name)
        if not obj:
            raise ValueError(
                f"Object '{object_name}' not found. Available objects: {[o.name for o in bpy.data.objects]}"
            )
    else:
        obj = context.active_object
        if not obj:
            raise ValueError("No active object to apply to! (Implicit object block requires an active object)")
        object_name = obj.name

    # Determine tree name
    # With 'as' clause: use explicit tree name
    # Without 'as': use object_name + "_Nodes" suffix to avoid collision with group display names
    # (Groups use their display_name as tree name, so we need a unique naming scheme)
    tree_name = tree_name_hint if tree_name_hint else f"{object_name}_Nodes"

    tree_type = "ShaderNodeTree" if is_material else "GeometryNodeTree"

    if is_material:
        if tree_name in bpy.data.materials:
            tree_container = bpy.data.materials[tree_name]
            tree_container.use_nodes = True
            tree = tree_container.node_tree
            if clearExisting:
                tree.nodes.clear()
                tree.interface.clear()
        else:
            tree_container = bpy.data.materials.new(tree_name)
            tree_container.use_nodes = True
            tree = tree_container.node_tree
            if clearExisting:
                tree.nodes.clear()
    else:
        if tree_name in bpy.data.node_groups:
            tree = bpy.data.node_groups[tree_name]
            if clearExisting:
                tree.nodes.clear()
                tree.interface.clear()
        else:
            tree = bpy.data.node_groups.new(tree_name, tree_type)

    # Create builder and compiler for this block
    builder = BlenderNodeBuilder(tree, registry)
    compiler = Compiler(
        builder,
        parent_chain=parent_chain,
        python_namespace=python_namespace,
        source_map=source_map,
        filepath=filepath,
        source_text=source_text,
    )

    # Copy shared groups, python_namespace, and pending_materials from the shared compiler
    if shared_compiler:
        compiler.groups = shared_compiler.groups
        if hasattr(shared_compiler, "python_namespace") and shared_compiler.python_namespace:
            compiler.python_namespace.update(shared_compiler.python_namespace)
        if hasattr(shared_compiler, "pending_materials") and shared_compiler.pending_materials is not None:
            compiler.pending_materials = shared_compiler.pending_materials

    # Compile block statements
    from lark import Tree

    # Wrap statements in a 'start' node for the compiler
    block_ast = Tree("start", block_statements)
    compiler.compile(block_ast, source_text=source_text)

    if shared_compiler:
        shared_compiler.python_namespace.update(compiler.python_namespace)

    # Execute deferred blocks for this object block
    if deferred_blocks:
        deferred_namespace = {
            **python_namespace,
            "bpy": bpy,
            "__builtins__": __builtins__,
            "__tree__": tree,
            "__context__": context,
            "__object__": obj,
        }
        combined_code = "\n\n".join(code for code, _ in deferred_blocks if code.strip())
        if combined_code.strip():
            try:
                exec(combined_code, deferred_namespace)
            except Exception as e:
                raise RuntimeError(
                    f"Error executing deferred block for object '{object_name}': {e}"
                )

    # Apply to object
    if is_material:
        mat = tree_container
        _sync_material_viewport_color(mat)
        if obj.data and hasattr(obj.data, "materials"):
            mat_idx = -1
            for i, slot_mat in enumerate(obj.data.materials):
                if slot_mat and slot_mat.name == tree_name:
                    mat_idx = i
                    break

            if mat_idx >= 0:
                obj.data.materials[mat_idx] = mat
                obj.active_material_index = mat_idx
            else:
                obj.data.materials.append(mat)
                obj.active_material_index = len(obj.data.materials) - 1
        return (True, f"Applied '{tree_name}' to '{object_name}'", tree)
    else:
        # Apply tree to object as geometry nodes modifier
        mod_name = tree_name
        mod = None
        for m in obj.modifiers:
            if m.type == "NODES" and m.name == mod_name:
                mod = m
                break

        if not mod:
            mod = obj.modifiers.new(mod_name, "NODES")

        mod.node_group = tree
        _sync_modifier_defaults(mod, tree)

        return (True, f"Applied '{tree_name}' to '{object_name}'", tree)


def _sync_modifier_defaults(mod, tree):
    """Sync default socket values from node tree interface to modifier inputs in Blender 5.2+."""
    if not mod or not tree or not hasattr(tree, "interface"):
        return
    for item in tree.interface.items_tree:
        if getattr(item, "item_type", "") == "SOCKET" and getattr(item, "in_out", "") == "INPUT":
            if hasattr(item, "default_value") and item.default_value is not None:
                if hasattr(mod, "properties") and hasattr(mod.properties, "inputs"):
                    s = getattr(mod.properties.inputs, item.identifier, None)
                    if s is not None and hasattr(s, "value"):
                        try:
                            s.value = item.default_value
                        except Exception:
                            pass
                else:
                    try:
                        mod[item.identifier] = item.default_value
                    except Exception:
                        pass


def _sync_material_viewport_color(mat):
    """Auto-sync material viewport display diffuse_color, metallic, and roughness from its node tree."""
    if not mat or not getattr(mat, "node_tree", None):
        return
    for node in mat.node_tree.nodes:
        if getattr(node, "bl_idname", "") == "ShaderNodeBsdfPrincipled":
            base_col = node.inputs.get("Base Color")
            if base_col:
                if base_col.is_linked and base_col.links:
                    from_node = base_col.links[0].from_node
                    if getattr(from_node, "bl_idname", "") == "ShaderNodeRGB" and len(from_node.outputs) > 0:
                        mat.diffuse_color = from_node.outputs[0].default_value[:]
                else:
                    mat.diffuse_color = base_col.default_value[:]
            met = node.inputs.get("Metallic")
            if met and hasattr(met, "default_value"):
                try:
                    mat.metallic = float(met.default_value)
                except Exception:
                    pass
            rough = node.inputs.get("Roughness")
            if rough and hasattr(rough, "default_value"):
                try:
                    mat.roughness = float(rough.default_value)
                except Exception:
                    pass
            trans = node.inputs.get("Transmission Weight") or node.inputs.get("Transmission")
            if trans and hasattr(trans, "default_value") and trans.default_value > 0.5:
                if hasattr(mat, "blend_method"):
                    try:
                        mat.blend_method = "BLEND"
                    except Exception:
                        pass
            break


def compile_world_block(
    scene_name,
    world_name_hint,
    block_statements,
    context,
    registry,
    python_namespace,
    parent_chain,
    shared_compiler,
    clearExisting,
    deferred_blocks,
    source_map=None,
    filepath=None,
    source_text=None,
):
    """
    Compile a world block to a ShaderNodeTree on a World datablock and assign to scene.world.

    Args:
        scene_name: Optional name of the Blender scene to apply to (default: active scene)
        world_name_hint: Optional world name from 'as' clause, or None
        block_statements: List of statement AST nodes for this block
        context: Blender context
        registry: NodeRegistry instance
        python_namespace: Python namespace
        parent_chain: Parent chain
        shared_compiler: Compiler with shared groups
        clearExisting: Whether to clear existing nodes
        deferred_blocks: Deferred blocks for this world block
        source_map: SourceMap instance for error location mapping
        filepath: Filepath of the source script
        source_text: Full source code text for logging and line context

    Returns:
        (success, message, tree)
    """
    # Look up target scene
    if scene_name:
        scene = bpy.data.scenes.get(scene_name)
        if not scene:
            raise ValueError(
                f"Scene '{scene_name}' not found. Available scenes: {[s.name for s in bpy.data.scenes]}"
            )
    else:
        scene = context.scene if (context and hasattr(context, "scene")) else bpy.context.scene

    # Determine world datablock name
    if world_name_hint:
        world_name = world_name_hint
    elif scene and scene.world:
        world_name = scene.world.name
    else:
        world_name = f"{scene.name}_World" if scene else "World"

    # Get or create World datablock
    if world_name in bpy.data.worlds:
        world = bpy.data.worlds[world_name]
        world.use_nodes = True
        tree = world.node_tree
        if clearExisting:
            tree.nodes.clear()
            tree.interface.clear()
    else:
        world = bpy.data.worlds.new(world_name)
        world.use_nodes = True
        tree = world.node_tree
        if clearExisting:
            tree.nodes.clear()

    # Create builder and compiler for this world block
    builder = BlenderNodeBuilder(tree, registry)
    compiler = Compiler(
        builder,
        parent_chain=parent_chain,
        python_namespace=python_namespace,
        source_map=source_map,
        filepath=filepath,
        source_text=source_text,
    )

    if shared_compiler:
        compiler.groups = shared_compiler.groups
        if hasattr(shared_compiler, "python_namespace") and shared_compiler.python_namespace:
            compiler.python_namespace.update(shared_compiler.python_namespace)
        if hasattr(shared_compiler, "pending_materials") and shared_compiler.pending_materials is not None:
            compiler.pending_materials = shared_compiler.pending_materials

    from lark import Tree
    block_ast = Tree("start", block_statements)
    compiler.compile(block_ast, source_text=source_text)

    if shared_compiler:
        shared_compiler.python_namespace.update(compiler.python_namespace)

    # Execute deferred blocks for this world block
    if deferred_blocks:
        deferred_namespace = {
            **python_namespace,
            "bpy": bpy,
            "__builtins__": __builtins__,
            "__tree__": tree,
            "__context__": context,
            "__world__": world,
            "__scene__": scene,
        }
        combined_code = "\n\n".join(code for code, _ in deferred_blocks if code.strip())
        if combined_code.strip():
            try:
                exec(combined_code, deferred_namespace)
            except Exception as e:
                raise RuntimeError(
                    f"Error executing deferred block for world '{world_name}': {e}"
                )

    # Assign to scene.world
    if scene:
        scene.world = world

    return (True, f"Applied World '{world_name}' to Scene '{scene.name if scene else 'Default'}'", tree)


def compile_script(
    script_content, tree_name, context, filepath=None, clearExisting=True, tree_type=None
):
    """
    Compile a script into a node tree, material, or modifier.
    Returns (success: bool, message: str, node_tree)

    Args:
        script_content: The script text to compile
        tree_name: Name for the node tree (or material name for materials)
        context: Blender context
        filepath: Optional filepath for include directive resolution
        clearExisting: Clear existing nodes if tree exists (default: True)
        tree_type: Optional tree type override ("GeometryNodeTree", "ShaderNodeTree", "CompositorNodeTree")

    Note: Node arrangement should be done by the caller (operator level)
    """

    # Extract magic version comment (e.g., #!4.2)
    target_version = None
    first_line = script_content.split('\n')[0].strip()
    if first_line.startswith('#!'):
        target_version = first_line[2:].strip()

    # Fallback to directory-based target version if not specified via comment
    if not target_version and filepath:
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

    # Parse the script (with filepath for include resolution)
    ast, parent_chain, python_namespace, source_map, deferred_blocks = parse(
        script_content, filepath=filepath
    )

    # Extract sequential top-level items in exact script order
    top_level_items = extract_sequential_top_level_items(
        ast, tree_name, filepath, context=context, tree_type=tree_type
    )

    if top_level_items:
        registry = NodeRegistry(include_material_nodes=True, target_version=target_version)

        from lark import Tree

        # Determine base script tree type:
        # 1. Explicit tree_type argument (e.g. from CLI --tree shader/geometry)
        if tree_type:
            tt_lower = str(tree_type).lower()
            if tt_lower in ("shader", "shadernodetree", "material"):
                base_tree_type = "ShaderNodeTree"
            elif tt_lower in ("compositor", "compositornodetree"):
                base_tree_type = "CompositorNodeTree"
            else:
                base_tree_type = "GeometryNodeTree"
        # 2. Active editor space in Blender UI
        elif (
            context
            and hasattr(context, "space_data")
            and getattr(context.space_data, "type", None) == "NODE_EDITOR"
            and getattr(context.space_data, "tree_type", None)
        ):
            base_tree_type = context.space_data.tree_type
        # 3. Active NODE_EDITOR in Blender screen (e.g. when run from Text Editor or 3D View)
        elif (
            context
            and hasattr(context, "screen")
            and context.screen
            and any(a.type == "NODE_EDITOR" for a in context.screen.areas)
        ):
            found_tt = None
            for a in context.screen.areas:
                if a.type == "NODE_EDITOR":
                    sp = getattr(getattr(a, "spaces", None), "active", None)
                    tt = getattr(sp, "tree_type", None) or getattr(a, "ui_type", None)
                    if tt in ("ShaderNodeTree", "GeometryNodeTree", "CompositorNodeTree"):
                        found_tt = tt
                        break
            base_tree_type = found_tt if found_tt else "GeometryNodeTree"
        # 4. Automatic detection based on script content (geometry content takes precedence)
        else:
            has_geometry_content = any(
                item[0] == "geometry_block" or (
                    item[0] not in ("material_block", "world_block", "python_block", "group_def")
                )
                for item in top_level_items
            )
            has_material_or_world = any(
                item[0] in ("material_block", "world_block") for item in top_level_items
            )
            
            if has_material_or_world and not has_geometry_content:
                base_tree_type = "ShaderNodeTree"
            else:
                base_tree_type = "GeometryNodeTree"

        temp_tree_type = base_tree_type
        temp_tree_name = f"__temp_global_{tree_name}"
        if temp_tree_name in bpy.data.node_groups:
            temp_tree = bpy.data.node_groups[temp_tree_name]
            if temp_tree.bl_idname != temp_tree_type:
                bpy.data.node_groups.remove(temp_tree)
                temp_tree = bpy.data.node_groups.new(temp_tree_name, temp_tree_type)
            else:
                temp_tree.nodes.clear()
                temp_tree.interface.clear()
        else:
            temp_tree = bpy.data.node_groups.new(temp_tree_name, temp_tree_type)

        temp_trees_to_clean = [temp_tree]
        temp_builder = BlenderNodeBuilder(temp_tree, registry)
        shared_compiler = Compiler(
            temp_builder,
            parent_chain=parent_chain,
            python_namespace=python_namespace,
            source_map=source_map,
            filepath=filepath,
            source_text=script_content,
        )

        results = []
        all_trees = []

        # Phase 1: Compile python blocks FIRST
        for item in top_level_items:
            if item[0] == "python_block":
                stmt = item[1]
                global_ast = Tree("start", [stmt])
                shared_compiler.compile(global_ast, source_text=script_content)

        # Phase 2: Compile material group definitions (group material ...)
        for item in top_level_items:
            if item[0] == "group_def" and is_material_group_def(
                item[1],
                registry=registry,
                filepath=filepath,
                context=context,
                tree_type=base_tree_type,
                top_level_items=top_level_items,
            ):
                stmt = item[1]
                if shared_compiler.builder.node_tree.bl_idname != "ShaderNodeTree":
                    temp_mat = bpy.data.node_groups.new(f"__temp_mat_{tree_name}", "ShaderNodeTree")
                    temp_trees_to_clean.append(temp_mat)
                    shared_compiler.builder.node_tree = temp_mat
                global_ast = Tree("start", [stmt])
                shared_compiler.compile(global_ast, source_text=script_content)

        # Phase 3: Compile material object blocks (creates materials in bpy.data.materials)
        for item in top_level_items:
            if item[0] == "material_block":
                _, obj_name, block_tree_name, explicit_domain, block_stmts = item
                block_deferred = []
                success, message, tree = compile_object_block(
                    obj_name,
                    block_tree_name,
                    block_stmts,
                    context,
                    registry,
                    python_namespace,
                    parent_chain,
                    shared_compiler,
                    clearExisting,
                    block_deferred,
                    is_material=True,
                    source_map=source_map,
                    filepath=filepath,
                    source_text=script_content,
                )
                results.append((success, message))
                if tree:
                    all_trees.append(tree)

        # Phase 4: Compile geometry group definitions (all materials now exist for set_material!)
        for item in top_level_items:
            if item[0] == "group_def" and not is_material_group_def(
                item[1],
                registry=registry,
                filepath=filepath,
                context=context,
                tree_type=base_tree_type,
                top_level_items=top_level_items,
            ):
                stmt = item[1]
                if shared_compiler.builder.node_tree.bl_idname != "GeometryNodeTree":
                    temp_geo = bpy.data.node_groups.new(f"__temp_geo_{tree_name}", "GeometryNodeTree")
                    temp_trees_to_clean.append(temp_geo)
                    shared_compiler.builder.node_tree = temp_geo
                global_ast = Tree("start", [stmt])
                shared_compiler.compile(global_ast, source_text=script_content)

        # Phase 5: Compile world blocks
        for item in top_level_items:
            if item[0] == "world_block":
                _, scene_name, block_world_name, explicit_domain, block_stmts = item
                block_deferred = []
                success, message, tree = compile_world_block(
                    scene_name,
                    block_world_name,
                    block_stmts,
                    context,
                    registry,
                    python_namespace,
                    parent_chain,
                    shared_compiler,
                    clearExisting,
                    block_deferred,
                    source_map=source_map,
                    filepath=filepath,
                    source_text=script_content,
                )
                results.append((success, message))
                if tree:
                    all_trees.append(tree)

        # Phase 6: Compile geometry object blocks
        for item in top_level_items:
            if item[0] == "geometry_block":
                _, obj_name, block_tree_name, explicit_domain, block_stmts = item
                block_deferred = []
                success, message, tree = compile_object_block(
                    obj_name,
                    block_tree_name,
                    block_stmts,
                    context,
                    registry,
                    python_namespace,
                    parent_chain,
                    shared_compiler,
                    clearExisting,
                    block_deferred,
                    is_material=False,
                    source_map=source_map,
                    filepath=filepath,
                    source_text=script_content,
                )
                results.append((success, message))
                if tree:
                    all_trees.append(tree)

        # Phase 7: Resolve any pending material sockets (where material was created after group definition)
        shared_compiler.resolve_pending_materials()

        # Remove temp trees (we only needed them for shared compilation)
        for t in temp_trees_to_clean:
            if t.name in bpy.data.node_groups:
                bpy.data.node_groups.remove(t)

        # Execute global deferred blocks (if any)
        if deferred_blocks:
            deferred_namespace = {
                **python_namespace,
                "bpy": bpy,
                "_selfobj": context.view_layer.objects.active if (context and hasattr(context, "view_layer") and context.view_layer) else None,
                "__builtins__": __builtins__,
                "__trees__": all_trees,  # List of all created trees
                "__context__": context,
            }
            try:
                for code, block_parent_chain in deferred_blocks:
                    if code.strip():
                        deferred_namespace["__parents__"] = block_parent_chain
                        deferred_namespace["__file__"] = block_parent_chain[0] if block_parent_chain else filepath
                        exec(code, deferred_namespace)
            except Exception as e:
                raise RuntimeError(
                    f"Error executing global deferred Python block: {e}"
                )

        # Return summary
        messages = [msg for _, msg in results if msg]
        
        return (
            True,
            f"Compiled {len(top_level_items)} top-level items: " + "; ".join(messages),
            [t for t in all_trees if t],
        )

    # ============================================
    # Original single-object compilation logic
    # ============================================

    # Check if script ONLY has group definitions (no other statements)
    # If it has groups AND other code, compile the non-group code
    has_only_group_defs = False
    has_group_defs = False
    has_other_statements = False

    for stmt in ast.children:
        if hasattr(stmt, "data") and stmt.data == "statement" and stmt.children:
            inner_stmt = stmt.children[0]
            if hasattr(inner_stmt, "data"):
                if inner_stmt.data == "group_def":
                    has_group_defs = True
                else:
                    has_other_statements = True

    # Only treat as pure group definition if it ONLY has groups
    has_only_group_defs = has_group_defs and not has_other_statements

    # Auto-detect tree type: check if script uses material nodes
    # Strip Python blocks first to avoid false positives from material creation code
    import re

    script_without_python = re.sub(r"```[\s\S]*?```", "", script_content)

    # Check for material-specific nodes in XFY code (not Python blocks)
    has_material_nodes = (
        "output_material" in script_without_python
        or "mix_shader" in script_without_python
        or "bsdf_" in script_without_python
        or "emission" in script_without_python
        or "_matoutput" in script_without_python
        or "_prnbsdf" in script_without_python
        or "_diffbsdf" in script_without_python
        or "_emission" in script_without_python
    )

    # Check for geometry-only nodes that can't exist in shader trees
    has_geometry_nodes = (
        "mesh_" in script_without_python
        or "curve_" in script_without_python
        or "instance_" in script_without_python
        or "join_geometry" in script_without_python
        or "transform(" in script_without_python
    )

    # Material script if it has material nodes and no geometry nodes
    # Or if filepath indicates it's a material
    is_material_script = (has_material_nodes and not has_geometry_nodes) or (
        filepath and "/material/" in filepath
    )
    tree_type = "ShaderNodeTree" if is_material_script else "GeometryNodeTree"

    # Compile with material nodes support
    registry = NodeRegistry(include_material_nodes=True, target_version=target_version)

    # For material scripts, compile directly into material's node tree (like old xnodify2)
    # For geometry scripts, compile into a node group
    if is_material_script:
        # Get or create the material
        if tree_name in bpy.data.materials:
            mat = bpy.data.materials[tree_name]
            mat.use_nodes = True
            tree = mat.node_tree
            if clearExisting:
                tree.nodes.clear()
                tree.interface.clear()
        else:
            mat = bpy.data.materials.new(tree_name)
            mat.use_nodes = True
            tree = mat.node_tree
            if clearExisting:
                tree.nodes.clear()
                tree.interface.clear()
    else:
        # Geometry nodes: compile to a node group
        if tree_name in bpy.data.node_groups:
            tree = bpy.data.node_groups[tree_name]
            if clearExisting:
                tree.nodes.clear()
                tree.interface.clear()
        else:
            tree = bpy.data.node_groups.new(tree_name, tree_type)

    builder = BlenderNodeBuilder(tree, registry)
    compiler = Compiler(
        builder,
        parent_chain=parent_chain,
        python_namespace=python_namespace,
        source_map=source_map,
        filepath=filepath,
        source_text=script_content,
    )
    compiler.compile(ast, source_text=script_content)

    # Prepare to determine final compilation result
    result = None

    if has_only_group_defs:
        # Script ONLY has group definitions - done, just return the tree
        if is_material_script:
            result = (
                True,
                f"Created material: {tree_name} with {len(tree.nodes)} nodes",
                tree,
            )
        else:
            result = (
                True,
                f"Created node group: {tree_name} with {len(tree.nodes)} nodes",
                tree,
            )
    else:
        # Script has executable code - apply to active object
        # Check for active object AFTER compilation (Python blocks may have created it)
        obj = context.active_object
        if not obj:
            # No object to apply to, but compilation was successful
            result = (
                True,
                f"Created node group: {tree_name} with {len(tree.nodes)} nodes (no object to apply to)",
                tree,
            )

        elif is_material_script:
            # Material already compiled directly into mat.node_tree
            # Just need to assign it to the object
            mat_name = tree_name
            mat = bpy.data.materials[mat_name]  # Must exist since we created it above

            # Assign material to object (match old xnodify2 behavior)
            if obj.data and hasattr(obj.data, "materials"):
                # Try to find if this material is already in a slot
                mat_idx = -1
                for i, slot_mat in enumerate(obj.data.materials):
                    if slot_mat and slot_mat.name == mat_name:
                        mat_idx = i
                        break

                if mat_idx >= 0:
                    # Material already in a slot, update it
                    obj.data.materials[mat_idx] = mat
                    obj.active_material_index = mat_idx
                else:
                    # Material not in any slot, append it
                    obj.data.materials.append(mat)
                    obj.active_material_index = len(obj.data.materials) - 1

            result = (True, f"Applied material: {mat_name} to {obj.name}", tree)
        else:
            # Apply compiled tree as geometry nodes modifier
            mod_name = tree_name

            # Find or create geometry nodes modifier
            mod = None
            for m in obj.modifiers:
                if m.type == "NODES":
                    mod = m
                    break

            if not mod:
                mod = obj.modifiers.new(mod_name, "NODES")

            # Assign the compiled tree to the modifier
            mod.node_group = tree
            _sync_modifier_defaults(mod, tree)

            result = (
                True,
                f"Applied geometry nodes: {mod_name} to {obj.name} with {len(tree.nodes)} nodes",
                tree,
            )

    # Execute deferred Python blocks AFTER compilation AND modifier assignment
    # These have access to the created tree, assigned modifier, and other context
    if deferred_blocks:
        obj = context.active_object  # May be None
        deferred_namespace = {
            **python_namespace,  # Access to all variables from normal blocks
            "bpy": bpy,
            "__builtins__": __builtins__,
            "__tree__": tree,  # The created node tree/group
            "__context__": context,
            "__object__": obj,  # Active object (may be None)
        }

        # Combine all deferred blocks in order and execute as single unit
        try:
            for code, block_parent_chain in deferred_blocks:
                if code.strip():
                    deferred_namespace["__parents__"] = block_parent_chain
                    deferred_namespace["__file__"] = block_parent_chain[0] if block_parent_chain else filepath
                    
                    import sys, os
                    deferred_namespace["__name__"] = "__main__"
                    deferred_namespace["__package__"] = ""
                    if deferred_namespace["__file__"]:
                        s_dir = os.path.dirname(os.path.abspath(deferred_namespace["__file__"]))
                        if s_dir not in sys.path: sys.path.insert(0, s_dir)
                        
                    exec(code, deferred_namespace)
        except Exception as e:
            raise RuntimeError(f"Error executing deferred Python block: {e}")

    # Normalize: wrap single tree in list for consistent return type
    if result:
        success, message, single_tree = result
        return (success, message, [single_tree] if single_tree else [])
    return result


class XNodifyProperties(PropertyGroup):
    """Properties for XNodify addon"""

    def get_text_blocks(self, context):
        """Get list of available text blocks"""
        items = []
        for i, text in enumerate(bpy.data.texts):
            items.append((text.name, text.name, f"Use text block: {text.name}"))
        if not items:
            items.append(("NONE", "No Text Blocks", "No text blocks available"))
        return items

    text_block: bpy.props.EnumProperty(
        name="Text Block",
        description="Select text block to compile",
        items=get_text_blocks,
    )

    auto_create_object: BoolProperty(
        name="Auto Create Object",
        description="Create new object with node tree. If unchecked, applies to selected object",
        default=True,
    )


class XNODIFY_OT_run_script(Operator):
    """Run XNodify script from text editor"""

    bl_idname = "xnodify.run_script"
    bl_label = "Run Script"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # Check if there are any text blocks available
        return len(bpy.data.texts) > 0

    def execute(self, context):
        props = context.scene.xnodify_props

        # Get the selected text block
        text = None
        if props.text_block and props.text_block in bpy.data.texts:
            text = bpy.data.texts[props.text_block]
        elif hasattr(context, "space_data") and hasattr(context.space_data, "text"):
            # Fallback to current text editor if available
            text = context.space_data.text
        elif len(bpy.data.texts) > 0:
            # Last resort: use first text block
            text = bpy.data.texts[0]

        if not text:
            self.report({"ERROR"}, "No text block selected")
            return {"CANCELLED"}

        # Get the script content
        script_content = text.as_string()
        tree_name = text.name
        filepath = bpy.path.abspath(text.filepath) if (hasattr(text, "filepath") and text.filepath) else None

        try:
            # If auto_create_object is enabled and no active object, create one
            if props.auto_create_object and not context.active_object:
                obj_name = f"{tree_name}_Object"
                if obj_name in bpy.data.objects:
                    obj = bpy.data.objects[obj_name]
                else:
                    mesh = bpy.data.meshes.new(f"{tree_name}_Mesh")
                    obj = bpy.data.objects.new(obj_name, mesh)
                    context.collection.objects.link(obj)

                # Set as active object
                bpy.ops.object.select_all(action="DESELECT")
                obj.select_set(True)
                context.view_layer.objects.active = obj

            # Get clear_existing and arrange_nodes from preferences
            prefs = get_prefs(context)
            clear_existing = prefs.clear_existing if prefs else True
            do_arrange = prefs.arrange_nodes if prefs else True

            # Compile the script
            success, message, trees = compile_script(
                script_content, tree_name, context, filepath=filepath, clearExisting=clear_existing
            )

            # Sync and arrange ALL generated trees (geometry + material)
            if success and trees:
                for t in trees:
                    sync_nodes(t, context)
                if do_arrange:
                    for t in trees:
                        arrange_nodes(t, context)

            if success:
                self.report({"INFO"}, message)
                return {"FINISHED"}
            else:
                self.report({"WARNING"}, message)
                return {"CANCELLED"}

        except Exception as e:
            self.report({"ERROR"}, f"Error: {str(e)}")
            import traceback

            traceback.print_exc()
            return {"CANCELLED"}


class XNODIFY_OT_run_file(Operator):
    """Execute XNodify script from file path in preferences"""

    bl_idname = "xnodify.run_file"
    bl_label = "Execute File"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = get_prefs(context)
        props = context.scene.xnodify_props

        if not prefs or not prefs.last_path:
            self.report(
                {"ERROR"},
                "No file path specified. Use the folder button to select a file.",
            )
            return {"CANCELLED"}

        filepath = bpy.path.abspath(prefs.last_path)

        if not os.path.exists(filepath):
            self.report({"ERROR"}, f"File not found: {filepath}")
            return {"CANCELLED"}

        try:
            # If auto_create_object is enabled and no active object, create one
            if props.auto_create_object and not context.active_object:
                # Get tree name from file
                tree_name = os.path.splitext(os.path.basename(filepath))[0]
                obj_name = f"{tree_name}_Object"
                if obj_name in bpy.data.objects:
                    obj = bpy.data.objects[obj_name]
                else:
                    mesh = bpy.data.meshes.new(f"{tree_name}_Mesh")
                    obj = bpy.data.objects.new(obj_name, mesh)
                    context.collection.objects.link(obj)

                # Set as active object
                bpy.ops.object.select_all(action="DESELECT")
                obj.select_set(True)
                context.view_layer.objects.active = obj

            # Read file
            with open(filepath, "r") as f:
                script_content = f.read()

            # Get tree name from file
            tree_name = os.path.splitext(os.path.basename(filepath))[0]

            # Use clearExisting and arrange_nodes from preferences
            clear_existing = prefs.clear_existing if prefs else True
            do_arrange = prefs.arrange_nodes if prefs else True

            # Compile the script
            success, message, trees = compile_script(
                script_content, tree_name, context, filepath, clear_existing
            )

            # Sync and arrange ALL generated trees (geometry + material)
            if success and trees:
                for t in trees:
                    sync_nodes(t, context)
                if do_arrange:
                    for t in trees:
                        arrange_nodes(t, context)

            if success:
                self.report({"INFO"}, message)
                return {"FINISHED"}
            else:
                self.report({"WARNING"}, message)
                return {"CANCELLED"}

        except Exception as e:
            self.report({"ERROR"}, f"Error: {str(e)}")
            import traceback

            traceback.print_exc()
            return {"CANCELLED"}


class XNODIFY_PT_main_panel(Panel):
    """Main panel for XNodify in Node Editor"""

    bl_label = "XNodify"
    bl_idname = "XNODIFY_PT_main_panel"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "XNodify"

    @classmethod
    def poll(cls, context):
        # Show in Geometry Nodes and Shader Editor
        return (
            context.space_data.type == "NODE_EDITOR"
            and context.space_data.tree_type in {"GeometryNodeTree", "ShaderNodeTree"}
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.xnodify_props
        prefs = get_prefs(context)

        # Show current tree type
        tree_type = context.space_data.tree_type
        if tree_type == "GeometryNodeTree":
            layout.label(text="Geometry Nodes", icon="GEOMETRY_NODES")
        elif tree_type == "ShaderNodeTree":
            layout.label(text="Shader Nodes", icon="NODE_MATERIAL")

        # Settings
        box = layout.box()
        box.label(text="Settings:", icon="PREFERENCES")
        box.prop(props, "auto_create_object")
        if prefs:
            box.prop(prefs, "clear_existing")
            box.prop(prefs, "arrange_nodes")

        # Run from Text Editor
        box = layout.box()
        box.label(text="Run from Text Editor:", icon="TEXT")
        box.prop(props, "text_block", text="Script")
        box.operator("xnodify.run_script", icon="PLAY", text="Run Script")

        # Run from File
        box = layout.box()
        box.label(text="Run from File:", icon="FILE")
        if prefs:
            # Show textbox with file path and browse button
            row = box.row(align=True)
            row.prop(prefs, "last_path", text="")
            # Execute button
            box.operator("xnodify.run_file", icon="PLAY", text="Execute File")
        else:
            box.label(text="Preferences not available", icon="ERROR")


class XNODIFY_PT_text_editor_panel(Panel):
    """Panel in text editor"""

    bl_label = "XNodify"
    bl_idname = "XNODIFY_PT_text_editor"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "XNodify"

    def draw(self, context):
        layout = self.layout
        props = context.scene.xnodify_props
        prefs = get_prefs(context)

        text = context.space_data.text

        box = layout.box()
        box.prop(props, "auto_create_object")
        if prefs:
            box.prop(prefs, "clear_existing")
            box.prop(prefs, "arrange_nodes")

        layout.separator()

        if text:
            layout.label(text=f"Script: {text.name}", icon="TEXT")
            layout.operator("xnodify.run_script", icon="PLAY", text="Run Script")
        else:
            layout.label(text="No text selected", icon="ERROR")


# Registration
classes = (
    XNodifyPreferences,
    XNodifyProperties,
    XNODIFY_OT_run_script,
    XNODIFY_OT_run_file,
    XNODIFY_PT_main_panel,
    XNODIFY_PT_text_editor_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.xnodify_props = PointerProperty(type=XNodifyProperties)
    print("XNodify addon registered")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.xnodify_props
    print("XNodify addon unregistered")


if __name__ == "__main__":
    register()
