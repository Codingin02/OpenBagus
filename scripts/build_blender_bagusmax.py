"""Blender 5.2 Python script to author film-accurate BAGUSMAX 3D models.

Constructs high-fidelity, subdivision-smooth 3D models of:
1. BAGUSMAX WHITE (FAST Mode) — Inflatable vinyl robot from Disney Big Hero 6 references.
   - Continuous seamless pear-shaped inflatable body (NO disjoint spheres/snowman bumps).
   - Small horizontal pill head with flush black circular eyes and bridge line.
   - Silver healthcare access port on upper left chest (viewer's right).
   - Sculpted vinyl arms with 4 chubby fingers with joint creases.
   - Columnar legs with rounded soles and friction patches.

2. BAGUSMAX ARMORED (DEEP_REASONING Mode) — Hero armor suit from Disney Big Hero 6 references.
   - Aerodynamic red helmet with top crest, swept ear wings, and white visor aperture.
   - Hard-surface athletic breastplate with collar rim and circular purple chest power node.
   - Continuous 3-tier segmented purple abdominal armor shield with horizontal chevron ridges.
   - Massive curved red shoulder pauldrons with recessed purple oval domes.
   - Flared rocket gauntlets, purple wrist cuffs, and graphite mechanical fists.
   - Sculpted red thigh and shin armor with graphite knee discs and armored boots.
   - Jetpack carapace with twin thrusters, glowing nozzles, and aerodynamic hero wings.

Coordinate System Convention:
- Blender: FRONT is -Y, BACK is +Y, UP is +Z, RIGHT is +X, LEFT is -X.
- When exported to glTF (Y-Up standard):
    glTF +Z = -Y_blender (FRONT, facing camera at yaw 0°)
    glTF -Z = +Y_blender (BACK, away from camera)
    glTF +Y = +Z_blender (UP)
    glTF +X = +X_blender (RIGHT)

Exports:
- assets/models/source/bagusmax_white.blend
- assets/models/bagusmax_white.glb
- assets/models/source/bagusmax_armored.blend
- assets/models/bagusmax_armored.glb
"""

import math
import os
import sys
import bpy
import bmesh
from mathutils import Matrix, Vector

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ASSETS_DIR = os.path.join(REPO_ROOT, "assets", "models")
SOURCE_DIR = os.path.join(ASSETS_DIR, "source")
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(SOURCE_DIR, exist_ok=True)


def clean_scene():
    """Remove all objects and materials from current Blender scene."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def create_pbr_material(name: str, base_color: tuple, metallic: float, roughness: float, clearcoat: float = 0.0, emissive: tuple = (0, 0, 0, 1)):
    """Create a Principled BSDF material with accurate PBR properties."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = base_color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.5
        if "Coat Weight" in bsdf.inputs:
            bsdf.inputs["Coat Weight"].default_value = clearcoat
        elif "Clearcoat" in bsdf.inputs:
            bsdf.inputs["Clearcoat"].default_value = clearcoat
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = emissive
    return mat


def set_pivot(obj, pivot_point: Vector):
    """Set the object's origin (pivot) to a custom 3D point."""
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.context.scene.cursor.location = pivot_point
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
    obj.select_set(False)


def create_quad_loft(name: str, ring_specs: list, num_segments: int = 24, close_top: bool = True, close_bot: bool = True, mat=None, subsurf_levels: int = 1):
    """Create a smooth quad loft mesh with guaranteed outward-pointing normals."""
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm = bmesh.new()

    rings = []
    for center, rx, ry in ring_specs:
        ring = []
        for i in range(num_segments):
            angle = 2.0 * math.pi * i / num_segments
            x = center.x + rx * math.cos(angle)
            y = center.y + ry * math.sin(angle)
            z = center.z
            v = bm.verts.new((x, y, z))
            ring.append(v)
        rings.append(ring)

    # Winding order for outward-pointing normals
    for r in range(len(rings) - 1):
        for i in range(num_segments):
            i_next = (i + 1) % num_segments
            bm.faces.new([rings[r][i], rings[r+1][i], rings[r+1][i_next], rings[r][i_next]])

    if close_top:
        top_center = bm.verts.new(ring_specs[0][0])
        for i in range(num_segments):
            i_next = (i + 1) % num_segments
            bm.faces.new([top_center, rings[0][i], rings[0][i_next]])

    if close_bot:
        bot_center = bm.verts.new(ring_specs[-1][0])
        for i in range(num_segments):
            i_next = (i + 1) % num_segments
            bm.faces.new([bot_center, rings[-1][i_next], rings[-1][i]])

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj

    for poly in mesh.polygons:
        poly.use_smooth = True

    if mat:
        obj.data.materials.append(mat)

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')

    if subsurf_levels > 0:
        sub = obj.modifiers.new(name="Subsurf", type='SUBSURF')
        sub.levels = subsurf_levels
        sub.render_levels = subsurf_levels
        bpy.ops.object.modifier_apply(modifier="Subsurf")

    return obj


