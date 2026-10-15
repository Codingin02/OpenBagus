"""Refine the existing White asset and inspect exportable soft deformation."""

import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recover_white_anatomy as recovery
from build_white import ASSETS, REPORTS
from detail_white_anatomy import activate, smoothstep
from gltf_skinning import BLENDER_TO_GLTF, GLBSkin, self_test

SOURCE = ASSETS / "source/bagusmax_white_anatomy_v3.blend"
OUTPUT = ASSETS / "source/bagusmax_white_anatomy_v4.blend"
GLB = ASSETS / "runtime/bagusmax_white_anatomy_v4.glb"
FOLDER = REPORTS / "white_v4"
recovery.REVIEW = FOLDER


def panel_surface(obj, cy, cz, ry, rz, side_limit, old_depth, depth, contrast):
    if obj.data.shape_keys:
        obj.shape_key_clear()
    for vertex in obj.data.vertices:
        p = vertex.co
        d = math.hypot((p.y-cy)/ry, (p.z-cz)/rz)
        side = smoothstep(side_limit-.035, side_limit+.015, abs(p.x))
        if d < 1:
            p.x += math.copysign(old_depth*(1-smoothstep(.82, 1, d))*side, p.x)
    obj.data.update()
    for face in obj.data.polygons:
        face.use_smooth = True
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    edges = {e for f in bm.faces
             if .95 < math.hypot((f.calc_center_median().y-cy)/ry,
                                 (f.calc_center_median().z-cz)/rz) < 1.05
             and abs(f.calc_center_median().x) > side_limit-.03 for e in f.edges if e.calc_length() > .012}
    if edges:
        bmesh.ops.subdivide_edges(bm, edges=list(edges), cuts=1, use_grid_fill=True)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    colors = obj.data.color_attributes.get("VinylSurface")
    for vertex in obj.data.vertices:
        p = vertex.co
        d = math.hypot((p.y-cy)/ry, (p.z-cz)/rz)
        side = smoothstep(side_limit-.035, side_limit+.015, abs(p.x))
        boundary = math.exp(-((d-1)/.021)**2)*side
        interior = (1-smoothstep(.96, 1.02, d))*side
        color = np.array((.79, .79, .765))*(1-contrast*boundary-.008*interior)
        colors.data[vertex.index].color = (*color, 1)
        vertex.co -= vertex.normal*depth*boundary
    obj.data.update()


def shoulder_weights(obj, side):
    chest = obj.vertex_groups.get("Chest") or obj.vertex_groups.new(name="Chest")
    rig = bpy.data.objects["Bagusmax_Rig"]
    deform = {g.index: g for g in obj.vertex_groups if g.name in rig.data.bones}
    indices = [v.index for v in obj.data.vertices if v.co.z >= 1.04]
    for group in deform.values():
        group.remove(indices)
    for vertex in obj.data.vertices:
        z = vertex.co.z
        if z < 1.04:
            continue
        anchor = .92*smoothstep(1.27, 1.40, z)
        helper = smoothstep(1.06, 1.32, z)*(1-anchor)
        values = {"Chest": anchor, f"ShoulderVolume_{side}": helper,
                  f"UpperArm_{side}": 1-anchor-helper}
        for name, weight in values.items():
            if weight > 1e-6:
                obj.vertex_groups[name].add([vertex.index], weight, "REPLACE")


def elbow_weights(obj, side):
    names = [f"{kind}_{side}" for kind in ("UpperArm", "ElbowVolume", "Forearm")]
    groups = [obj.vertex_groups[name] for name in names]
    indices = [v.index for v in obj.data.vertices if .67 < v.co.z < 1.07]
    for group in obj.vertex_groups:
        if group.name in bpy.data.objects["Bagusmax_Rig"].data.bones:
            group.remove(indices)
    for vertex in obj.data.vertices:
        z = vertex.co.z
        if not .67 < z < 1.07:
            continue
        u = smoothstep(.67, 1.07, z)
        helper = 4*u*(1-u)
        weights = (u*(1-helper), helper, (1-u)*(1-helper))
        for group, weight in zip(groups, weights):
            group.add([vertex.index], weight, "REPLACE")


