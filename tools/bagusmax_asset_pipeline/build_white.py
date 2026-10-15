"""Author and inspect the White character without application integration."""

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets/bagusmax"
REPORTS = ROOT / "reports/bagusmax_3d"


def material(name, color, roughness=.42):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = 0
    return mat


def mesh_object(name, vertices, faces, mat):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj


def loft(name, profiles, mat, segments=48, subdivision=2):
    vertices, faces = [], []
    for x, y, z, rx, ry in profiles:
        for i in range(segments):
            angle = i * 2 * math.pi / segments
            vertices.append((x + rx * math.cos(angle), y + ry * math.sin(angle), z))
    for j in range(len(profiles) - 1):
        for i in range(segments):
            a, b = j * segments + i, j * segments + (i + 1) % segments
            faces.append((a, b, b + segments, a + segments))
    for row, reverse in ((0, True), (len(profiles) - 1, False)):
        center = len(vertices)
        vertices.append(tuple(profiles[row][:3]))
        for i in range(segments):
            a, b = row * segments + i, row * segments + (i + 1) % segments
            faces.append((center, b, a) if reverse else (center, a, b))
    obj = mesh_object(name, vertices, faces, mat)
    uv = obj.data.uv_layers.new(name="UVMap")
    for poly in obj.data.polygons:
        for li in poly.loop_indices:
            vi = obj.data.loops[li].vertex_index
            uv.data[li].uv = ((vi % segments) / segments, min(vi // segments, len(profiles)-1) / (len(profiles)-1))
    mod = obj.modifiers.new("Surface", "SUBSURF")
    mod.levels = mod.render_levels = subdivision
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def sweep(name, points, radius, mat, sides=12):
    vertices, faces = [], []
    for j, point in enumerate(points):
        point = Vector(point)
        tangent = Vector(points[min(j+1, len(points)-1)]) - Vector(points[max(0, j-1)])
        tangent.normalize()
        normal = tangent.cross(Vector((0, 1, 0))).normalized()
        if normal.length < .1:
            normal = tangent.cross(Vector((1, 0, 0))).normalized()
        other = tangent.cross(normal).normalized()
        for i in range(sides):
            angle = i * 2 * math.pi / sides
            vertices.append(point + radius * (math.cos(angle)*normal + math.sin(angle)*other))
    for j in range(len(points)-1):
        for i in range(sides):
            a, b = j*sides+i, j*sides+(i+1)%sides
            faces.append((a, b, b+sides, a+sides))
    faces.extend((tuple(reversed(range(sides))), tuple(range((len(points)-1)*sides, len(points)*sides))))
    return mesh_object(name, vertices, faces, mat)


def body():
    vinyl = material("Vinyl_WarmWhite", (.79, .79, .765), .43)
    eyes = material("Face_Charcoal", (.005, .006, .008), .65)
    port = material("AccessPort_White", (.72, .73, .72), .49)
    torso = loft("White_Torso", [
        (0, .005, .35, .055, .055), (0, .005, .38, .17, .15),
        (0, -.015, .43, .295, .24), (0, -.028, .53, .402, .326),
        (0, -.042, .68, .472, .389), (0, -.045, .86, .476, .405),
        (0, -.032, 1.02, .438, .367), (0, -.015, 1.17, .393, .31),
        (0, 0, 1.30, .346, .248), (0, .007, 1.39, .284, .198),
        (0, .010, 1.45, .203, .156), (0, .010, 1.475, .125, .101),
        (0, .010, 1.49, .06, .052)], vinyl)
    head = loft("White_Head", [
        (0, -.022, 1.457, .06, .048), (0, -.022, 1.468, .126, .080),
        (0, -.022, 1.488, .175, .110), (0, -.022, 1.524, .199, .128),
        (0, -.022, 1.576, .202, .132), (0, -.022, 1.621, .178, .119),
        (0, -.022, 1.651, .128, .085), (0, -.022, 1.669, .062, .044),
        (0, -.022, 1.675, .012, .010)], vinyl)

    def face_y(x, z):
        return -.022 - .133 * math.sqrt(max(.01, 1-(x/.204)**2-((z-1.564)/.125)**2)) - .002

    face_parts = []
    for sign in (-1, 1):
        xc, zc, radius = sign*.071, 1.565, .014
        vertices = [(xc, face_y(xc, zc)-.001, zc)]
        for i in range(40):
            angle = i*2*math.pi/40
            x, z = xc+radius*math.cos(angle), zc+radius*math.sin(angle)
            vertices.append((x, face_y(x, z), z))
        eye = mesh_object("Eye_L" if sign == 1 else "Eye_R", vertices,
                          [(0, i+1, (i+1)%40+1) for i in range(40)], eyes)
        mod = eye.modifiers.new("FacePatchThickness", "SOLIDIFY")
        mod.thickness = .0008
        bpy.context.view_layer.objects.active = eye
        bpy.ops.object.modifier_apply(modifier=mod.name)
        face_parts.append(eye)
    face_parts.append(sweep("Eye_ContourBridge", [(x, face_y(x, 1.565), 1.565)
                                                  for x in [-.071+i*.142/32 for i in range(33)]], .00155, eyes))
    radius, center = .026, Vector((.15, -.239, 1.31))
    normal = Vector((.30, -.92, .23)).normalized()
    basis_x = Vector((1, 0, 0)).cross(normal).normalized()
    basis_y = normal.cross(basis_x).normalized()
    ring_points = [center + radius*(math.cos(i*2*math.pi/96)*basis_x + math.sin(i*2*math.pi/96)*basis_y)
                   for i in range(97)]
    chest_port = sweep("Chest_AccessPort", ring_points, .00125, port, sides=8)

    arms, legs = {}, {}
    for sign, suffix in ((1, "L"), (-1, "R")):
        profiles = [
            (.235, .025, 1.405, .024, .024), (.310, .020, 1.367, .095, .095),
            (.385, .012, 1.300, .122, .132), (.440, .010, 1.200, .143, .152),
            (.506, -.003, 1.070, .143, .166), (.538, -.018, .925, .148, .164),
            (.554, -.035, .790, .144, .145), (.558, -.052, .665, .122, .119),
            (.557, -.062, .584, .087, .091), (.551, -.066, .546, .073, .075),
            (.549, -.069, .505, .035, .040)]
        arm = loft(f"White_Arm_{suffix}", [(sign*x, y, z, rx, ry) for x,y,z,rx,ry in profiles], vinyl)
        palm = loft(f"Palm_{suffix}", [(sign*.548, -.075, z, rx, ry) for z,rx,ry in
            ((.46,.032,.047),(.478,.071,.072),(.52,.085,.078),(.552,.07,.072),(.571,.035,.04))], vinyl, 32, 1)
        hand_parts = [palm]
        for name, x, y, end, radius in (("Index", .505, -.108, .403, .025),
                                       ("Middle", .552, -.085, .395, .026),
                                       ("Ring", .597, -.064, .413, .025),
                                       ("Thumb", .472, -.13, .458, .031)):
            points = [(sign*x, y, end, .004, .005),
                      (sign*(x+.004), y-.005, end+.005, radius*.65, radius*.70),
                      (sign*(x+.006), y-.001, end+.018, radius, radius),
                      (sign*x, y+.012, .491 if name!="Thumb" else .513, radius, radius*1.15),
                      (sign*(x+.008), y+.018, .532 if name!="Thumb" else .539, radius*.5, radius*.55)]
            hand_parts.append(loft(f"{name}_{suffix}", points, vinyl, 20, 1))
        bpy.ops.object.select_all(action="DESELECT")
        for obj in hand_parts:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = palm
        bpy.ops.object.join()
        palm.name = f"White_Hand_{suffix}"
        # Remesh only the hand union; body and limb quad loops remain intact.
        mod = palm.modifiers.new("HandUnion", "REMESH")
        mod.mode, mod.voxel_size = "VOXEL", .0035
        mod.use_smooth_shade = True
        bpy.ops.object.modifier_apply(modifier=mod.name)
        mod = palm.modifiers.new("HandRelax", "SMOOTH")
        mod.factor, mod.iterations = .7, 5
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.context.view_layer.objects.active = arm
        mod = arm.modifiers.new("WristUnion", "BOOLEAN")
        mod.operation, mod.solver, mod.object = "UNION", "EXACT", palm
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(palm, do_unlink=True)
        mod = arm.modifiers.new("WristRelax", "SMOOTH")
        mod.factor, mod.iterations = .5, 3
        bpy.ops.object.modifier_apply(modifier=mod.name)
        arms[suffix] = arm
        legs[suffix] = loft(f"White_Leg_{suffix}", [(sign*(x-.012), y, z, rx, ry) for x,y,z,rx,ry in [
            (.187,-.045,.003,.07,.07), (.187,-.059,.015,.117,.105),
            (.190,-.062,.055,.150,.136), (.192,-.041,.135,.170,.158),
            (.194,-.006,.240,.177,.174), (.195,.012,.351,.176,.169),
            (.185,.019,.437,.157,.150), (.178,.015,.491,.105,.107),
            (.175,.010,.512,.04,.045)]], vinyl)
    return torso, head, face_parts, chest_port, arms, legs


def rig_character(torso, head, face_parts, port, arms, legs):
    armature = bpy.data.armatures.new("Bagusmax_Skeleton")
    rig = bpy.data.objects.new("Bagusmax_Rig", armature)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    specs = {
        "Root": ((0,0,0),(0,0,.12),None), "Hips": ((0,0,.39),(0,0,.65),"Root"),
        "Spine": ((0,0,.65),(0,0,1.01),"Hips"), "Chest": ((0,0,1.01),(0,0,1.37),"Spine"),
        "Neck": ((0,0,1.37),(0,0,1.475),"Chest"), "Head": ((0,0,1.475),(0,0,1.66),"Neck")}
    for sign, suffix in ((1,"L"),(-1,"R")):
        specs.update({
            f"Shoulder_{suffix}": ((0,0,1.32),(sign*.36,0,1.32),"Chest"),
            f"UpperArm_{suffix}": ((sign*.36,0,1.32),(sign*.535,-.02,.90),f"Shoulder_{suffix}"),
            f"Forearm_{suffix}": ((sign*.535,-.02,.90),(sign*.55,-.066,.55),f"UpperArm_{suffix}"),
            f"Hand_{suffix}": ((sign*.55,-.066,.55),(sign*.55,-.08,.42),f"Forearm_{suffix}"),
            f"Thigh_{suffix}": ((sign*.19,0,.47),(sign*.19,0,.24),"Hips"),
            f"Shin_{suffix}": ((sign*.19,0,.24),(sign*.19,-.03,.08),f"Thigh_{suffix}"),
            f"Foot_{suffix}": ((sign*.19,-.03,.08),(sign*.19,-.15,.05),f"Shin_{suffix}")})
    for name, (a,b,parent) in specs.items():
        bone = armature.edit_bones.new(name)
        bone.head, bone.tail = a,b
        if parent:
            bone.parent = armature.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")

    def skin(obj, weights):
        groups = {name: obj.vertex_groups.new(name=name) for name in weights}
        for vertex in obj.data.vertices:
            values = {name: max(0, fn(vertex.co)) for name,fn in weights.items()}
            total = sum(values.values())
            for name, value in values.items():
                if value > 0:
                    groups[name].add([vertex.index], value/total, "REPLACE")
        obj.parent = rig
        mod = obj.modifiers.new("CharacterSkin", "ARMATURE")
        mod.object = rig
        if not obj.data.uv_layers:
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(island_margin=.025)
            bpy.ops.object.mode_set(mode="OBJECT")

    clamp = lambda x: max(0, min(1, x))
    skin(torso, {"Hips": lambda p: clamp((.76-p.z)/.32), "Chest": lambda p: clamp((p.z-.90)/.35),
                 "Spine": lambda p: max(.01, 1-clamp((.76-p.z)/.32)-clamp((p.z-.90)/.35))})
    for obj in [head]+face_parts:
        skin(obj, {"Head": lambda p: 1})
    skin(port, {"Chest": lambda p: 1})
    for suffix, arm in arms.items():
        skin(arm, {f"UpperArm_{suffix}": lambda p: clamp((p.z-.80)/.20),
                   f"Forearm_{suffix}": lambda p: (1-clamp((p.z-.80)/.20))*clamp((p.z-.49)/.09),
                   f"Hand_{suffix}": lambda p: 1-clamp((p.z-.49)/.09)})
    for suffix, leg in legs.items():
        skin(leg, {f"Thigh_{suffix}": lambda p: clamp((p.z-.17)/.15),
                   f"Shin_{suffix}": lambda p: 1-clamp((p.z-.17)/.15)})
    rig.show_in_front = True
    return rig


def clips(rig):
    rig.animation_data_create()
    for name in ("IDLE", "LISTEN", "SPEAK", "WAVE", "THINK", "RETURN_TO_IDLE"):
        rig.animation_data.action = None
        for frame, amount in ((1,0),(20,1),(40,0),(60,0)):
            bpy.context.scene.frame_set(frame)
            for bone in rig.pose.bones:
                bone.rotation_mode = "XYZ"
                bone.rotation_euler = (0,0,0)
                bone.scale = (1,1,1)
            if name == "IDLE":
                rig.pose.bones["Chest"].scale = (1+amount*.006,1,1+amount*.008)
            elif name == "LISTEN":
                rig.pose.bones["Head"].rotation_euler.y = amount*.09
            elif name == "SPEAK":
                rig.pose.bones["Head"].rotation_euler.x = amount*.04
                rig.pose.bones["Chest"].scale = (1+amount*.007,1,1)
            elif name == "WAVE":
                upper = rig.pose.bones["UpperArm_L"]
                forearm = rig.pose.bones["Forearm_L"]
                upper_delta = (upper.bone.tail_local-upper.bone.head_local).rotation_difference(Vector((.25,-.12,.05)))
                forearm_delta = (forearm.bone.tail_local-forearm.bone.head_local).rotation_difference(Vector((.10,-.03,.30)))
                basis = upper.bone.matrix_local.to_quaternion()
                upper.rotation_euler = (basis.inverted() @ upper_delta @ basis).to_euler()
                basis = forearm.bone.matrix_local.to_quaternion()
                forearm.rotation_euler = (basis.inverted() @ upper_delta.inverted() @ forearm_delta @ basis).to_euler()
                upper.rotation_euler = tuple(angle*amount for angle in upper.rotation_euler)
                forearm.rotation_euler = tuple(angle*amount for angle in forearm.rotation_euler)
                rig.pose.bones["Hand_L"].rotation_euler.y = amount*.18
            elif name == "THINK":
                rig.pose.bones["Head"].rotation_euler.y = amount*-.13
            for bone in rig.pose.bones:
                bone.keyframe_insert("rotation_euler", frame=frame)
                bone.keyframe_insert("scale", frame=frame)
        action = rig.animation_data.action
        action.name = name
        track = rig.animation_data.nla_tracks.new()
        track.name = name
        strip = track.strips.new(name, 1, action)
        strip.action_slot = rig.animation_data.action_slot
        track.mute = True
    rig.animation_data.action = None
    bpy.context.scene.frame_set(1)
    for bone in rig.pose.bones:
        bone.rotation_euler = (0,0,0)
        bone.scale = (1,1,1)


def studio():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 4
    scene.render.resolution_x = scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    world = bpy.data.worlds.new("Neutral_Studio")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (.45,.48,.52,1)
    world.node_tree.nodes["Background"].inputs[1].default_value = .28
    scene.world = world
    mesh_object("Studio_Floor", [(-200,-200,0),(200,-200,0),(200,200,0),(-200,200,0)], [(0,1,2,3)],
                material("Studio_Gray", (.18,.195,.21), .85))
    for name, location, energy, size in (("Key",(-3,-4,5),450,3.5),("Fill",(3,-2,3),260,3),("Rim",(1,3,4),480,2.5)):
        light = bpy.data.lights.new(name, "AREA")
        light.energy, light.shape, light.size = energy, "DISK", size
        obj = bpy.data.objects.new(name, light)
        bpy.context.collection.objects.link(obj)
        obj.location = location
        obj.rotation_euler = (Vector((0,0,.85))-obj.location).to_track_quat("-Z","Y").to_euler()
    camera = bpy.data.objects.new("Inspection_Camera", bpy.data.cameras.new("Inspection_Camera"))
    bpy.context.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 2.04
    camera.location = (0, -5, 1.02)
    camera.rotation_euler = (Vector((0,0,.845))-camera.location).to_track_quat("-Z","Y").to_euler()
    scene.camera = camera
    return camera


def render_views(camera, prefix, clay=False):
    scene = bpy.context.scene
    scene.view_layers[0].material_override = material("Neutral_Clay", (.43,.46,.49), .65) if clay else None
    views = {"front": (0,-5,1.02), "left": (5,0,1.02), "right": (-5,0,1.02),
             "three_quarter": (3,-5,1.75), "back": (0,5,1.02)}
    if not clay:
        views.update(head=(.35,-4,1.70), torso=(2,-5,1.5))
    for name, location in views.items():
        target = Vector((0,0,1.565 if name=="head" else (1.03 if name=="torso" else .845)))
        camera.location = location
        camera.rotation_euler = (target-camera.location).to_track_quat("-Z","Y").to_euler()
        camera.data.ortho_scale = .58 if name=="head" else (1.3 if name=="torso" else 2.04)
        scene.render.filepath = str(REPORTS/f"{prefix}_{name}.png")
        bpy.ops.render.render(write_still=True)
    scene.view_layers[0].material_override = None


def validate(rig):
    meshes = [o for o in bpy.context.scene.objects if o.type=="MESH" and o.name!="Studio_Floor"]
    defects, triangles = [], 0
    for obj in meshes:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        if any(not edge.is_manifold for edge in bm.edges):
            defects.append(obj.name+": non-manifold")
        bm.free()
        obj.data.calc_loop_triangles()
        triangles += len(obj.data.loop_triangles)
        if not obj.data.uv_layers or any(not v.groups for v in obj.data.vertices):
            defects.append(obj.name+": missing UV/weights")
    assert not defects, defects
    bounds = [obj.matrix_world @ Vector(c) for obj in meshes for c in obj.bound_box]
    low = [min(p[i] for p in bounds) for i in range(3)]
    high = [max(p[i] for p in bounds) for i in range(3)]
    result = {"blender": bpy.app.version_string, "mesh_count":len(meshes), "triangles": triangles,
              "materials": sorted({m.name for o in meshes for m in o.data.materials}),
              "blender_bounds": [low, high], "height_m":high[2]-low[2],
              "joints":[b.name for b in rig.data.bones], "clips":[t.name for t in rig.animation_data.nla_tracks],
              "geometry_checks":"MANIFOLD_UV_WEIGHT_PASS", "approval":"AWAITING_USER_VISUAL_REVIEW",
              "limitations":["Provisional procedural skinning; not production deformation acceptance",
                             "No facial blend shapes", "No application integration",
                             "No collision-free certification for all poses", "No external HDRI or textures bundled"]}
    (REPORTS/"white_asset_status.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return meshes


def main():
    for path in (ASSETS/"source", ASSETS/"runtime", REPORTS):
        path.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rig = rig_character(*body())
    clips(rig)
    camera = studio()
    meshes = validate(rig)
    bpy.context.scene.frame_set(1)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes+[rig]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = rig
    originals = {}
    try:
        for obj in meshes:
            if obj.name.startswith(("White_Torso", "White_Arm", "White_Leg")):
                originals[obj] = obj.data
                obj.data = obj.data.copy()
                bpy.context.view_layer.objects.active = obj
                mod = obj.modifiers.new("RuntimeReduction", "DECIMATE")
                mod.ratio = .55
                bpy.ops.object.modifier_move_up(modifier=mod.name)
                bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.ops.export_scene.gltf(filepath=str(ASSETS/"runtime/bagusmax_white.glb"), export_format="GLB",
            use_selection=True, export_yup=True, export_animations=True,
            export_animation_mode="NLA_TRACKS", export_skins=True, export_all_influences=False)
    finally:
        for obj, mesh in originals.items():
            reduced = obj.data
            obj.data = mesh
            bpy.data.meshes.remove(reduced)
    bpy.ops.wm.save_as_mainfile(filepath=str(ASSETS/"source/bagusmax_white.blend"))
    if "--export-only" in sys.argv:
        return
    render_views(camera, "white_material")
    render_views(camera, "white_clay", clay=True)
    camera.location = (0,-5,1.02)
    camera.rotation_euler = (Vector((0,0,.845))-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.ortho_scale = 2.04
    bpy.ops.wm.save_as_mainfile(filepath=str(ASSETS/"source/bagusmax_white.blend"))


if __name__ == "__main__":
    main()
