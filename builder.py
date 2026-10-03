try:
    from .registry import NodeRegistry
    from .logger import get_logger
    from .socket_types import get_bundle_type, get_dynamic_item_type_and_label, XNODIFY_TO_BLENDER
except ImportError:
    from registry import NodeRegistry
    from logger import get_logger
    from socket_types import get_bundle_type, get_dynamic_item_type_and_label, XNODIFY_TO_BLENDER

# Initialize logger for this module
logger = get_logger()

class NodeBuilder:
    def __init__(self, registry=None):
        self.registry = registry or NodeRegistry()
        self.nodes = {} # map name/id to node object
        self.compiler = None

    def warning(self, msg, node=None):
        """Log warning through compiler if available (for source location context) or logger."""
        if getattr(self, "compiler", None) and hasattr(self.compiler, "warning"):
            self.compiler.warning(msg, node=node)
        else:
            logger.warning(msg)

    def error(self, msg, node=None):
        """Log error through compiler if available (for source location context) or logger."""
        if getattr(self, "compiler", None) and hasattr(self.compiler, "error"):
            self.compiler.error(msg, node=node)
        else:
            logger.error(msg)

    def create_node(self, node_type, name=None, parent=None, **kwargs):
        raise NotImplementedError

    def create_frame(self, name, **kwargs):
        raise NotImplementedError

    def connect(self, from_node, from_socket, to_node, to_socket):
        raise NotImplementedError

    def set_property(self, node, property_name, value):
        raise NotImplementedError