def hand_surface(obj, sign):
    for vertex in obj.data.vertices:
        p = vertex.co
        x = sign*p.x
        if .46 < p.z < .58:
            center = Vector((sign*.502, -.066, p.z))
            radial = p-center
            if radial.length:
                fill = .003*math.exp(-((p.z-.516)/.050)**2)
                p += radial.normalized()*fill
        if .43 < p.z < .51 and .43 < x < .58:
            p.y -= .004*math.exp(-((p.z-.478)/.035)**2)*math.exp(-((x-.505)/.065)**4)
    obj.data.update()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    selected = [v for v in bm.verts if .43 < v.co.z < .59]
    for _ in range(6):
        bmesh.ops.smooth_vert(bm, verts=selected, factor=.2,
                              use_axis_x=True, use_axis_y=True, use_axis_z=True)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def clean_local_faces(obj):
    obj.data.calc_loop_triangles()
    indices = {t.polygon_index for t in obj.data.loop_triangles if t.area < 1e-10}
    indices.update(p.index for p in obj.data.polygons if len(p.vertices) > 4)
    if not indices:
        return
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.triangulate(bm, faces=[bm.faces[i] for i in indices])
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=1e-5)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def joint_edge_flow(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for _ in range(4):
        edges = [e for e in bm.edges if .64 < sum(v.co.z for v in e.verts)/2 < 1.39
                 and abs(e.verts[0].co.z-e.verts[1].co.z) > .012]
        if not edges:
            break
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=1, use_grid_fill=True)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def refine():
    rig = bpy.data.objects["Bagusmax_Rig"]
    activate(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    for side, sign in (("L", 1), ("R", -1)):
        pivot = Vector((sign*.39, 0, 1.34))
        rig.data.edit_bones[f"UpperArm_{side}"].head = pivot
        rig.data.edit_bones[f"Shoulder_{side}"].tail = pivot
        helper = rig.data.edit_bones[f"ShoulderVolume_{side}"]
        primary = rig.data.edit_bones[f"UpperArm_{side}"]
        helper.head = Vector((sign*.29, 0, 1.22))
        helper.tail = helper.head+(primary.tail-primary.head).normalized()*.12
        helper.roll = primary.roll
    bpy.ops.object.mode_set(mode="OBJECT")
    for side, sign in (("L", 1), ("R", -1)):
        arm = bpy.data.objects[f"White_Arm_{side}"]
        joint_edge_flow(arm)
        panel_surface(arm, -.006, .967, .137, .214, .505, .001, .00025, .11)
        shoulder_weights(arm, side)
        elbow_weights(arm, side)
        hand_surface(arm, sign)
        clean_local_faces(arm)
    panel_surface(bpy.data.objects["White_Torso"], .09, .740, .235, .280, .27,
                  .0004, .00010, .09)
    clean_local_faces(bpy.data.objects["White_Torso"])
    recovery.reset(rig)
    return rig


def coordinates(mesh):
    result = np.empty(len(mesh.vertices)*3)
    mesh.vertices.foreach_get("co", result)
    return result.reshape(-1, 3)


def lbs_matrices(obj, rig):
    names = list(rig.data.bones.keys())
    matrices = np.array([rig.pose.bones[n].matrix @ rig.data.bones[n].matrix_local.inverted() for n in names])
    groups = {g.index: names.index(g.name) for g in obj.vertex_groups if g.name in names}
    result = np.zeros((len(obj.data.vertices), 4, 4))
    for vertex in obj.data.vertices:
        for group in vertex.groups:
            if group.group in groups:
                result[vertex.index] += group.weight*matrices[groups[group.group]]
    return result


def center_profile(rest):
    grid = np.linspace(.64, 1.405, 180)
    centers = []
    for z in grid:
        distances = abs(rest[:, 2]-z)
        width = max(.009, np.partition(distances, 191)[191]+1e-7)
        points = rest[distances <= width]
        centers.append((points[:, :2].min(axis=0)+points[:, :2].max(axis=0))/2)
    centers = np.array(centers)
    fits = [np.polynomial.Polynomial.fit(grid, centers[:, i], 6) for i in range(2)]
    def at(z):
        z = np.asarray(z)
        return np.stack((fits[0](z), fits[1](z), z), axis=-1)
    return at


def bezier(points, t):
    p0, p1, p2, p3 = points
    t = t[:, None]
    center = (1-t)**3*p0+3*(1-t)**2*t*p1+3*(1-t)*t*t*p2+t**3*p3
    tangent = 3*(1-t)**2*(p1-p0)+6*(1-t)*t*(p2-p1)+3*t*t*(p3-p2)
    acceleration = 6*(1-t)*(p2-2*p1+p0)+6*t*(p3-2*p2+p1)
    speed = np.maximum(np.linalg.norm(tangent, axis=1), 1e-9)
    curvature = np.linalg.norm(np.cross(tangent, acceleration), axis=1)/speed**3
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-9)
    return center, tangent, curvature