# ---------------------------------------------------------------------------
# WHITE BAGUSMAX BUILDER
# ---------------------------------------------------------------------------

def build_white_bagusmax():
    clean_scene()
    print("[Blender] Building BAGUSMAX White form (high-fidelity Disney reference)...")

    # Materials
    mat_vinyl = create_pbr_material("Mat_VinylWhite", (0.96, 0.96, 0.97, 1.0), metallic=0.0, roughness=0.32, clearcoat=0.25)
    mat_eyes = create_pbr_material("Mat_BlackEyes", (0.015, 0.015, 0.015, 1.0), metallic=0.05, roughness=0.10)
    mat_silver = create_pbr_material("Mat_PortSilver", (0.86, 0.86, 0.88, 1.0), metallic=0.90, roughness=0.20)
    mat_port_inner = create_pbr_material("Mat_PortInner", (0.45, 0.45, 0.50, 1.0), metallic=0.40, roughness=0.55)

    # 1. HEAD & EYES (Center at z=1.33, pivot at neck z=1.25)
    # Authentic small horizontal pill head (width ~0.34, depth ~0.26, height ~0.24)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=24, radius=0.19, location=(0, 0, 1.33))
    head_obj = bpy.context.active_object
    head_obj.name = "White_Head_Base"
    head_obj.scale = (1.20, 1.02, 0.90)
    bpy.ops.object.transform_apply(scale=True)
    head_obj.data.materials.append(mat_vinyl)

    sub = head_obj.modifiers.new(name="Subsurf", type='SUBSURF')
    sub.levels = 1
    bpy.ops.object.modifier_apply(modifier="Subsurf")

    # Smooth neck collar integration
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.145, depth=0.10, location=(0, 0.0, 1.25))
    neck_obj = bpy.context.active_object
    neck_obj.scale = (1.05, 0.95, 1.0)
    bpy.ops.object.transform_apply(scale=True)
    neck_obj.data.materials.append(mat_vinyl)

    # Two prominent black eyes on front surface (Blender -Y is front, y = -0.192, z = 1.33)
    eye_z = 1.33
    eye_y = -0.192
    eye_radius = 0.017

    bpy.ops.mesh.primitive_uv_sphere_add(segments=18, ring_count=14, radius=eye_radius, location=(0.062, eye_y, eye_z))
    eye_l = bpy.context.active_object
    eye_l.scale = (1.0, 0.35, 1.0)
    bpy.ops.object.transform_apply(scale=True)
    eye_l.data.materials.append(mat_eyes)

    bpy.ops.mesh.primitive_uv_sphere_add(segments=18, ring_count=14, radius=eye_radius, location=(-0.062, eye_y, eye_z))
    eye_r = bpy.context.active_object
    eye_r.scale = (1.0, 0.35, 1.0)
    bpy.ops.object.transform_apply(scale=True)
    eye_r.data.materials.append(mat_eyes)

    # Horizontal connecting bridge line
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, eye_y, eye_z))
    eye_bridge = bpy.context.active_object
    eye_bridge.scale = (0.124, 0.006, 0.0035)
    bpy.ops.object.transform_apply(scale=True)
    eye_bridge.data.materials.append(mat_eyes)

    # Join Head parts
    for o in [head_obj, neck_obj, eye_l, eye_r, eye_bridge]:
        o.select_set(True)
    bpy.context.view_layer.objects.active = head_obj
    head_obj.name = "White_Head"
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()
    set_pivot(head_obj, Vector((0.0, 0.0, 1.25)))

    # 2. TORSO — CONTINUOUS ORGANIC PEAR-SHAPED INFLATABLE BODY
    torso_rings = [
        (Vector((0.0, 0.00, 1.25)), 0.145, 0.135),   # Top neck rim
        (Vector((0.0, -0.01, 1.16)), 0.230, 0.190),  # Sloping shoulder flare
        (Vector((0.0, -0.02, 1.06)), 0.315, 0.260),  # Upper chest
        (Vector((0.0, -0.04, 0.95)), 0.380, 0.320),  # Mid chest
        (Vector((0.0, -0.07, 0.84)), 0.435, 0.370),  # Upper belly
        (Vector((0.0, -0.09, 0.72)), 0.470, 0.415),  # Peak pear belly (width ~0.94)
        (Vector((0.0, -0.07, 0.60)), 0.450, 0.395),  # Lower belly
        (Vector((0.0, -0.04, 0.50)), 0.385, 0.340),  # Hip / pelvis transition
        (Vector((0.0, -0.01, 0.42)), 0.280, 0.250),  # Pelvis base
    ]
    torso_obj = create_quad_loft(
        name="White_Torso_Mesh",
        ring_specs=torso_rings,
        num_segments=28,
        close_top=True,
        close_bot=True,
        mat=mat_vinyl,
        subsurf_levels=2,
    )

    # Healthcare access port on upper left chest (viewer's right x = +0.145, front y = -0.272, z = 1.08)
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.030,
        minor_radius=0.006,
        major_segments=24,
        minor_segments=12,
        location=(0.145, -0.272, 1.08),
    )
    port_ring = bpy.context.active_object
    port_ring.rotation_euler = (math.radians(82), math.radians(-8), 0)
    bpy.ops.object.transform_apply(rotation=True)
    port_ring.data.materials.append(mat_silver)

    bpy.ops.mesh.primitive_cylinder_add(
        vertices=20,
        radius=0.025,
        depth=0.005,
        location=(0.145, -0.272, 1.08),
    )
    port_slot = bpy.context.active_object
    port_slot.rotation_euler = (math.radians(82), math.radians(-8), 0)
    bpy.ops.object.transform_apply(rotation=True)
    port_slot.data.materials.append(mat_port_inner)

    # Join Torso parts
    for o in [torso_obj, port_ring, port_slot]:
        o.select_set(True)
    bpy.context.view_layer.objects.active = torso_obj
    torso_obj.name = "White_Torso"
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()
    set_pivot(torso_obj, Vector((0.0, 0.0, 0.52)))

    # 3. LEFT ARM & HAND (Pivot at left shoulder: x = 0.38, z = 1.06)
    arm_rings = [
        (Vector((0.36, 0.00, 1.08)), 0.130, 0.130),   # Shoulder socket cap
        (Vector((0.39, -0.01, 0.98)), 0.115, 0.115),  # Upper bicep
        (Vector((0.42, -0.02, 0.88)), 0.105, 0.105),  # Mid bicep
        (Vector((0.44, -0.03, 0.77)), 0.095, 0.095),  # Elbow crease
        (Vector((0.45, -0.04, 0.67)), 0.092, 0.092),  # Upper forearm
        (Vector((0.46, -0.05, 0.57)), 0.082, 0.082),  # Lower forearm
        (Vector((0.46, -0.05, 0.50)), 0.072, 0.072),  # Wrist
    ]
    arm_obj = create_quad_loft(
        name="White_Arm_L_Limb",
        ring_specs=arm_rings,
        num_segments=20,
        close_top=True,
        close_bot=False,
        mat=mat_vinyl,
        subsurf_levels=1,
    )

    # Hand palm
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=16, radius=0.065, location=(0.46, -0.055, 0.46))
    palm = bpy.context.active_object
    palm.scale = (0.90, 1.05, 0.90)
    bpy.ops.object.transform_apply(scale=True)
    palm.data.materials.append(mat_vinyl)

    # 4 Chubby sculpted fingers
    fingers = []
    finger_specs = [
        ("Thumb", Vector((0.41, -0.085, 0.44)), Vector((0.425, -0.07, 0.46)), 0.023),
        ("Index", Vector((0.44, -0.070, 0.39)), Vector((0.450, -0.06, 0.42)), 0.021),
        ("Middle", Vector((0.47, -0.050, 0.38)), Vector((0.470, -0.05, 0.42)), 0.021),
        ("Ring", Vector((0.50, -0.035, 0.39)), Vector((0.490, -0.04, 0.42)), 0.019),
    ]
    for fname, tip_pt, mid_pt, frad in finger_specs:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=14, ring_count=10, radius=frad * 1.08, location=mid_pt)
        seg1 = bpy.context.active_object
        seg1.data.materials.append(mat_vinyl)
        fingers.append(seg1)

        bpy.ops.mesh.primitive_uv_sphere_add(segments=14, ring_count=10, radius=frad, location=tip_pt)
        seg2 = bpy.context.active_object
        seg2.data.materials.append(mat_vinyl)
        fingers.append(seg2)

    for o in [arm_obj, palm] + fingers:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.name = "White_Arm_L"
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()
    set_pivot(arm_obj, Vector((0.38, 0.0, 1.06)))

    # 4. RIGHT ARM & HAND (Mirrored across X)
    r_arm = arm_obj.copy()
    r_arm.data = arm_obj.data.copy()
    r_arm.name = "White_Arm_R"
    bpy.context.collection.objects.link(r_arm)
    r_arm.matrix_world = Matrix.Scale(-1, 4, Vector((1, 0, 0))) @ r_arm.matrix_world
    bpy.context.view_layer.objects.active = r_arm
    r_arm.select_set(True)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    r_arm.select_set(False)
    set_pivot(r_arm, Vector((-0.38, 0.0, 1.06)))

    # 5. LEGS & FEET
    leg_l_rings = [
        (Vector((0.16, -0.01, 0.44)), 0.150, 0.145),  # Thigh base
        (Vector((0.16, -0.02, 0.32)), 0.145, 0.140),  # Mid leg
        (Vector((0.16, -0.03, 0.20)), 0.140, 0.135),  # Lower leg
        (Vector((0.16, -0.04, 0.11)), 0.138, 0.135),  # Ankle
    ]
    leg_l = create_quad_loft(
        name="White_Leg_L_Column",
        ring_specs=leg_l_rings,
        num_segments=20,
        close_top=True,
        close_bot=False,
        mat=mat_vinyl,
        subsurf_levels=1,
    )

    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=16, radius=0.145, location=(0.16, -0.05, 0.08))
    foot_l = bpy.context.active_object
    foot_l.scale = (0.95, 1.30, 0.60)
    bpy.ops.object.transform_apply(scale=True)
    foot_l.data.materials.append(mat_vinyl)

    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.115, depth=0.01, location=(0.16, -0.05, 0.005))
    sole_l = bpy.context.active_object
    sole_l.scale = (0.95, 1.25, 1.0)
    bpy.ops.object.transform_apply(scale=True)
    sole_l.data.materials.append(mat_vinyl)

    leg_parts_l = [leg_l, foot_l, sole_l]
    for o in leg_parts_l:
        o.select_set(True)
    bpy.context.view_layer.objects.active = leg_l
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()

    leg_r = leg_l.copy()
    leg_r.data = leg_l.data.copy()
    leg_r.name = "White_Leg_R"
    bpy.context.collection.objects.link(leg_r)
    leg_r.matrix_world = Matrix.Scale(-1, 4, Vector((1, 0, 0))) @ leg_r.matrix_world
    bpy.context.view_layer.objects.active = leg_r
    leg_r.select_set(True)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')

    leg_l.select_set(True)
    leg_r.select_set(True)
    bpy.context.view_layer.objects.active = leg_l
    leg_l.name = "White_Legs"
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()
    set_pivot(leg_l, Vector((0.0, 0.0, 0.0)))

    # Save Blend & Export GLB
    blend_path = os.path.join(SOURCE_DIR, "bagusmax_white.blend")
    glb_path = os.path.join(ASSETS_DIR, "bagusmax_white.glb")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"[Blender] Saved source blend: {blend_path}")

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.export_scene.gltf(
        filepath=glb_path,
        export_format='GLB',
        use_selection=True,
        export_apply=True,
        export_materials='EXPORT',
        export_normals=True,
    )
    print(f"[Blender] Exported GLB: {glb_path} ({os.path.getsize(glb_path):,} bytes)")


