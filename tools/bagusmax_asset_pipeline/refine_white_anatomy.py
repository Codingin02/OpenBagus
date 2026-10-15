"""Refine the existing White Blender source for static anatomical review."""

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_white import ASSETS, REPORTS, material, sweep


SOURCE = ASSETS / "source/bagusmax_white_before_anatomy_refinement.blend"
REFINED = ASSETS / "source/bagusmax_white_anatomy_refined.blend"
RUNTIME = ASSETS / "runtime/bagusmax_white_anatomy_refined.glb"
REVIEW = REPORTS / "anatomy"
MESH_NAMES = (
    "White_Torso", "White_Head", "White_Arm_L", "White_Arm_R",
    "White_Leg_L", "White_Leg_R", "Eye_L", "Eye_R",
    "Eye_ContourBridge", "Chest_AccessPort",
)


def mesh_bounds(obj):
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    return [[min(p[i] for p in points) for i in range(3)],
            [max(p[i] for p in points) for i in range(3)]]


def measure():
    boxes = {name: mesh_bounds(bpy.data.objects.get(name) or
                               bpy.data.objects["Chest_Access_Port"]) for name in MESH_NAMES}
    low = [min(box[0][i] for box in boxes.values()) for i in range(3)]
    high = [max(box[1][i] for box in boxes.values()) for i in range(3)]
    height = high[2] - low[2]
    def width(name, axis):
        return round((boxes[name][1][axis]-boxes[name][0][axis])/height, 4)
    eye_centers = [(boxes[name][0][0]+boxes[name][1][0])/2 for name in ("Eye_L", "Eye_R")]
    arm_span = boxes["White_Arm_L"][1][0]-boxes["White_Arm_R"][0][0]
    return {
        "height_m": round(height, 5), "arm_span_m": round(arm_span, 5),
        "arm_span_over_H": round(arm_span/height, 4),
        "head_width_over_H": width("White_Head", 0),
        "head_height_over_H": width("White_Head", 2),
        "head_depth_over_H": width("White_Head", 1),
        "torso_height_over_H": width("White_Torso", 2),
        "torso_width_over_H": width("White_Torso", 0),
        "torso_depth_over_H": width("White_Torso", 1),
        "leg_height_over_H": width("White_Leg_L", 2),
        "leg_width_over_H": width("White_Leg_L", 0),
        "eye_spacing_over_head_width": round(abs(eye_centers[0]-eye_centers[1]) /
                                              (boxes["White_Head"][1][0]-boxes["White_Head"][0][0]), 4),
        "port_x_over_torso_width": round(((boxes["Chest_AccessPort"][0][0]+
                                            boxes["Chest_AccessPort"][1][0])/2) /
                                           (boxes["White_Torso"][1][0]-boxes["White_Torso"][0][0]), 4),
        "objects": boxes,
    }


def edit_mesh(obj, transform):
    for vertex in obj.data.vertices:
        vertex.co = transform(vertex.co.copy())
    obj.data.update()


def control_group(obj, name, predicate):
    group = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
    indices = [v.index for v in obj.data.vertices if predicate(v.co)]
    if indices:
        group.add(indices, 1.0, "REPLACE")


