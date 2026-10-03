"""
Common node attributes and their valid enum values.

This module defines the most frequently used node attributes in XFY scripts.
Used by:
- LSP server for autocomplete suggestions
- Semantic analyzer for attribute validation

These are the user-facing attributes (not internal properties like bl_*, location_*, etc.)
"""

# Common attribute names mapped to their valid enum values
# None means any value is allowed (not an enum)
COMMON_ATTRIBUTES = {
    # Domain selection (used by many nodes)
    "domain": ["POINT", "EDGE", "FACE", "CORNER", "CURVE", "INSTANCE", "LAYER"],

    # Data type selection
    "data_type": [
        "FLOAT", "INT", "FLOAT_VECTOR", "FLOAT_COLOR", "BYTE_COLOR",
        "BOOLEAN", "FLOAT2", "INT8", "RGBA", "STRING", "QUATERNION", "MATRIX"
    ],

    # Input type for switch/index nodes
    "input_type": [
        "FLOAT", "INT", "BOOLEAN", "VECTOR", "ROTATION",
        "STRING", "RGBA", "OBJECT", "IMAGE", "GEOMETRY",
        "COLLECTION", "MATERIAL", "MENU"
    ],

    # Math operations
    "operation": [
        # Math node
        "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "MULTIPLY_ADD", "POWER",
        "LOGARITHM", "SQRT", "INVERSE_SQRT", "ABSOLUTE", "EXPONENT",
        "MINIMUM", "MAXIMUM", "LESS_THAN", "GREATER_THAN", "SIGN",
        "COMPARE", "SMOOTH_MIN", "SMOOTH_MAX", "ROUND", "FLOOR", "CEIL",
        "TRUNC", "FRACT", "MODULO", "FLOORED_MODULO", "WRAP", "SNAP",
        "PINGPONG", "SINE", "COSINE", "TANGENT", "ARCSINE", "ARCCOSINE",
        "ARCTANGENT", "ARCTAN2", "SINH", "COSH", "TANH", "RADIANS", "DEGREES",
        # Vector math
        "SCALE", "NORMALIZE", "DOT_PRODUCT", "CROSS_PRODUCT", "PROJECT",
        "REFLECT", "REFRACT", "FACEFORWARD", "LENGTH", "DISTANCE",
        "SINE", "COSINE", "TANGENT",
        # Boolean math
        "AND", "OR", "NOT", "NAND", "NOR", "XNOR", "XOR", "IMPLY", "NIMPLY",
        # Compare
        "EQUAL", "NOT_EQUAL", "LESS_THAN", "LESS_EQUAL",
        "GREATER_THAN", "GREATER_EQUAL",
        # Mix
        "MIX", "DARKEN", "LIGHTEN", "SCREEN", "DODGE", "BURN",
        "HUE", "SATURATION", "VALUE", "COLOR", "SOFT_LIGHT", "LINEAR_LIGHT",
    ],

    # Vector type
    "vector_type": ["POINT", "VECTOR", "NORMAL"],

    # Clamp toggle
    "use_clamp": None,  # Boolean, not an enum

    # Mode selections
    "mode": [
        # Attribute transfer modes
        "NEAREST_FACE_INTERPOLATED", "NEAREST", "INDEX",
        # Curve handle modes
        "FREE", "AUTO", "VECTOR", "ALIGN",
        # Various other modes
        "ALL", "EDGE", "FACE", "VERTICES", "EDGES", "FACES",
    ],

    # Interpolation types
    "interpolation_type": ["LINEAR", "SMOOTH", "SMOOTHER"],

    # Mapping type
    "mapping": ["LINEAR", "STEPPED", "SMOOTHSTEP", "SMOOTHERSTEP"],

    # Handle type for curves
    "handle_type": ["FREE", "AUTO", "VECTOR", "ALIGN"],

    # Selection type
    "selection_type": ["ALL", "RANDOM", "EDGE_ANGLE", "EDGE_LENGTH"],

    # Sort mode
    "sort_element": ["POINT", "EDGE", "FACE", "CURVE", "INSTANCE"],

    # Distribute points mode
    "distribute_method": ["RANDOM", "POISSON"],

    # Raycast mapping
    "mapping": ["INTERPOLATED", "NEAREST"],

    # Align euler mode
    "pivot_axis": ["X", "Y", "Z", "AUTO"],

    # Mesh boolean
    "solver": ["EXACT", "FAST"],

    # Subdivision
    "uv_smooth": ["NONE", "PRESERVE_CORNERS", "PRESERVE_CORNERS_AND_JUNCTIONS",
                  "PRESERVE_CORNERS_JUNCTIONS_AND_CONCAVE", "PRESERVE_BOUNDARIES",
                  "SMOOTH_ALL"],
    "boundary_smooth": ["PRESERVE_CORNERS", "ALL"],
    
    # Node label (sets the bl_label on the node)
    "label": None,  # String, not an enum
}

# Preprocessor attributes - handled during preprocessing, not actual node properties
# These are valid in XFY but get transformed before reaching the compiler
PREPROCESSOR_ATTRIBUTES = {
    "file_path",     # tex_image: loads image by path
    "add",           # val_to_rgb (color ramp): add color stop
    "remove",        # val_to_rgb (color ramp): remove color stop
}

# Internal properties that should be filtered out from autocomplete
INTERNAL_PROPERTIES = {
    "location_absolute",
    "warning_propagation",
    "show_options",
    "show_preview",
    "hide",
    "mute",
    "show_texture",
    "bl_idname",
    "bl_label",
    "bl_description",
    "bl_icon",
    "bl_width_default",
    "bl_width_min",
    "bl_width_max",
    "bl_height_default",
    "bl_height_min",
    "bl_height_max",
    "active_index",
    "active_item",
    "parent",
    # "label" is now in COMMON_ATTRIBUTES - allows setting node label
    "name",
    "location",
    "width",
    "height",
    "dimensions",
    "color",
    "use_custom_color",
    "select",
    "inputs",
    "outputs",
}


def get_user_facing_properties(node_properties: dict) -> list[str]:
    """
    Filter node properties to only include user-facing ones.

    Args:
        node_properties: Dict of property_name -> property_info from registry

    Returns:
        List of user-facing property names
    """
    return [
        name for name in node_properties.keys()
        if name not in INTERNAL_PROPERTIES
    ]


def is_valid_attribute(attr_name: str, node_name: str = None, registry=None) -> bool:
    """
    Check if an attribute name is valid.

    If node_name and registry are provided, checks against the node's actual properties.
    Otherwise, checks against common attributes.

    Args:
        attr_name: The attribute name to validate
        node_name: Optional node name to check against
        registry: Optional NodeRegistry instance

    Returns:
        True if attribute is valid
    """
    # If we have node info, check against its properties
    if node_name and registry:
        node_info = registry.nodes.get(node_name)
        if node_info and "properties" in node_info:
            props = node_info["properties"]
            user_props = get_user_facing_properties(props)
            return attr_name in user_props

    # Fall back to common attributes
    return attr_name in COMMON_ATTRIBUTES


def get_valid_values(attr_name: str) -> list[str] | None:
    """
    Get valid enum values for an attribute.

    Args:
        attr_name: The attribute name

    Returns:
        List of valid values, or None if not an enum
    """
    return COMMON_ATTRIBUTES.get(attr_name)
