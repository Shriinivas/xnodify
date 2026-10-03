import bpy
import json
import os
import sys
import time
import re

def transform_node_name(bl_idname, is_geometry=False, is_common=False, is_material=False, reserved_names=None):
    """
    Transform a Blender node ID name to a concise, user-friendly name.

    Args:
        bl_idname: Original Blender node ID (e.g., 'GeometryNodeInputPosition')
        is_geometry: True if this is a geometry-only node
        is_common: True if this is a common shader node (works in both contexts)
        is_material: True if this is a material-only shader node
        reserved_names: Set of names already taken (for conflict detection)

    Returns:
        Transformed short name (e.g., 'position')
    """
    if reserved_names is None:
        reserved_names = set()

    # Step 1: Remove node type prefix
    short_name = bl_idname
    if short_name.startswith('GeometryNode'):
        short_name = short_name[len('GeometryNode'):]
    elif short_name.startswith('ShaderNode'):
        short_name = short_name[len('ShaderNode'):]
    elif short_name.startswith('FunctionNode'):
        short_name = short_name[len('FunctionNode'):]
    elif short_name.startswith('Node') and short_name not in ['NodeFrame', 'NodeGroup', 'NodeGroupInput', 'NodeGroupOutput', 'NodeReroute']:
        short_name = short_name[len('Node'):]

    # Step 2: Convert CamelCase to snake_case
    name = re.sub(r'(?<!^)(?=[A-Z])', '_', short_name).lower()

    # Step 3: Apply acronym compressions (ALWAYS - these are safe and unambiguous)
    acronym_map = {
        'x_y_z': 'xyz',
        'r_g_b': 'rgb',
        'h_s_v': 'hsv',
        'u_v': 'uv',
        's_d_f': 'sdf',
        'i_d': 'id',
        'b_w': 'bw',
        'a_o_v': 'aov',
        'c_s_v': 'csv',
        'o_b_j': 'obj',
        'p_l_y': 'ply',
        's_t_l': 'stl',
        'u_s_d': 'usd',
        'g_l_t_f': 'gltf',
        'f_b_x': 'fbx',
    }

    for old_pattern, new_pattern in acronym_map.items():
        name = name.replace(old_pattern, new_pattern)

    # Step 4: Simplify mesh primitives (geometry nodes only)
    if is_geometry:
        primitive_map = {
            'mesh_ico_sphere': 'icosphere',
            'mesh_uv_sphere': 'uvsphere',
        }

        if name in primitive_map:
            name = primitive_map[name]

    # Step 5: Remove redundant prefixes for geometry nodes
    # These are field accessors where context is obvious from usage
    if is_geometry:
        # Remove input_mesh_ prefix (these are mesh-specific field accessors)
        if name.startswith('input_mesh_'):
            name = name.replace('input_mesh_', '')

        # Remove input_ prefix for commonly used field inputs
        # (Keep for ambiguous ones like input_image, input_material, etc.)
        simple_inputs = [
            'input_position',
            'input_normal',
            'input_index',
            'input_id',
            'input_radius',
        ]

        if name in simple_inputs:
            name = name.replace('input_', '')

    # Step 6: Material-only nodes: add shader_ prefix if conflicts with geometry/common
    # But if it's already specific (like 'bsdf_diffuse', 'tex_*', 'output_*'), keep as is
    if is_material:
        # Check if name would conflict with geometry/common nodes
        if name in reserved_names and not name.startswith(('bsdf_', 'tex_', 'output_', 'shader_')):
            # Add shader_ prefix to disambiguate
            name = 'shader_' + name

    return name