def corrective_target(obj, rig, kind, side, current, matrices):
    rest = coordinates(obj.data)
    profile = center_profile(rest)
    z = rest[:, 2]
    sign = 1 if side == "L" else -1
    low, high = (1.0, 1.405) if kind == "Shoulder" else (.64, 1.12)
    t = np.clip((high-z)/(high-low), 0, 1)
    primary = f"{'UpperArm' if kind=='Shoulder' else 'Forearm'}_{side}"
    transform = np.array(rig.pose.bones[primary].matrix @ rig.data.bones[primary].matrix_local.inverted())
    p0 = profile(high)
    p3 = transform[:3, :3] @ profile(low)+transform[:3, 3]
    tangent3 = profile(low-.005)-profile(low+.005)
    tangent3 = transform[:3, :3] @ (tangent3/np.linalg.norm(tangent3))
    if kind == "Shoulder":
        distance = np.linalg.norm(p3-p0)
        p1 = p0+np.array((sign, 0, .10))*distance*.5
        p2 = p3-tangent3*distance*.4
    else:
        tangent0 = profile(high-.005)-profile(high+.005)
        tangent0 /= np.linalg.norm(tangent0)
        p1 = p0+tangent0*(high-low)*.4
        p2 = p3-tangent3*(high-low)*.4
    center, tangent, curvature = bezier((p0, p1, p2, p3), t)
    offset = rest-profile(z)
    rest_tangent = profile(z-.005)-profile(z+.005)
    desired = current.copy()
    if kind == "Shoulder":
        angle = np.arctan2(tangent[:, 0], -tangent[:, 2])-np.arctan2(rest_tangent[:, 0], -rest_tangent[:, 2])
        normal = np.stack((np.cos(angle), np.zeros(len(t)), np.sin(angle)), axis=1)
        desired = center+normal*offset[:, 0, None]
        desired[:, 1] += offset[:, 1]
    else:
        angle = np.arctan2(-tangent[:, 1], -tangent[:, 2])-np.arctan2(-rest_tangent[:, 1], -rest_tangent[:, 2])
        dy = offset[:, 1].copy()
        compression = np.sin(np.pi*t)**2
        # Keep the inner section inside its local bend radius to avoid fold inversion.
        limit = .65/np.maximum(curvature, 1e-6)
        dy = np.where(dy < 0, -limit*np.tanh(-dy/limit), dy*(1+.04*compression))
        desired = center.copy()
        desired[:, 0] = rest[:, 0]+offset[:, 0]*.035*compression
        desired[:, 1] += dy*np.cos(angle)
        desired[:, 2] -= dy*np.sin(angle)
    lower_blend, upper_blend = (.11, .045) if kind == "Shoulder" else (.09, .08)
    mask = np.array([smoothstep(low, low+lower_blend, value)*(1-smoothstep(high-upper_blend, high, value)) for value in z])
    target = current+(desired-current)*mask[:, None]
    edge_indices = np.empty(len(obj.data.edges)*2, dtype=np.int32)
    obj.data.edges.foreach_get("vertices", edge_indices)
    edges = edge_indices.reshape(-1, 2)
    a = np.concatenate((edges[:, 0], edges[:, 1]))
    b = np.concatenate((edges[:, 1], edges[:, 0]))
    counts = np.bincount(a, minlength=len(rest))
    for _ in range(12):
        for factor in (.45, -.47):
            total = np.column_stack([np.bincount(a, weights=target[b, i], minlength=len(rest)) for i in range(3)])
            target += factor*mask[:, None]*(total/counts[:, None]-target)
    return target