class BlenderNodeBuilder(NodeBuilder):
    def __init__(self, node_tree, registry=None):
        super().__init__(registry)
        self.node_tree = node_tree
        self.compiler = None

    def create_node(self, node_type, name=None, parent=None, **kwargs):
        # Special handling for repeat zone nodes
        if node_type == 'repeat_input':
            node = self.node_tree.nodes.new('GeometryNodeRepeatInput')
            if name:
                node.name = name
                node.label = name
            if parent:
                node.parent = parent
            return node
        elif node_type == 'repeat_output':
            node = self.node_tree.nodes.new('GeometryNodeRepeatOutput')
            if name:
                node.name = name
                node.label = name
            if parent:
                node.parent = parent
            return node
        
        # Normal node creation
        tree_type = self.node_tree.bl_idname if hasattr(self.node_tree, 'bl_idname') else None
        node_def = self.registry.get_node_def(node_type, tree_type=tree_type)
        if not node_def:
            # Try to find by bl_idname as fallback
            found = False
            for key, info in self.registry.nodes.items():
                if info.get('bl_idname') == node_type:
                    node_def = info
                    found = True
                    break
            
            if not found:
                raise ValueError(f"Unknown node type: {node_type}")
        
        bl_idname = node_def['bl_idname']
        node = self.node_tree.nodes.new(bl_idname)
        
        if name:
            node.name = name
            node.label = name # Useful for debugging in UI
            
        if parent:
            # parent is expected to be the actual Blender node object for the frame
            node.parent = parent
            
        # Set properties
        for prop, val in kwargs.items():
            self.set_property(node, prop, val)
            
        return node

    def create_frame(self, name, **kwargs):
        node = self.node_tree.nodes.new("NodeFrame")
        if name:
            node.name = name
            node.label = name
            
        for prop, val in kwargs.items():
            setattr(node, prop, val)
            
        return node

    def create_link(self, from_socket, to_socket):
        """Create a direct link between two sockets."""
        self.node_tree.links.new(from_socket, to_socket)

    def _create_virtual_socket(self, node, socket_index, from_socket):
        """Create virtual socket for nodes that support dynamic sockets

        Args:
            node: The target node
            socket_index: Index of the socket to check
            from_socket: The source socket being connected (to determine type)

        Returns:
            The actual socket to use (may be newly created)
        """
        if socket_index >= len(node.inputs):
            return None

        input_socket = node.inputs[socket_index]

        # Check if this is a virtual socket that needs to be created
        if getattr(input_socket, "bl_idname", None) == "NodeSocketVirtual":
            if node.bl_idname == "GeometryNodeIndexSwitch":
                # Create new index switch item
                node.index_switch_items.new()
                return node.inputs[-2]
            elif node.bl_idname in ("GeometryNodeCaptureAttribute", "GeometryNodeFieldToGrid"):
                from_id = getattr(from_socket, "bl_idname", "")
                type_name, name = get_dynamic_item_type_and_label(from_id, for_capture=True)
                if node.bl_idname == "GeometryNodeFieldToGrid":
                    node.grid_items.new(type_name, name)
                else:
                    node.capture_items.new(type_name, name)
                return node.inputs[-2]
            elif node.bl_idname == "GeometryNodeFieldToList":
                from_id = getattr(from_socket, "bl_idname", "")
                type_name, name = get_dynamic_item_type_and_label(from_id)
                item_count = len(node.list_items) + 1
                node.list_items.new(type_name, f"{name} {item_count}")
                return node.inputs[-2]
            elif node.bl_idname in ("NodeClosureOutput", "NodeEvaluateClosure"):
                from_id = getattr(from_socket, "bl_idname", "")
                type_name, name = get_dynamic_item_type_and_label(from_id)
                if node.bl_idname == "NodeClosureOutput":
                    item_count = len(node.output_items) + 1
                    node.output_items.new(type_name, f"{name} {item_count}")
                else:
                    item_count = len(node.input_items) + 1
                    node.input_items.new(type_name, f"{name} {item_count}")
                return node.inputs[-2]
            elif node.bl_idname == "NodeCombineBundle":
                if from_socket:
                    try:
                        type_enum = get_bundle_type(from_socket.bl_idname)
                        if type_enum:
                            name_to_use = "Type" if getattr(from_socket, "name", "").lower() == "type" else from_socket.name
                            node.bundle_items.new(type_enum, name_to_use)
                            if hasattr(node, "define_signature"):
                                node.define_signature = True
                            return node.inputs[-2]
                    except Exception as e:
                        self.warning(f"Failed to create input for NodeCombineBundle: {e}")

        return input_socket

    def connect(self, from_node, from_socket, to_node, to_socket):
        # Resolve sockets
        out_sock = self._get_socket(from_node.outputs, from_socket)

        # Handle virtual sockets for dynamic nodes
        socket_index = -1
        if isinstance(to_socket, int):
            socket_index = to_socket
        else:
            temp_sock = self._get_socket(to_node.inputs, to_socket)
            if temp_sock and getattr(temp_sock, "bl_idname", None) == "NodeSocketVirtual":
                for i, s in enumerate(to_node.inputs):
                    if s == temp_sock:
                        socket_index = i
                        break
        
        in_sock = None
        if socket_index != -1:
            in_sock = self._create_virtual_socket(to_node, socket_index, out_sock)
        
        if in_sock is None:
            in_sock = self._get_socket(to_node.inputs, to_socket)
        
        # Handle dynamic INPUTS (NodeCombineBundle) when socket doesn't exist yet
        if getattr(to_node, "bl_idname", None) == "NodeCombineBundle" and in_sock is None and out_sock:
            try:
                from_id = getattr(out_sock, "bl_idname", "")
                type_enum = get_bundle_type(from_id) or "FLOAT"
                item_name = str(to_socket) if isinstance(to_socket, str) and to_socket != "__extend__" else getattr(out_sock, "name", "Item")
                if item_name.lower() == "type":
                    item_name = "Type"
                to_node.bundle_items.new(type_enum, item_name)
                if hasattr(to_node, "define_signature"):
                    to_node.define_signature = True
                in_sock = to_node.inputs[-2]
            except Exception as e:
                self.warning(f"Failed to create input for NodeCombineBundle: {e}")

        # Handle dynamic OUTPUTS (NodeSeparateBundle)
        if getattr(from_node, "bl_idname", None) == "NodeSeparateBundle" and out_sock and in_sock:
            if getattr(out_sock, "identifier", None) == "__extend__":
                try:
                    type_enum = get_bundle_type(in_sock.bl_idname)
                    if type_enum:
                        from_node.bundle_items.new(type_enum, in_sock.name)
                        if hasattr(from_node, "define_signature"):
                            from_node.define_signature = True
                        out_sock = from_node.outputs[-2]
                except Exception as e:
                    self.warning(f"Failed to create output for NodeSeparateBundle: {e}")

        if out_sock and in_sock:
            self.node_tree.links.new(in_sock, out_sock)
            logger.debug(f"Connected {from_node.name}.{out_sock.name} -> {to_node.name}.{in_sock.name}")
        else:
            self.error(f"Error connecting {from_node.name}.{from_socket} -> {to_node.name}.{to_socket}")
            if not out_sock:
                self.error(f"  Output socket not found. Available outputs ({len(from_node.outputs)}):")
                for i, s in enumerate(from_node.outputs):
                    self.error(f"    [{i}] {s.name}")
            if not in_sock:
                self.error(f"  Input socket not found. Available inputs ({len(to_node.inputs)}):")
                for i, s in enumerate(to_node.inputs):
                    self.error(f"    [{i}] {s.name}")

    def _resolve_datablock(self, target_obj, prop_name, value):
        """Generically resolve a string value to a Blender ID datablock (image, font, material, object, collection)."""
        if not isinstance(value, str):
            return value

        import os
        try:
            import bpy
        except ImportError:
            return value

        prop_lower = prop_name.lower().replace('_', '')

        # 1. Inspect Blender RNA property type directly if available
        if hasattr(target_obj, 'bl_rna') and prop_name in target_obj.bl_rna.properties:
            prop = target_obj.bl_rna.properties[prop_name]
            if prop.type == 'POINTER' and getattr(prop, 'fixed_type', None):
                target_type = prop.fixed_type.name
                if target_type == 'Image':
                    for img in bpy.data.images:
                        if img.filepath == value or img.name == value or (img.filepath and os.path.basename(img.filepath) == os.path.basename(value)):
                            return img
                    try:
                        return bpy.data.images.load(value, check_existing=True)
                    except Exception:
                        return bpy.data.images.get(value)
                elif target_type == 'VectorFont':
                    for f in bpy.data.fonts:
                        if f.filepath == value or f.name == value or (f.filepath and os.path.basename(f.filepath) == os.path.basename(value)):
                            return f
                    try:
                        return bpy.data.fonts.load(value)
                    except Exception:
                        return bpy.data.fonts.get(value)
                elif target_type == 'Material':
                    return bpy.data.materials.get(value)
                elif target_type == 'Object':
                    return bpy.data.objects.get(value)
                elif target_type == 'Collection':
                    return bpy.data.collections.get(value)
            # If RNA property is not a pointer (e.g. enum, bool, float), do not resolve as datablock
            return value

        # 2. Inspect Socket type
        if hasattr(target_obj, 'type') and isinstance(getattr(target_obj, 'type', None), str):
            sock_type = target_obj.type
            if sock_type == 'IMAGE':
                for img in bpy.data.images:
                    if img.filepath == value or img.name == value or (img.filepath and os.path.basename(img.filepath) == os.path.basename(value)):
                        return img
                try:
                    return bpy.data.images.load(value, check_existing=True)
                except Exception:
                    return bpy.data.images.get(value)
            elif sock_type == 'MATERIAL':
                return bpy.data.materials.get(value)
            elif sock_type == 'OBJECT':
                return bpy.data.objects.get(value)
            elif sock_type == 'COLLECTION':
                return bpy.data.collections.get(value)

        # 3. Filepath / image / font property aliases
        if prop_lower in ('filepath', 'imagepath', 'filepath', 'image_path'):
            for img in bpy.data.images:
                if img.filepath == value or img.name == value or (img.filepath and os.path.basename(img.filepath) == os.path.basename(value)):
                    return img
            try:
                return bpy.data.images.load(value, check_existing=True)
            except Exception:
                return bpy.data.images.get(value)
        elif prop_lower in ('fontpath', 'font_path'):
            for f in bpy.data.fonts:
                if f.filepath == value or f.name == value or (f.filepath and os.path.basename(f.filepath) == os.path.basename(value)):
                    return f
            try:
                return bpy.data.fonts.load(value)
            except Exception:
                return bpy.data.fonts.get(value)

        return value

    def _set_attribute_generic(self, target_obj, attr_name, value):
        """Set an attribute on an RNA object with automatic type conversion and enum-case tolerance."""
        if not hasattr(target_obj, attr_name):
            return False

        resolved_val = self._resolve_datablock(target_obj, attr_name, value)

        try:
            setattr(target_obj, attr_name, resolved_val)
            return True
        except Exception:
            if isinstance(resolved_val, str):
                # Check Blender RNA enum items to match UI names/variants to RNA identifiers
                if hasattr(target_obj, 'bl_rna') and attr_name in target_obj.bl_rna.properties:
                    prop = target_obj.bl_rna.properties[attr_name]
                    if getattr(prop, 'type', None) == 'ENUM':
                        val_norm = resolved_val.strip().upper().replace(' ', '_').replace('-', '_')
                        # Pass 1: exact match with identifier or UI name
                        for item in prop.enum_items:
                            id_norm = item.identifier.upper().replace(' ', '_').replace('-', '_')
                            name_norm = item.name.upper().replace(' ', '_').replace('-', '_')
                            if val_norm in (id_norm, name_norm):
                                try:
                                    setattr(target_obj, attr_name, item.identifier)
                                    return True
                                except Exception:
                                    pass
                        # Pass 2: prefix or abbreviation match (e.g. SINE -> SIN, TRIANGLE -> TRI)
                        for item in prop.enum_items:
                            id_norm = item.identifier.upper().replace(' ', '_').replace('-', '_')
                            name_norm = item.name.upper().replace(' ', '_').replace('-', '_')
                            if (val_norm.startswith(id_norm) or id_norm.startswith(val_norm) or
                                val_norm.startswith(name_norm) or name_norm.startswith(val_norm)):
                                try:
                                    setattr(target_obj, attr_name, item.identifier)
                                    return True
                                except Exception:
                                    pass

                candidates = [
                    resolved_val.upper(),
                    resolved_val.title(),
                    resolved_val.lower(),
                    resolved_val.replace('_', ' ').upper(),
                    resolved_val.replace('_', ' ').title(),
                    resolved_val.replace('_', ' ').lower(),
                ]
                if resolved_val.upper() == 'UDIM':
                    candidates.insert(0, 'TILED')
                for cand in candidates:
                    try:
                        setattr(target_obj, attr_name, cand)
                        return True
                    except Exception:
                        pass
            elif isinstance(resolved_val, bool):
                if resolved_val:
                    for cand in ('TILED', 'TRUE', 'True'):
                        try:
                            setattr(target_obj, attr_name, cand)
                            return True
                        except Exception:
                            pass
            return False

    def set_property(self, node, property_name, value):
        """Generic property setter for all Blender nodes, sub-objects, and sockets."""
        # 1. Handle bracket notation like outputs[0].default_value or inputs[2].default_value
        if '[' in property_name and ']' in property_name:
            try:
                parts = property_name.split('[')
                collection_name = parts[0]
                rest = parts[1]
                index_str = rest.split(']')[0]
                index = int(index_str)
                remaining = rest.split(']', 1)[1]
                if remaining.startswith('.'):
                    remaining = remaining[1:]

                collection = getattr(node, collection_name)
                item = collection[index]
                if remaining:
                    self._set_attribute_generic(item, remaining, value)
                return
            except Exception as e:
                self.error(f"Error setting property {property_name} on {node.name}: {e}")
                return

        # 2. Handle nested properties using dot notation, e.g. color_ramp.interpolation, image.source
        if '.' in property_name:
            try:
                parts = property_name.split('.')
                obj = node
                for part in parts[:-1]:
                    obj = getattr(obj, part)
                if self._set_attribute_generic(obj, parts[-1], value):
                    logger.debug(f"Set {node.name}.{property_name} = {value}")
                    return
            except Exception as e:
                self.error(f"Error setting nested property {property_name} on {node.name}: {e}")
                return

        # 3. Handle specific property aliases before direct node attributes
        if property_name in ('name', 'attr_name', 'attribute', 'attribute_name') and hasattr(node, 'attribute_name'):
            if self._set_attribute_generic(node, 'attribute_name', value):
                logger.debug(f"Set {node.name}.attribute_name = {value}")
                return

        if property_name in ('file_path', 'filepath', 'font_path', 'image_path'):
            for target_attr in ('image', 'font'):
                if hasattr(node, target_attr) and self._set_attribute_generic(node, target_attr, value):
                    logger.debug(f"Set {node.name}.{target_attr} = {value}")
                    return

        # 4. Direct property on node
        if self._set_attribute_generic(node, property_name, value):
            logger.debug(f"Set {node.name}.{property_name} = {value}")
            return

        # 5. Generic sub-object property search (e.g. source -> node.image.source)
        sub_attrs = ('image', 'image_user', 'font', 'texture_mapping', 'color_mapping', 'color_ramp', 'mapping')
        for sub_name in sub_attrs:
            sub_obj = getattr(node, sub_name, None)
            if sub_obj and self._set_attribute_generic(sub_obj, property_name, value):
                logger.debug(f"Set {node.name}.{sub_name}.{property_name} = {value}")
                return

        # 6. Input socket fallback
        if hasattr(node, "inputs"):
            socket = self._get_socket(node.inputs, property_name)
            if socket is None and property_name in ('file_path', 'filepath', 'image_path', 'image'):
                socket = self._get_socket(node.inputs, 'Image')
            if socket is None and property_name in ('font_path', 'font'):
                socket = self._get_socket(node.inputs, 'Font')

            if socket and self._set_socket_value(socket, value, node=node):
                logger.debug(f"Set input socket default value {node.name}.{socket.name} = {value}")
                return

        # 7. Output socket fallback for value/color input nodes (nodes with 0 inputs)
        if hasattr(node, "inputs") and len(node.inputs) == 0 and hasattr(node, "outputs") and len(node.outputs) > 0:
            if property_name.lower() in ('color', 'value', 'val', 'default_value', 'rgb', 'rgba') or property_name == node.outputs[0].name.lower():
                if self._set_socket_value(node.outputs[0], value, node=node):
                    logger.debug(f"Set output socket default value {node.name}.{node.outputs[0].name} = {value}")
                    return

        self.warning(f"Could not set property or input socket '{property_name}' on node '{node.name}'")

    def _set_socket_value(self, socket, value, socket_label=None, node=None):
        """Generic setter for socket default_value with datablock resolution, hex colors, vector conversion, and enum tolerance."""
        if not socket or getattr(socket, "bl_idname", None) == "NodeSocketVirtual":
            return False

        # 1. Handle MenuSwitch custom labels
        if socket_label and node and getattr(node, "bl_idname", None) == "GeometryNodeMenuSwitch":
            socket_index = next((idx for idx, inp in enumerate(node.inputs) if inp == socket), None)
            if socket_index is not None and socket_index >= 1:
                enum_index = socket_index - 1
                if enum_index < len(node.enum_items):
                    node.enum_items[enum_index].name = socket_label

        # 2. Hex color strings on RGBA sockets
        if hasattr(socket, "type") and socket.type == "RGBA" and isinstance(value, str) and value.startswith("#"):
            hex_color = value.lstrip("#")
            if len(hex_color) == 6:
                r = int(hex_color[0:2], 16) / 255.0
                g = int(hex_color[2:4], 16) / 255.0
                b = int(hex_color[4:6], 16) / 255.0
                socket.default_value = (r, g, b, 1.0)
                return True
            elif len(hex_color) == 8:
                r = int(hex_color[0:2], 16) / 255.0
                g = int(hex_color[2:4], 16) / 255.0
                b = int(hex_color[4:6], 16) / 255.0
                a = int(hex_color[6:8], 16) / 255.0
                socket.default_value = (r, g, b, a)
                return True

        # 3. Scalar-to-vector auto-conversion
        if hasattr(socket, "type") and socket.type == "VECTOR" and isinstance(value, (int, float)):
            socket.default_value = (float(value), float(value), float(value))
            return True

        # 4. Generic datablock resolution (Material, Object, Image, Font, Collection)
        resolved_val = self._resolve_datablock(socket, getattr(socket, "name", ""), value)

        # If this is a material socket and material was specified by name but not yet found, register as pending
        is_mat_socket = (
            getattr(socket, "type", None) == "MATERIAL"
            or getattr(socket, "bl_idname", None) == "NodeSocketMaterial"
            or getattr(socket, "bl_socket_idname", None) == "NodeSocketMaterial"
        )
        if is_mat_socket and isinstance(value, str) and value.strip() and resolved_val is None:
            if self.compiler is not None and hasattr(self.compiler, "pending_materials"):
                self.compiler.pending_materials.append((socket, value.strip()))

        # 5. Direct assignment with enum case tolerance
        try:
            socket.default_value = resolved_val
            return True
        except Exception:
            if isinstance(resolved_val, str):
                candidates = [
                    resolved_val.title(),
                    resolved_val.upper(),
                    resolved_val.lower(),
                    resolved_val.replace('_', ' ').title(),
                    resolved_val.replace('_', ' ').upper(),
                ]
                for cand in candidates:
                    try:
                        socket.default_value = cand
                        return True
                    except Exception:
                        pass
            return False

    def _get_socket(self, sockets, key):
        # If key is already a socket object, return it directly
        if hasattr(key, 'name') and hasattr(key, 'type'):
            return key
        
        if isinstance(key, int):
            if 0 <= key < len(sockets):
                return sockets[key]
            elif -len(sockets) <= key < 0:
                return sockets[key]
        elif isinstance(key, str):
            # Normalize search key (space-separated and no-space)
            key_norm = key.replace('_', ' ').lower().strip()
            key_nospace = key.replace('_', '').replace(' ', '').lower().strip()

            def matches_name(cand):
                if not cand:
                    return False
                c_norm = cand.replace('_', ' ').lower().strip()
                c_nospace = cand.replace('_', '').replace(' ', '').lower().strip()
                return cand.lower() == key.lower() or c_norm == key_norm or c_nospace == key_nospace

            active_label_matches = []
            active_name_matches = []
            inactive_label_matches = []
            inactive_name_matches = []

            for socket_obj in sockets:
                is_active = getattr(socket_obj, 'enabled', True) and not getattr(socket_obj, 'hide', False)
                s_label = getattr(socket_obj, 'label', '')
                s_name = getattr(socket_obj, 'name', '')
                s_id = getattr(socket_obj, 'identifier', '')

                if s_label and matches_name(s_label):
                    if is_active:
                        active_label_matches.append(socket_obj)
                    else:
                        inactive_label_matches.append(socket_obj)
                elif matches_name(s_name) or (s_id and matches_name(s_id)):
                    if is_active:
                        active_name_matches.append(socket_obj)
                    else:
                        inactive_name_matches.append(socket_obj)

            if active_label_matches:
                return active_label_matches[0]
            if active_name_matches:
                return active_name_matches[0]
            if inactive_label_matches:
                return inactive_label_matches[0]
            if inactive_name_matches:
                return inactive_name_matches[0]

        return None

    def create_group(self, group_name, inputs_spec, outputs_spec, tree_type=None, display_name=None):
        """Create a new NodeGroup with specified inputs and outputs

        Args:
            group_name: Name of the group
            inputs_spec: List of dicts with keys: var_name, type, socket_name, tooltip, default, min, max
            outputs_spec: List of dicts with keys: var_name, type, socket_name
            tree_type: Type of node tree (GeometryNodeTree or ShaderNodeTree). If None, inherits from parent tree.
            display_name: Optional display name for the group (shown in UI)

        Returns:
            The created node group (bpy NodeTree)
        """
        import bpy

        # Default to parent tree type if not specified, but try to auto-detect first
        if tree_type is None:
            # Check for shader-only or geometry-only types in specs
            has_shader = False
            has_geometry = False
            for spec in inputs_spec + outputs_spec:
                t = spec.get("type", "").lower()
                if t in ("shader",):
                    has_shader = True
                elif t in (
                    "geometry", "string", "collection", "image", "object",
                    "material", "mat", "rotation", "matrix", "font", "sound"
                ):
                    has_geometry = True
            
            if has_shader and not has_geometry:
                tree_type = "ShaderNodeTree"
            elif has_geometry and not has_shader:
                tree_type = "GeometryNodeTree"
            else:
                tree_type = self.node_tree.bl_idname if hasattr(self.node_tree, 'bl_idname') else "GeometryNodeTree"

        # Create the node group tree using display_name if provided
        # This allows Python code blocks to reference the group by display name
        # e.g., bpy.data.node_groups['Field Value']
        tree_name = display_name if display_name else group_name
        group_tree = bpy.data.node_groups.new(tree_name, tree_type)
        
        # Create Group Input and Output nodes
        group_input = group_tree.nodes.new("NodeGroupInput")
        group_input.name = "Group Input"
        group_input.label = "Group Input"
        
        group_output = group_tree.nodes.new("NodeGroupOutput")
        group_output.name = "Group Output"
        group_output.label = "Group Output"
        
        # Create input sockets
        for inp_spec in inputs_spec:
            self._create_group_socket(
                group_tree,
                inp_spec,
                is_input=True
            )
        
        # Create output sockets
        for out_spec in outputs_spec:
            self._create_group_socket(
                group_tree,
                out_spec,
                is_input=False
            )
        
        return group_tree

    def _create_group_socket(self, group_tree, spec, is_input):
        """Create a socket on a NodeGroup interface
        
        Args:
            group_tree: The NodeGroup tree
            spec: Dict with socket specification
            is_input: True for input, False for output
        """
        socket_type_name = str(spec.get('type', 'float')).lower()
        socket_type = XNODIFY_TO_BLENDER.get(socket_type_name, 'NodeSocketFloat')
        socket_name = spec.get('socket_name', spec.get('var_name', 'Socket'))
        
        # Create the socket
        in_out = 'INPUT' if is_input else 'OUTPUT'
        socket = group_tree.interface.new_socket(
            socket_type=socket_type,
            name=socket_name,
            in_out=in_out
        )
        
        # Set tooltip/description
        if 'tooltip' in spec and spec['tooltip']:
            socket.description = spec['tooltip']
        
        # Set default value (only for inputs)
        if is_input and 'default' in spec and spec['default'] is not None:
            try:
                # Handle special cases for certain socket types
                if socket_type == 'NodeSocketObject' and isinstance(spec['default'], str):
                    # Convert object name string to actual object reference
                    import bpy
                    if spec['default'] in bpy.data.objects:
                        socket.default_value = bpy.data.objects[spec['default']]
                        print(f"Set default value for group input '{socket_name}': {spec['default']} (object)")
                    else:
                        self.warning(f"Object '{spec['default']}' not found for group input '{socket_name}'", node=spec.get('ast_node'))
                elif socket_type == 'NodeSocketMaterial' and isinstance(spec['default'], str):
                    # Convert material name string to actual material reference
                    import bpy
                    if spec['default'] in bpy.data.materials:
                        socket.default_value = bpy.data.materials[spec['default']]
                        print(f"Set default value for group input '{socket_name}': {spec['default']} (material)")
                    else:
                        if self.compiler is not None and hasattr(self.compiler, "pending_materials"):
                            self.compiler.pending_materials.append((socket, spec['default']))
                        self.warning(f"Material '{spec['default']}' not found for group input '{socket_name}'", node=spec.get('ast_node'))
                elif socket_type == 'NodeSocketBool' and isinstance(spec['default'], str):
                    # Convert string boolean to actual bool
                    if spec['default'].lower() in ('true', '1'):
                        socket.default_value = True
                    elif spec['default'].lower() in ('false', '0'):
                        socket.default_value = False
                    else:
                        socket.default_value = spec['default']
                    print(f"Set default value for group input '{socket_name}': {socket.default_value} (bool)")
                elif isinstance(spec['default'], list):
                    for i, val in enumerate(spec['default']):
                        socket.default_value[i] = val
                else:
                    socket.default_value = spec['default']
            except Exception as e:
                # For Menu sockets, failure is expected if items aren't populated yet.
                # The compiler handles this via deferred defaults, so we suppress the warning.
                if socket_type == 'NodeSocketMenu':
                    pass
                else:
                    print(f"Warning: Could not set default value for {socket_name}: {e}")

            # Also set the modifier property value (matches Old XNodify behavior)
            # This is crucial for initializing sockets like Menu types correctly
            try:
                import bpy
                if bpy.context.object and bpy.context.object.modifiers:
                    modifier = bpy.context.object.modifiers.active
                    if modifier and hasattr(modifier, socket.identifier):
                        val_to_set = spec['default']
                        
                        # Handle special cases/conversions
                        if socket_type == 'NodeSocketMenu':
                             # For Menu socket, modifier expects Integer index
                             # We can't easily map String to Index here without Items info
                             # But if default is None, explicitly set 0 (Old XNodify does this)
                             if val_to_set is None:
                                 val_to_set = 0
                             else:
                                 # If default is string 'Float', we can't set it to modifier easily
                                 # unless we know the index.
                                 # But if we skip, it remains unset.
                                 pass
                        
                        if val_to_set is not None and not isinstance(val_to_set, str):
                            # Avoid setting string defaults to modifier properties which expect specific types
                             modifier[socket.identifier] = val_to_set
            except Exception as e:
                # Modifiers might not always be available or active
                pass
        
        # Set min/max (only for numeric types)
        if is_input and socket_type in ('NodeSocketFloat', 'NodeSocketInt'):
            if 'min' in spec and spec['min'] is not None:
                try:
                    socket.min_value = spec['min']
                except:
                    pass
            if 'max' in spec and spec['max'] is not None:
                try:
                    socket.max_value = spec['max']
                except:
                    pass

    def instantiate_group(self, group_tree, name=None, parent=None):
        """Create an instance of a NodeGroup in the current tree

        Args:
            group_tree: The NodeGroup tree to instantiate
            name: Optional name for the instance
            parent: Optional parent frame

        Returns:
            The group instance node
        """
        # Use context-aware group node type
        if self.node_tree.bl_idname == 'ShaderNodeTree':
            node = self.node_tree.nodes.new('ShaderNodeGroup')
        else:
            node = self.node_tree.nodes.new('GeometryNodeGroup')

        node.node_tree = group_tree

        if name:
            node.name = name
            node.label = name

        if parent:
            node.parent = parent

        return node

    def _ensure_bundle_helper_group(self, node_type):
        """Create a helper node group for bundle operations if it doesn't exist."""
        import bpy
        
        # Determine group name based on operation
        # e.g. "Combine Bundle", "Separate Bundle"
        group_name = node_type.replace("GeometryNode", "").replace("Bundle", " Bundle")
        
        # Check if it already exists
        if group_name in bpy.data.node_groups:
            return bpy.data.node_groups[group_name]
            
        # Create new group
        tree = bpy.data.node_groups.new(group_name, "GeometryNodeTree")
        
        try:
            # Create Loop/Interface
            if hasattr(tree, "interface"):
                 # Blender 4.0+
                 # Combine/Join/Separate are all logically Bundle -> Bundle checks or pass-throughs
                 
                 if "Combine" in group_name:
                     # Input: "Inputs" (Bundle), Output: "Bundle" (Bundle)
                     tree.interface.new_socket("Inputs", in_out='INPUT', socket_type='NodeSocketBundle')
                     tree.interface.new_socket("Bundle", in_out='OUTPUT', socket_type='NodeSocketBundle')
                 elif "Separate" in group_name:
                     # Input: "Bundle" (Bundle), Output: "Outputs" (Bundle)
                     tree.interface.new_socket("Bundle", in_out='INPUT', socket_type='NodeSocketBundle')
                     tree.interface.new_socket("Outputs", in_out='OUTPUT', socket_type='NodeSocketBundle')
                 else: # Join
                     # Input: "Bundle" (Bundle), Output: "Bundle" (Bundle)
                     tree.interface.new_socket("Bundle", in_out='INPUT', socket_type='NodeSocketBundle')
                     tree.interface.new_socket("Bundle", in_out='OUTPUT', socket_type='NodeSocketBundle')
                     
            else:
                 # Blender < 4.0 fallback
                 if "Combine" in group_name:
                     tree.inputs.new("NodeSocketBundle", "Inputs")
                     tree.outputs.new("NodeSocketBundle", "Bundle")
                 elif "Separate" in group_name:
                     tree.inputs.new("NodeSocketBundle", "Bundle")
                     tree.outputs.new("NodeSocketBundle", "Outputs")
                 else:
                     tree.inputs.new("NodeSocketBundle", "Bundle")
                     tree.outputs.new("NodeSocketBundle", "Bundle")
    
            # Create internal nodes (Group Input -> Group Output)
            input_node = tree.nodes.new("NodeGroupInput")
            input_node.location = (-200, 0)
            output_node = tree.nodes.new("NodeGroupOutput")
            output_node.location = (200, 0)
            
            # Connect them
            try:
                tree.links.new(input_node.outputs[0], output_node.inputs[0])
            except Exception as e:
                self.warning(f"Failed to internally connect bundle group {group_name}: {e}")
                
        except Exception as e:
            self.error(f"Error creating bundle group {group_name}: {e}")
            
        return tree
