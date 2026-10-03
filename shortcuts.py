# Function Shortcuts and Aliases
# Maps convenient short names to full node types with default attributes

FUNCTION_SHORTCUTS = {
    # Math operations - single argument
    'sin': ('math', {'operation': 'SINE'}),
    'cos': ('math', {'operation': 'COSINE'}),
    'tan': ('math', {'operation': 'TANGENT'}),
    'asin': ('math', {'operation': 'ARCSINE'}),
    'acos': ('math', {'operation': 'ARCCOSINE'}),
    'atan': ('math', {'operation': 'ARCTANGENT'}),
    'sinh': ('math', {'operation': 'SINH'}),
    'cosh': ('math', {'operation': 'COSH'}),
    'tanh': ('math', {'operation': 'TANH'}),
    
    'sqrt': ('math', {'operation': 'SQRT'}),
    'abs': ('math', {'operation': 'ABSOLUTE'}),
    'floor': ('math', {'operation': 'FLOOR'}),
    'ceil': ('math', {'operation': 'CEIL'}),
    'round': ('math', {'operation': 'ROUND'}),
    'trunc': ('math', {'operation': 'TRUNC'}),
    'fract': ('math', {'operation': 'FRACT'}),
    'sign': ('math', {'operation': 'SIGN'}),
    'radians': ('math', {'operation': 'RADIANS'}),
    'degrees': ('math', {'operation': 'DEGREES'}),
    'exp': ('math', {'operation': 'EXPONENT'}),
    'ln': ('math', {'operation': 'LOGARITHM'}),
    
    # Math operations - two arguments
    'pow': ('math', {'operation': 'POWER'}),
    'log': ('math', {'operation': 'LOGARITHM'}),
    'min': ('math', {'operation': 'MINIMUM'}),
    'max': ('math', {'operation': 'MAXIMUM'}),
    'mod': ('math', {'operation': 'MODULO'}),
    'atan2': ('math', {'operation': 'ARCTAN2'}),
    'snap': ('math', {'operation': 'SNAP'}),
    'wrap': ('math', {'operation': 'WRAP'}),
    'pingpong': ('math', {'operation': 'PINGPONG'}),
    
    # Math operations - three arguments
    'smoothmin': ('math', {'operation': 'SMOOTH_MIN'}),
    'smoothmax': ('math', {'operation': 'SMOOTH_MAX'}),
    # NOTE: 'compare' is NOT a shortcut - it's a real node (FunctionNodeCompare)
    # Don't add it here or it will incorrectly create Math nodes instead
    'multiply_add': ('math', {'operation': 'MULTIPLY_ADD'}),
    
    # Vector math - single argument
    'vnormalize': ('vector_math', {'operation': 'NORMALIZE'}),
    'vlength': ('vector_math', {'operation': 'LENGTH'}),
    'vabs': ('vector_math', {'operation': 'ABSOLUTE'}),
    'vfloor': ('vector_math', {'operation': 'FLOOR'}),
    'vceil': ('vector_math', {'operation': 'CEIL'}),
    'vfract': ('vector_math', {'operation': 'FRACTION'}),
    'vsin': ('vector_math', {'operation': 'SINE'}),
    'vcos': ('vector_math', {'operation': 'COSINE'}),
    'vtan': ('vector_math', {'operation': 'TANGENT'}),
    
    # Vector math - two arguments
    'vadd': ('vector_math', {'operation': 'ADD'}),
    'vsub': ('vector_math', {'operation': 'SUBTRACT'}),
    'vmul': ('vector_math', {'operation': 'MULTIPLY'}),
    'vdiv': ('vector_math', {'operation': 'DIVIDE'}),
    'vcross': ('vector_math', {'operation': 'CROSS_PRODUCT'}),
    'vdot': ('vector_math', {'operation': 'DOT_PRODUCT'}),
    'vdist': ('vector_math', {'operation': 'DISTANCE'}),
    'vreflect': ('vector_math', {'operation': 'REFLECT'}),
    'vproject': ('vector_math', {'operation': 'PROJECT'}),
    'vmin': ('vector_math', {'operation': 'MINIMUM'}),
    'vmax': ('vector_math', {'operation': 'MAXIMUM'}),
    'vmod': ('vector_math', {'operation': 'MODULO'}),
    'vsnap': ('vector_math', {'operation': 'SNAP'}),
    'vscale': ('vector_math', {'operation': 'SCALE'}),
    
    # Vector math - three arguments
    'vrefract': ('vector_math', {'operation': 'REFRACT'}),
    'vfaceforward': ('vector_math', {'operation': 'FACEFORWARD'}),
    'vwrap': ('vector_math', {'operation': 'WRAP'}),
    
    # Boolean operations
    'bool_and': ('boolean_math', {'operation': 'AND'}),
    'bool_or': ('boolean_math', {'operation': 'OR'}),
    'bool_not': ('boolean_math', {'operation': 'NOT'}),
    'bool_xor': ('boolean_math', {'operation': 'XOR'}),
    'bool_nand': ('boolean_math', {'operation': 'NAND'}),
    'bool_nor': ('boolean_math', {'operation': 'NOR'}),
    'bool_xnor': ('boolean_math', {'operation': 'XNOR'}),
    'bool_imply': ('boolean_math', {'operation': 'IMPLY'}),
    'bool_nimply': ('boolean_math', {'operation': 'NIMPLY'}),
    'and': ('boolean_math', {'operation': 'AND'}),
    'or': ('boolean_math', {'operation': 'OR'}),
    'not': ('boolean_math', {'operation': 'NOT'}),
    
    # Comparison shortcuts
    'eq': ('compare', {'operation': 'EQUAL', 'data_type': 'FLOAT'}),
    'ne': ('compare', {'operation': 'NOT_EQUAL', 'data_type': 'FLOAT'}),
    'lt': ('compare', {'operation': 'LESS_THAN', 'data_type': 'FLOAT'}),
    'le': ('compare', {'operation': 'LESS_EQUAL', 'data_type': 'FLOAT'}),
    'gt': ('compare', {'operation': 'GREATER_THAN', 'data_type': 'FLOAT'}),
    'ge': ('compare', {'operation': 'GREATER_EQUAL', 'data_type': 'FLOAT'}),
    
    # Color operations
    'color': 'rgb',
    'hsv': ('combine_color', {'mode': 'HSV'}),
    'hsl': ('combine_color', {'mode': 'HSL'}),

    # Mix/lerp operations (these set specific data types, not pure aliases)
    'lerp': ('mix', {'data_type': 'FLOAT'}),
    'vlerp': ('mix', {'data_type': 'VECTOR'}),
    
    # Material node shortcuts
    '_prnbsdf': 'bsdf_principled',        # Principled BSDF (internal shortcut)
    '_matoutput': 'output_material',       # Material Output (internal shortcut)
    'bsdf_background': 'background',       # Background shader alias
    'color_ramp': 'val_to_rgb',            # Color Ramp alias
    'principled_bsdf': 'bsdf_principled',  # Principled BSDF alias
    
    # Bundle operations
    'combine_bundle': 'NodeCombineBundle',
    'join_bundle': 'NodeJoinBundle',
    'separate_bundle': 'NodeSeparateBundle',
    
    # Missing geometry nodes
    'cube': 'mesh_cube',
    'image': 'input_image',
    'transform_geometry': 'transform',
    'grid': 'mesh_grid',
    'curve_line': 'curve_primitive_line',
    'curve_circle': 'curve_primitive_circle',
    
    # Physics & Dynamics (Blender 5.2+)
    'cloth_dynamics': 'Cloth Dynamics (Experimental)',
    'hair_dynamics': 'Hair Dynamics',
    'gravity': 'Gravity',
    'collider': 'Collider',
    'edge_length_constraint': 'Edge Length Constraint',
    'xpbd_simulation': 'XPBD Simulation',
    'xpbd_solver': 'XPBD Solver',
    
    # Old xnodify2 aliases for backward compatibility
    'objinfo': 'object_info',
    'selfobj': 'self_object',
    'scenetime': 'input_scene_time',
    'camdata': 'camera_data',
    'attrstat': 'attribute_statistic',
    'storenamedattr': 'store_named_attribute',
    'domainsize': 'attribute_domain_size',
    'namedattr': 'input_named_attribute',
    'captureattr': 'capture_attribute',
    'curvelen': 'curve_length',
    'curve2pts': 'curve_to_points',
    'samplecurve': 'sample_curve',
    'offsetptincurve': 'offset_point_in_curve',
    'curveofpt': 'curve_of_point',
    'ptofcurve': 'points_of_curve',
    'splinelen': 'spline_length',
    'splineparam': 'spline_parameter',
    'splineres': 'input_spline_resolution',
    'subdivsurf': 'subdivision_surface',
    'delgeom': 'delete_geometry',
    'menuswitch': 'menu_switch',
    'idxswitch': 'index_switch',
    'meshcircle': 'mesh_circle',
    'mesh2pts': 'mesh_to_points',
    'randval': 'random_value',
    'alignrot2vect': 'align_rotation_to_vector',
    'comxform': 'combine_transform',
    'xformpt': 'transform_point',
    'invmat': 'invert_matrix',
    'cross': 'vcross',
    'rotrot': 'rotate_rotation',
    'vectrotate': 'vector_rotate',
    'setinstxform': 'set_instance_transform',
    'ceq': ('compare', {'operation': 'EQUAL'}),
}

def expand_function_shortcut(func_name, attrs=None):
    """
    Expand a function shortcut to its full form.
    
    Args:
        func_name: The function name (might be a shortcut)
        attrs: Optional dict of attributes already specified
        
    Returns:
        (expanded_name, merged_attrs) tuple
    """
    if func_name not in FUNCTION_SHORTCUTS:
        return (func_name, attrs or {})
    
    shortcut = FUNCTION_SHORTCUTS[func_name]
    
    # Handle simple string shortcuts (just aliases)
    if isinstance(shortcut, str):
        return (shortcut, attrs or {})
    
    # Handle (node_type, default_attrs) tuples
    node_type, default_attrs = shortcut
    
    # Merge attributes: user-specified attrs override defaults
    merged_attrs = default_attrs.copy()
    if attrs:
        merged_attrs.update(attrs)
    
    return (node_type, merged_attrs)
