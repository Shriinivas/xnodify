# XNodify Samples & Recipes Suite

Welcome to the curated samples library for **XNodify** (Blender 5.2+).

This directory contains standalone examples, procedural modeling components, and real-world production setups demonstrating the full expressive power of the XFY domain-specific language.

---

## Directory Architecture

```text
samples/
├── common/
│   └── xfy_utils.py             # Reusable Python helper library (materials, scene setup)
│
├── mesh_utils/                  # Reusable all-quad procedural modeling primitives
│   ├── cylinder.xfy             # All-quad subdivision cylinder with support loops & 4-quad caps
│   ├── quadstadium.xfy          # 2D pure-quad stadium / rounded capsule profile
│   ├── quadstadium3d.xfy        # 3D filleted stadium bar with tri-axial corner radii
│   ├── hole.xfy                 # 2D concentric quad hole puncher
│   └── hole3d.xfy               # 3D hole boring with rim chamfer/fillet beveling & blind/through modes
│
├── 01_language_features/        # Focused, 100% self-contained syntax demos (zero dependencies)
│   ├── 01_repeat_zone.xfy       # Repeat Zone: procedural spiral staircase with state accumulation
│   ├── 02_simulation_zone.xfy   # Simulation Zone: rising particle field with delta-time integration
│   ├── 03_foreach_zone.xfy      # Foreach Zone: face-aligned 3D extruded numbers
│   ├── 04_closures.xfy          # First-class functional closures, signatures, and evaluate_closure
│   ├── 05_typed_bundles.xfy     # Typed bundles: packing, unpacking, and geometry attachment
│   ├── 06_groups_and_nesting.xfy# Reusable custom node groups and nested hierarchical assemblies
│   ├── 07_python_embedding.xfy  # Preprocessing Python, py! macros, py. vars, __parents__, and #defer
│   └── 08_multi_tree_scene.xfy  # Unified Geo modifier, Object shader, and World background
│
├── 02_shaders_and_materials/    # Pure declarative surface and world shader graphs
│   ├── procedural_tiles.xfy     # Mathematical grid tiling, mortar masks & per-tile color variation
│   ├── procedural_wood.xfy      # Multi-octave organic wood grain, knots, and tactile bump normal
│   └── space_environment.xfy    # Procedural starry night, glowing nebula clouds & emission
│
├── 03_procedural_motion/        # Kinematics and dynamic physics
│   └── bouncing_ball.xfy        # Dynamic bounding-box kinematics, squash & stretch, rolling roll
│
├── 04_mechanical_and_cad/       # CAD mechanisms and inverse kinematics
│   ├── involute_gear.xfy        # Parametric gear with teeth, tapers, lightening spokes, and bore
│   └── inverse_kinematics.xfy   # 3D FABRIK IK solver with swept lines & spherical joint articulation
│
├── 05_technical_measurement/    # CAD & architectural dimensioning utilities
│   ├── measure.xfy              # Master dual dimensioning setup (distance & angle)
│   ├── distance.xfy             # Procedural linear dimensioning (mesh & Grease Pencil 5.2)
│   ├── angle.xfy                # Procedural angular dimensioning (mesh & Grease Pencil 5.2)
│   ├── distance_gp.xfy          # Native Grease Pencil linear dimension component
│   ├── distance_mesh.xfy        # 3D mesh linear dimension component
│   ├── angle_gp.xfy             # Native Grease Pencil angular dimension component
│   ├── angle_mesh.xfy           # 3D mesh angular dimension component
│   ├── gp_text.xfy              # Native Grease Pencil 3D text generator
│   └── grp_string_to_curves.xfy # Formatted numeric text generator
│
└── 06_book_animation/           # Complex procedural deformation & flipbook
    ├── discbound_book.xfy       # Master discbound flipping book assembly (includes mesh_utils)
    ├── flipbook.xfy             # Dynamic animated flipbook with UDIM texture sequence and covers
    ├── page_bend.xfy            # Dynamic page curl / bending deformation
    ├── page_tile_coords.xfy     # Multi-page UV coordinate mapping & tiling
    └── pngs/                    # Lightweight demo image sequence (20 PNG frames)
```

---

## How to Run Samples

### 1. From Blender's Text Editor
1. Open Blender 5.2.
2. Switch to the **Scripting** workspace (or open a **Text Editor** area).
3. Open any `.xfy` file (e.g., `samples/01_language_features/01_repeat_zone.xfy`).
4. Click **Run Script** (or press `Alt+P`).
5. XNodify compiles the script instantly into a Geometry Node modifier, Shader Tree, or World Shader, and applies fast, automatic layout arrangement.

### 2. From Neovim
Using the bundled Neovim plugin (`nvim-support/`):
- Open any `.xfy` file in Neovim.
- Press `<leader>xr` to compile and send the node graph directly to your active Blender session in real-time.

### 3. From the Terminal (Validation Tool)
Validate any sample or batch of samples headlessly without opening the Blender UI:
```bash
python3 tools/validate_xfy.py --blender samples/01_language_features/*.xfy
```

---

## Detailed Catalog