def smooth_wrist(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    verts = [v for v in bm.verts if .544 < v.co.z < .578 and abs(v.co.x) > .43]
    for _ in range(6):
        bmesh.ops.smooth_vert(bm, verts=verts, factor=.42, use_axis_x=True,
                              use_axis_y=True, use_axis_z=True)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def refine_torso():
    obj = bpy.data.objects["White_Torso"]
    def transform(p):
        belly = math.exp(-((p.z-.79)/.37)**2)
        lower = math.exp(-((p.z-.43)/.115)**2)
        p.x *= 1 - .055*belly + .105*lower
        if p.y < -.03:
            p.y -= (-p.y-.03)*(.075*belly)
        if p.z < .50:
            p.z += .05 * math.exp(-((p.z-.38)/.09)**2) * (1-min(1, abs(p.x)/.31))
        return p
    edit_mesh(obj, transform)
    control_group(obj, "Edit_Belly_Width", lambda p: .48 < p.z < 1.06)
    control_group(obj, "Edit_Belly_Depth", lambda p: .48 < p.z < 1.06 and p.y < 0)
    control_group(obj, "Edit_Lower_Belly", lambda p: .34 < p.z < .58)
    control_group(obj, "Edit_Chest_Contour", lambda p: 1.05 < p.z < 1.48)


def refine_head():
    def transform(p):
        p.x *= 1.06
        p.y = -.022 + (p.y+.022)*1.12
        p.z = 1.565 + (p.z-1.565)*1.055 + .006
        return p
    edit_mesh(bpy.data.objects["White_Head"], transform)
    for name in ("Eye_L", "Eye_R", "Eye_ContourBridge"):
        obj = bpy.data.objects[name]
        def face(p):
            p.x *= 1.17
            p.y = -.022 + (p.y+.022)*1.12 - .003
            p.z = 1.565 + (p.z-1.565)*1.055 + .006
            return p
        edit_mesh(obj, face)
    head = bpy.data.objects["White_Head"]
    control_group(head, "Edit_Head_Silhouette", lambda p: True)
    control_group(head, "Edit_Face_Region", lambda p: p.y < -.08)


def refine_arms():
    for suffix, sign in (("L", 1), ("R", -1)):
        obj = bpy.data.objects[f"White_Arm_{suffix}"]
        def transform(p):
            x = sign*p.x
            hand = max(0, min(1, (.57-p.z)/.085))
            p.x = sign*(.205+(x-.205)*.86)
            if p.z < .57:
                p.x = sign*(.205+(sign*p.x-.205)*(1+.16*hand))
                p.y = -.07+(p.y+.07)*(1+.18*hand)
                p.z = .57+(p.z-.57)*(1+.22*hand)
            return p
        edit_mesh(obj, transform)
        smooth_wrist(obj)
        control_group(obj, "Edit_Shoulder", lambda p: p.z > 1.22)
        control_group(obj, "Edit_UpperArm", lambda p: .95 < p.z < 1.31)
        control_group(obj, "Edit_Elbow", lambda p: .72 < p.z < 1.0)
        control_group(obj, "Edit_Forearm", lambda p: .56 < p.z < .80)
        control_group(obj, "Edit_Wrist", lambda p: .53 < p.z < .61)
        control_group(obj, "Edit_Hand", lambda p: p.z < .56)


def refine_legs():
    for suffix, sign in (("L", 1), ("R", -1)):
        obj = bpy.data.objects[f"White_Leg_{suffix}"]
        def transform(p):
            x = sign*p.x
            p.x = sign*(.171+(x-.171)*1.025)
            if p.z > .10:
                p.z = .10+(p.z-.10)*.955
            if p.y < -.06 and p.z < .20:
                p.y -= .008
            return p
        edit_mesh(obj, transform)
        control_group(obj, "Edit_Thigh", lambda p: p.z > .28)
        control_group(obj, "Edit_Knee", lambda p: .15 < p.z < .33)
        control_group(obj, "Edit_Foot", lambda p: p.z < .16)


def refine_port():
    obj = bpy.data.objects["Chest_AccessPort"]
    obj.name = "Chest_Access_Port"
    torso = bpy.data.objects["White_Torso"]
    def surface_y(x, z):
        hit, point, _, _ = torso.ray_cast((x, -2, z), (0, 1, 0))
        if not hit:
            raise ValueError(f"No torso surface below chest port at {x}, {z}")
        return point.y
    def project(p):
        p.x += .016
        p.z -= .004
        p.y = surface_y(p.x, p.z)-.0011
        return p
    edit_mesh(obj, project)
    port_material = obj.data.materials[0]
    port_material.diffuse_color = (.68, .69, .68, 1)
    port_material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (.68, .69, .68, 1)
    cx, cz = .166, 1.306
    contour = [(-.012,-.005),(-.012,.003),(-.008,.009),(-.002,.010),
               (.004,.007),(.010,.007),(.013,.003),(.012,-.004),
               (.006,-.009),(-.003,-.008)]
    points = [(cx+x, surface_y(cx+x,cz+z)-.0016, cz+z) for x,z in contour]
    detail = sweep("Chest_Access_Detail", points, .00085, port_material, sides=8)
    rig = bpy.data.objects["Bagusmax_Rig"]
    detail.vertex_groups.new(name="Chest").add(list(range(len(detail.data.vertices))), 1.0, "REPLACE")
    detail.parent = rig
    modifier = detail.modifiers.new("CharacterSkin", "ARMATURE")
    modifier.object = rig
    bpy.ops.object.select_all(action="DESELECT")
    detail.select_set(True)
    bpy.context.view_layer.objects.active = detail
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=.025)
    bpy.ops.object.mode_set(mode="OBJECT")