def add_correctives(rig):
    records = []
    for side, sign in (("L", 1), ("R", -1)):
        obj = bpy.data.objects[f"White_Arm_{side}"]
        obj.shape_key_add(name="Basis")
        for kind, angle in (("Shoulder", 90), ("Shoulder", 145), ("Elbow", 90), ("Elbow", 130)):
            recovery.reset(rig)
            primary = f"{'UpperArm' if kind=='Shoulder' else 'Forearm'}_{side}"
            changes = {primary: (0, -sign*math.radians(angle), 0) if kind == "Shoulder" else (-math.radians(angle), 0, 0)}
            recovery.apply_pose(rig, changes)
            matrices = lbs_matrices(obj, rig)
            rest = coordinates(obj.data)
            current = np.einsum("nij,nj->ni", matrices[:, :3, :3], rest)+matrices[:, :3, 3]
            desired = corrective_target(obj, rig, kind, side, current, matrices)
            delta = np.linalg.solve(matrices[:, :3, :3], (desired-current)[..., None])[..., 0]
            name = f"{kind}_{angle}_{side}"
            key = obj.shape_key_add(name=name)
            key.data.foreach_set("co", (rest+delta).ravel())
            key.value = 0
            records.append({"name": name, "mesh": obj.name, "primary": primary,
                            "kind": kind, "angle_deg": angle, "default": 0,
                            "affected_vertices": int(np.count_nonzero(np.linalg.norm(delta, axis=1) > 1e-7)),
                            "max_rest_delta_m": float(np.linalg.norm(delta, axis=1).max())})
    recovery.reset(rig)
    for record in records:
        primary, kind, angle = record["primary"], record["kind"], record["angle_deg"]
        side = primary[-1]
        sign = 1 if side == "L" else -1
        row = np.array(rig.data.bones[primary].matrix_local.to_3x3())[1 if kind == "Shoulder" else 0]
        scale = -sign if kind == "Shoulder" else -1
        projection = "+".join(f"({scale*c:.9f}*{v})" for c, v in zip(row, ("x", "y", "z")))
        a = f"(2*atan2(max(0,{projection}),abs(w)))"
        def ramp(low, high):
            return f"min(1,max(0,({a}-{math.radians(low):.9f})/{math.radians(high-low):.9f}))"
        if kind == "Shoulder":
            expression = ramp(60, 90)+f"*(1-{ramp(90, 145)})" if angle == 90 else ramp(90, 145)
        else:
            expression = ramp(50, 90)+f"*(1-{ramp(90, 130)})" if angle == 90 else ramp(90, 130)
        key = bpy.data.objects[record["mesh"]].data.shape_keys.key_blocks[record["name"]]
        driver = key.driver_add("value").driver
        driver.expression = expression
        for i, variable in enumerate(("w", "x", "y", "z")):
            item = driver.variables.new()
            item.name = variable
            item.type = "SINGLE_PROP"
            item.targets[0].id = rig
            item.targets[0].data_path = f'pose.bones["{primary}"].rotation_quaternion[{i}]'
        record["driver_expression"] = expression
    recovery.reset(rig)
    return records


def checks():
    result = recovery.poses()
    for side, sign in (("L", 1), ("R", -1)):
        for angle in (0, 30, 60, 90, 120, 145, 160):
            result[f"shoulder_{side}_{angle:03}"] = {
                f"UpperArm_{side}": (0, -sign*math.radians(angle), 0)}
        for angle in (0, 30, 60, 90, 110, 130, 145):
            result[f"elbow_{side}_{angle:03}"] = {
                f"Forearm_{side}": (-math.radians(angle), 0, 0)}
        result[f"F2_closed_{side}"] = {f"{digit}_{side}": (-.95, 0, 0) for digit in ("Index", "Middle", "Ring")}
        result[f"F2_closed_{side}"][f"Thumb_{side}"] = (0, 0, -sign*.45)
        result[f"F3_hold_{side}"] = {f"Index_{side}": (-.5, 0, 0), f"Middle_{side}": (-.6, 0, 0),
                                   f"Ring_{side}": (-.65, 0, 0), f"Thumb_{side}": (-.2, 0, -sign*.35)}
    return result


def studio_signature():
    scene = bpy.context.scene
    return {"engine": scene.render.engine, "exposure": scene.view_settings.exposure,
            "gamma": scene.view_settings.gamma, "look": scene.view_settings.look,
            "view_transform": scene.view_settings.view_transform,
            "world": list(scene.world.color),
            "lights": [{"name": o.name, "type": o.data.type, "energy": o.data.energy,
                        "color": list(o.data.color), "matrix": [list(r) for r in o.matrix_world]}
                       for o in sorted(scene.objects, key=lambda o: o.name) if o.type == "LIGHT"]}


def panel_views(rig, label):
    originals = recovery.visible_meshes()
    for side, sign in (("L", 1), ("R", -1)):
        for obj in originals:
            obj.hide_render = obj.name not in (f"White_Arm_{side}", f"Elbow_Panel_Seam_{side}")
        for angle in (0, 60, 130):
            recovery.apply_pose(rig, {f"Forearm_{side}": (-math.radians(angle), 0, 0)})
            views = {"front": (sign*1.2, -5, 1.2), "back": (sign*1.2, 5, 1.2),
                     "outside": (sign*5, -1, 1.2), "inside": (-sign*5, -1, 1.2),
                     "quarter": (sign*4, -4, 1.6)}
            for view, location in views.items():
                recovery.render_frame(f"{label}_panel_{side}_{angle:03}_{view}", location,
                                      (sign*.49, -.07, .94), .85)
        for obj in originals:
            obj.hide_render = False
    recovery.reset(rig)


