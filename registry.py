"""Node registry for XNodify - Single Source of Truth

This module provides access to the unified node registry with bidirectional
lookup capability:
- Forward: canonical_name → node definition (inputs, outputs, properties)
- Reverse: bl_idname → canonical_name

The registry is loaded from node_registry.json which contains all nodes
(geometry, common, material) with embedded bl_idname for reverse lookups.
"""
import json
import os


# Nodes that support multi-input sockets (variadic inputs)
# These nodes accept multiple inputs into a single socket (e.g., Join Geometry)
# In scripting, these are joined using the tilde (~) operator
MULTI_INPUT_NODES = {
    "GeometryNodeJoinGeometry",
    "GeometryNodeJoinStrings",
    "NodeJoinBundle", # BL_IDNAME for join_bundle
}


class NodeRegistry:

    """Registry of Blender nodes for XNodify with bidirectional lookup.
    
    Loads from unified node_registry.json which contains:
    - All geometry nodes
    - Common shader nodes (usable in geometry trees)
    - Material-only shader nodes (optional)
    
    Each node entry includes bl_idname for reverse lookup, eliminating
    the need for separate mapping files.
    """
    
    def __init__(self, include_material_nodes=False, target_version=None):
        """Load node registry with bidirectional lookup maps.

        Args:
            include_material_nodes: If True, also include material-only shader nodes
            target_version: Optional Blender version string (e.g., '4.2', '5.1')
        """
        base_path = os.path.dirname(__file__)
        registries_path = os.path.join(base_path, 'registries')
        
        version_dir = None
        
        # 1. Try target_version
        if target_version and os.path.exists(os.path.join(registries_path, target_version)):
            version_dir = target_version
            
        # 2. Try running blender version
        if not version_dir:
            try:
                import bpy
                running_version = f"{bpy.app.version[0]}.{bpy.app.version[1]}"
                if os.path.exists(os.path.join(registries_path, running_version)):
                    version_dir = running_version
            except Exception:
                pass
                
        # 3. Fallback to highest available version
        if not version_dir and os.path.exists(registries_path):
            versions = [d for d in os.listdir(registries_path) if os.path.isdir(os.path.join(registries_path, d))]
            if versions:
                # Sort versions numerically e.g., "5.1" > "4.2"
                versions.sort(key=lambda s: [int(x) for x in s.split('.') if x.isdigit()], reverse=True)
                version_dir = versions[0]
                
        if version_dir:
            registry_base = os.path.join(registries_path, version_dir)
            print(f"NodeRegistry mapping to version: {version_dir}")
        else:
            registry_base = base_path
        
        # Try to load unified registry first (preferred)
        unified_path = os.path.join(registry_base, 'node_registry.json')
        if os.path.exists(unified_path):
            self._load_unified_registry(unified_path, include_material_nodes)
        else:
            # Fallback to separate files for backward compatibility
            self._load_separate_registries(registry_base, include_material_nodes)
    
    def _load_unified_registry(self, unified_path, include_material_nodes):
        """Load from unified node_registry.json."""
        with open(unified_path, 'r') as f:
            all_nodes = json.load(f)
        
        # Build forward and reverse lookup maps
        self.nodes = {}  # canonical_name → node_data
        self._bl_idname_to_name = {}  # bl_idname → canonical_name
        self._name_to_bl_idname = {}  # canonical_name → bl_idname
        
        # Filter by category
        self.geometry_nodes = {}
        self.material_nodes = {}
        
        for canonical_name, node_data in all_nodes.items():
            category = node_data.get('category', 'geometry')
            bl_idname = node_data.get('bl_idname')
            
            # Skip material-only nodes if not requested
            if category == 'material' and not include_material_nodes:
                continue
            
            # Add to main registry
            self.nodes[canonical_name] = node_data
            
            # Build bidirectional maps
            if bl_idname:
                self._bl_idname_to_name[bl_idname] = canonical_name
                self._name_to_bl_idname[canonical_name] = bl_idname
            
            # Categorize for tree-specific lookups
            if category in ('geometry', 'common'):
                self.geometry_nodes[canonical_name] = node_data
            if category in ('material', 'common'):
                self.material_nodes[canonical_name] = node_data

        # Link shader-specific variants from JSON registry (e.g. shader_combine_color -> combine_color in material_nodes)
        for canonical_name, node_data in all_nodes.items():
            if canonical_name.startswith('shader_'):
                base_name = canonical_name[7:]
                self.material_nodes[base_name] = node_data
        
        # Legacy compatibility
        self.bl_idname_map = self._bl_idname_to_name
        
        geo_count = len([n for n, d in all_nodes.items() if d.get('category') == 'geometry'])
        common_count = len([n for n, d in all_nodes.items() if d.get('category') == 'common'])
        mat_count = len([n for n, d in all_nodes.items() if d.get('category') == 'material'])
        
        if include_material_nodes:
            print(f"Loaded {geo_count} geometry + {common_count} common + {mat_count} material = {len(self.nodes)} total nodes")
        else:
            print(f"Loaded {geo_count} geometry + {common_count} common = {len(self.nodes)} total nodes")
    
    def _load_separate_registries(self, base_path, include_material_nodes):
        """Fallback: load from separate JSON files."""
        # Load geometry nodes
        with open(os.path.join(base_path, 'geometry_nodes.json'), 'r') as f:
            geometry_nodes = json.load(f)

        # Load common nodes (shader nodes that work in geometry trees)
        with open(os.path.join(base_path, 'common_nodes.json'), 'r') as f:
            common_nodes = json.load(f)

        # Load reverse mapping: bl_idname → canonical_name
        with open(os.path.join(base_path, 'bl_idname_map.json'), 'r') as f:
            self.bl_idname_map = json.load(f)

        # Store nodes by tree type
        self.geometry_nodes = {}
        self.geometry_nodes.update(geometry_nodes)
        self.geometry_nodes.update(common_nodes)
        
        self.material_nodes = {}
        
        # Optionally load material-only nodes
        if include_material_nodes:
            with open(os.path.join(base_path, 'material_nodes.json'), 'r') as f:
                material_nodes_data = json.load(f)
            self.material_nodes.update(material_nodes_data)
            self.material_nodes.update(common_nodes)
            print(f"Loaded {len(geometry_nodes)} geometry + {len(common_nodes)} common + {len(material_nodes_data)} material = {len(self.geometry_nodes) + len(material_nodes_data)} total nodes")
        else:
            print(f"Loaded {len(geometry_nodes)} geometry + {len(common_nodes)} common = {len(self.geometry_nodes)} total nodes")
        
        # Legacy: combined nodes dict
        self.nodes = self.geometry_nodes.copy()
        if include_material_nodes:
            self.nodes.update(self.material_nodes)
        
        # Build bidirectional maps from bl_idname_map
        self._bl_idname_to_name = self.bl_idname_map
        self._name_to_bl_idname = {v: k for k, v in self.bl_idname_map.items()}
    
    def get_node_def(self, node_type, tree_type=None):
        """Get node definition by canonical name or bl_idname.
        
        Args:
            node_type: The canonical node name (e.g., 'icosphere') or bl_idname
            tree_type: Optional tree type ('GeometryNodeTree' or 'ShaderNodeTree')
                      If provided, will select the appropriate version
        
        Returns:
            Node definition dict or None if not found
        """
        # If tree type is specified, use tree-specific lookup
        if tree_type == 'ShaderNodeTree' and self.material_nodes:
            if node_type in self.material_nodes:
                return self.material_nodes[node_type]
            if hasattr(self, '_bl_idname_to_name') and node_type in self._bl_idname_to_name:
                can_name = self._bl_idname_to_name[node_type]
                if can_name in self.material_nodes:
                    return self.material_nodes[can_name]
        elif tree_type == 'GeometryNodeTree':
            if node_type in self.geometry_nodes:
                return self.geometry_nodes[node_type]
            if hasattr(self, '_bl_idname_to_name') and node_type in self._bl_idname_to_name:
                can_name = self._bl_idname_to_name[node_type]
                if can_name in self.geometry_nodes:
                    return self.geometry_nodes[can_name]
        
        # Fallback to combined registry
        if node_type in self.nodes:
            return self.nodes[node_type]
        if hasattr(self, '_bl_idname_to_name') and node_type in self._bl_idname_to_name:
            can_name = self._bl_idname_to_name[node_type]
            return self.nodes.get(can_name)
        
        # Also check values for bl_idname match
        for key, info in self.nodes.items():
            if info.get('bl_idname') == node_type:
                return info
                
        return None
    
    def get_socket_info(self, node_type, socket_name):
        """Get socket information for a node type."""
        node_def = self.get_node_def(node_type)
        if not node_def:
            return None

        # Check inputs
        if 'inputs' in node_def:
            for socket in node_def['inputs']:
                if socket.get('name') == socket_name:
                    return socket

        # Check outputs
        if 'outputs' in node_def:
            for socket in node_def['outputs']:
                if socket.get('name') == socket_name:
                    return socket

        return None

    def get_canonical_name(self, bl_idname):
        """Get canonical node name from Blender bl_idname (reverse lookup).

        Args:
            bl_idname: Blender node identifier (e.g., 'GeometryNodeMeshIcoSphere')

        Returns:
            Canonical node name (e.g., 'icosphere') or None if not found
        """
        return self._bl_idname_to_name.get(bl_idname)
    
    def get_bl_idname(self, canonical_name):
        """Get Blender bl_idname from canonical name (forward lookup).

        Args:
            canonical_name: The canonical node name (e.g., 'icosphere') or bl_idname

        Returns:
            Blender bl_idname (e.g., 'GeometryNodeMeshIcoSphere') or None if not found
        """
        if canonical_name in self._name_to_bl_idname:
            return self._name_to_bl_idname[canonical_name]
        if canonical_name in self._bl_idname_to_name:
            return canonical_name
        node_def = self.nodes.get(canonical_name)
        if node_def:
            return node_def.get('bl_idname')
        return self._name_to_bl_idname.get(canonical_name)
    
    def list_nodes(self, category=None):
        """List all available node names, optionally filtered by category.
        
        Args:
            category: Optional filter - 'geometry', 'common', or 'material'
        
        Returns:
            List of canonical node names
        """
        if category:
            return [name for name, data in self.nodes.items() 
                    if data.get('category') == category]
        return list(self.nodes.keys())