def generate_registries():
    """Generate separate registries for geometry nodes, common nodes, and material nodes"""

    print("Starting registry generation...")

    import bpy
    blender_version = f"{bpy.app.version[0]}.{bpy.app.version[1]}"
    print(f"Detected Blender version: {blender_version}")

    # Load the list of common shader nodes (that work in geometry trees)
    common_list_path = os.path.join(os.path.dirname(__file__), "../common_nodes_list.json")
    with open(common_list_path, 'r') as f:
        common_data = json.load(f)
        common_shader_nodes = set(common_data['common_shader_nodes'])

    print(f"Loaded {len(common_shader_nodes)} common shader nodes")

    # Create temporary node trees for both geometry and material nodes
    geo_tree = bpy.data.node_groups.new("TempGeoTree", "GeometryNodeTree")
    mat_tree = bpy.data.node_groups.new("TempMatTree", "ShaderNodeTree")

    # Get all potential node types
    node_types = []
    bundle_closure_nodes = {
        'NodeCombineBundle', 'NodeSeparateBundle', 'NodeJoinBundle',
        'NodeGetBundleItem', 'NodeStoreBundleItem', 'NodeGetNestedBundlePaths',
        'NodeClosureInput', 'NodeClosureOutput', 'NodeEvaluateClosure'
    }
    for type_name in dir(bpy.types):
        if (any(type_name.startswith(prefix) for prefix in ['GeometryNode', 'ShaderNode', 'FunctionNode']) or
            type_name in bundle_closure_nodes):
             if 'Legacy' in type_name:
                continue
             node_types.append(type_name)

    print(f"Found {len(node_types)} potential node types")

    # First pass: extract all node data and categorize
    geometry_data = {}
    common_data = {}
    material_data = {}

    count = 0
    start_time = time.time()

    for type_name in node_types:
        count += 1
        if count % 50 == 0:
            print(f"Processing {count}/{len(node_types)}")

        can_geo = False
        can_mat = False
        geo_node = None
        mat_node = None

        try:
            geo_node = geo_tree.nodes.new(type_name)
            can_geo = True
        except Exception:
            pass

        try:
            mat_node = mat_tree.nodes.new(type_name)
            can_mat = True
        except Exception:
            pass

        node = geo_node or mat_node
        if node is None:
            continue

        bl_idname = node.bl_idname

        node_data = {
            "bl_idname": bl_idname,
            "inputs": {},
            "outputs": {},
            "properties": {}
        }

        # Extract Inputs
        for i, socket in enumerate(node.inputs):
            node_data["inputs"][socket.name] = {
                "index": i,
                "type": socket.type,
                "identifier": socket.identifier
            }

        # Extract Outputs
        for i, socket in enumerate(node.outputs):
            node_data["outputs"][socket.name] = {
                "index": i,
                "type": socket.type,
                "identifier": socket.identifier
            }

        # Extract Properties
        if hasattr(node, 'rna_type'):
            for prop in node.rna_type.properties:
                if prop.identifier in ['rna_type', 'name', 'label', 'parent', 'location', 'width', 'height', 'inputs', 'outputs', 'color', 'use_custom_color', 'select', 'dimensions']:
                    continue
                
                try:
                    default_val = getattr(node, prop.identifier, None)
                    is_struct = isinstance(default_val, bpy.types.bpy_struct) and not isinstance(default_val, (bpy.types.Node, bpy.types.NodeTree, bpy.types.ID))
                    
                    if prop.is_readonly and not is_struct:
                        continue
 
                    def serialize(val):
                        if val is None: return None
                        if isinstance(val, (int, float, str, bool)): return val
                        if isinstance(val, (bpy.types.bpy_prop_collection, bpy.types.bpy_struct, bpy.types.ID)):
                            if isinstance(val, bpy.types.bpy_struct) and not isinstance(val, (bpy.types.Node, bpy.types.NodeTree, bpy.types.ID)):
                                struct_props = {}
                                for sub_prop in val.rna_type.properties:
                                    if sub_prop.identifier in ['rna_type', 'name']:
                                        continue
                                    try:
                                        sub_val = getattr(val, sub_prop.identifier)
                                    except:
                                        continue
                                    
                                    sub_is_struct = isinstance(sub_val, bpy.types.bpy_struct) and not isinstance(sub_val, (bpy.types.Node, bpy.types.NodeTree, bpy.types.ID))
                                    if sub_prop.is_readonly and not sub_is_struct:
                                        continue
                                        
                                    try:
                                        serialized_sub = serialize(sub_val)
                                        if serialized_sub is not None:
                                            prop_type = "STRUCT" if isinstance(serialized_sub, dict) and serialized_sub.get("type") == "STRUCT" else sub_prop.type
                                            struct_props[sub_prop.identifier] = {
                                                "type": prop_type,
                                                "default": serialized_sub
                                            }
                                    except:
                                        pass
                                if struct_props:
                                    return {
                                        "type": "STRUCT",
                                        "properties": struct_props
                                    }
                            return "COMPLEX"
                        if hasattr(val, "to_list"): return [list(x) if hasattr(x, "__iter__") else x for x in val.to_list()]
                        if hasattr(val, "to_tuple"): return list(val.to_tuple())
                        if hasattr(val, "__iter__"): return [serialize(x) for x in val]
                        return str(val)
 
                    serialized_val = serialize(default_val)
                    prop_type = "STRUCT" if isinstance(serialized_val, dict) and serialized_val.get("type") == "STRUCT" else prop.type
                    node_data["properties"][prop.identifier] = {
                        "type": prop_type,
                        "default": serialized_val
                    }
                except:
                    pass

        # Categorize node dynamically: both trees = common, only geo = geometry, only mat = material
        if can_geo and can_mat:
            common_data[bl_idname] = node_data
        elif can_geo:
            geometry_data[bl_idname] = node_data
        elif can_mat:
            material_data[bl_idname] = node_data

        # Clean up from whichever tree we used
        if geo_node:
            geo_tree.nodes.remove(geo_node)
        if mat_node:
            mat_tree.nodes.remove(mat_node)

    # Clean up trees
    bpy.data.node_groups.remove(geo_tree)
    bpy.data.node_groups.remove(mat_tree)

    # Second pass: apply naming transformations with conflict detection
    print("\nApplying name transformations...")

    reserved_names = set()
    geometry_registry = {}
    common_registry = {}
    material_registry = {}

    # Process geometry nodes first (highest priority for short names)
    for bl_idname, node_data in geometry_data.items():
        name = transform_node_name(bl_idname, is_geometry=True, reserved_names=reserved_names)
        reserved_names.add(name)
        geometry_registry[name] = node_data

    # Process common nodes (also high priority)
    for bl_idname, node_data in common_data.items():
        name = transform_node_name(bl_idname, is_common=True, reserved_names=reserved_names)
        reserved_names.add(name)
        common_registry[name] = node_data

    # Process material nodes last (will add shader_ prefix if conflicts)
    for bl_idname, node_data in material_data.items():
        name = transform_node_name(bl_idname, is_material=True, reserved_names=reserved_names)
        material_registry[name] = node_data

    # Write registries to versioned directory and root addon directory
    version_path = os.path.join(os.path.dirname(__file__), "..", "registries", blender_version)
    root_path = os.path.join(os.path.dirname(__file__), "..")
    os.makedirs(version_path, exist_ok=True)

    # Generate reverse mapping: bl_idname → canonical_name
    bl_idname_map = {}
    for canonical_name, node_data in geometry_registry.items():
        bl_idname = node_data.get('bl_idname')
        if bl_idname:
            bl_idname_map[bl_idname] = canonical_name
    for canonical_name, node_data in common_registry.items():
        bl_idname = node_data.get('bl_idname')
        if bl_idname:
            bl_idname_map[bl_idname] = canonical_name
    for canonical_name, node_data in material_registry.items():
        bl_idname = node_data.get('bl_idname')
        if bl_idname:
            bl_idname_map[bl_idname] = canonical_name

    # Generate unified node_registry.json with category field
    unified_registry = {}
    
    for canonical_name, node_data in geometry_registry.items():
        unified_registry[canonical_name] = {
            **node_data,
            "category": "geometry"
        }
    
    for canonical_name, node_data in common_registry.items():
        unified_registry[canonical_name] = {
            **node_data,
            "category": "common"
        }
    
    for canonical_name, node_data in material_registry.items():
        unified_registry[canonical_name] = {
            **node_data,
            "category": "material"
        }

    for base_dir in [version_path, root_path]:
        with open(os.path.join(base_dir, "geometry_nodes.json"), 'w') as f:
            json.dump(geometry_registry, f, indent=2)
        with open(os.path.join(base_dir, "common_nodes.json"), 'w') as f:
            json.dump(common_registry, f, indent=2)
        with open(os.path.join(base_dir, "material_nodes.json"), 'w') as f:
            json.dump(material_registry, f, indent=2)
        with open(os.path.join(base_dir, "bl_idname_map.json"), 'w') as f:
            json.dump(bl_idname_map, f, indent=2, sort_keys=True)
        with open(os.path.join(base_dir, "node_registry.json"), 'w') as f:
            json.dump(unified_registry, f, indent=2, sort_keys=True)

    # Also update common_nodes_list.json
    common_list_path = os.path.join(os.path.dirname(__file__), "../common_nodes_list.json")
    with open(common_list_path, 'w') as f:
        json.dump({
            "common_shader_nodes": sorted(list(common_data.keys())),
            "count": len(common_data)
        }, f, indent=2)

    print(f"✓ Geometry nodes: {len(geometry_registry)}")
    print(f"✓ Common nodes: {len(common_registry)}")
    print(f"✓ Material nodes: {len(material_registry)}")
    print(f"✓ bl_idname reverse map: {len(bl_idname_map)}")
    print(f"✓ Unified node_registry.json: {len(unified_registry)} nodes")

    print(f"Time: {time.time() - start_time:.2f}s")

if __name__ == "__main__":
    generate_registries()

