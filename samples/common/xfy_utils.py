"""XNodify Sample Utilities for Blender 5.x.

Lightweight helper library providing scene setup, material creation,
and object management for procedural node samples.
"""

from __future__ import annotations
import bpy
import bmesh
from typing import Optional, Sequence


def create_mat(
    obj: Optional[bpy.types.Object] = None,
    name: str = "Material",
    color_val: Sequence[float] = (0.8, 0.8, 0.8, 1.0),
    emission_strength: float = 0.0,
    roughness: float = 0.5,
    metallic: float = 0.0,
) -> bpy.types.Material:
    """Create or retrieve a standard Principled BSDF material."""
    mat = bpy.data.materials.get(name)
    if not mat:
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            if len(color_val) == 3:
                color_val = (*color_val, 1.0)
            if "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = color_val
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = roughness
            if "Metallic" in bsdf.inputs:
                bsdf.inputs["Metallic"].default_value = metallic
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = emission_strength
            if "Emission Color" in bsdf.inputs and emission_strength > 0:
                bsdf.inputs["Emission Color"].default_value = color_val

    if obj and hasattr(obj, "data") and hasattr(obj.data, "materials"):
        if mat.name not in obj.data.materials:
            obj.data.materials.append(mat)

    return mat


def create_gp_mat(
    name: str,
    *,
    stroke: Optional[Sequence[float]] = (0.0, 0.0, 0.0, 1.0),
    fill: Optional[Sequence[float]] = (0.0, 1.0, 1.0, 1.0),
    stroke_holdout: bool = False,
    fill_holdout: bool = False,
    show_stroke: bool = False,
    show_fill: bool = True,
) -> bpy.types.Material:
    """Create or retrieve a Grease Pencil material in Blender 5.x."""
    mat = bpy.data.materials.get(name)
    if not mat:
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = False

        if hasattr(bpy.data.materials, "create_gpencil_data"):
            bpy.data.materials.create_gpencil_data(mat)

        if hasattr(mat, "grease_pencil") and mat.grease_pencil:
            gp = mat.grease_pencil
            gp.show_stroke = bool(show_stroke)
            gp.show_fill = bool(show_fill)
            if stroke:
                gp.color = stroke if len(stroke) == 4 else (*stroke, 1.0)
            if fill:
                gp.fill_color = fill if len(fill) == 4 else (*fill, 1.0)
            gp.use_stroke_holdout = bool(stroke_holdout)
            gp.use_fill_holdout = bool(fill_holdout)

    return mat


def create_obj(
    otype: str = "cube",
    co_data: Optional[Sequence] = None,
    name: str = "Object",
    size: float = 2.0,
    set_active: bool = True,
) -> bpy.types.Object:
    """Create a basic primitive object and link it to the current scene collection."""
    obj = bpy.data.objects.get(name)
    if obj:
        return obj

    mesh_data = bpy.data.meshes.new(name)
    bm = bmesh.new()

    match otype.lower():
        case "poly":
            if not co_data or len(co_data) < 2:
                co_data = [(0, 0, 0), (0, 0, 1)]
            prev_vert = bm.verts.new(co_data[0])
            for co in co_data[1:]:
                vert = bm.verts.new(co)
                bm.edges.new([prev_vert, vert])
                prev_vert = vert
        case "cube":
            bmesh.ops.create_cube(bm, size=size)
        case "grid" | "plane":
            bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=size / 2.0)
        case "ico" | "icosphere":
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=size / 2.0)
        case "uvsphere":
            bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=size / 2.0)
        case _:
            bmesh.ops.create_cube(bm, size=size)

    bm.to_mesh(mesh_data)
    bm.free()

    obj = bpy.data.objects.new(name, mesh_data)
    if bpy.context.scene.collection:
        bpy.context.scene.collection.objects.link(obj)

    if set_active:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

    return obj


def delete_obj(obj: Optional[bpy.types.Object] = None, name: Optional[str] = None):
    """Safely unlink and remove an object and its data block."""
    if not obj and name:
        obj = bpy.data.objects.get(name)
    if not obj:
        return

    try:
        if obj.name in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.unlink(obj)
    except Exception:
        pass

    data = obj.data
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass

    if data:
        try:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
            elif hasattr(bpy.types, "GreasePencil") and isinstance(data, bpy.types.GreasePencil):
                bpy.data.grease_pencils.remove(data)
        except Exception:
            pass


def clear_scene(keep_camera_and_light: bool = True):
    """Remove scene mesh and curve objects, leaving studio camera/light if requested."""
    for obj in list(bpy.context.scene.objects):
        if keep_camera_and_light and obj.type in {"CAMERA", "LIGHT"}:
            continue
        delete_obj(obj)


def setup_studio_lighting(energy: float = 1000.0):
    """Ensure a standard key light is present and configured."""
    light = bpy.data.objects.get("Light")
    if not light:
        light_data = bpy.data.lights.new("Light", type="POINT")
        light = bpy.data.objects.new("Light", light_data)
        bpy.context.scene.collection.objects.link(light)

    light.location = (4.0, -4.0, 6.0)
    light.data.energy = energy


def set_viewport_shading(shading_type: str = "MATERIAL"):
    """Set the 3D viewport shading to MATERIAL or RENDERED if viewport is open."""
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.type = shading_type