def hand_views(rig, label):
    for side, sign in (("L", 1), ("R", -1)):
        poses = {"neutral": {}, "closed": checks()[f"F2_closed_{side}"], "hold": checks()[f"F3_hold_{side}"]}
        if side == "L":
            poses["point"] = checks()["F1_point"]
        for name, changes in poses.items():
            recovery.apply_pose(rig, changes)
            recovery.render_frame(f"{label}_hand_{side}_{name}", (sign*1.7, -4, .8),
                                  (sign*.50, -.075, .475), .40)
    recovery.reset(rig)


def transition_views(rig, label):
    recovery.reset(rig)
    recovery.render_frame(f"{label}_waist_front", (0, -5, .8), (0, -.02, .50), 1.0)
    recovery.render_frame(f"{label}_waist_side", (5, -.1, 1), (0, -.02, .50), 1.05)
    recovery.apply_pose(rig, checks()["C9"])
    recovery.render_frame(f"{label}_hip_flex", (3, -5, .9), (0, 0, .4), 1.0)
    recovery.reset(rig)


def arm_pose_metrics():
    records = {}
    graph = bpy.context.evaluated_depsgraph_get()
    for side in ("L", "R"):
        obj = bpy.data.objects[f"White_Arm_{side}"]
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        indices = np.empty(len(mesh.loop_triangles)*3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", indices)
        vertices = coordinates(mesh)
        triangles = vertices[indices.reshape(-1, 3)]
        volume = abs(np.einsum("ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])).sum())/6
        areas = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)/2
        records[side] = {"volume_m3": float(volume), "near_zero_triangles": int(np.count_nonzero(areas < 1e-12))}
        evaluated.to_mesh_clear()
    return records


def baseline_views():
    signature = None
    for label, source in (("detailed", ASSETS/"source/bagusmax_white_anatomy_detailed.blend"), ("v3", SOURCE)):
        bpy.ops.wm.open_mainfile(filepath=str(source))
        current = studio_signature()
        if signature is not None:
            assert current == signature, "Baseline studio differs"
        signature = current
        rig = bpy.data.objects["Bagusmax_Rig"]
        recovery.reset(rig)
        recovery.neutral_views(label)
        panel_views(rig, label)
        if label == "v3":
            metrics = {}
            for name, changes in checks().items():
                render_pose(rig, name, changes, label)
                metrics[name] = arm_pose_metrics()
            hand_views(rig, label)
            transition_views(rig, label)
            (FOLDER/"baseline_pose_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return signature


def morph_inputs(changes):
    values = {}
    for side, sign in (("L", 1), ("R", -1)):
        for primary, kind in (("UpperArm", "Shoulder"), ("Forearm", "Elbow")):
            x, y, z = [v/2 for v in changes.get(f"{primary}_{side}", (0, 0, 0))]
            w = math.cos(x)*math.cos(y)*math.cos(z)+math.sin(x)*math.sin(y)*math.sin(z)
            component = (math.cos(x)*math.sin(y)*math.cos(z)+math.sin(x)*math.cos(y)*math.sin(z))*(-sign) if kind == "Shoulder" else -(math.sin(x)*math.cos(y)*math.cos(z)-math.cos(x)*math.sin(y)*math.sin(z))
            angle = math.degrees(2*math.atan2(max(0, component), abs(w)))
            if kind == "Shoulder":
                high = min(1, max(0, (angle-90)/55))
                values[f"Shoulder_90_{side}"] = min(1, max(0, (angle-60)/30))*(1-high)
                values[f"Shoulder_145_{side}"] = high
            else:
                high = min(1, max(0, (angle-90)/40))
                values[f"Elbow_90_{side}"] = min(1, max(0, (angle-50)/40))*(1-high)
                values[f"Elbow_130_{side}"] = high
    return values


def source_positions():
    graph = bpy.context.evaluated_depsgraph_get()
    result = {}
    for obj in recovery.visible_meshes():
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        points = coordinates(mesh)
        world = np.array(obj.matrix_world)
        points = points @ world[:3, :3].T+world[:3, 3]
        result[obj.name] = points @ BLENDER_TO_GLTF.T
        evaluated.to_mesh_clear()
    return result


def source_normals(name):
    obj = bpy.data.objects[name]
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    values = np.empty(len(mesh.vertices)*3)
    mesh.vertices.foreach_get("normal", values)
    matrix = np.linalg.inv(np.array(obj.matrix_world)[:3, :3]).T
    values = values.reshape(-1, 3) @ matrix.T @ BLENDER_TO_GLTF.T
    values /= np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-12)
    evaluated.to_mesh_clear()
    return values


def export_correspondence(exported):
    source = source_positions()
    mapping = []
    for part in exported.primitives:
        points = source[part["name"]]
        tree = KDTree(len(points))
        for i, point in enumerate(points):
            tree.insert(point, i)
        tree.balance()
        nearest = [tree.find(p) for p in part["position"]]
        assert max(p[2] for p in nearest) < 1e-5
        mapping.append(np.array([p[1] for p in nearest]))
    return mapping


def repair_normal_targets(rig, morphs):
    recovery.reset(rig)
    exported = GLBSkin(GLB)
    mapping = export_correspondence(exported)
    overrides = {}
    records = []
    for record in morphs:
        side = record["primary"][-1]
        sign = 1 if side == "L" else -1
        angle = math.radians(record["angle_deg"])
        changes = {record["primary"]: (0, -sign*angle, 0) if record["kind"] == "Shoulder" else (-angle, 0, 0)}
        recovery.apply_pose(rig, changes)
        matrices = exported.skin_matrices(changes)
        for part, indices in zip(exported.primitives, mapping):
            if part["name"] != record["mesh"]:
                continue
            desired = source_normals(part["name"])[indices]
            blended = exported.blend(part, matrices)[:, :3, :3]
            normal = np.linalg.solve(blended, desired[..., None])[..., 0]
            normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
            target = part["target_names"].index(record["name"])
            accessor = part["target_accessors"][target]["NORMAL"]
            overrides[accessor] = normal-part["normal"]
            records.append({"name": record["name"], "vertices": len(normal),
                            "normal_deltas_over_1e4": int(np.count_nonzero(np.linalg.norm(overrides[accessor], axis=1) > 1e-4))})
    exported.replace_normal_targets(overrides)
    recovery.reset(rig)
    return {"convention": "rigid per-joint blended normal matrices; pose-baked morph NORMAL deltas", "targets": records}


def inspect_asset(rig):
    meshes = {}
    bounds = []
    for obj in recovery.visible_meshes():
        points = coordinates(obj.data)
        world = np.array(obj.matrix_world)
        points = points @ world[:3, :3].T+world[:3, 3]
        bounds.append(points)
        record = {"vertices": len(points), "bounds": [points.min(axis=0).tolist(), points.max(axis=0).tolist()],
                  "custom_normals": obj.data.has_custom_normals,
                  "flat_faces": sum(not p.use_smooth for p in obj.data.polygons)}
        if obj.name.startswith("White_Arm"):
            indices = np.array([e.vertices[:] for e in obj.data.edges])
            edge_vectors = points[indices[:, 0]]-points[indices[:, 1]]
            z = (points[indices[:, 0], 2]+points[indices[:, 1], 2])/2
            band = (z > .67) & (z < 1.35)
            record["joint_max_longitudinal_step_m"] = float(abs(edge_vectors[band, 2]).max())
            record["joint_long_edges_over_20mm"] = int(np.count_nonzero(band & (abs(edge_vectors[:, 2]) > .02)))
        color = obj.data.color_attributes.get("VinylSurface")
        if color:
            values = np.empty(len(color.data)*4)
            color.data.foreach_get("color", values)
            record["linear_color_min"] = values.reshape(-1, 4)[:, :3].min(axis=0).tolist()
        record["preserve_volume"] = any(m.type == "ARMATURE" and m.use_deform_preserve_volume for m in obj.modifiers)
        meshes[obj.name] = record
    all_points = np.concatenate(bounds)
    return {"meshes": meshes, "full_bounds": [all_points.min(axis=0).tolist(), all_points.max(axis=0).tolist()],
            "joints": [{"name": b.name, "parent": b.parent.name if b.parent else None,
                        "head": list(b.head_local), "tail": list(b.tail_local),
                        "matrix": [list(row) for row in b.matrix_local]} for b in rig.data.bones],
            "actions": len(bpy.data.actions),
            "nla_tracks": sum(len(o.animation_data.nla_tracks) for o in bpy.context.scene.objects if o.animation_data)}


def render_independent(name, result):
    originals = recovery.visible_meshes()
    for obj in originals:
        obj.hide_render = True
    temporary = []
    for part in result:
        mesh = bpy.data.meshes.new("Inspection_LBS")
        mesh.from_pydata((part["position"] @ BLENDER_TO_GLTF).tolist(), [], part["indices"].tolist())
        mesh.update()
        for face in mesh.polygons:
            face.use_smooth = True
        mesh.normals_split_custom_set_from_vertices((part["normal"] @ BLENDER_TO_GLTF).tolist())
        colors = part["colors"]
        if colors is not None:
            attribute = mesh.color_attributes.new(name="VinylSurface", type="FLOAT_COLOR", domain="POINT")
            if colors.shape[1] == 3:
                colors = np.column_stack((colors, np.ones(len(colors))))
            attribute.data.foreach_set("color", colors.ravel())
        original = bpy.data.objects[part["name"]]
        mesh.materials.append(original.data.materials[0])
        obj = bpy.data.objects.new("Inspection_LBS", mesh)
        bpy.context.collection.objects.link(obj)
        temporary.append((obj, mesh))
    recovery.render_frame(name, *CURRENT_CAMERA)
    for obj, mesh in temporary:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    for obj in originals:
        obj.hide_render = False


def verify_export(rig):
    global CURRENT_CAMERA
    source_state = {"actions": len(bpy.data.actions),
                    "nla_tracks": sum(len(o.animation_data.nla_tracks) for o in bpy.context.scene.objects if o.animation_data),
                    "max_pose_angle_rad": max(b.rotation_quaternion.angle for b in rig.pose.bones),
                    "max_corrective_weight": max(abs(k.value) for side in ("L", "R")
                        for k in list(bpy.data.objects[f"White_Arm_{side}"].data.shape_keys.key_blocks)[1:])}
    assert source_state["actions"] == 0 and source_state["nla_tracks"] == 0
    assert source_state["max_pose_angle_rad"] < 1e-5 and source_state["max_corrective_weight"] < 1e-5
    self_test()
    exported = GLBSkin(GLB)
    assert not exported.doc.get("animations")
    assert len(exported.doc["skins"][0]["joints"]) == 32
    recovery.reset(rig)
    mapping = export_correspondence(exported)
    names = [f"{kind}_{side}_{angle:03}" for kind, angle in
             (("shoulder", 90), ("shoulder", 120), ("shoulder", 145), ("elbow", 60), ("elbow", 90), ("elbow", 110), ("elbow", 130))
             for side in ("L", "R")]+["S0", "C2", "C5", "F1_point"]
    reports = {}
    for name in names:
        changes = checks()[name]
        recovery.apply_pose(rig, changes)
        inputs = morph_inputs(changes)
        for side in ("L", "R"):
            keys = bpy.data.objects[f"White_Arm_{side}"].data.shape_keys.key_blocks
            for key in list(keys)[1:]:
                assert abs(key.value-inputs[key.name]) < 1e-5, (name, key.name, key.value, inputs[key.name])
        expected = source_positions()
        result = exported.evaluate(changes, inputs)
        errors = [np.linalg.norm(part["position"]-expected[part["name"]][indices], axis=1)
                  for part, indices in zip(result, mapping)]
        error = np.concatenate(errors)
        reports[name] = {"max_position_error_m": float(error.max()),
                         "rms_position_error_m": float(np.sqrt(np.mean(error**2))),
                         "vertices": len(error), "pass": bool(error.max() < .0001)}
        normal_errors = []
        for part, indices in zip(result, mapping):
            if part["name"].startswith("White_Arm"):
                normals = source_normals(part["name"])[indices]
                normal_errors.extend(np.degrees(np.arccos(np.clip(np.sum(normals*part["normal"], axis=1), -1, 1))))
        reports[name]["arm_normal_error_degrees"] = {"p95": float(np.percentile(normal_errors, 95)), "max": float(np.max(normal_errors)),
                                                   "vertices_over_90_degrees": int(np.count_nonzero(np.array(normal_errors) > 90))}
        assert reports[name]["pass"], (name, reports[name])
        if name in ("shoulder_L_120", "shoulder_L_145", "shoulder_R_145", "elbow_L_110", "elbow_L_130", "elbow_R_130", "C2", "C5", "F1_point"):
            if name == "F1_point":
                CURRENT_CAMERA = ((1.7, -4, .8), (.50, -.075, .475), .4)
                recovery.render_frame(f"source_{name}", *CURRENT_CAMERA)
            else:
                render_pose(rig, f"source_{name}", changes)
            render_independent(f"glb_{name}", result)
    durations = []
    for _ in range(5):
        started = time.perf_counter()
        exported.evaluate(checks()["shoulder_L_145"], morph_inputs(checks()["shoulder_L_145"]))
        durations.append(time.perf_counter()-started)
    report = {"implementation": "NumPy glTF accessors + sparse morphs + hierarchy + inverse binds + LBS; no Blender skinning",
              "source_state": source_state,
              "poses": reports, "cpu_numpy_evaluation_ms": {"median": statistics.median(durations)*1000,
              "min": min(durations)*1000, "max": max(durations)*1000, "samples": len(durations)},
              "not_tested": ["OpenBagus renderer", "GPU skinning cost", "runtime FPS", "runtime VRAM"]}
    (FOLDER/"independent_skinning.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    recovery.reset(rig)
    return report


CURRENT_CAMERA = ((3, -5, 1.8), (0, 0, 1), 2.6)


def render_pose(rig, name, pose, prefix=None):
    global CURRENT_CAMERA
    recovery.apply_pose(rig, pose)
    side = "R" if "_R" in name else "L"
    sign = -1 if side == "R" else 1
    if "shoulder_" in name or name.startswith("S"):
        CURRENT_CAMERA = ((sign*2, -5, 2), (sign*.35, 0, 1.36), 1.55)
    elif "elbow_" in name or name.startswith("E"):
        CURRENT_CAMERA = ((sign*5, -2, 1.4), (sign*.48, -.10, .94), 1.0)
    else:
        CURRENT_CAMERA = ((3, -5, 1.8), (0, 0, 1), 2.6)
    recovery.render_frame(f"{prefix}_{name}" if prefix else name, *CURRENT_CAMERA)


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    if "--verify-only" in sys.argv:
        bpy.ops.wm.open_mainfile(filepath=str(OUTPUT))
        verify_export(bpy.data.objects["Bagusmax_Rig"])
        return
    existing = json.loads((REPORTS/"white_v3/asset_hashes.json").read_text(encoding="utf-8"))
    root = ASSETS.parents[1]
    paths = [root/p for p in existing]+[root/"docs/bagusmax_3d/WHITE_LIGHTING_SPEC.md"]
    preserved = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if "--after-only" in sys.argv:
        studio = json.loads((FOLDER/"asset_audit.json").read_text(encoding="utf-8"))["studio"]
    else:
        studio = baseline_views() if "--quick" not in sys.argv else None
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    if studio is not None:
        assert studio_signature() == studio
    before = inspect_asset(bpy.data.objects["Bagusmax_Rig"])
    rig = refine()
    morphs = add_correctives(rig)
    after = inspect_asset(rig)
    assert before["meshes"]["White_Head"]["bounds"] == after["meshes"]["White_Head"]["bounds"]
    for side in ("L", "R"):
        assert before["meshes"][f"White_Leg_{side}"]["bounds"] == after["meshes"][f"White_Leg_{side}"]["bounds"]
    assert np.max(abs(np.array(before["full_bounds"])-np.array(after["full_bounds"]))) < .003
    assert not after["actions"] and not after["nla_tracks"]
    geometry = recovery.audit(rig)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in recovery.visible_meshes()+[rig]:
        obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(GLB), export_format="GLB", use_selection=True,
        export_skins=True, export_animations=False, export_morph=True, export_yup=True,
        export_all_influences=False, export_morph_normal=True, export_try_sparse_sk=True,
        export_morph_animation=False)
    normal_patch = repair_normal_targets(rig, morphs)
    if "--quick" not in sys.argv:
        verify_export(rig)
    recovery.neutral_views("after")
    suite = checks()
    names = ("shoulder_L_090", "shoulder_L_145", "shoulder_R_145",
             "elbow_L_130", "elbow_R_130") if "--quick" in sys.argv else suite
    metrics = {}
    for name in names:
        render_pose(rig, name, suite[name])
        metrics[name] = arm_pose_metrics()
    (FOLDER/"pose_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    if "--quick" not in sys.argv:
        panel_views(rig, "v4")
        hand_views(rig, "v4")
        transition_views(rig, "v4")
    recovery.reset(rig)
    for path, digest in preserved.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    report = {"before": before, "after": after, "studio": studio, "mesh_audit": geometry, "morphs": morphs,
              "normal_patch": normal_patch, "preserved_sha256": preserved,
              "source_sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
              "glb_sha256": hashlib.sha256(GLB.read_bytes()).hexdigest()}
    (FOLDER/"asset_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"source": str(OUTPUT), "glb": str(GLB), "meshes": len(geometry), "morphs": len(morphs),
                      "triangles": sum(m["triangles"] for m in geometry.values()), "report": str(FOLDER/"asset_audit.json")}))


if __name__ == "__main__":
    main()
