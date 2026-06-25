"""
Helpers for changing DEFORM materials programmatically.

The DEFORM API manual lists two practical material workflows:

1. Replace the material definition currently assigned to the workpiece by
   importing a material from the system or user material library.
2. Assign an existing material object/name/number to a DEFORM object.

This module keeps those calls isolated from the main runner so material changes
can be controlled through config without cluttering the hit loop.
"""

from deformModel import defModel


VALID_MATERIAL_SOURCES = {"system_library", "user_library", "key", "db", "assign"}


def is_material_change_enabled(config):
    """Return True when the run config requests a programmatic material change."""
    return bool(config.get("change_material", False))


def _get_target_object(object_name):
    """Return the target object, falling back to object number 1 for Workpiece."""
    try:
        return defModel.getObj(object_name)
    except Exception:
        if object_name == "Workpiece":
            return defModel.getObjByNo(1)
        raise


def _get_or_add_material(material_name):
    """Return an existing material by name, adding it if needed."""
    try:
        return defModel.getMat(material_name)
    except Exception:
        defModel.addMat(material_name)
        return defModel.getMat(material_name)


def replace_dominant_material(
    object_name="Workpiece",
    material_name="",
    material_source="system_library",
    system_material_library_dir="",
    user_material_library_dir="",
):
    """Replace the target object's dominant material definition.

    This follows the DEFORM manual's "Replace Material" use case:

    - get the workpiece object
    - get its dominant material number
    - get the corresponding DeformMaterial object
    - import a material definition into that DeformMaterial

    Parameters
    ----------
    object_name : str
        DEFORM object whose dominant material should be replaced.
    material_name : str
        Material name in the selected library, key file, or DB file.
    material_source : str
        One of: system_library, user_library, key, db.
    system_material_library_dir : str
        DEFORM system material library path used by importLib.
    user_material_library_dir : str
        User material library path used by importUsrLib.
    """
    if not material_name:
        raise ValueError("material_name is required when change_material is true.")

    source = str(material_source or "system_library").lower()
    if source not in VALID_MATERIAL_SOURCES:
        raise ValueError(
            "material_source must be one of: "
            + ", ".join(sorted(VALID_MATERIAL_SOURCES))
        )
    if source == "assign":
        raise ValueError("Use assign_material_to_object for material_source='assign'.")

    target_object = _get_target_object(object_name)
    dominant_mat_no = target_object.getDominantMatNo()
    target_material = defModel.getMatByNo(dominant_mat_no)

    if source == "system_library":
        if system_material_library_dir:
            defModel.setMatLibDir(system_material_library_dir)
        target_material.importLib(material_name)
    elif source == "user_library":
        if user_material_library_dir:
            defModel.setUsrMatLibDir(user_material_library_dir)
        target_material.importUsrLib(material_name)
    elif source == "key":
        target_material.importKey(material_name)
    elif source == "db":
        target_material.importDB(material_name)

    return {
        "object_name": object_name,
        "material_name": material_name,
        "material_source": source,
        "dominant_material_number": dominant_mat_no,
    }


def assign_material_to_object(object_name="Workpiece", material_name="", material_number=None):
    """Assign an existing material to a DEFORM object.

    Use this when the material already exists in the model and the object should
    point to it, instead of replacing the existing dominant material definition.
    """
    target_object = _get_target_object(object_name)
    if material_number is not None:
        target_object.assignMatByNo(int(material_number))
        return {
            "object_name": object_name,
            "material_number": int(material_number),
            "material_source": "assign",
        }

    if not material_name:
        raise ValueError("material_name or material_number is required for assignment.")
    target_object.assignMat(material_name)
    return {
        "object_name": object_name,
        "material_name": material_name,
        "material_source": "assign",
    }


def apply_material_from_config(config):
    """Apply the configured material change, if enabled.

    Expected config keys:

    - change_material: bool
    - material_source: system_library | user_library | key | db | assign
    - deform_material_name: name in library, key file, DB file, or model
    - material_object_name: object to modify, usually Workpiece
    - system_material_library_dir: optional path for system materials
    - user_material_library_dir: optional path for user materials
    - material_number: optional material number for assign mode
    """
    if not is_material_change_enabled(config):
        return None

    source = str(config.get("material_source", "system_library")).lower()
    object_name = config.get("material_object_name", "Workpiece")
    material_name = config.get("deform_material_name") or config.get("material", "")

    if source == "assign":
        return assign_material_to_object(
            object_name=object_name,
            material_name=material_name,
            material_number=config.get("material_number"),
        )

    return replace_dominant_material(
        object_name=object_name,
        material_name=material_name,
        material_source=source,
        system_material_library_dir=config.get("system_material_library_dir", ""),
        user_material_library_dir=config.get("user_material_library_dir", ""),
    )
