"""
Asset loader for Blender's built-in node group assets.

Handles loading of built-in geometry, shading, hair, dynamics, compositing,
and utility node assets (e.g., "Combine Spherical", "Combine Cylindrical",
"Is Edge Boundary", "Smooth by Angle", "Array") so they can be used
transparently in scripts without manual import.

Assets are loaded LAZILY - only when actually referenced in a script.
"""

import bpy
import os
import re
from pathlib import Path


# Library filename mapping
LIBRARY_FILENAMES = {
    "essentials": "geometry_nodes_essentials.blend",
    "dynamics": "geometry_nodes_dynamics_assets.blend",
    "shading": "shading_nodes_essentials.blend",
    "compositing": "compositing_nodes_essentials.blend",
    "hair": "procedural_hair_node_assets.blend",
    "principal": "principal_components.blend",
}

# Known built-in node group assets (Blender 4.0+)
KNOWN_ASSETS = {
    # Essentials (Geometry Nodes)
    "Combine Spherical": "essentials",
    "Combine Cylindrical": "essentials",
    "Separate Spherical": "essentials",
    "Separate Cylindrical": "essentials",
    "Array": "essentials",
    "Box Selection": "essentials",
    "Capture Rest Geometry": "essentials",
    "Curve to Tube": "essentials",
    "Displace Geometry": "essentials",
    "Edge Length": "essentials",
    "Face Corner Angle": "essentials",
    "Geometry Input": "essentials",
    "Instance on Elements": "essentials",
    "Is Edge Boundary": "essentials",
    "Is Edge Loose": "essentials",
    "Is Edge Manifold": "essentials",
    "Is UV Split": "essentials",
    "Normal Selection": "essentials",
    "Project with Depth": "essentials",
    "Random Rotation": "essentials",
    "Randomize Transforms": "essentials",
    "Scatter on Surface": "essentials",
    "Screen to 3D Space": "essentials",
    "3D to Screen Space": "essentials",
    "Smooth Geometry": "essentials",
    "Smooth by Angle": "essentials",
    "Sphere Selection": "essentials",
    "Transform and Project": "essentials",

    # Principal Components
    "Principal Components": "principal",
    "Geometry Principal Components": "principal",

    # Procedural Hair Node Assets
    "Attach Hair Curves to Surface": "hair",
    "Attachment Info": "hair",
    "Blend Hair Curves": "hair",
    "Braid Hair Curves": "hair",
    "Clump Hair Curves": "hair",
    "Create Guide Index Map": "hair",
    "Curl Hair Curves": "hair",
    "Curve Info": "hair",
    "Curve Root": "hair",
    "Curve Segment": "hair",
    "Curve Tip": "hair",
    "Displace Hair Curves": "hair",
    "Duplicate Hair Curves": "hair",
    "Frizz Hair Curves": "hair",
    "Generate Hair Curves": "hair",
    "Get Attachment Surface": "hair",
    "Get Hair Surface Geometry": "hair",
    "Get Rest Geometry": "hair",
    "Hair Curves Noise": "hair",
    "Interpolate Hair Curves": "hair",
    "Redistribute Curve Points": "hair",
    "Rest Surface": "hair",
    "Restore Curve Segment Length": "hair",
    "Roll Hair Curves": "hair",
    "Rotate Hair Curves": "hair",
    "Set Attachment Surface": "hair",
    "Set Hair Curve Profile": "hair",
    "Shrinkwrap Hair Curves": "hair",
    "Smooth Hair Curves": "hair",
    "Straighten Hair Curves": "hair",
    "Trim Hair Curves": "hair",

    # Dynamics (Blender 5.2+)
    "Apply Each Geometry Cache": "dynamics",
    "Apply Geo Cache - Deform Only": "dynamics",
    "Apply Geo Cache - Topology Changing": "dynamics",
    "Clear Previous World Items": "dynamics",
    "Cloth Dynamics (Experimental)": "dynamics",
    "Collection Effector": "dynamics",
    "Collider": "dynamics",
    "Convert Space Transform": "dynamics",
    "Copy Solver Data": "dynamics",
    "Cross Edge Length Constraint": "dynamics",
    "Curve Bending Compliance": "dynamics",
    "Curve Stretching Compliance": "dynamics",
    "Custom Effector": "dynamics",
    "Custom Force": "dynamics",
    "Custom/World/Object Space": "dynamics",
    "Damping": "dynamics",
    "Edge Length Constraint": "dynamics",
    "Evaluate Custom Effectors": "dynamics",
    "Evaluate Effector Attributes": "dynamics",
    "Evaluate Forces": "dynamics",
    "For Each Sim Geometry": "dynamics",
    "For Each Typed Bundle": "dynamics",
    "Gravity": "dynamics",
    "Hair Dynamics": "dynamics",
    "Is Effector for Geometry": "dynamics",
    "Object Effector": "dynamics",
    "Pin Positions": "dynamics",
    "Pin Rotation": "dynamics",
    "Randomize Float": "dynamics",
    "Remove Sim Attributes": "dynamics",
    "Rename Sim Attributes": "dynamics",
    "Rod Bend/Twist Constraint": "dynamics",
    "Rod Stretch/Shear Constraint": "dynamics",
    "Sample Surface Deformation": "dynamics",
    "Sample Surface Transform": "dynamics",
    "Set Effector": "dynamics",
    "Set Friction": "dynamics",
    "Set Geo Updater - Deform Only": "dynamics",
    "Set Geo Updater - Simulated Topology": "dynamics",
    "Set Geometry Tags": "dynamics",
    "Set Mass": "dynamics",
    "Set Previous World Items": "dynamics",
    "Setup Structural Rest Data": "dynamics",
    "Sim Attributes": "dynamics",
    "Simplify Cached Collider Info": "dynamics",
    "Softness to Compliance": "dynamics",
    "Store Bend Rotation": "dynamics",
    "Store Edge Length": "dynamics",
    "Store Segment Length": "dynamics",
    "Store Segment Rotation": "dynamics",
    "String to List": "dynamics",
    "Tearing Effector": "dynamics",
    "Thin Rod Moment of Inertia": "dynamics",
    "XPBD Simulation": "dynamics",
    "XPBD Solver": "dynamics",

    # Compositing Essentials
    "Cheap Blur 2.001": "compositing",
    "Chromatic Aberration": "compositing",
    "Film Grain": "compositing",
    "Retime": "compositing",
    "Rounded Square Mask": "compositing",
    "Sensor Noise": "compositing",
    "Sepia": "compositing",
    "Split Toning": "compositing",
    "Tune Image": "compositing",
    "Unsharp Mask": "compositing",
    "Vignette": "compositing",
}


