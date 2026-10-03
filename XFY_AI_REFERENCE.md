# XFY Language Reference Manual
> Single source of truth for the XFY language in Blender Geometry Node and Shader Node Trees.
> Node names, sockets, properties, and shortcuts are verified against the compiler registry and `shortcuts.py`.

---

## 1. Execution & Mental Model

XFY compiles declarative text into a Blender **dataflow graph** (`NodeTree`), not sequential CPU instructions.

1. **Graph Construction**: Every function call creates a node. Variables are wires connecting output sockets to input sockets. There is no imperative execution order—only data dependencies.
2. **Multiplexing**: Conditional nodes (`switch`, `menu_switch`, `index_switch`) are graph multiplexers. All input branches exist in the graph; the selector routes the active wire to the output.
3. **Multi-Input Lists (`~`)**: The `~` operator creates variadic multi-socket connections inside node arguments (for example, `join_geometry(a ~ b ~ c)`). It is valid only inside function call arguments.
4. **Field Evaluation**: Field nodes (such as `position()`, `normal()`, `index()`) represent per-element functions evaluated within geometry contexts (points, edges, faces, instances), not static global values.
5. **Zone Subgraphs**: Zones (`repeat`, `foreach`, `simulation`) define subgraphs with explicit input and output boundaries. Variables do not implicitly cross zone boundaries.
6. **Three-Stage Processing Pipeline**:
   - **Preprocessing Stage**: Normal Python blocks (```` ``` ````) execute first, computing values, establishing a shared namespace, and expanding text macros (`py!.*`).
   - **Compilation Stage**: XFY AST statements compile into Blender node data structures, link sockets, configure RNA properties, and assign modifiers/materials.
   - **Deferred Post-Compilation Stage**: Deferred Python blocks (`#defer`) execute last, providing direct access to the compiled node tree (`__tree__`), active object (`__object__`), and Blender context (`bpy`).

---

## 2. Program Structure

### 2.1 File-Level Structure
```python
# User parameter inputs (create interface sockets on modifier / group)
input scale: float "Scale" = 1.0 [0.0, 10.0] @ "Transform"
input mode: menu "Distribution" = 'RANDOM' @ "Settings"

# Output socket declarations
output result: geometry "Geometry"

# Graph body
geo = mesh_grid(size_x=scale, size_y=scale)
result = geo
```

### 2.2 Includes
```python
include ./components/math_helpers.xfy       # Relative path
include /absolute/path/to/library.xfy       # Absolute path
```
Included files are resolved and inlined during preprocessing. Use `if not __parents__:` inside Python blocks to guard setup code intended only for top-level script execution.

### 2.3 Context Blocks (Multi-Object, Material, World, Scene)
```python
# Geometry nodes block assigned to an object
object "Ground" geometry as "GroundScatter" {
    output geo: geometry
    geo = mesh_grid(10.0, 10.0, 50, 50)
}

# Material node block assigned to an object
object "Ground" material as "GroundMaterial" {
    tex = tex_image{file_path:"textures/diffuse.png"}()
    bsdf = bsdf_principled(base_color=tex[0], roughness=0.8)
    output_material(surface=bsdf)
}

# World shading block
world "Environment" {
    sky = tex_environment{file_path:"hdris/sunset.exr"}()
    background = background(color=sky[0], strength=1.5)
    output_world(surface=background)
}
```

---

## 3. Data Types & Socket Declarations

### 3.1 Supported Types
| Type Keyword | Blender Data Type | Description |
|---|---|---|
| `float` | `NodeSocketFloat` | Single-precision floating point scalar |
| `int` | `NodeSocketInt` | 32-bit signed integer |
| `vector` | `NodeSocketVector` | 3D Cartesian vector $(x, y, z)$ |
| `int_vector` | `NodeSocketVectorInt` | 3D integer vector $(i, j, k)$ |
| `bool` | `NodeSocketBool` | Boolean truth value (`True`, `False`) |
| `string` | `NodeSocketString` | Text string |
| `geometry` | `NodeSocketGeometry` | Mesh, Curve, PointCloud, Volume, or Instances |
| `color` | `NodeSocketColor` | RGBA color tuple $(r, g, b, a)$ |
| `mat` / `material` | `NodeSocketMaterial` | Blender Material datablock |
| `shader` | `NodeSocketShader` | Shader closure (BSDF, Emission, Volume) |
| `object` | `NodeSocketObject` | Blender Object datablock |
| `collection` | `NodeSocketCollection` | Blender Collection datablock |
| `image` | `NodeSocketImage` | Image datablock |
| `texture` | `NodeSocketTexture` | Texture datablock |
| `rotation` | `NodeSocketRotation` | 3D rotation representation |
| `matrix` | `NodeSocketMatrix` | $4 \times 4$ transformation matrix |
| `menu` | `NodeSocketMenu` | Dynamic enum/menu switch selector |
| `bundle` | `NodeSocketBundle` | Heterogeneous typed packet |
| `closure` | `NodeSocketClosure` | First-class functional node subgraph |

### 3.2 Socket Declarations
```python
# Full input declaration syntax:
# [hidden] input NAME: TYPE ["Label"] ["Tooltip"] [= DEFAULT] [RANGE] [@ "Panel"]
input radius: float "Base Radius" "Outer cylinder radius" = 1.0 [0.1, 50.0] @ "Dimensions"
input segments: int "Segments" = 32 [3, 256] @ "Dimensions"
hidden input debug_id: int = 0

# Range specification variants:
input a: float = 1.0 [0.0, 10.0]    # Clamped min and max
input b: float = 0.5 [0.0, ]         # Clamped min only
input c: float = 5.0 [, 100.0]       # Clamped max only

# Output declaration syntax:
# [hidden] output NAME: TYPE ["Label"] [@ "Panel"]
output mesh_out: geometry "Mesh Output" @ "Results"
output count_out: int "Total Count"
```

---

## 4. Literals, Constants, and Operators

### 4.1 Literals & Constant Nodes
- **Scalar Numerics**: `10`, `3.14159`, `-0.5`
- **Strings**: `"Mesh Output"`, `'Offset'`
- **Booleans**: `True`, `False`
- **Vectors**: `(0.0, 1.0, 2.0)`
- **Literal Constant Nodes (`$`)**: Prepending `$` forces the creation of a persistent Constant input node rather than inlining an attribute:
  ```python
  unit_str = string_join(, value_to_string(length, 2) ~ $" m")
  single_quote = $"'"
  const_vec = $(0.0, 0.0, 1.0)
  ```

### 4.2 Operators
| Operator | Function | Graph Mapping / Behavior |
|---|---|---|
| `+` `-` `*` `/` `%` `**` | Arithmetic | Auto-selects `math` or `vector_math` based on operand types |
| `==` `!=` `<` `>` `<=` `>=` | Comparison | Auto-selects `compare` or `math{operation:'COMPARE'}` |
| `&` `\|` `!` `^` | Boolean | Maps to `boolean_math` (`AND`, `OR`, `NOT`, `XOR`) |
| `!&` `!\|` `!^` | Negated Boolean | Maps to `boolean_math` (`NAND`, `NOR`, `XNOR`) |
| `=>` `!=>` | Implication | Maps to `boolean_math` (`IMPLY`, `NIMPLY`) |
| `? :` | Ternary | `cond ? a : b` compiles to `switch` with type inference |
| `~` | Multi-Input Link | Concatenates variadic inputs inside node arguments |
| `=` | Assignment | Wires expression output to variable name |

### 4.3 Ternary Conditionals
```python
# Syntax: condition ? value_if_true : value_if_false
offset = is_active ? 2.5 : 0.0
color = is_valid ? (0.0, 1.0, 0.0, 1.0) : (1.0, 0.0, 0.0, 1.0)
```

---

## 5. Node Calls & Argument Binding

### 5.1 Call Syntax Overview
```python
# node_name{attributes}(arguments)
result = mesh_line{mode:'OFFSET'}(10, , (0, 0, 0), (0, 0, 1))
```

### 5.2 Attributes vs. Arguments
- **Attributes `{...}`**: Configure node settings, RNA enum modes, dynamic element operations (`add:`, `remove:`), and structural flags before the node tree updates.
- **Arguments `(...)`**: Provide socket connections, scalar inputs, or keyword parameter overrides.

### 5.3 Zero-Argument Calls
Node functions taking zero inputs require explicit parentheses `()` to distinguish invocation from symbol references:
```python
pos = position()                            # Correct
nrm = normal()                              # Correct
info = object_info()                        # Correct
attr = attribute{attribute_name:"Theme"}()  # Correct
```

### 5.4 Positional Arguments & Bare-Comma Skips
Positional arguments map directly to input sockets in the order listed in `geometry_nodes.json` / `material_nodes.json`. An empty argument between commas skips that socket, preserving its default value:
```python
# transform signature: [0: Geometry, 1: Mode (property), 2: Translation, 3: Rotation, 4: Scale]
# Translation only:
t1 = transform(geo, , (0, 0, 5))

# Rotation only (skip mode at index 1 and translation at index 2):
t2 = transform(geo, , , (0, 1.57, 0))
```

### 5.5 Keyword Arguments (kwargs) & Two-Pass Evaluation
Keyword arguments allow inputs and configuration properties to be set directly by name (using `snake_case` or space-separated names):
```python
# Properties and sockets can be specified as kwargs:
line = mesh_line(mode='END_POINTS', start_location=(0, 1, 1), end_location=(3, 4, 5))
```

#### Two-Pass Evaluation Architecture
Function call arguments are processed in two passes:
1. **Pass 1 (Configuration & Properties)**: Kwargs that match node RNA properties (such as `mode`, `operation`, `data_type`, `count_mode`, `domain`) are applied first. Blender's RNA immediately updates dynamic socket availability, enabled/disabled states, and UI labels.
2. **Pass 2 (Socket Binding)**: Connects socket inputs (positional args, labeled args, and socket kwargs). Because properties are applied in Pass 1, kwargs are completely **order-independent**:
   ```python
   # Evaluates identically regardless of argument order:
   line1 = mesh_line(mode='END_POINTS', start_location=(0, 1, 1), end_location=(3, 4, 5))
   line2 = mesh_line(start_location=(0, 1, 1), end_location=(3, 4, 5), mode='END_POINTS')
   ```

### 5.6 Dynamic Sockets & Label Matching
In Blender, nodes whose interface changes with mode switches often retain underlying socket names while altering their UI `label`:
- **`mesh_line`**: When `mode='END_POINTS'`, socket `Offset` updates its UI label to `End Location`. The compiler matches both `end_location` and `offset`.
- **`combine_color`**: When `mode='HSV'`, sockets `Red`, `Green`, `Blue` update labels to `Hue`, `Saturation`, `Value`. Kwargs `hue=...`, `saturation=...`, `value=...` match automatically.
- **`math`**: Sockets update dynamic labels based on `operation` (for example, `Multiplier` and `Addend` for `MULTIPLY_ADD`, `Base` and `Exponent` for `POWER`).
- **`random_value`**: When `data_type='BOOLEAN'`, socket `Min` is replaced with `Probability`.

### 5.7 Output Socket Selection
```python
# 1. Multi-output indexing:
ray = raycast(geo, ray_direction=(0, 0, -1))
hit_pos = ray[1]
hit_norm = ray[2]

# 2. Named attribute selection (matches canonical name and dynamic labels):
hit_pos = ray.hit_position
hit_norm = ray.hit_normal

sep = separate_color(mode='HSV')(col)
h = sep.hue                  # Matches dynamic label 'Hue'
s = sep.saturation

# 3. Tuple unpacking (requires parentheses on left-hand side):
(is_hit, hit_position, hit_normal, hit_distance) = raycast(geo, ray_direction=(0, 0, -1))
(_, hit_pos, _, _) = raycast(geo, ray_direction=(0, 0, -1))   # Underscore discards
```

---

## 6. Canonical Nodes Reference

*Names correspond to internal identifiers in `geometry_nodes.json`.*

### 6.1 Primitives
```python
mesh_cube(size)
mesh_cylinder(vertices, side_segments, fill_segments, radius, depth)
mesh_cone(vertices, side_segments, fill_segments, radius_top, radius_bottom, depth)
mesh_circle(vertices, radius)
icosphere(radius, subdivisions)
uvsphere(segments, rings, radius)
mesh_grid(size_x, size_y, verts_x, verts_y)
mesh_torus(major_segments, minor_segments, major_radius, minor_radius)
mesh_line{mode:'OFFSET'}(count, , , offset)

curve_primitive_circle(resolution, radius)
curve_primitive_line(start, end)
curve_primitive_bezier_segment()
curve_spiral(resolution, rotations, start_radius, end_radius, height)
curve_star(points, inner_radius, outer_radius, twist)
points(count)
```

### 6.2 Key Geometry Operations
```python
join_geometry(geo1 ~ geo2 ~ geo3)
transform(geo, , translation, rotation, scale)
set_position(geo, selection, position, offset)
instance_on_points(points, , instance)
curve_to_mesh(curve, profile, fill_caps)
merge_by_distance(geo, , distance)
subdivide_mesh(geo, level)
subdivide_curve(curve, cuts)
extrude_mesh(geo, selection, offset)
delete_geometry(geo, selection)
separate_geometry(geo, selection)
realize_instances(geo)
set_shade_smooth(geo, selection, shade_smooth)
set_material(geo, selection, material)
set_spline_cyclic(curve, selection, cyclic)
set_spline_resolution(curve, selection, resolution)
store_named_attribute{data_type:'TYPE', domain:'DOMAIN'}(geo, selection, name, value)
input_named_attribute{data_type:'TYPE'}(name)
field_on_domain{domain:'DOMAIN'}(field)
geometry_to_instance(geo)
```

### 6.3 Grease Pencil
```python
curves_to_grease_pencil(geo)
set_grease_pencil_color(gp, selection, color)
set_grease_pencil_depth(gp, selection, depth)
set_grease_pencil_softness(gp, selection, softness)
```

### 6.4 Strings
```python
string_join(separator, s1 ~ s2 ~ s3)
string_length(string)
slice_string(string, position, length)
value_to_string(value, precision)
string_to_value(string)
```

### 6.5 Sampling
```python
sample_index{domain:'DOMAIN', data_type:'TYPE'}(geo, value, index)
sample_curve(curve, , parameter)
sample_nearest(geo, sample_position)     # Geo must be mesh or point cloud
sample_nearest_surface{data_type:'TYPE'}(geo, value, sample_position)
```

### 6.6 Fields and Input Nodes
```python
position()                     # Vector position field
index()                        # Integer element index field
normal()                       # Vector surface normal field
id()                           # Integer element identifier field
radius()                       # Float point/curve radius field
input_scene_time()             # Returns [seconds[0], frame[1]]
spline_parameter()             # Returns [factor[0], length[1], index[2]]
edge_vertices()                # Returns [v1[0], v2[1], pos1[2], pos2[3]]
```

### 6.7 Combine & Separate
```python
combine_xyz(x, y, z)
separate_xyz(vector)                 # Returns [x, y, z]
combine_color{mode:'RGB'}(r, g, b)  # Geometry Nodes
separate_color{mode:'RGB'}(color)   # Geometry Nodes

# Shader Nodes:
shader_combine_color(r, g, b)
hue_saturation(hue, sat, val)
```

### 6.8 Built-in Node Group Assets (Blender Essentials)
Assets from Blender's built-in libraries (such as `essentials.blend`) are resolved dynamically using quoted names:
```python
edge_boundary = "Is Edge Boundary"()[0]
edge_len = "Edge Length"()[0]
```

---

## 7. Math, Vector, and Comparison Shortcuts

*Shortcuts expand automatically to their canonical nodes with corresponding RNA operation properties.*

### 7.1 Scalar Math
- **Single-argument**: `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `sinh`, `cosh`, `tanh`, `sqrt`, `abs`, `floor`, `ceil`, `round`, `trunc`, `fract`, `sign`, `radians`, `degrees`, `exp`, `ln`
- **Two-argument**: `pow(base, exp)`, `log(val, base)`, `min(a, b)`, `max(a, b)`, `mod(a, b)`, `atan2(y, x)`, `snap(val, inc)`, `wrap(val, min, max)`, `pingpong(val, scale)`
- **Three-argument**: `smoothmin(a, b, dist)`, `smoothmax(a, b, dist)`, `multiply_add(a, b, c)`

### 7.2 Vector Math
- `vnormalize(v)`, `vlength(v)`, `vabs(v)`, `vfloor(v)`, `vceil(v)`, `vfract(v)`
- `vsin(v)`, `vcos(v)`, `vtan(v)`, `vadd(a, b)`, `vsub(a, b)`, `vmul(a, b)`, `vdiv(a, b)`
- `vcross(a, b)`, `vdot(a, b)`, `vdist(a, b)`, `vreflect(v, n)`, `vproject(v, target)`
- `vmin(a, b)`, `vmax(a, b)`, `vscale(vec, scalar)`, `vrefract(v, n, ior)`, `vwrap(v, min, max)`

### 7.3 Interpolation
- `lerp(factor, a, b)` $\rightarrow$ `mix{data_type:'FLOAT'}(factor, a, b)`
- `vlerp(factor, a, b)` $\rightarrow$ `mix{data_type:'VECTOR'}(factor, a, b)`

### 7.4 Comparisons & Cross-Context Compare
- **Shortcuts**: `eq(a, b)`, `ne(a, b)`, `lt(a, b)`, `le(a, b)`, `gt(a, b)`, `ge(a, b)`
- **Cross-Context Behavior**:
  - In **Geometry Nodes**, `compare` maps to `FunctionNodeCompare`. When no operation is provided, it defaults to `operation:'EQUAL'` with `data_type:'FLOAT'` (taking inputs `A`, `B`, `Epsilon`).
  - In **Shader Nodes**, `FunctionNodeCompare` does not exist in Blender. XFY maps `compare(...)` to `math{operation:'COMPARE'}` (taking inputs `Value1`, `Value2`, `Epsilon`).

---

## 8. Dynamic Elements: Color Ramps & Curves

### 8.1 Color Ramp (`color_ramp`)
Manipulate gradient stops sequentially via `add:` and `remove:` attributes:
- **`add: 'pos:color'`**: Stop position in $[0.0, 1.0]$. Color can be hex (`'#ff0000'`) or an RGBA string tuple (`'(0.0, 1.0, 0.0, 1.0)'`).
- **`remove: pos`**: Position float to remove.
- **`interpolation`**: `'LINEAR'`, `'CONSTANT'`, `'EASE'`, `'CARDINAL'`, `'B_SPLINE'`.

```python
cr = color_ramp{
    interpolation: 'EASE',
    add: '0.25:#ff0000',
    add: '0.75:(0.0, 1.0, 0.0, 1.0)',
    remove: 0.0
}(factor)
```

### 8.2 Curve Mappings (`float_curve`, `rgb_curves`, `vector_curves`)
Add, modify, and remove control points dynamically on `CurveMapping` nodes:

#### Syntax
- **`add: 'x:y'`** or **`add: 'x:y:HANDLE'`**: Point coordinate and handle type (`'AUTO'`, `'AUTO_CLAMPED'`, `'VECTOR'`). Points sharing an existing $x$-coordinate update in place.
- **`remove: pos`** or **`remove: index`**: Remove point by $x$-coordinate or integer index. *(Blender requires at least 2 curve points at all times).*
- **`points: ['x:y:HANDLE', ...]`**: Define/replace points using an attribute list.
- **`mapping` Properties**: Exposes `extend: 'EXTRAPOLATED'` / `'HORIZONTAL'`, `use_clip: True`/`False`, `clip_min_x`, `clip_max_x`, `clip_min_y`, `clip_max_y`.
- **Channel Targeting**: Multi-channel curve nodes (`rgb_curves`, `vector_curves`) specify target curves via channel suffixes (`:R`, `:G`, `:B`, `:C`, or index `:0`, `:1`, `:2`):

```python
# Float curve with custom handles and extrapolation:
fc = float_curve{
    extend: 'EXTRAPOLATED',
    add: '0.0:0.2:VECTOR',
    add: '0.5:0.8:AUTO',
    add: '1.0:0.1:VECTOR'
}(factor)

# Defining points using a points list:
fc_pts = float_curve{
    points: ['0.0:0.0', '0.4:0.9:VECTOR', '1.0:1.0']
}(factor)

# Targeting specific curves in RGB curves:
rgb_c = rgb_curves{
    add: '0.5:0.8:AUTO:R',       # Target Red curve
    add: '0.3:0.9:VECTOR:1'      # Target curve index 1 (Red)
}(color)
```

---

## 9. Control Flow & Graph Zones

### 9.1 `switch`
```python
# Argument order: (condition, value_if_false, value_if_true)
result = switch{input_type:'FLOAT'}(is_active, 0.0, 1.0)
```
*Note: Argument order is `(condition, false_val, true_val)`. If the true branch is omitted, it falls back to the socket's default value (`switch(cond, false_val, )`).*

### 9.2 `menu_switch` and `index_switch`
```python
# Menu Switch (uses labeled arguments with @):
shape = menu_switch{data_type:'GEOMETRY'}(
    selector,
    mesh_cube() @ 'Cube',
    uvsphere() @ 'Sphere',
    mesh_cylinder() @ 'Cylinder'
)

# Index Switch (0-indexed integer selection):
active_geo = index_switch{data_type:'GEOMETRY'}(index, geo0, geo1, geo2)
```

### 9.3 `repeat` Zone
```python
repeat ITERATIONS, GEO_INPUT, state=(var1, var2):ITER_VAR, geo_var {
    geo_var = subdivide_mesh(geo_var, 1)
    var1 = var1 + 1
}(geo_var, var1, var2)
```
*Note: The `repeat` output clause `}(...)` always produces a Geometry socket at index `0`. If `GEO_INPUT` is omitted, prepend a bare comma `(, var1=var1, var2=var2)` to skip the unused geometry socket.*

### 9.4 `foreach` Zone
```python
foreach{domain:'FACE'} mesh, selection, state=(accum):idx, elem {
    accum = join_geometry(accum ~ some_geo)
}(elem_input : accum, result)
#            ↑ Colon is mandatory: (inputs fed in : outputs produced)
```
Valid domains: `'POINT'`, `'EDGE'`, `'FACE'`, `'CORNER'`, `'CURVE'`, `'INSTANCE'`.

### 9.5 `simulation` Zone
```python
simulation GEO_INPUT, state=(vel):dt, geo {
    new_pos = position() + vscale(vel, dt)
    geo = set_position(geo, , new_pos)
}(geo, vel)
```

---

## 10. Closures (Blender 5.2+)

Closures encapsulate reusable subgraphs into first-class handles that can be passed as variables, switched with `index_switch{data_type:'CLOSURE'}`, and called directly.

### 10.1 Defining Closures
```python
# Assignment syntax:
square_fn = closure(x: float) {
    y = x * x
}(y)

