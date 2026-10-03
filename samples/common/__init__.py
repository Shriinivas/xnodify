"""XNodify Samples Common Utilities.
Provides reusable Python helpers for sample setup, materials, and scene management.
"""

from .xfy_utils import (
    create_mat,
    create_gp_mat,
    create_obj,
    delete_obj,
    clear_scene,
    setup_studio_lighting,
    set_viewport_shading,
)

__all__ = [
    "create_mat",
    "create_gp_mat",
    "create_obj",
    "delete_obj",
    "clear_scene",
    "setup_studio_lighting",
    "set_viewport_shading",
]
