"""
Shared socket type mappings - single source of truth for all socket type conversions
"""

# Map XNodify script types to Blender socket types
XNODIFY_TO_BLENDER = {
    'int': 'NodeSocketInt',
    'float': 'NodeSocketFloat',
    'bool': 'NodeSocketBool',
    'vector': 'NodeSocketVector',
    'color': 'NodeSocketColor',
    'geometry': 'NodeSocketGeometry',
    'string': 'NodeSocketString',
    'mat': 'NodeSocketMaterial',
    'material': 'NodeSocketMaterial',
    'object': 'NodeSocketObject',
    'collection': 'NodeSocketCollection',
    'image': 'NodeSocketImage',
    'texture': 'NodeSocketTexture',
    'shader': 'NodeSocketShader',
    'menu': 'NodeSocketMenu',
    'rotation': 'NodeSocketRotation',
    'matrix': 'NodeSocketMatrix',
    'rgba': 'NodeSocketColor',
    'bundle': 'NodeSocketBundle',
    'font': 'NodeSocketFont',
    'sound': 'NodeSocketSound',
    'closure': 'NodeSocketClosure',
    'int_vector': 'NodeSocketIntVector3D',
    'custom': 'NodeSocketVirtual',
}

# Map Blender socket types to registry types
# This is used for validation and type checking
BLENDER_TO_REGISTRY = {
    'NodeSocketFloat': 'VALUE',
    'NodeSocketFloatFactor': 'VALUE',
    'NodeSocketFloatDistance': 'VALUE',
    'NodeSocketFloatAngle': 'VALUE',
    'NodeSocketFloatTime': 'VALUE',
    'NodeSocketFloatTimeAbsolute': 'VALUE',
    'NodeSocketFloatUnsigned': 'VALUE',
    'NodeSocketInt': 'INT',
    'NodeSocketIntFactor': 'INT',
    'NodeSocketIntPercentage': 'INT',
    'NodeSocketIntUnsigned': 'INT',
    'NodeSocketBool': 'BOOLEAN',
    'NodeSocketVector': 'VECTOR',
    'NodeSocketVectorTranslation': 'VECTOR',
    'NodeSocketVectorDirection': 'VECTOR',
    'NodeSocketVectorEuler': 'VECTOR',
    'NodeSocketVectorXYZ': 'VECTOR',
    'NodeSocketVectorVelocity': 'VECTOR',
    'NodeSocketVectorAcceleration': 'VECTOR',
    'NodeSocketString': 'STRING',
    'NodeSocketGeometry': 'GEOMETRY',
    'NodeSocketRotation': 'ROTATION',
    'NodeSocketMatrix': 'MATRIX',
    'NodeSocketMenu': 'MENU',
    'NodeSocketColor': 'RGBA',
    'NodeSocketMaterial': 'MATERIAL',
    'NodeSocketObject': 'OBJECT',
    'NodeSocketImage': 'IMAGE',
    'NodeSocketTexture': 'TEXTURE',
    'NodeSocketShader': 'SHADER',
    'NodeSocketBundle': 'BUNDLE',
    'NodeSocketFont': 'FONT',
    'NodeSocketSound': 'SOUND',
    'NodeSocketClosure': 'CLOSURE',
    'NodeSocketIntVector3D': 'INT_VECTOR',
    'NodeSocketVirtual': 'CUSTOM',
}

# Map registry types to Blender socket types (reverse of above, simplified)
REGISTRY_TO_BLENDER = {
    'VALUE': 'NodeSocketFloat',
    'INT': 'NodeSocketInt',
    'BOOLEAN': 'NodeSocketBool',
    'VECTOR': 'NodeSocketVector',
    'STRING': 'NodeSocketString',
    'GEOMETRY': 'NodeSocketGeometry',
    'ROTATION': 'NodeSocketRotation',
    'MATRIX': 'NodeSocketMatrix',
    'MENU': 'NodeSocketMenu',
    'RGBA': 'NodeSocketColor',
    'MATERIAL': 'NodeSocketMaterial',
    'OBJECT': 'NodeSocketObject',
    'IMAGE': 'NodeSocketImage',
    'TEXTURE': 'NodeSocketTexture',
    'SHADER': 'NodeSocketShader',
    'BUNDLE': 'NodeSocketBundle',
    'FONT': 'NodeSocketFont',
    'SOUND': 'NodeSocketSound',
    'CLOSURE': 'NodeSocketClosure',
    'INT_VECTOR': 'NodeSocketIntVector3D',
    'CUSTOM': 'NodeSocketVirtual',
}

# Incompatible type conversions that should be flagged as errors
# Format: (from_type, to_type)
INCOMPATIBLE_CONVERSIONS = [
    ('GEOMETRY', 'VALUE'),
    ('GEOMETRY', 'INT'),
    ('GEOMETRY', 'VECTOR'),
    ('VECTOR', 'MENU'),
    ('VALUE', 'MENU'),
    ('INT', 'MENU'),
    ('BOOLEAN', 'MENU'),
    ('STRING', 'MENU'),
    ('GEOMETRY', 'MENU'),
    ('ROTATION', 'MENU'),
    ('MATRIX', 'MENU'),
    ('RGBA', 'MENU'),
    ('MATERIAL', 'MENU'),
    ('OBJECT', 'MENU'),
    ('SHADER', 'MENU'),
]