# Multi-output closure:
math_bundle = closure(a: float, b: float) {
    s = a + b
    d = a - b
}(s, d)
```

### 10.2 Invocation & Group Signatures
```python
group evaluator "Graph Evaluator" {
    # Functional signature declaration:
    input fn: closure(x: float) -> (y: float) "Function"
    input val: float "Input" = 2.0

    # Direct functional call:
    result_val = fn(val)
    output result_val: float "Output"
}
```

### 10.3 Dynamic Closure Switching
```python
active_fn = index_switch{data_type:'CLOSURE'}(selector, sin_fn, cos_fn, linear_fn)
y = active_fn(x)
```

---

## 11. Typed Bundles

Bundles package heterogeneous sockets (floats, vectors, matrices, closures, geometry) into a single transport link (`bundle`).

### 11.1 Bundle Packing & Unpacking
```python
# Pack named fields into a bundle:
b = combine_bundle(pos=position(), scale=2.5, factor=0.5)

# Unpack fields from a bundle:
(pos, scale, factor) = separate_bundle(b)

# Merge two bundles:
merged_b = join_bundle(bundle_a, bundle_b)
```

### 11.2 Geometry Bundles
```python
# Attach bundle to geometry attributes:
geo_with_data = set_geometry_bundle(geo, b)