def adjust_rest_rig():
    rig = bpy.data.objects["Bagusmax_Rig"]
    rig.animation_data_clear()
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for suffix, sign in (("L", 1), ("R", -1)):
        for name in ("Shoulder", "UpperArm", "Forearm", "Hand"):
            bone = rig.data.edit_bones[f"{name}_{suffix}"]
            for point in (bone.head, bone.tail):
                point.x = sign*(.205+(sign*point.x-.205)*.86)
        for name in ("Thigh", "Shin", "Foot"):
            bone = rig.data.edit_bones[f"{name}_{suffix}"]
            bone.head.x = sign*.171
            bone.tail.x = sign*.171
    head = rig.data.edit_bones["Head"]
    head.tail.z += .012
    bpy.ops.object.mode_set(mode="OBJECT")
    for bone in rig.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0, 0, 0)
        bone.scale = (1, 1, 1)
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and obj.name != "Studio_Floor" and obj.parent == rig:
            world = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = world
    bpy.context.scene.frame_set(1)


VIEWS = {
    "front": ((0,-5,1.02),(0,0,.845),2.04),
    "left": ((5,0,1.02),(0,0,.845),2.04),
    "right": ((-5,0,1.02),(0,0,.845),2.04),
    "back": ((0,5,1.02),(0,0,.845),2.04),
    "three_quarter": ((3,-5,1.75),(0,0,.845),2.04),
    "head": ((.35,-4,1.7),(0,0,1.57),.58),
    "shoulder": ((2,-4,1.9),(.39,0,1.24),.77),
    "elbow": ((3,-4,1.2),(.52,0,.84),.61),
    "belly_profile": ((5,0,1.02),(0,0,.81),1.22),
    "chest_port": ((.8,-4,1.6),(.16,0,1.29),.34),
    "legs": ((1,-4,.75),(0,0,.28),.9),
}


