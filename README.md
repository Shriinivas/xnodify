# XNodify

[![Blender 4.2+](https://img.shields.io/badge/Blender-4.2%20%7C%205.x-orange.svg)](https://www.blender.org/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Version: 1.0.0](https://img.shields.io/badge/Version-1.0.0-green.svg)](https://github.com/Shriinivas/xnodify)

**XNodify** is a declarative scripting language and compiler (`.xfy`) for Blender. It allows you to build complex **Geometry Nodes**, **Shader Nodes** (Materials), and **World Shaders** using readable, concise Pythonic code instead of wiring endless spaghetti nodes in the graph editor.

---

## Key Features

- **Multi-Context Tree Support**: First-class generation for **Geometry Node Trees**, **Object Shader Trees**, and **World Shader Trees**.
- **First-Class Zones**: Native, intuitive syntax for **Repeat**, **Simulation**, and **Foreach** zones with explicit state variable tracking.
- **Pythonic Syntax**: Clean arithmetic, tuple unpacking (`(a, b) = ...`), keyword arguments, and math shortcuts.
- **Modular Subgraphs & Nesting**: Define reusable `group` blocks directly in scripts with auto-generated interfaces and multi-file `include` support.
- **Closures & Typed Bundles**: First-class functional closures, custom signatures, and strongly-typed attribute bundles.
- **Seamless Python Interop**: Inline Python calculations, `py!` code macros, dynamic socket evaluation, and `#defer` blocks.
- **Zero-Dependency Quickstart**: Bundles the `lark` parsing engine internally in `vendor/lark` — install the ZIP and start scripting immediately with zero terminal commands.
- **Blender 4.2+ & 5.2+ Native**: Modern `blender_manifest.toml` packaging with full support for Matrix sockets, relative coordinate spaces, and integrated auto-layout (`lineupnodes`).
- **Offline Validation & CLI**: Validate syntax, semantics, and socket typing from your terminal or CI without starting Blender GUI.
- **Editor Tooling**: Neovim LSP server and syntax highlighting for diagnostics, auto-completion, and parameter hints.

---

## Installation

### Method 1: Install from ZIP (Recommended / Zero-Config)

XNodify comes with bundled dependencies (`vendor/lark`), requiring **no command-line setup**:

1. Download this repository as a `.zip` archive (e.g. `xnodify.zip`).
2. Open Blender:
   - **Blender 4.2+ / 5.x**: Go to `Edit` → `Preferences` → `Get Extensions` → click the top-right menu (down arrow) → **Install from Disk...**
   - **Blender 4.1 and earlier**: Go to `Edit` → `Preferences` → `Add-ons` → **Install...**
3. Select `xnodify.zip` and enable **XNodify**.

### Method 2: Manual / Developer Setup

If you clone the repository directly or prefer managing dependencies via Python:

```bash
# Clone the repository
git clone https://github.com/Shriinivas/xnodify.git
```

Symlink or copy the `xnodify` folder into your Blender addons / extensions directory:
- **Linux**: `~/.config/blender/<version>/scripts/addons/xnodify`
- **macOS**: `~/Library/Application Support/Blender/<version>/scripts/addons/xnodify`
- **Windows**: `%USERPROFILE%\AppData\Roaming\Blender Foundation\Blender\<version>\scripts\addons\xnodify`

*(Optional)* If you wish to use an external system-wide or Blender-managed Lark installation rather than the bundled fallback:
```bash
pip install lark
# or using Blender's bundled python:
/path/to/blender/python -m pip install lark
```

---

## Quick Start

### 1. Write an XFY Script

In Blender's **Text Editor**, create a new text block named `arrow.xfy`:

```python
input start: vector "Start" = (0, 0, 0)
input end: vector "End" = (0, 0, 2)
output geo: geometry

# Compute direction vector and arrow geometry
dir = vector_math{operation:'SUBTRACT'}(end, start)
stem = curve_primitive_line(start, end)
head = mesh_cone(radius_bottom=0.2, depth=0.5)

# Combine using multi-input concatenation operator (~)
geo = join_geometry(stem ~ head)
```

### 2. Compile and Apply

1. Press `N` in Blender's **Text Editor** to open the sidebar.
2. Locate the **XNodify** panel.
3. Select an object in your 3D Viewport (or check **Auto Create Object**).
4. Click **Run Script** (or use the shortcut `Alt + P`).
5. A new Geometry Nodes modifier is attached to the object with your compiled node tree.

---

## The Complete Language Specification

For the authoritative specification covering the full language grammar, execution order, built-in nodes, properties, and strict coding rules, see:

👉 **[`XFY_AI_REFERENCE.md`](XFY_AI_REFERENCE.md)**

> **Note for AI Coding Assistants**: `XFY_AI_REFERENCE.md` is the **single source of truth** designed specifically for human developers and LLM agents generating or debugging `.xfy` scripts. It includes socket signatures, pre-flight checklists, loop return rules, and common compilation pitfalls.

---

## Language Highlights

### 1. Shader Materials & World Shaders

Generate shader node trees simply by setting `@tree_type`:

```python
@tree_type = "shader"
@material_name = "GlossyGold"

base_col = (1.0, 0.76, 0.33, 1.0)
shader = principled_bsdf(base_color=base_col, metallic=1.0, roughness=0.15)
output = material_output(surface=shader)
```

### 2. Repeat Zones & Simulation Zones

Iterative state accumulation with explicit state tracking:

```python
input steps: int "Step Count" = 20
input step_height: float "Step Height" = 0.18
output staircase: geometry

base_step = mesh_cube(size=(1.2, 0.35, 0.08))

# Repeat Zone: accumulates geometry across steps
repeat steps, base_step, state=():idx, current_geom {
    z_offset = idx * step_height
    rot_z = idx * 0.314
    step = transform_geometry(base_step, translation=combine_xyz(0.0, 0.0, z_offset), rotation=combine_xyz(0.0, 0.0, rot_z))
    current_geom = join_geometry(current_geom ~ step)
}(accumulated=current_geom)

staircase = accumulated
```

### 3. Reusable Subgraphs (`group`)

Define encapsulated node groups with typed interface sockets:

```python
group MySubdiv {
    input mesh: geometry
    input levels: int "Levels" = 2
    output out: geometry

    sub = subdivide_mesh(mesh, level=levels)
    out = set_shade_smooth(sub)
}

input count: int "Levels" = 2
output geo: geometry

cube = mesh_cube(size=1.0)
geo = MySubdiv(cube, count)
```

### 4. Closures & Typed Bundles

First-class functional closures and strongly typed data bundles:

```python
# First-class closure definition
closure square(x: float) -> (sq: float) {
    sq = x * x
}

# Evaluate closure dynamically
result = evaluate_closure(square, 4.0)

# Typed data bundle packing & unpacking
stats = combine_bundle(area=12.5, count=4, label='panel')
(area, count, label) = separate_bundle(stats)
```

---

## CLI & Offline Validation

XNodify includes offline validation tooling in `tools/validate_xfy.py` that can parse, check semantics, and verify socket signatures without launching the Blender GUI:

```bash
# Fast offline validation (syntax + semantics):
python3 tools/validate_xfy.py path/to/script.xfy -v

# Full headless Blender validation (checks runtime compilation):
python3 tools/validate_xfy.py path/to/script.xfy --blender

# Batch validate all scripts in a directory:
bash tools/batch_validate.sh
```

---

## Editor Integration (Neovim LSP)

A dedicated Language Server Protocol (LSP) server is provided in `nvim-support/`:
- **Real-time Diagnostics**: Syntax and semantic error markers as you type.
- **IntelliSense & Autocomplete**: Node names, socket parameters, and keywords.
- **Hover Documentation**: Node inputs, outputs, and descriptions.
- **Go-to-Definition**: Jump directly to `group` declarations and included files.

Refer to [`nvim-support/README.md`](nvim-support/README.md) for setup instructions.

---

## Curated Samples & Recipes

A rich suite of verified examples is available in [`samples/`](samples/):
- **Language Features (`samples/01_language_features/`)**: Focused, self-contained demos of `repeat` zones, `simulation` zones, `foreach` zones, closures, typed bundles, group nesting, Python embedding (`py!`, `#defer`), and multi-tree files.
- **Procedural Shaders (`samples/02_shaders_and_materials/`)**: Procedural tile grids, organic hardwood, and cosmic nebula starfield environments.
- **Procedural Motion (`samples/03_procedural_motion/`)**: Kinetic squash-and-stretch bouncing ball with volume preservation.
- **CAD & Mechanisms (`samples/04_mechanical_and_cad/`)**: Parametric involute gears and 3D FABRIK inverse kinematics robotic arms.
- **Technical Dimensioning (`samples/05_technical_measurement/`)**: Dual Mesh / Grease Pencil distance and angle dimensioning.
- **Procedural Books (`samples/06_book_animation/`)**: Flipbook and discbound notebook simulations.
- **Mesh Utilities (`samples/mesh_utils/`)**: Reusable all-quad modeling primitives (cylinders, quad stadiums, and 3D hole boring).

See [`samples/README.md`](samples/README.md) for the full catalog and execution guide.

---

## Repository Structure

```
xnodify/
├── blender_manifest.toml    # Blender 4.2+ / 5.x extension manifest
├── __init__.py              # Addon entry point, UI panels & operators
├── compiler.py              # XFY compiler (AST → Blender Node Trees)
├── parser.py                # Lark-based parser & preprocessor
├── builder.py               # Low-level Blender node tree construction
├── registry.py              # Canonical node registry & bidirectional lookup
├── semantic_analyzer.py     # Static validation engine
├── socket_types.py          # Node socket type system & type inference
├── shortcuts.py             # Math & vector operator shortcuts
├── grammar.lark             # Formal EBNF grammar
├── node_registry.json       # Unified node signatures
├── XFY_AI_REFERENCE.md      # Authoritative language reference for humans & AI
├── samples/                 # Curated sample scripts and procedural recipes
├── vendor/                  # Bundled pure-python dependencies (lark)
├── tools/                   # Validation & registry generator scripts
└── nvim-support/            # Neovim LSP server & syntax plugins
```

---

## License & Credits

- Distributed under the **GNU General Public License v3.0 or later** ([GPL-3.0-or-later](https://www.gnu.org/licenses/gpl-3.0.html)).
- Built upon foundational concepts by Shrinivas Kulkarni; refactored and maintained as the unified XNodify project.