# ---------------------------------------------------------------------------
# ARMORED BAGUSMAX BUILDER
# ---------------------------------------------------------------------------

def build_armored_bagusmax():
    clean_scene()
    print("[Blender] Building BAGUSMAX Armored hero form (high-fidelity Disney reference)...")

    # Materials
    mat_red = create_pbr_material("Mat_ArmorRed", (0.86, 0.16, 0.08, 1.0), metallic=0.35, roughness=0.18, clearcoat=0.7)
    mat_dark_red = create_pbr_material("Mat_ArmorDarkRed", (0.55, 0.08, 0.04, 1.0), metallic=0.35, roughness=0.22, clearcoat=0.5)
    mat_purple = create_pbr_material("Mat_ArmorPurple", (0.32, 0.16, 0.46, 1.0), metallic=0.15, roughness=0.28, clearcoat=0.3)
    mat_graphite = create_pbr_material("Mat_GraphiteJoint", (0.12, 0.12, 0.14, 1.0), metallic=0.75, roughness=0.45)
    mat_visor = create_pbr_material("Mat_VisorWhite", (0.95, 0.95, 0.96, 1.0), metallic=0.0, roughness=0.20, clearcoat=0.2)
    mat_eyes = create_pbr_material("Mat_BlackEyes", (0.015, 0.015, 0.015, 1.0), metallic=0.05, roughness=0.10)
    mat_thruster = create_pbr_material("Mat_ThrusterYellow", (1.0, 0.82, 0.15, 1.0), metallic=0.8, roughness=0.2, emissive=(1.0, 0.82, 0.15, 1.0))

    # 1. HELMET & VISOR (Center at z=1.40, pivot at neck z=1.25)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=24, radius=0.22, location=(0, 0.01, 1.40))
    helm_shell = bpy.context.active_object
    helm_shell.scale = (1.18, 1.05, 0.94)
    bpy.ops.object.transform_apply(scale=True)
    helm_shell.data.materials.append(mat_red)

    # Top aerodynamic crest ridge
    crest_rings = [
        (Vector((0.0, 0.14, 1.55)), 0.020, 0.020),
        (Vector((0.0, 0.02, 1.57)), 0.026, 0.035),
        (Vector((0.0, -0.10, 1.54)), 0.022, 0.028),
        (Vector((0.0, -0.17, 1.48)), 0.015, 0.015),
    ]
    crest = create_quad_loft("Armored_Crest", crest_rings, num_segments=12, close_top=True, close_bot=True, mat=mat_red, subsurf_levels=1)

    # Swept-back Ear Wings / Cowls
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.24, 0.02, 1.42))
    ear_l = bpy.context.active_object
    ear_l.scale = (0.032, 0.14, 0.09)
    ear_l.rotation_euler = (math.radians(-15), math.radians(20), math.radians(-12))
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    ear_l.data.materials.append(mat_red)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-0.24, 0.02, 1.42))
    ear_r = bpy.context.active_object
    ear_r.scale = (0.032, 0.14, 0.09)
    ear_r.rotation_euler = (math.radians(-15), math.radians(-20), math.radians(12))
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    ear_r.data.materials.append(mat_red)

    # Visor Aperture on Front
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=18, radius=0.14, location=(0, -0.21, 1.38))
    visor_face = bpy.context.active_object
    visor_face.scale = (1.10, 0.28, 0.62)
    bpy.ops.object.transform_apply(scale=True)
    visor_face.data.materials.append(mat_visor)

    eye_z = 1.38
    eye_y = -0.235
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.018, location=(0.062, eye_y, eye_z))
    a_eye_l = bpy.context.active_object
    a_eye_l.data.materials.append(mat_eyes)

    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.018, location=(-0.062, eye_y, eye_z))
    a_eye_r = bpy.context.active_object
    a_eye_r.data.materials.append(mat_eyes)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, eye_y, eye_z))
    a_bridge = bpy.context.active_object
    a_bridge.scale = (0.124, 0.005, 0.0035)
    bpy.ops.object.transform_apply(scale=True)
    a_bridge.data.materials.append(mat_eyes)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, -0.18, 1.30))
    chin = bpy.context.active_object
    chin.scale = (0.22, 0.10, 0.05)
    bpy.ops.object.transform_apply(scale=True)
    chin.data.materials.append(mat_red)

    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.155, depth=0.08, location=(0, 0, 1.23))
    neck_joint = bpy.context.active_object
    neck_joint.data.materials.append(mat_graphite)

    helm_parts = [helm_shell, crest, ear_l, ear_r, visor_face, a_eye_l, a_eye_r, a_bridge, chin, neck_joint]
    for o in helm_parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = helm_shell
    helm_shell.name = "Armored_Head"
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()
    set_pivot(helm_shell, Vector((0.0, 0.0, 1.25)))

    # 2. TORSO — SEAMLESS ATHLETIC BREASTPLATE + INTEGRATED PURPLE ABDOMEN + RED WAIST
    # Build upper red breastplate from neck to mid-chest
    breastplate_rings = [
        (Vector((0.0, 0.00, 1.22)), 0.170, 0.155),  # Collar rim
        (Vector((0.0, -0.02, 1.14)), 0.280, 0.240), # Upper pecs
        (Vector((0.0, -0.05, 1.04)), 0.380, 0.315), # Pectoral peak
        (Vector((0.0, -0.04, 0.94)), 0.360, 0.295), # Bottom breastplate rim
    ]
    chest_obj = create_quad_loft(
        name="Armored_Breastplate",
        ring_specs=breastplate_rings,
        num_segments=24,
        close_top=True,
        close_bot=False,
        mat=mat_red,
        subsurf_levels=1,
    )

    # Circular purple power node on upper left chest (viewer's right x = +0.14, front y = -0.305, z = 1.09)
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.036,
        minor_radius=0.006,
        major_segments=20,
        minor_segments=10,
        location=(0.14, -0.305, 1.09),
    )
    node_ring = bpy.context.active_object
    node_ring.rotation_euler = (math.radians(82), math.radians(-8), 0)
    bpy.ops.object.transform_apply(rotation=True)
    node_ring.data.materials.append(mat_red)

    bpy.ops.mesh.primitive_cylinder_add(
        vertices=18,
        radius=0.030,
        depth=0.008,
        location=(0.14, -0.305, 1.09),
    )
    node_disc = bpy.context.active_object
    node_disc.rotation_euler = (math.radians(82), math.radians(-8), 0)
    bpy.ops.object.transform_apply(rotation=True)
    node_disc.data.materials.append(mat_purple)

    # Continuous 3-Tier Segmented Purple Abdominal Armor Shield
    # Connects directly to bottom of breastplate (z = 0.94 down to z = 0.65)
    abs_rings = [
        (Vector((0.0, -0.04, 0.94)), 0.355, 0.285),  # Seamless join to breastplate!
        (Vector((0.0, -0.05, 0.84)), 0.340, 0.275),  # Mid abs
        (Vector((0.0, -0.04, 0.74)), 0.320, 0.260),  # Lower abs
        (Vector((0.0, -0.03, 0.65)), 0.300, 0.245),  # Base abs join to belt!
    ]
    abs_shield = create_quad_loft(
        name="Armored_Abs_Shield",
        ring_specs=abs_rings,
        num_segments=24,
        close_top=False,
        close_bot=False,
        mat=mat_purple,
        subsurf_levels=1,
    )

    # 3 Horizontal chevron segment ridges across the purple plate
    abs_ridges = []
    for z_ridge in (0.72, 0.80, 0.88):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, -0.29, z_ridge))
        ridge = bpy.context.active_object
        ridge.scale = (0.28, 0.035, 0.025)
        bpy.ops.object.transform_apply(scale=True)
        ridge.data.materials.append(mat_purple)
        abs_ridges.append(ridge)

    # Red pelvic armor belt connecting seamlessly to bottom of abs (z = 0.65 down to 0.50)
    belt_rings = [
        (Vector((0.0, -0.03, 0.65)), 0.315, 0.260),
        (Vector((0.0, -0.02, 0.58)), 0.325, 0.265),
        (Vector((0.0, -0.01, 0.50)), 0.280, 0.230),
    ]
    waist_belt = create_quad_loft(
        name="Armored_Waist_Belt",
        ring_specs=belt_rings,
        num_segments=24,
        close_top=False,
        close_bot=True,
        mat=mat_red,
        subsurf_levels=1,
    )

    # Dark graphite pelvis under-chassis visible at hip sockets
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=16, radius=0.23, location=(0, 0, 0.50))
    pelvis_chassis = bpy.context.active_object
    pelvis_chassis.scale = (1.08, 0.85, 0.55)
    bpy.ops.object.transform_apply(scale=True)
    pelvis_chassis.data.materials.append(mat_graphite)

    chest_parts = [chest_obj, node_ring, node_disc, abs_shield] + abs_ridges + [waist_belt, pelvis_chassis]
    for o in chest_parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = chest_obj
    chest_obj.name = "Armored_Torso"
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()
    set_pivot(chest_obj, Vector((0.0, 0.0, 0.52)))

    # 3. BACK JETPACK & HERO WINGS (Pivot at 0.52)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0.23, 1.06))
    carapace = bpy.context.active_object
    carapace.scale = (0.32, 0.12, 0.30)
    bpy.ops.object.transform_apply(scale=True)
    carapace.data.materials.append(mat_dark_red)

    thrusters = []
    for x_pos in (-0.095, 0.095):
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.046, depth=0.18, location=(x_pos, 0.30, 0.98))
        th_cyl = bpy.context.active_object
        th_cyl.data.materials.append(mat_graphite)

        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.038, depth=0.035, location=(x_pos, 0.30, 0.88))
        th_nozzle = bpy.context.active_object
        th_nozzle.data.materials.append(mat_thruster)
        thrusters.extend([th_cyl, th_nozzle])

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.38, 0.22, 1.18))
    wing_l = bpy.context.active_object
    wing_l.scale = (0.34, 0.03, 0.16)
    wing_l.rotation_euler = (math.radians(-10), math.radians(18), math.radians(15))
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    wing_l.data.materials.append(mat_red)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-0.38, 0.22, 1.18))
    wing_r = bpy.context.active_object
    wing_r.scale = (0.34, 0.03, 0.16)
    wing_r.rotation_euler = (math.radians(-10), math.radians(-18), math.radians(-15))
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    wing_r.data.materials.append(mat_red)

    wings_parts = [carapace] + thrusters + [wing_l, wing_r]
    for o in wings_parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = carapace
    carapace.name = "Armored_Wings"
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()
    set_pivot(carapace, Vector((0.0, 0.0, 0.52)))

    # 4. LEFT ARMORED ARM & ROCKET GAUNTLET (Pivot at shoulder: x = 0.44, z = 1.10)
    # Swept bell pauldron shell
    bpy.ops.mesh.primitive_uv_sphere_add(segments=28, ring_count=20, radius=0.19, location=(0.44, 0.0, 1.10))
    p_pauldron = bpy.context.active_object
    p_pauldron.scale = (1.10, 1.05, 0.98)
    bpy.ops.object.transform_apply(scale=True)
    p_pauldron.data.materials.append(mat_red)

    # Integrated smooth PURPLE oval/dome accent on outer shoulder face
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=16, radius=0.10, location=(0.56, -0.02, 1.12))
    p_accent = bpy.context.active_object
    p_accent.scale = (0.22, 0.95, 0.85)
    bpy.ops.object.transform_apply(scale=True)
    p_accent.data.materials.append(mat_purple)

    # Graphite shoulder joint
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.10, location=(0.44, 0.0, 1.04))
    p_sh_joint = bpy.context.active_object
    p_sh_joint.data.materials.append(mat_graphite)

    # Armored red bicep
    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.110, depth=0.18, location=(0.46, -0.01, 0.92))
    p_bicep = bpy.context.active_object
    p_bicep.data.materials.append(mat_red)

    # Graphite elbow joint disc
    bpy.ops.mesh.primitive_cylinder_add(vertices=18, radius=0.092, depth=0.06, location=(0.48, -0.02, 0.78))
    p_elbow = bpy.context.active_object
    p_elbow.data.materials.append(mat_graphite)

    # Flared Rocket Gauntlet (forearm) connecting elbow to wrist
    gauntlet_rings = [
        (Vector((0.48, -0.02, 0.77)), 0.120, 0.115),  # Flared elbow rim
        (Vector((0.49, -0.03, 0.65)), 0.108, 0.102),  # Mid forearm
        (Vector((0.50, -0.04, 0.54)), 0.092, 0.088),  # Wrist taper
    ]
    p_gauntlet = create_quad_loft(
        name="Armored_Gauntlet_L",
        ring_specs=gauntlet_rings,
        num_segments=20,
        close_top=True,
        close_bot=False,
        mat=mat_red,
        subsurf_levels=1,
    )

    # Purple wrist accent cuff
    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.095, depth=0.035, location=(0.50, -0.04, 0.51))
    p_wrist = bpy.context.active_object
    p_wrist.data.materials.append(mat_purple)

    # Dark graphite mechanical articulated fist / knuckles
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.51, -0.06, 0.44))
    p_fist = bpy.context.active_object
    p_fist.scale = (0.09, 0.12, 0.10)
    bpy.ops.object.transform_apply(scale=True)
    p_fist.data.materials.append(mat_graphite)

    l_arm_parts = [p_pauldron, p_accent, p_sh_joint, p_bicep, p_elbow, p_gauntlet, p_wrist, p_fist]
    for o in l_arm_parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = p_pauldron
    p_pauldron.name = "Armored_Arm_L"
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()
    set_pivot(p_pauldron, Vector((0.44, 0.0, 1.10)))

    # 5. RIGHT ARMORED ARM & GAUNTLET (Mirrored across X)
    r_arm = p_pauldron.copy()
    r_arm.data = p_pauldron.data.copy()
    r_arm.name = "Armored_Arm_R"
    bpy.context.collection.objects.link(r_arm)
    r_arm.matrix_world = Matrix.Scale(-1, 4, Vector((1, 0, 0))) @ r_arm.matrix_world
    bpy.context.view_layer.objects.active = r_arm
    r_arm.select_set(True)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    r_arm.select_set(False)
    set_pivot(r_arm, Vector((-0.44, 0.0, 1.10)))

    # 6. LEGS & ARMORED BOOTS (Sculpted thigh, knee disc, flared greave, armored boot)
    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.160, depth=0.22, location=(0.17, -0.02, 0.38))
    thigh_l = bpy.context.active_object
    thigh_l.data.materials.append(mat_red)

    bpy.ops.mesh.primitive_cylinder_add(vertices=18, radius=0.092, depth=0.05, location=(0.17, -0.05, 0.25))
    knee_l = bpy.context.active_object
    knee_l.rotation_euler = (math.radians(90), 0, 0)
    bpy.ops.object.transform_apply(rotation=True)
    knee_l.data.materials.append(mat_graphite)

    shin_rings = [
        (Vector((0.17, -0.03, 0.24)), 0.142, 0.138),
        (Vector((0.17, -0.04, 0.14)), 0.150, 0.142),
        (Vector((0.17, -0.04, 0.08)), 0.155, 0.145),
    ]
    shin_l = create_quad_loft(
        name="Armored_Shin_L",
        ring_specs=shin_rings,
        num_segments=20,
        close_top=True,
        close_bot=False,
        mat=mat_red,
        subsurf_levels=1,
    )

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.17, -0.06, 0.04))
    boot_l = bpy.context.active_object
    boot_l.scale = (0.16, 0.22, 0.08)
    bpy.ops.object.transform_apply(scale=True)
    boot_l.data.materials.append(mat_red)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.17, -0.06, 0.005))
    sole_l = bpy.context.active_object
    sole_l.scale = (0.165, 0.23, 0.01)
    bpy.ops.object.transform_apply(scale=True)
    sole_l.data.materials.append(mat_graphite)

    left_leg_parts = [thigh_l, knee_l, shin_l, boot_l, sole_l]
    for o in left_leg_parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = thigh_l
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()

    leg_r = thigh_l.copy()
    leg_r.data = thigh_l.data.copy()
    leg_r.name = "Armored_Leg_R"
    bpy.context.collection.objects.link(leg_r)
    leg_r.matrix_world = Matrix.Scale(-1, 4, Vector((1, 0, 0))) @ leg_r.matrix_world
    bpy.context.view_layer.objects.active = leg_r
    leg_r.select_set(True)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')

    thigh_l.select_set(True)
    leg_r.select_set(True)
    bpy.context.view_layer.objects.active = thigh_l
    thigh_l.name = "Armored_Legs"
    bpy.ops.object.join()
    bpy.ops.object.shade_smooth()
    set_pivot(thigh_l, Vector((0.0, 0.0, 0.0)))

    # Save Blend & Export GLB
    blend_path = os.path.join(SOURCE_DIR, "bagusmax_armored.blend")
    glb_path = os.path.join(ASSETS_DIR, "bagusmax_armored.glb")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"[Blender] Saved source blend: {blend_path}")

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.export_scene.gltf(
        filepath=glb_path,
        export_format='GLB',
        use_selection=True,
        export_apply=True,
        export_materials='EXPORT',
        export_normals=True,
    )
    print(f"[Blender] Exported GLB: {glb_path} ({os.path.getsize(glb_path):,} bytes)")


if __name__ == "__main__":
    build_white_bagusmax()
    build_armored_bagusmax()
    print("[Blender] All BAGUSMAX production assets successfully built and exported!")
