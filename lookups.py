#
# Lookup tables for XNodify.
# Node dimensions are hard-codes for 1980x1080 resolution
# (Since they can't be obtained dynamically)
#
# Copyright (C) 2020  Shrinivas Kulkarni
#
# License: GPL (https://github.com/Shriinivas/xnodify/blob/master/LICENSE)
#

# Constants
SHADER_MATH = 'ShaderNodeMath'
SHADER_VMATH = 'ShaderNodeVectorMath'
SHADER_GROUP = 'ShaderNodeGroup'

nodeGroups = [None] * 9
nodeGroups[0] = ('0', 'Input', 'Category Input Node')
nodeGroups[1] = ('1', 'Output', 'Category Output Node')
nodeGroups[2] = ('2', 'Shader', 'Category Shader Node')
nodeGroups[3] = ('3', 'Texture', 'Category Texture Node')
nodeGroups[4] = ('4', 'Color', 'Category Color Node')
nodeGroups[5] = ('5', 'Vector', 'Category Vector Node')
nodeGroups[6] = ('6', 'converter', 'Category converter Node')
nodeGroups[7] = ('100', 'Math', 'Category Math Node')
nodeGroups[8] = ('200', 'Vector Math', 'Category Vector Math Node')

# Key should be unique in all three maps
fnMap = {}
mathFnMap = {}
vmathFnMap = {}

mathPrefix = 'math_'
vmathPrefix = 'vmath_'

MATH_ADD = 'math_add'
MATH_SUB = 'math_sub'
MATH_MULT = 'math_mult'
MATH_DIV = 'math_div'

mathFnMap[MATH_ADD] = ('100', 'ADD', 'Add', 2, 1, (153.61, 164.39))
mathFnMap[MATH_SUB] = ('100', 'SUBTRACT', 'Subtract', 2, 1,(153.61, 164.39))
mathFnMap[MATH_MULT] = ('100', 'MULTIPLY', 'Multiply', 2, 1,(153.61, 164.39))
mathFnMap[MATH_DIV] = ('100', 'DIVIDE', 'Divide', 2, 1,(153.61, 164.39))
# ~ mathFnMap['math_add2'] = ('100', 'ADD', 'Add2', 3, 1,(153.61, 164.39))
# ~ mathFnMap['math_sub2'] = ('100', 'SUBTRACT', 'Subtract2', 3, 1,(153.61, 164.39))
mathFnMap['math_multadd'] = ('100', 'MULTIPLY_ADD', 'Multiply_add', 3, 1,(153.61, 185.63))
mathFnMap['math_pow'] = ('100', 'POWER', 'Power', 2, 1,(153.61, 164.39))
mathFnMap['math_log'] = ('100', 'LOGARITHM', 'Logarithm', 2, 1,(153.61, 164.39))
mathFnMap['math_sqrt'] = ('100', 'SQRT', 'Sqrt', 1, 1,(153.61, 141.39))
mathFnMap['math_invsqrt'] = ('100', 'INVERSE_SQRT', 'Inverse_sqrt', 1, 1,(153.61, 141.39))
mathFnMap['math_abs'] = ('100', 'ABSOLUTE', 'Absolute', 1, 1,(153.61, 141.39))
mathFnMap['math_exp'] = ('100', 'EXPONENT', 'Exponent', 1, 1,(153.61, 141.39))
mathFnMap['math_min'] = ('100', 'MINIMUM', 'Minimum', 2, 1,(153.61, 164.39))
mathFnMap['math_max'] = ('100', 'MAXIMUM', 'Maximum', 2, 1,(153.61, 164.39))
mathFnMap['math_lt'] = ('100', 'LESS_THAN', 'Less_than', 2, 1,(153.61, 164.39))
mathFnMap['math_gt'] = ('100', 'GREATER_THAN', 'Greater_than', 2, 1,(153.61, 164.39))
mathFnMap['math_sign'] = ('100', 'SIGN', 'Sign', 1, 1,(153.61, 141.39))
mathFnMap['math_cmp'] = ('100', 'COMPARE', 'Compare', 3, 1,(153.61, 185.63))
mathFnMap['math_smthmin'] = ('100', 'SMOOTH_MIN', 'Smooth_min', 3, 1,(153.61, 185.63))
mathFnMap['math_smthmax'] = ('100', 'SMOOTH_MAX', 'Smooth_max', 3, 1,(153.61, 185.63))
mathFnMap['math_round'] = ('100', 'ROUND', 'Round', 1, 1,(153.61, 141.39))
mathFnMap['math_floor'] = ('100', 'FLOOR', 'Floor', 1, 1,(153.61, 141.39))
mathFnMap['math_ceil'] = ('100', 'CEIL', 'Ceil', 1, 1,(153.61, 141.39))
mathFnMap['math_trunc'] = ('100', 'TRUNC', 'Trunc', 1, 1,(153.61, 141.39))
mathFnMap['math_fract'] = ('100', 'FRACT', 'Fract', 1, 1,(153.61, 141.39))
mathFnMap['math_mod'] = ('100', 'MODULO', 'Modulo', 2, 1,(153.61, 164.39))
mathFnMap['math_wrap'] = ('100', 'WRAP', 'Wrap', 3, 1,(153.61, 185.63))
mathFnMap['math_snap'] = ('100', 'SNAP', 'Snap', 2, 1,(153.61, 164.39))
mathFnMap['math_pingpong'] = ('100', 'PINGPONG', 'Pingpong', 2, 1,(153.61, 164.39))
mathFnMap['math_sin'] = ('100', 'SINE', 'Sine', 1, 1,(153.61, 141.39))
mathFnMap['math_cos'] = ('100', 'COSINE', 'Cosine', 1, 1,(153.61, 141.39))
mathFnMap['math_tan'] = ('100', 'TANGENT', 'Tangent', 1, 1,(153.61, 141.39))
mathFnMap['math_asin'] = ('100', 'ARCSINE', 'Arcsine', 1, 1,(153.61, 141.39))
mathFnMap['math_acos'] = ('100', 'ARCCOSINE', 'Arccosine', 1, 1,(153.61, 141.39))
mathFnMap['math_atan'] = ('100', 'ARCTANGENT', 'Arctangent', 1, 1,(153.61, 141.39))
mathFnMap['math_atan2'] = ('100', 'ARCTAN2', 'Arctan2', 2, 1,(153.61, 164.39))
mathFnMap['math_sinh'] = ('100', 'SINH', 'Sinh', 1, 1,(153.61, 141.39))
mathFnMap['math_cosh'] = ('100', 'COSH', 'Cosh', 1, 1,(153.61, 141.39))
mathFnMap['math_tanh'] = ('100', 'TANH', 'Tanh', 1, 1,(153.61, 141.39))
mathFnMap['math_rad'] = ('100', 'RADIANS', 'Radians', 1, 1,(153.61, 141.39))
mathFnMap['math_deg'] = ('100', 'DEGREES', 'Degrees', 1, 1,(153.61, 141.39))