# Retrieve bundle from geometry:
retrieved_b = get_geometry_bundle(geo_with_data)[0]
```

---

## 12. Materials & Shading

### 12.1 Material Block Definition
```python
object "Model" material as "PrincipledMaterial" {
    tex = tex_image{file_path:"textures/albedo.png"}()
    bsdf = bsdf_principled(
        base_color=tex[0],
        roughness=0.4,
        metallic=0.0
    )
    output_material(surface=bsdf)
}
```

### 12.2 Textures & UDIMs
```python
# Direct socket assignment:
tex1 = image_texture(Image="textures/diffuse.png", Vector=uv)

# Dedicated Image node:
img = image{file_path:"textures/normal.png"}()
norm_map = normal_map(color=image_texture(Image=img, Vector=uv)[0])

# Tiled / UDIM texture sets:
udim_tex = tex_image{file_path:"textures/body.1001.png", source:'TILED'}()
```

---

## 13. Python Integration & Macro System

Python code can be embedded directly in XFY scripts to compute parameters, generate procedural graph code, inspect the inclusion hierarchy, or perform post-compilation scene setup.

### 13.1 Preprocessing Macros & Constants
Normal Python blocks (```` ``` ... ``` ````) execute before graph compilation, populating a shared Python namespace:

- **Value Substitution (`py.var`)**: Evaluates a Python expression or variable value at compile time:
  ```python
  x_scale = py.math.cos(py.phi)
  ```
- **Text Macro Expansion (`py!.macro`)**: Inlines raw string content directly into the XFY source text prior to AST tokenization:
  ````python
  ```
  import math
  phi = (1 + math.sqrt(5)) / 2

  def make_chain(n):
      return ' ~ '.join([f'mesh_cube({i})' for i in range(n)])

  cubes_code = make_chain(4)
  ```

  geo = join_geometry(py!.cubes_code)
  ````
- **Procedural Script Generation (`py!.op`)**: Constructs multi-statement XFY graph blocks dynamically:
  ````python
  ```
  count = 6
  spheres = ' ~ '.join([f'icosphere(radius={0.2 * i + 0.1})' for i in range(1, count + 1)])
  op = f'''
  output result: geometry
  result = join_geometry({spheres})
  '''
  ```

  py!.op
  ````

### 13.2 Deferred Python Blocks (`#defer`)
Blocks marked with `#defer` (either as ```` ```#defer ```` on the opening fence or as `#defer` on the first non-empty line) execute **after** AST compilation, node tree construction, and modifier/material assignment have completed:

````python
output result: geometry "Mesh"
result = mesh_cube(size=2.0)

```#defer
import bpy

# Access the compiled node tree and scene context
tree = __tree__
obj = __object__

# Configure modifier or object properties post-compilation
if obj:
    obj.display_type = 'WIRE'

# Set up keyframe animation or render settings
scene = __context__.scene
scene.frame_start = 1
scene.frame_end = 100
```
````

#### Injected Execution Context
Deferred blocks receive an enriched runtime namespace:

| Variable | Type | Description |
|---|---|---|
| `bpy` | `module` | The active Blender Python API module |
| `__tree__` | `NodeTree` | The compiled node group / modifier tree (single-tree scripts) |
| `__trees__` | `list[NodeTree]` | List of all compiled trees (multi-block scripts) |
| `__object__` | `Object` / `None` | The active target object receiving the modifier/material |
| `__context__` | `Context` | The active Blender execution context (`bpy.context`) |
| `__file__` | `str` | Absolute path of the current script file |
| `__parents__` | `list[str]` | Filepath chain of including parent scripts |
| `**python_namespace` | `dict` | All variables and functions defined in preceding normal Python blocks |

*Note: The script directory is automatically inserted at `sys.path[0]`, allowing deferred blocks to import local Python modules via standard `import` statements.*

### 13.3 The Built-in `__parents__` Variable
The `__parents__` variable tracks the inclusion hierarchy, allowing scripts to behave both as standalone test files and as reusable included components.

- **Root Script**: When executed directly as the top-level script, `__parents__` is an empty list `[]` (`bool(__parents__) == False`).
- **Included Script**: When pulled in via `include path/to/file.xfy`, `__parents__` contains the filepaths of all ancestor scripts: `[direct_parent, ..., root_script]`.

#### Component / Test Standalone Pattern
Use `if not __parents__:` inside preprocessing blocks to execute test geometry or default outputs only when the file is run standalone:

````python
# components/leaf_generator.xfy
group make_leaf "Generate Leaf" {
    input length: float = 1.0
    output leaf_geo: geometry
    leaf_geo = mesh_grid(length, length * 0.5)
}

```
# Only create demo output when tested directly, not when included into a book/tree model
if not __parents__:
    demo_code = '''
output result: geometry
result = make_leaf(length=2.5)
'''
else:
    demo_code = ''
```

py!.demo_code
````

---

## 14. Validation & Tooling

```bash
# Fast validation (syntax + semantics, runs without Blender):
python3 tools/validate_xfy.py path/to/script.xfy -v

# Comprehensive runtime validation (executes in headless Blender):
python3 tools/validate_xfy.py path/to/script.xfy --blender

# Batch validation:
python3 tools/validate_xfy.py samples/**/*.xfy
```

---

## 15. Pre-Flight Verification Checklist

Before running or committing any `.xfy` script, verify:

- [ ] **Socket Indices**: Positional arguments follow socket orders in `geometry_nodes.json` / `material_nodes.json`.
- [ ] **`switch` Order**: Arguments follow `(condition, false_value, true_value)`.
- [ ] **Tuple Unpacking**: Targets use parentheses on the left (`(a, b) = ...`) and `_` for discards.
- [ ] **`~` Usage**: Concatenation `~` is used only inside multi-input node calls (e.g. `join_geometry(a ~ b)`).
- [ ] **Zero-Argument Nodes**: Field and generator calls include parentheses (e.g. `position()`, `normal()`).
- [ ] **Properties vs Inputs**: Configuration options (`mode`, `operation`, `data_type`) use attributes `{...}` or kwargs (`mode='...'`).
- [ ] **Bare Commas**: Unused positional sockets are explicitly skipped with commas (e.g. `transform(geo, , translation)`).
- [ ] **`repeat` Loop Return**: Geometry loops output `geo` at index 0; non-geometry loops use `(, state1=...)`.
- [ ] **`foreach` Output**: Colon separator is present between inputs and outputs: `(inputs : outputs)`.
- [ ] **Validation**: Passes `python3 tools/validate_xfy.py script.xfy -v`.