def render_set(label):
    scene = bpy.context.scene
    camera = bpy.data.objects["Inspection_Camera"]
    scene.render.resolution_x = scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.view_layers[0].material_override = None
    clay = bpy.data.materials.get("Anatomy_Clay") or material("Anatomy_Clay",(.43,.46,.49),.65)
    for name, (location, target, scale) in VIEWS.items():
        camera.location = location
        camera.rotation_euler = (Vector(target)-camera.location).to_track_quat("-Z","Y").to_euler()
        camera.data.ortho_scale = scale
        scene.render.filepath = str(REVIEW/f"{label}_{name}.png")
        bpy.ops.render.render(write_still=True)
        if name in ("front", "left", "three_quarter"):
            scene.view_layers[0].material_override = clay
            scene.render.filepath = str(REVIEW/f"{label}_clay_{name}.png")
            bpy.ops.render.render(write_still=True)
            scene.view_layers[0].material_override = None
    camera.location = (0,-5,1.02)
    camera.rotation_euler = (Vector((0,0,.845))-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.ortho_scale = 2.04


def render_masks():
    for label, source in (("before", SOURCE), ("refined", REFINED)):
        bpy.ops.wm.open_mainfile(filepath=str(source))
        scene = bpy.context.scene
        scene.render.resolution_x = scene.render.resolution_y = 640
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True
        bpy.data.objects["Studio_Floor"].hide_render = True
        white = bpy.data.materials.new("Silhouette_Mask")
        white.use_nodes = True
        white.node_tree.nodes.clear()
        shader = white.node_tree.nodes.new("ShaderNodeEmission")
        shader.inputs["Color"].default_value = (1, 1, 1, 1)
        output = white.node_tree.nodes.new("ShaderNodeOutputMaterial")
        white.node_tree.links.new(shader.outputs[0], output.inputs[0])
        scene.view_layers[0].material_override = white
        camera = bpy.data.objects["Inspection_Camera"]
        for name in ("front", "left"):
            location, target, scale = VIEWS[name]
            camera.location = location
            camera.rotation_euler = (Vector(target)-camera.location).to_track_quat("-Z","Y").to_euler()
            camera.data.ortho_scale = scale
            scene.render.filepath = str(REVIEW/f"{label}_mask_{name}.png")
            bpy.ops.render.render(write_still=True)


def validate_source():
    flaws = []
    for obj in (o for o in bpy.context.scene.objects if o.type == "MESH" and o.name != "Studio_Floor"):
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        if any(not edge.is_manifold for edge in bm.edges):
            flaws.append(f"{obj.name}: non-manifold")
        bm.free()
        if any(not all(math.isfinite(v) for v in vertex.co) for vertex in obj.data.vertices):
            flaws.append(f"{obj.name}: non-finite")
        if any(not vertex.groups for vertex in obj.data.vertices):
            flaws.append(f"{obj.name}: missing skin weights")
    if flaws:
        raise ValueError(flaws)


def main():
    REVIEW.mkdir(parents=True, exist_ok=True)
    if "--masks-only" in sys.argv:
        render_masks()
        return
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    before = measure()
    if "--after-only" not in sys.argv:
        render_set("before")
    refine_torso()
    refine_head()
    refine_arms()
    refine_legs()
    refine_port()
    adjust_rest_rig()
    validate_source()
    after = measure()
    report = {
        "source_before":str(SOURCE), "source_after":str(REFINED),
        "measurement_method":"world-space mesh vertex bounds, normalized by standing height",
        "reference_target_estimate":{"arm_span_over_H":"about 0.74-0.78",
                                     "head_width_over_H":"about 0.25-0.27",
                                     "torso_width_over_H":"about 0.53-0.58"},
        "reference_limit":"Film frames differ in pose, perspective and lighting; ranges are visual estimates",
        "before":before, "after":after,
        "animation_clips":[], "skinning":"20-joint neutral armature, no keyframes",
    }
    (REVIEW/"measurements.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    bpy.context.scene.frame_set(1)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(REFINED))
    bpy.ops.object.select_all(action="DESELECT")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name != "Studio_Floor"]
    rig = bpy.data.objects["Bagusmax_Rig"]
    for obj in meshes+[rig]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.export_scene.gltf(filepath=str(RUNTIME), export_format="GLB", use_selection=True,
                              export_yup=True, export_animations=False, export_skins=True,
                              export_all_influences=False)
    bpy.ops.object.select_all(action="DESELECT")
    render_set("refined")
    bpy.context.scene.view_layers[0].material_override = None
    print(json.dumps({"before":{k:v for k,v in before.items() if k!="objects"},
                      "after":{k:v for k,v in after.items() if k!="objects"}},indent=2))


if __name__ == "__main__":
    main()