vmathFnMap['vmath_vadd'] = ('200', 'ADD', 'Add', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_vsub'] = ('200', 'SUBTRACT', 'Subtract', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_vmult'] = ('200', 'MULTIPLY', 'Multiply', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_vdiv'] = ('200', 'DIVIDE', 'Divide', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_cross'] = ('200', 'CROSS_PRODUCT', 'Cross_product', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_project'] = ('200', 'PROJECT', 'Project', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_reflect'] = ('200', 'REFLECT', 'Reflect', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_dot'] = ('200', 'DOT_PRODUCT', 'Dot_product', 2, 1, (153.61, 268.84))
vmathFnMap['vmath_vdist'] = ('200', 'DISTANCE', 'Distance', 2, 1, (153.61, 268.84))
vmathFnMap['vmath_vlen'] = ('200', 'LENGTH', 'Length', 1, 1, (153.61, 179.84))
vmathFnMap['vmath_vscale'] = ('200', 'SCALE', 'Scale', 2, 1, (153.61, 202.08))
vmathFnMap['vmath_vnorm'] = ('200', 'NORMALIZE', 'Normalize', 1, 1, (153.61, 180.84))
vmathFnMap['vmath_vabs'] = ('200', 'ABSOLUTE', 'Absolute', 1, 1, (153.61, 180.84))
vmathFnMap['vmath_vmin'] = ('200', 'MINIMUM', 'Minimum', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_vmax'] = ('200', 'MAXIMUM', 'Maximum', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_vfloor'] = ('200', 'FLOOR', 'Floor', 1, 1, (153.61, 180.84))
vmathFnMap['vmath_vceil'] = ('200', 'CEIL', 'Ceil', 1, 1, (153.61, 180.84))
vmathFnMap['vmath_vfract'] = ('200', 'FRACTION', 'Fraction', 1, 1, (153.61, 180.84))
vmathFnMap['vmath_vmod'] = ('200', 'MODULO', 'Modulo', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_wrap'] = ('200', 'WRAP', 'Wrap', 3, 1, (153.61, 358.84))
vmathFnMap['vmath_snap'] = ('200', 'SNAP', 'Snap', 2, 1, (153.61, 269.84))
vmathFnMap['vmath_vsin'] = ('200', 'SINE', 'Sine', 1, 1, (153.61, 180.84))
vmathFnMap['vmath_vcos'] = ('200', 'COSINE', 'Cosine', 1, 1, (153.61, 180.84))
vmathFnMap['vmath_vtan'] = ('200', 'TANGENT', 'Tangent', 1, 1, (153.61, 180.84))

# Input
# -----
fnMap['amboccl'] = ('0', 'ShaderNodeAmbientOcclusion', 'Ambient Occlusion', 3, 2, (153.61, 235.77))
fnMap['bevel'] = ('0', 'ShaderNodeBevel', 'Bevel', 2, 1, (153.61, 135.77))
fnMap['fresnel'] = ('0', 'ShaderNodeFresnel', 'Fresnel', 2, 1, (153.61, 103.77))
fnMap['layerwt'] = ('0', 'ShaderNodeLayerWeight', 'Layer Weight', 2, 2, (153.61, 126.77))
fnMap['prtclinf'] = ('0', 'ShaderNodeParticleInfo', 'Particle Info', 0, 8, (153.61, 214.77))
fnMap['wireframe'] = ('0', 'ShaderNodeWireframe', 'Wireframe', 1, 1, (153.61, 112.77))
fnMap['attrib'] = ('0', 'ShaderNodeAttribute', 'Attribute', 0, 3, (153.61, 131.77))
fnMap['camdata'] = ('0', 'ShaderNodeCameraData', 'Camera Data', 0, 3, (153.61, 99.77))
fnMap['geom'] = ('0', 'ShaderNodeNewGeometry', 'Geometry', 0, 9, (153.61, 237.77))
fnMap['hairinf'] = ('0', 'ShaderNodeHairInfo', 'Hair Info', 0, 5, (153.61, 145.77))
fnMap['lgtpth'] = ('0', 'ShaderNodeLightPath', 'Light Path', 0, 13, (153.61, 329.77))
fnMap['objinf'] = ('0', 'ShaderNodeObjectInfo', 'Object Info', 0, 5, (153.61, 145.77))
fnMap['shadrgb'] = ('0', 'ShaderNodeRGB', 'RGB', 0, 1, (153.61, 197.77))
fnMap['tangent'] = ('0', 'ShaderNodeTangent', 'Tangent', 0, 1, (164.58, 85.77))
fnMap['texco'] = ('0', 'ShaderNodeTexCoord', 'Texture Coordinate', 0, 7, (153.61, 250.77))
fnMap['uvmap'] = ('0', 'ShaderNodeUVMap', 'UV Map', 0, 1, (164.58, 112.77))
fnMap['value'] = ('0', 'ShaderNodeValue', 'Value', 0, 1, (153.61, 85.77))
fnMap['vertcol'] = ('0', 'ShaderNodeVertexColor', 'Vertex Color', 0, 2, (153.61, 108.77))
fnMap['volinf'] = ('0', 'ShaderNodeVolumeInfo', 'Volume Info', 0, 4, (153.61, 122.77))

# Output
# ------
fnMap['output'] = ('1', 'ShaderNodeOutputMaterial', 'Material Output', 3, 0, (153.61, 126.77))

# Shader
# ------
fnMap['addshad'] = ('2', 'ShaderNodeAddShader', 'Add Shader', 2, 1, (153.61, 103.77))
fnMap['diffbsdf'] = ('2', 'ShaderNodeBsdfDiffuse', 'Diffuse BSDF', 3, 1, (164.58, 126.77))
fnMap['emission'] = ('2', 'ShaderNodeEmission', 'Emission', 2, 1, (153.61, 103.77))
fnMap['glasbsdf'] = ('2', 'ShaderNodeBsdfGlass', 'Glass BSDF', 4, 1, (164.58, 181.77))
fnMap['glosbsdf'] = ('2', 'ShaderNodeBsdfGlossy', 'Glossy BSDF', 3, 1, (164.58, 158.77))
fnMap['mixshad'] = ('2', 'ShaderNodeMixShader', 'Mix Shader', 3, 1, (153.61, 126.77))
fnMap['prnbsdf'] = ('2', 'ShaderNodeBsdfPrincipled', 'Principled BSDF', 22, 1, (263.33, 622.77))
# ~ fnMap['prnbsdf'] = ('2', 'ShaderNodeBsdfPrincipled', 'Principled BSDF', 22, 1, (263.33, 800))
fnMap['prnvol'] = ('2', 'ShaderNodeVolumePrincipled', 'Principled Volume', 12, 1, (263.33, 333.77))
fnMap['refrbsdf'] = ('2', 'ShaderNodeBsdfRefraction', 'Refraction BSDF', 4, 1, (164.58, 181.77))
fnMap['specular'] = ('2', 'ShaderNodeEeveeSpecular', 'Specular', 10, 1, (153.61, 287.77))
fnMap['subsrfsct'] = ('2', 'ShaderNodeSubsurfaceScattering', 'Subsurface Scattering', 5, 1, (164.58, 204.77))
fnMap['tcntbsdf'] = ('2', 'ShaderNodeBsdfTranslucent', 'Translucent BSDF', 2, 1, (153.61, 103.77))
fnMap['tpntbsdf'] = ('2', 'ShaderNodeBsdfTransparent', 'Transparent BSDF', 1, 1, (153.61, 80.77))
fnMap['volabs'] = ('2', 'ShaderNodeVolumeAbsorption', 'Volume Absorption', 2, 1, (153.61, 103.77))
fnMap['volscat'] = ('2', 'ShaderNodeVolumeScatter', 'Volume Scatter', 3, 1, (153.61, 126.77))

fnMap['holdout'] = ('2', 'ShaderNodeHoldout', 'Holdout', 0, 1, (153.61, 53.77))

# Texture
# -------
fnMap['brcktex'] = ('3', 'ShaderNodeTexBrick', 'Brick Texture', 10, 2, (164.58, 413.77))
fnMap['chctex'] = ('3', 'ShaderNodeTexChecker', 'Checker Texture', 4, 2, (153.61, 172.77))
fnMap['envtex'] = ('3', 'ShaderNodeTexEnvironment', 'Environment Texture', 1, 1, (263.33, 166.77))
fnMap['gradtex'] = ('3', 'ShaderNodeTexGradient', 'Gradient Texture', 1, 2, (153.61, 135.77))
fnMap['iestex'] = ('3', 'ShaderNodeTexIES', 'IES Texture', 2, 1, (153.61, 162.77))
fnMap['imgtex'] = ('3', 'ShaderNodeTexImage', 'Image Texture', 1, 2, (263.33, 216.77))
fnMap['magictex'] = ('3', 'ShaderNodeTexMagic', 'Magic Texture', 3, 2, (153.61, 181.77))
# ~ fnMap['mustex'] = ('3', 'ShaderNodeTexMusgrave', 'Musgrave Texture', 5, 1, (164.58, 233.53))
fnMap['mustex'] = ('3', 'ShaderNodeTexMusgrave', 'Musgrave Texture', 5, 1, (164.58, 250))
fnMap['noisetex'] = ('3', 'ShaderNodeTexNoise', 'Noise Texture', 5, 2, (153.61, 227.77))
fnMap['ptdnsty'] = ('3', 'ShaderNodeTexPointDensity', 'Point Density', 1, 2, (153.61, 297.77))
fnMap['skytex'] = ('3', 'ShaderNodeTexSky', 'Sky Texture', 0, 1, (164.58, 313.77))
fnMap['vorntex'] = ('3', 'ShaderNodeTexVoronoi', 'Voronoi Texture', 3, 3, (153.61, 259.77))
fnMap['wavetex'] = ('3', 'ShaderNodeTexWave', 'Wave Texture', 7, 2, (164.58, 327.77))
fnMap['whnsetex'] = ('3', 'ShaderNodeTexWhiteNoise', 'White Noise Texture', 1, 2, (153.61, 203.53))

# Color
# -----
fnMap['brtcst'] = ('4', 'ShaderNodeBrightContrast', 'Bright/Contrast', 3, 1, (153.61, 126.77))
fnMap['gamma'] = ('4', 'ShaderNodeGamma', 'Gamma', 2, 1, (153.61, 103.77))
fnMap['hsval'] = ('4', 'ShaderNodeHueSaturation', 'Hue Saturation Value', 5, 1, (164.58, 172.77))
fnMap['invert'] = ('4', 'ShaderNodeInvert', 'Invert', 2, 1, (153.61, 103.77))
fnMap['ltfloff'] = ('4', 'ShaderNodeLightFalloff', 'Light Falloff', 2, 3, (164.58, 149.77))
fnMap['mixrgb'] = ('4', 'ShaderNodeMixRGB', 'Mix', 3, 1, (153.61, 182.77))
fnMap['rgbcrvs'] = ('4', 'ShaderNodeRGBCurve', 'RGB Curves', 2, 1, (263.33, 343.77))

# Vector
# ------
fnMap['bump'] = ('5', 'ShaderNodeBump', 'Bump', 4, 1, (153.61, 181.77))
fnMap['disp'] = ('5', 'ShaderNodeDisplacement', 'Displacement', 4, 1, (153.61, 181.77))
fnMap['mapping'] = ('5', 'ShaderNodeMapping', 'Mapping', 4, 1, (153.61, 445.77))
fnMap['normal'] = ('5', 'ShaderNodeNormal', 'Normal', 1, 2, (153.61, 223.77))
fnMap['normmap'] = ('5', 'ShaderNodeNormalMap', 'Normal Map', 2, 1, (164.58, 162.77))
fnMap['vctcrvs'] = ('5', 'ShaderNodeVectorCurve', 'Vector Curves', 2, 1, (263.33, 382.77))
fnMap['vctdisp'] = ('5', 'ShaderNodeVectorDisplacement', 'Vector Displacement', 3, 1, (153.61, 158.77))
fnMap['vctrot'] = ('5', 'ShaderNodeVectorRotate', 'Vector Rotate', 4, 1, (153.61, 342.53))
fnMap['vcttrns'] = ('5', 'ShaderNodeVectorTransform', 'Vector Transform', 1, 1, (153.61, 232.77))

# converter
# ---------
fnMap['blkbody'] = ('6', 'ShaderNodeBlackbody', 'Blackbody', 1, 1, (164.58, 80.77))
fnMap['clamp'] = ('6', 'ShaderNodeClamp', 'Clamp', 3, 1, (153.61, 158.77))
fnMap['colramp'] = ('6', 'ShaderNodeValToRGB', 'ColorRamp', 1, 2, (263.33, 226.77))
fnMap['comhsv'] = ('6', 'ShaderNodeCombineHSV', 'Combine HSV', 3, 1, (153.61, 126.77))
fnMap['comrgb'] = ('6', 'ShaderNodeCombineRGB', 'Combine RGB', 3, 1, (153.61, 126.77))
fnMap['comxyz'] = ('6', 'ShaderNodeCombineXYZ', 'Combine XYZ', 3, 1, (153.61, 126.77))
fnMap['maprange'] = ('6', 'ShaderNodeMapRange', 'Map Range', 5, 1, (153.61, 233.53))
fnMap['rgb2bw'] = ('6', 'ShaderNodeRGBToBW', 'RGB to BW', 1, 1, (153.61, 80.77))
fnMap['sephsv'] = ('6', 'ShaderNodeSeparateHSV', 'Separate HSV', 1, 3, (153.61, 126.77))
fnMap['seprgb'] = ('6', 'ShaderNodeSeparateRGB', 'Separate RGB', 1, 3, (153.61, 126.77))
fnMap['sepxyz'] = ('6', 'ShaderNodeSeparateXYZ', 'Separate XYZ', 1, 3, (153.61, 192.77))
fnMap['shd2rgb'] = ('6', 'ShaderNodeShaderToRGB', 'Shader to RGB', 1, 2, (153.61, 103.77))
fnMap['wvlngth'] = ('6', 'ShaderNodeWavelength', 'Wavelength', 1, 1, (164.58, 80.77))
#fnMap['math'] = ('6', 'ShaderNodeMath', 'Math', 3, 1, (153.61, 164.53)),
#fnMap['vctmth'] = ('6', 'ShaderNodeVectorMath', 'Vector Math', 4, 2, (153.61, 270.53))

fnMap['nodegrp'] = ('7', SHADER_GROUP, 'Node Group', 0, 1, (153.61, 65.0))
fnMap['nodeip'] = ('7', 'NodeGroupInput', 'Group Input', 0, 1, (153.61, 122.77))
fnMap['nodeop'] = ('7', 'NodeGroupOutput', 'Group Output', 0, 1, (153.61, 122.77))

def getCombinedMap():
    cmap = {}
    cmap.update(fnMap)
    cmap.update(mathFnMap)
    cmap.update(vmathFnMap)
    return cmap

_reverseLookup ={}

# _reverseLookup will be populated incrementally
def reverseLookup(revKey):
    val = _reverseLookup.get(revKey)
    if(val != None):
        return val

    # TODO: Uniform reverse lookup as much as possible
    if(revKey.startswith(SHADER_MATH) or revKey.startswith(SHADER_VMATH)):
        shaderName, operation = revKey.split('_')
        mp = mathFnMap if revKey.startswith(SHADER_MATH) \
            else vmathFnMap
        for customName in mp.keys():
            revKey = shaderName + '_' + mp[customName][1]
            _reverseLookup[revKey] = customName
    else:
        mp = fnMap
        for customName in mp.keys():
            revKey = mp[customName][1]
            _reverseLookup[revKey] = customName
    return _reverseLookup.get(revKey)