def get_registry_type(blender_socket_type):
    """
    Convert a Blender socket type (bl_idname) to a registry type

    Args:
        blender_socket_type: Blender socket type like 'NodeSocketFloat'

    Returns:
        Registry type like 'VALUE', or None if unknown
    """
    return BLENDER_TO_REGISTRY.get(blender_socket_type)

def get_blender_type(registry_type):
    """
    Convert a registry type to a Blender socket type

    Args:
        registry_type: Registry type like 'VALUE'

    Returns:
        Blender socket type like 'NodeSocketFloat', or None if unknown
    """
    return REGISTRY_TO_BLENDER.get(registry_type)

def is_compatible_conversion(from_type, to_type):
    """
    Check if a socket type conversion is compatible

    Args:
        from_type: Source registry type (e.g., 'VECTOR')
        to_type: Destination registry type (e.g., 'MENU')

    Returns:
        True if conversion is allowed, False otherwise
    """
    return (from_type, to_type) not in INCOMPATIBLE_CONVERSIONS


# Map Blender socket types to Bundle Item Types (for CombineBundle/SeparateBundle)
BLENDER_TO_BUNDLE_TYPE = {
    'NodeSocketFloat': 'FLOAT',
    'NodeSocketVector': 'VECTOR',
    'NodeSocketInt': 'INT',
    'NodeSocketBool': 'BOOLEAN',
    'NodeSocketColor': 'RGBA',
    'NodeSocketString': 'STRING',
    'NodeSocketObject': 'OBJECT',
    'NodeSocketCollection': 'COLLECTION',
    'NodeSocketImage': 'IMAGE',
    'NodeSocketGeometry': 'GEOMETRY',
    'NodeSocketMaterial': 'MATERIAL',
    'NodeSocketTexture': 'TEXTURE',
    'NodeSocketMenu': 'MENU',
    'NodeSocketRotation': 'ROTATION',
    'NodeSocketMatrix': 'MATRIX',
    'NodeSocketFont': 'FONT',
    'NodeSocketSound': 'SOUND',
    'NodeSocketClosure': 'CLOSURE',
    'NodeSocketIntVector3D': 'INT_VECTOR',
    'NodeSocketBundle': 'BUNDLE',
    'NodeSocketVirtual': 'CUSTOM',
}


def get_bundle_type(blender_socket_type):
    """
    Convert a Blender socket type (bl_idname) to a Bundle Item Type enum value.
    
    Args:
        blender_socket_type: Blender socket type like 'NodeSocketFloat'
        
    Returns:
        Bundle item type like 'FLOAT', or None if unknown
    """
    return BLENDER_TO_BUNDLE_TYPE.get(blender_socket_type)


DYNAMIC_SOCKET_TYPE_MAP = {
    'NodeSocketFloat': ('FLOAT', 'Value'),
    'NodeSocketVector': ('VECTOR', 'Vector'),
    'NodeSocketInt': ('INT', 'Integer'),
    'NodeSocketBool': ('BOOLEAN', 'Boolean'),
    'NodeSocketColor': ('RGBA', 'Color'),
    'NodeSocketString': ('STRING', 'String'),
    'NodeSocketObject': ('OBJECT', 'Object'),
    'NodeSocketCollection': ('COLLECTION', 'Collection'),
    'NodeSocketImage': ('IMAGE', 'Image'),
    'NodeSocketGeometry': ('GEOMETRY', 'Geometry'),
    'NodeSocketMaterial': ('MATERIAL', 'Material'),
    'NodeSocketTexture': ('TEXTURE', 'Texture'),
    'NodeSocketMenu': ('MENU', 'Menu'),
    'NodeSocketRotation': ('ROTATION', 'Rotation'),
    'NodeSocketMatrix': ('MATRIX', 'Matrix'),
    'NodeSocketFont': ('FONT', 'Font'),
    'NodeSocketSound': ('SOUND', 'Sound'),
    'NodeSocketClosure': ('CLOSURE', 'Closure'),
    'NodeSocketIntVector3D': ('INT_VECTOR', 'Int Vector'),
    'NodeSocketBundle': ('BUNDLE', 'Bundle'),
}


def get_dynamic_item_type_and_label(blender_socket_type, for_capture=False):
    """
    Convert a Blender socket type (bl_idname) to (type_enum, default_label).
    Handles Capture Attribute specifics (FLOAT_VECTOR, FLOAT_COLOR) automatically.
    """
    type_name, label = DYNAMIC_SOCKET_TYPE_MAP.get(blender_socket_type, ('FLOAT', 'Value'))
    if for_capture:
        if type_name == 'VECTOR':
            type_name = 'FLOAT_VECTOR'
        elif type_name == 'RGBA':
            type_name = 'FLOAT_COLOR'
    return type_name, label
