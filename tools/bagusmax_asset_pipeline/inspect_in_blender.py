"""Round-trip the runtime GLB and render an equal-framing geometry baseline."""

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_white import ASSETS, REPORTS, ROOT, material, studio


def bounds(objects):
    graph = bpy.context.evaluated_depsgraph_get()
    points = []
    for obj in objects:
        obj = obj.evaluated_get(graph)
        mesh = obj.to_mesh()
        try:
            points.extend(obj.matrix_world @ vertex.co for vertex in mesh.vertices)
        finally:
            obj.to_mesh_clear()
    return [[min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]]


def frame(camera, filename, clay=False, pose_bounds=None):
    scene = bpy.context.scene
    camera.location = (0, -5, 1.02)
    camera.rotation_euler = (Vector((0,0,.845))-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.ortho_scale = 2.04
    if pose_bounds:
        low, high = pose_bounds
        center = Vector(((low[0]+high[0])/2,0,(low[2]+high[2])/2))
        camera.location = (center.x,-5,center.z+.2)
        camera.rotation_euler = (center-camera.location).to_track_quat("-Z","Y").to_euler()
        camera.data.ortho_scale = max(high[0]-low[0],high[2]-low[2])*1.2
    scene.view_layers[0].material_override = material("InspectionClay", (.43,.46,.49), .65) if clay else None
    scene.render.filepath = str(REPORTS/filename)
    bpy.ops.render.render(write_still=True)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(ASSETS/"runtime/bagusmax_white.glb"))
    bpy.context.view_layer.update()
    meshes = [obj for obj in bpy.context.scene.objects if obj.type=="MESH" and obj.visible_get()]
    runtime_bounds = bounds(meshes)
    assert len([obj for obj in bpy.context.scene.objects if obj.type=="ARMATURE"]) == 1
    camera = studio()
    frame(camera, "white_runtime_front.png")
    frame(camera, "white_runtime_clay_front.png", clay=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(ROOT/"assets/models/bagusmax_white.glb"))
    bpy.context.view_layer.update()
    meshes = [obj for obj in bpy.context.scene.objects if obj.type=="MESH" and obj.visible_get()]
    old_bounds = bounds(meshes)
    group = bpy.data.objects.new("BaselineHeightNormalization", None)
    bpy.context.collection.objects.link(group)
    for obj in list(bpy.context.scene.objects):
        if obj != group and obj.parent is None:
            obj.parent = group
    scale = (runtime_bounds[1][2]-runtime_bounds[0][2])/(old_bounds[1][2]-old_bounds[0][2])
    group.scale = (scale,scale,scale)
    group.location.z = runtime_bounds[0][2]-old_bounds[0][2]*scale
    bpy.context.view_layer.update()
    camera = studio()
    frame(camera, "baseline_clay_front.png", clay=True)

    bpy.ops.wm.open_mainfile(filepath=str(ASSETS/"source/bagusmax_white.blend"))
    rig = bpy.data.objects["Bagusmax_Rig"]
    for track in rig.animation_data.nla_tracks:
        track.mute = True
        if track.name == "WAVE":
            rig.animation_data.action = track.strips[0].action
            rig.animation_data.action_slot = track.strips[0].action_slot
    bpy.context.scene.frame_set(20)
    bpy.context.view_layer.update()
    meshes = [obj for obj in bpy.context.scene.objects if obj.type=="MESH" and obj.name!="Studio_Floor"]
    pose_bounds = bounds(meshes)
    assert all(abs(value)<3 for box in pose_bounds for value in box)
    frame(bpy.context.scene.camera, "white_wave_test.png", pose_bounds=pose_bounds)
    result = {"runtime_import":"PASS", "runtime_blender_bounds":runtime_bounds,
              "baseline_height_scale":scale, "wave_evaluated_bounds":pose_bounds,
              "wave_status":"RENDERED_FOR_VISUAL_REVIEW_NOT_COLLISION_CERTIFIED",
              "main_application_modified":False}
    (REPORTS/"white_roundtrip_validation.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