def _normalize_name(name):
    """Normalize a name for comparison (e.g. 'combine_spherical' -> 'combinespherical')."""
    s = name.replace("-", " ").replace("/", " ").replace(".", " ").replace("_", " ")
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', s)
    return re.sub(r'\s+', '', s).lower()


def resolve_asset_name(name):
    """
    Resolve a user-provided name (e.g. 'combine_spherical', 'Combine Spherical', 'array')
    to its canonical asset name in KNOWN_ASSETS.
    """
    if name in KNOWN_ASSETS:
        return name

    norm_target = _normalize_name(name)
    for canonical in KNOWN_ASSETS:
        if _normalize_name(canonical) == norm_target:
            return canonical

    return None


def get_asset_library_path(library_name="essentials"):
    """
    Get the path to Blender's built-in asset library.

    Args:
        library_name: Name of the library ('essentials', 'dynamics', 'shading', 'compositing', 'hair', 'principal')

    Returns:
        Path to the library .blend file, or None if not found
    """
    blender_path = Path(bpy.app.binary_path).parent
    version_short = f"{bpy.app.version[0]}.{bpy.app.version[1]}"  # e.g., "5.2"

    filename = LIBRARY_FILENAMES.get(library_name, "geometry_nodes_essentials.blend")

    # Common search locations
    possible_paths = [
        # Portable / Local installation
        blender_path / "datafiles" / "assets" / "nodes" / filename,
        blender_path / ".." / "datafiles" / "assets" / "nodes" / filename,
        blender_path / version_short / "datafiles" / "assets" / "nodes" / filename,

        # Linux system installations - Blender 5.0+
        Path("/usr/share/blender") / version_short / "datafiles" / "assets" / "nodes" / filename,
        Path("/usr/share/blender") / "datafiles" / "assets" / "nodes" / filename,

        # Snap installations
        Path("/snap/blender/current") / version_short / "datafiles" / "assets" / "nodes" / filename,

        # Flatpak installations
        Path.home() / ".var" / "app" / "org.blender.Blender" / "data" / "blender" / version_short / "datafiles" / "assets" / "nodes" / filename,
    ]

    # Older naming fallback for essentials
    if library_name == "essentials":
        possible_paths.extend([
            blender_path / "datafiles" / "assets" / "geometry_nodes" / "essentials.blend",
            blender_path / ".." / "datafiles" / "assets" / "geometry_nodes" / "essentials.blend",
            blender_path / version_short / "datafiles" / "assets" / "geometry_nodes" / "essentials.blend",
            Path("/usr/share/blender") / version_short / "datafiles" / "assets" / "geometry_nodes" / "essentials.blend",
            Path("/usr/share/blender") / "datafiles" / "assets" / "geometry_nodes" / "essentials.blend",
            Path("/snap/blender/current") / version_short / "datafiles" / "assets" / "geometry_nodes" / "essentials.blend",
            Path.home() / ".var" / "app" / "org.blender.Blender" / "data" / "blender" / version_short / "datafiles" / "assets" / "geometry_nodes" / "essentials.blend",
        ])

    for path in possible_paths:
        try:
            resolved = path.resolve()
            if resolved.exists():
                return resolved
        except Exception:
            pass

    return None


