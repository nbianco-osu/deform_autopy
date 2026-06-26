from pathlib import Path

def list_deform_material_library_names(material_library_dir):
    material_library_dir = Path(material_library_dir)
    names = []

    for path in material_library_dir.rglob("*"):
        if path.is_file():
            names.append(path.stem)

    return sorted(set(names))


materials = list_deform_material_library_names(
    r"C:\Program Files\SFTC\DEFORM\v14.1.1\MaterialLibrary\Standard"
)

for name in materials:
    print(name)