### 01. Language Features (`01_language_features/`)
Every script in this category is completely self-contained with **zero external dependencies**.
- **`01_repeat_zone.xfy`**: Uses a `repeat` zone to iteratively assemble a procedural spiral staircase with central support pole, computing rotational and vertical offsets on each step.
- **`02_simulation_zone.xfy`**: Uses a `simulation` zone to advance particle positions by integrating per-frame delta time (`dt`) with an upward velocity vector.
- **`03_foreach_zone.xfy`**: Iterates over each face of an icosphere using `foreach{domain:'FACE'}`, aligns rotation to the face normal, converts the face index into 3D extruded text, and stamps it directly onto the mesh.
- **`04_closures.xfy`**: Showcases closures as first-class citizens in geometry node trees: closure assignment, explicit `evaluate_closure`, typed closure arguments `closure(...) -> (...)` in node groups, and geometry-generating closures.
- **`05_typed_bundles.xfy`**: Packs heterogeneous transformation parameters into named `bundle` types, passes them across node group boundaries, and stores/retrieves them from geometry datablocks.
- **`06_groups_and_nesting.xfy`**: Demonstrates group hierarchy and composition: an inner `FlutedColumn` group is nested inside a `ClassicalPillar` assembly, which is in turn instanced four times under a shared temple architrave.
- **`07_python_embedding.xfy`**: Demonstrates the three-stage XFY pipeline: preprocessing Python calculates golden ratio proportions, `py!.macro` expands dynamic inputs, `py.var` injects Python constants, and `#defer` blocks run post-compilation to inspect compiled trees (`__trees__`) and adjust Blender objects.
- **`08_multi_tree_scene.xfy`**: Defines a Geometry Nodes modifier (`object "Pedestal"`), an Object Material shader (`object "Pedestal" material as "PedestalMarble"`), and a World Environment shader (`world "MinimalistStudio"`) in a single declarative file.

### 02. Shaders & Materials (`02_shaders_and_materials/`)
- **`procedural_tiles.xfy`**: Mathematical tiling using UV coordinate modular arithmetic, creating ceramic terracotta tiles separated by a procedural mortar border.
- **`procedural_wood.xfy`**: Multi-scale distorted noise simulating hardwood fibers, rings, and localized knots, with automatic bump normal mapping.
- **`space_environment.xfy`**: Procedural deep-space world background with crushed high-frequency noise for pinpoint stars and layered colored nebula dust clouds.

### 03. Procedural Motion (`03_procedural_motion/`)
- **`bouncing_ball.xfy`**: Realistic procedural squash and stretch kinematics. Dynamically computes the ball's bounding box, computes kinetic energy decay over time, squashes the mesh while preserving 3D volume upon floor impact, and calculates rolling wheel rotation matching forward travel.

### 04. Mechanical & CAD (`04_mechanical_and_cad/`)
- **`involute_gear.xfy`**: Parametric spur gear generator based on standard gear tooth formulas (module, pitch diameter, addendum, dedendum), complete with center bore, lightening spokes, and optional 3D embossed tooth numbering.
- **`inverse_kinematics.xfy`**: Pure 3D FABRIK (Forward And Backward Reaching Inverse Kinematics) solver. Solves an N-link skeletal chain inside a Repeat Zone to reach a procedural 3D target, sweeping clean cylindrical links and instancing spherical joints with zero mesh overlaps.

### 05. Technical Measurement (`05_technical_measurement/`)
- **`measure.xfy`**: Complete CAD/architectural dimensioning rig.
- Supports dual visualization modes:
  1. **3D Mesh Mode**: Swept curve arrows, extension lines, witness ticks, and extruded 3D numerical text.
  2. **Grease Pencil Mode**: Native Blender 5.2 Grease Pencil stroke and fill annotations.

### 06. Book Animation (`06_book_animation/`)
- **`flipbook.xfy`**: Classic procedural flipbook animation with UDIM image strip playback (`pngs/`), dynamic sequential page curl (`page_bend.xfy`), multi-page UV mapping (`page_tile_coords.xfy`), and animated hard/paper covers with dynamic connected spine.
- **`discbound_book.xfy`**: Advanced procedural flipbook and discbound notebook.
- Leverages modular imports from `mesh_utils/` (`quadstadium.xfy` and `hole.xfy`) to punch binder disc holes, and simulates realistic multi-page turning, cascading sheet delays, and dynamic curvature curling (`page_bend.xfy`).

### Mesh Utilities (`mesh_utils/`)
Reusable, all-quad procedural modeling primitives:
- **`cylinder.xfy`**: All-quad subdivision cylinder with support loops and welded 4-quad caps.
- **`quadstadium.xfy`**: 2D all-quad stadium/capsule profile with conformal squircle elliptical corner mapping.
- **`quadstadium3d.xfy`**: 3D all-quad filleted stadium bar with independent tri-axial bevel radii.
- **`hole.xfy`**: 2D concentric quad hole puncher with boundary protection.
- **`hole3d.xfy`**: 3D manifold hole boring with rim chamfer/fillet beveling and blind/through modes.