def load_asset_node_group(asset_name):
    """
    Load a built-in asset node group into bpy.data.node_groups.

    This is called LAZILY - only when the asset is actually referenced.

    Args:
        asset_name: Name of the asset (e.g., "Combine Spherical", "Is Edge Boundary")

    Returns:
        The loaded node group, or None if loading failed
    """
    canonical_name = resolve_asset_name(asset_name) or asset_name

    # Check if already loaded
    if canonical_name in bpy.data.node_groups:
        return bpy.data.node_groups[canonical_name]

    # Check if this is a known asset
    if canonical_name not in KNOWN_ASSETS:
        return None

    # Get the asset library path
    library_name = KNOWN_ASSETS[canonical_name]
    library_path = get_asset_library_path(library_name)
    if not library_path:
        print(f"⚠️  Warning: Could not find Blender asset library for '{canonical_name}' (lib: {library_name})")
        return None

    try:
        # Append the node group from the asset library
        with bpy.data.libraries.load(str(library_path), link=False) as (data_from, data_to):
            if canonical_name in data_from.node_groups:
                data_to.node_groups = [canonical_name]
            else:
                print(f"⚠️  Warning: '{canonical_name}' not found in asset library {library_path}")
                return None

        # Get the appended node group
        if canonical_name in bpy.data.node_groups:
            print(f"✓ Loaded built-in asset: '{canonical_name}'")
            return bpy.data.node_groups[canonical_name]
        else:
            print(f"⚠️  Warning: Failed to load '{canonical_name}' from asset library")
            return None

    except Exception as e:
        print(f"⚠️  Warning: Error loading asset '{canonical_name}': {e}")
        return None


def is_known_asset(name):
    """
    Check if a name refers to a known built-in asset.

    Args:
        name: Node/group name to check

    Returns:
        True if this is a known asset, False otherwise
    """
    return resolve_asset_name(name) is not None


def try_load_asset_if_needed(name):
    """
    Try to load an asset if it's known but not yet loaded.

    This is the main entry point called by the compiler when an
    unknown node name is encountered.

    Args:
        name: Node/group name that wasn't found

    Returns:
        The node group if it's a known asset and was loaded successfully,
        None otherwise
    """
    # Already loaded under exact name?
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]

    canonical_name = resolve_asset_name(name)
    if canonical_name:
        if canonical_name in bpy.data.node_groups:
            return bpy.data.node_groups[canonical_name]
        return load_asset_node_group(canonical_name)

    return None
