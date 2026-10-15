"""Continue the refined Blender mesh with vinyl details and neutral rig review."""

import json
import math
import sys
import time
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector, Euler
from mathutils.kdtree import KDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_white import ASSETS, REPORTS, loft, sweep, material, mesh_object
from refine_white_anatomy import VIEWS, measure, control_group

SOURCE = ASSETS / "source/bagusmax_white_anatomy_refined.blend"
OUTPUT = ASSETS / "source/bagusmax_white_anatomy_detailed.blend"
GLB = ASSETS / "runtime/bagusmax_white_anatomy_detailed.glb"
REVIEW = REPORTS / "white_detail"


def smoothstep(low, high, value):
    t = max(0, min(1, (value-low)/(high-low)))
    return t*t*(3-2*t)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def finish_skin(obj, rig):
    mod = next((m for m in obj.modifiers if m.type == "ARMATURE"), None)
    if mod is None:
        mod = obj.modifiers.new("CharacterSkin", "ARMATURE")
    mod.object = rig
    mod.use_deform_preserve_volume = False
    obj.parent = None
    if not obj.data.uv_layers:
        activate(obj)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=.025)
        bpy.ops.object.mode_set(mode="OBJECT")


def arm_weights(obj, suffix):
    obj.vertex_groups.clear()
    groups = {n: obj.vertex_groups.new(name=n) for n in
              ("Chest",f"UpperArm_{suffix}",f"Forearm_{suffix}",f"Hand_{suffix}")}
    for v in obj.data.vertices:
        hand = 1-smoothstep(.49,.59,v.co.z)
        chest = .4*smoothstep(1.36,1.415,v.co.z)
        upper = smoothstep(.78,1.02,v.co.z)
        remainder = 1-hand-chest
        values = (chest,remainder*upper,remainder*(1-upper),hand)
        for g,w in zip(groups.values(),values):
            if w > 0:
                g.add([v.index],w,"REPLACE")
    for name,low,high in (("Shoulder",1.22,1.5),("Elbow",.72,1.0),
                          ("Wrist",.52,.62),("Hand",0,.56)):
        control_group(obj,f"Edit_{name}",lambda p,a=low,b=high:a<p.z<b)


def leg_weights():
    for suffix in ("L","R"):
        obj=bpy.data.objects[f"White_Leg_{suffix}"]
        groups={name:obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
                for name in (f"Thigh_{suffix}",f"Shin_{suffix}",f"Foot_{suffix}")}
        for v in obj.data.vertices:
            foot=1-smoothstep(.06,.14,v.co.z)
            thigh=smoothstep(.17,.32,v.co.z)
            values=((1-foot)*thigh,(1-foot)*(1-thigh),foot)
            for group,value in zip(groups.values(),values):
                group.add([v.index],value,"REPLACE")


def transfer_skin(detail, surface):
    tree = KDTree(len(surface.data.vertices))
    for v in surface.data.vertices:
        tree.insert(v.co, v.index)
    tree.balance()
    rig = bpy.data.objects["Bagusmax_Rig"]
    bone_names = set(rig.data.bones.keys())
    groups = {g.index:g.name for g in surface.vertex_groups if g.name in bone_names}
    target = {name:detail.vertex_groups.new(name=name) for name in groups.values()}
    for v in detail.data.vertices:
        _,index,_ = tree.find(v.co)
        weights = [(groups[g.group],g.weight) for g in surface.data.vertices[index].groups if g.group in groups]
        total = sum(w for _,w in weights)
        for name,w in weights:
            target[name].add([v.index],w/total,"REPLACE")
    finish_skin(detail,rig)


def replacement(obj, new):
    obj.data.use_fake_user = True
    obj.data = new.data
    bpy.data.objects.remove(new, do_unlink=True)
    obj.vertex_groups.clear()


def closed_sweep(name,points,radius,mat,sides=8):
    if (points[-1]-points[0]).length < .00001:
        points=points[:-1]
    obj=sweep(name,points,radius,mat,sides)
    bm=bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm,geom=[bm.faces[-1],bm.faces[-2]],context="FACES_ONLY")
    bm.verts.ensure_lookup_table()
    last=(len(points)-1)*sides
    for i in range(sides):
        j=(i+1)%sides
        bm.faces.new((bm.verts[last+i],bm.verts[last+j],bm.verts[j],bm.verts[i]))
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    for p in obj.data.polygons:
        p.use_smooth=True
    return obj


def hands():
    vinyl = bpy.data.materials["Vinyl_WarmWhite"]
    rig = bpy.data.objects["Bagusmax_Rig"]
    for suffix,sign in (("L",1),("R",-1)):
        arm = bpy.data.objects[f"White_Arm_{suffix}"]
        arm.data.use_fake_user = True
        arm.data = arm.data.copy()
        bm = bmesh.new()
        bm.from_mesh(arm.data)
        bmesh.ops.bisect_plane(bm, geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                                     dist=.00001,plane_co=(0,0,.555),plane_no=(0,0,1),clear_inner=True)
        edges = [e for e in bm.edges if e.is_boundary]
        bmesh.ops.holes_fill(bm,edges=edges,sides=0)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.to_mesh(arm.data)
        bm.free()
        palm = loft(f"Hand_Edit_{suffix}",[(sign*.503,-.072,z,rx,ry) for z,rx,ry in
                    ((.443,.031,.035),(.465,.070,.052),(.49,.086,.061),
                     (.522,.082,.067),(.563,.075,.085),(.584,.057,.073),
                     (.609,.025,.035))],vinyl,32,1)
        parts = [palm]
        for x,y,end,radius in ((.445,-.082,.360,.029),(.504,-.09,.348,.031),
                              (.563,-.071,.374,.029),(.403,-.105,.415,.033)):
            pts = [(sign*x,y,end,.003,.004),(sign*x,y-.004,end+.008,radius*.7,radius*.75),
                   (sign*x,y,end+.023,radius,radius),
                   (sign*(x+.006),y+.010,.467 if x>.42 else .490,radius,radius*1.1),
                   (sign*(x+.018),y+.014,.505 if x>.42 else .527,radius*.6,radius*.7)]
            parts.append(loft(f"Finger_Edit_{suffix}",pts,vinyl,24,1))
        bpy.ops.object.select_all(action="DESELECT")
        for obj in parts:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = palm
        bpy.ops.object.join()
        remesh = palm.modifiers.new("LocalHandUnion","REMESH")
        remesh.mode,remesh.voxel_size = "VOXEL",.0035
        remesh.use_smooth_shade = True
        bpy.ops.object.modifier_apply(modifier=remesh.name)
        relax = palm.modifiers.new("LocalHandRelax","SMOOTH")
        relax.factor,relax.iterations = .5,4
        bpy.ops.object.modifier_apply(modifier=relax.name)
        activate(arm)
        union = arm.modifiers.new("WristSurfaceUnion","BOOLEAN")
        union.operation,union.solver,union.object = "UNION","EXACT",palm
        bpy.ops.object.modifier_move_up(modifier=union.name)
        bpy.ops.object.modifier_apply(modifier=union.name)
        bpy.data.objects.remove(palm,do_unlink=True)
        bm=bmesh.new()
        bm.from_mesh(arm.data)
        wrist=[v for v in bm.verts if .525<v.co.z<.615]
        for _ in range(10):
            bmesh.ops.smooth_vert(bm,verts=wrist,factor=.45,use_axis_x=True,use_axis_y=True,use_axis_z=True)
        bmesh.ops.dissolve_degenerate(bm,dist=.000001,edges=list(bm.edges))
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.to_mesh(arm.data)
        bm.free()
        arm.data.update()
        for p in arm.data.polygons:
            p.use_smooth = True
        arm_weights(arm,suffix)
        finish_skin(arm,rig)


def surface_front(obj,x,z,offset):
    hit,p,_,_ = obj.ray_cast((x,-2,z),(0,1,0))
    if not hit:
        raise ValueError(f"No surface at {obj.name}: {x},{z}")
    return Vector((x,p.y-offset,z))


def face_contact():
    head = bpy.data.objects["White_Head"]
    for name in ("Eye_L","Eye_R"):
        obj = bpy.data.objects[name]
        half = len(obj.data.vertices)//2
        for v in obj.data.vertices:
            v.co = surface_front(head,v.co.x,v.co.z,.0009 if v.index < half else .00015)
        obj.data.update()
    bridge = bpy.data.objects["Eye_ContourBridge"]
    for row in range(33):
        verts = list(bridge.data.vertices)[row*12:(row+1)*12]
        center = sum((v.co for v in verts),Vector())/12
        target = surface_front(head,center.x,center.z,.0011)
        for v in verts:
            v.co += target-center
    bridge.data.update()


def belly():
    torso = bpy.data.objects["White_Torso"]
    for v in torso.data.vertices:
        p = v.co
        if p.z < .50:
            p.z += .025*math.exp(-((p.z-.40)/.05)**2)*max(0,1-abs(p.x)/.26)
    torso.data.update()


def port():
    torso = bpy.data.objects["White_Torso"]
    mat = bpy.data.materials["AccessPort_White"]
    mat.diffuse_color = (.75,.76,.745,1)
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = mat.diffuse_color
    cx,cz,r = .175,1.300,.0365
    ring = [surface_front(torso,cx+r*math.cos(t),cz+r*math.sin(t),.00115)
            for t in [i*2*math.pi/128 for i in range(129)]]
    new = closed_sweep("Port_Rim_Edit",ring,.00065,mat,10)
    rim = bpy.data.objects["Chest_Access_Port"]
    replacement(rim,new)
    transfer_skin(rim,torso)
    points = []
    controls = [(-r*.96,.001),(-.024,.003),(-.017,.010),(-.006,.010),
                (.003,.003),(.016,.001),(r*.96,-.005)]
    for i in range(len(controls)-1):
        a,b = controls[i],controls[i+1]
        for j in range(8):
            t = j/8
            x,z = cx+a[0]*(1-t)+b[0]*t,cz+a[1]*(1-t)+b[1]*t
            points.append(surface_front(torso,x,z,.00175))
    points.append(surface_front(torso,cx+controls[-1][0],cz+controls[-1][1],.00175))
    detail = bpy.data.objects["Chest_Access_Detail"]
    replacement(detail,sweep("Port_Latch_Edit",points,.00062,mat,8))
    transfer_skin(detail,torso)
    vertices = [surface_front(torso,cx,cz,.0012)]
    for i in range(64):
        t = i*2*math.pi/64
        vertices.append(surface_front(torso,cx+.0356*math.cos(t),cz+.0356*math.sin(t),.0012))
    lid = mesh_object("Chest_Access_Lid",vertices,[(0,i+1,(i+1)%64+1) for i in range(64)],mat)
    solid = lid.modifiers.new("ShallowLidThickness","SOLIDIFY")
    solid.thickness = .0004
    activate(lid)
    bpy.ops.object.modifier_apply(modifier=solid.name)
    transfer_skin(lid,torso)


def vinyl_panels():
    panel = material("Vinyl_Panel",(.735,.742,.728),.52)
    seam = material("Vinyl_Seam",(.73,.735,.72),.56)
    for suffix,sign in (("L",1),("R",-1)):
        arm = bpy.data.objects[f"White_Arm_{suffix}"]
        arm.data.materials.append(panel)
        for poly in arm.data.polygons:
            center = poly.center
            if ((center.y+.01)/.128)**2+((center.z-.965)/.195)**2 < 1 and sign*center.x > .53:
                poly.material_index = len(arm.data.materials)-1
        points=[]
        for i in range(129):
            t=i*2*math.pi/128
            y,z=-.01+.128*math.cos(t),.965+.195*math.sin(t)
            hit,p,normal,_=arm.ray_cast((sign*2,y,z),(-sign,0,0))
            if hit:
                points.append(p+normal*.0005)
        boundary=closed_sweep(f"Elbow_Panel_Seam_{suffix}",points,.00055,seam,8)
        transfer_skin(boundary,arm)
    torso=bpy.data.objects["White_Torso"]
    points=[]
    for i in range(161):
        t=i*2*math.pi/160
        direction=Vector((math.cos(t),math.sin(t),0))
        hit,p,normal,_=torso.ray_cast((0,-.045,.80),direction)
        if not hit:
            raise ValueError("Torso seam ray failed")
        points.append(p+normal*.0005)
    seam_mesh=closed_sweep("Torso_Vinyl_Seam",points,.00042,seam,8)
    transfer_skin(seam_mesh,torso)


def meshes():
    return [o for o in bpy.context.scene.objects if o.type=="MESH" and o.name!="Studio_Floor"]


def render(label):
    scene=bpy.context.scene
    camera=scene.camera
    scene.render.resolution_x=scene.render.resolution_y=640
    views=dict(VIEWS)
    views.update(three_quarter_right=((-3,-5,1.75),(0,0,.845),2.04),
                 hand=((1.7,-4,.8),(.50,-.075,.475),.36))
    for name,(loc,target,scale) in views.items():
        camera.location=loc
        camera.rotation_euler=(Vector(target)-camera.location).to_track_quat("-Z","Y").to_euler()
        camera.data.ortho_scale=scale
        scene.render.filepath=str(REVIEW/f"{label}_{name}.png")
        bpy.ops.render.render(write_still=True)


def reset(rig):
    for b in rig.pose.bones:
        b.rotation_mode="XYZ"
        b.rotation_euler=(0,0,0)
        b.scale=(1,1,1)
    bpy.context.view_layer.update()


def shoulder_pivots():
    rig=bpy.data.objects["Bagusmax_Rig"]
    activate(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    for suffix,sign in (("L",1),("R",-1)):
        pivot=Vector((sign*.24,0,1.37))
        rig.data.edit_bones[f"Shoulder_{suffix}"].tail=pivot
        rig.data.edit_bones[f"UpperArm_{suffix}"].head=pivot
    bpy.ops.object.mode_set(mode="OBJECT")


def point_bone(rig,name,direction):
    bone=rig.pose.bones[name]
    delta=(bone.bone.tail_local-bone.bone.head_local).rotation_difference(Vector(direction))
    basis=bone.bone.matrix_local.to_quaternion()
    bone.rotation_euler=(basis.inverted() @ delta @ basis).to_euler()


def raised_arm(rig,suffix):
    sign=1 if suffix=="L" else -1
    upper=rig.pose.bones[f"UpperArm_{suffix}"]
    fore=rig.pose.bones[f"Forearm_{suffix}"]
    delta=(upper.bone.tail_local-upper.bone.head_local).rotation_difference(Vector((sign*.3,-.02,.025)))
    fore_delta=(fore.bone.tail_local-fore.bone.head_local).rotation_difference(Vector((sign*.08,-.03,.32)))
    basis=upper.bone.matrix_local.to_quaternion()
    upper.rotation_euler=(basis.inverted() @ delta @ basis).to_euler()
    basis=fore.bone.matrix_local.to_quaternion()
    fore.rotation_euler=(basis.inverted() @ delta.inverted() @ fore_delta @ basis).to_euler()


def volume(obj):
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh=evaluated.to_mesh()
    mesh.calc_loop_triangles()
    value=abs(sum(mesh.vertices[t.vertices[0]].co.dot(
                  mesh.vertices[t.vertices[1]].co.cross(mesh.vertices[t.vertices[2]].co))
                  for t in mesh.loop_triangles)/6)
    evaluated.to_mesh_clear()
    return value


def pose_tests(rig):
    primary=[bpy.data.objects[n] for n in ("White_Torso","White_Arm_L","White_Arm_R","White_Leg_L","White_Leg_R")]
    baseline={o.name:volume(o) for o in primary}
    tests={
        "T1_rest":{}, "T2_left_arm_raised":{},
        "T3_right_arm_raised":{},
        "T4_elbow_flexion":{"Forearm_L":("point",(0,-.35,.04))},
        "T5_hug_forward":{"UpperArm_L":("point",(.10,-.38,-.12)),
                           "UpperArm_R":("point",(-.10,-.38,-.12))},
        "T6_head_left":{"Head":("euler",(0,.25,0))},
        "T6_head_right":{"Head":("euler",(0,-.25,0))},
        "T7_torso_forward":{"Spine":("euler",(.25,0,0))},
        "T8_torso_side":{"Spine":("euler",(0,.20,0))},
        "T9_leg":{"Thigh_L":("euler",(.20,0,0))},
        "T10_rotation":{"Root":("euler",(0,0,math.pi))},
    }
    results={}
    camera=bpy.context.scene.camera
    camera.location=(0,-5,1.2)
    camera.rotation_euler=(Vector((0,0,1.0))-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.ortho_scale=2.7
    for name,changes in tests.items():
        reset(rig)
        if name in ("T2_left_arm_raised","T3_right_arm_raised"):
            raised_arm(rig,"L" if name.startswith("T2") else "R")
        for bone,(mode,angles) in changes.items():
            if mode=="point":
                point_bone(rig,bone,angles)
            else:
                posed=rig.pose.bones[bone]
                basis=posed.bone.matrix_local.to_quaternion()
                posed.rotation_euler=(basis.inverted() @ Euler(angles).to_quaternion() @ basis).to_euler()
        bpy.context.view_layer.update()
        ratios={o.name:round(volume(o)/baseline[o.name],4) for o in primary}
        results[name]={"mesh_volume_ratio":ratios,
                       "volume_flags":[n for n,r in ratios.items() if not .85<r<1.15],
                       "collision_certified":False}
        bpy.context.scene.render.filepath=str(REVIEW/f"pose_{name}.png")
        bpy.ops.render.render(write_still=True)
        if name.startswith(("T2","T4","T5")):
            camera.location=(5,0,1.2)
            camera.rotation_euler=(Vector((0,0,1.0))-camera.location).to_track_quat("-Z","Y").to_euler()
            bpy.context.scene.render.filepath=str(REVIEW/f"pose_{name}_side.png")
            bpy.ops.render.render(write_still=True)
            camera.location=(0,-5,1.2)
            camera.rotation_euler=(Vector((0,0,1.0))-camera.location).to_track_quat("-Z","Y").to_euler()
    reset(rig)
    return results


def audit(rig):
    result={}
    for obj in meshes():
        obj.data.calc_loop_triangles()
        bm=bmesh.new()
        bm.from_mesh(obj.data)
        nonmanifold=sum(not e.is_manifold for e in bm.edges)
        bm.free()
        groups={g.index for g in obj.vertex_groups if g.name in rig.data.bones}
        errors=0
        influences=0
        for v in obj.data.vertices:
            weights=[g.weight for g in v.groups if g.group in groups]
            influences=max(influences,len(weights))
            if not weights or abs(sum(weights)-1)>.001 or any(w<0 for w in weights):
                errors+=1
        result[obj.name]={"triangles":len(obj.data.loop_triangles),"nonmanifold_edges":nonmanifold,
                          "duplicate_positions_1e_7":len(obj.data.vertices)-len({tuple(round(c,7) for c in v.co) for v in obj.data.vertices}),
                          "degenerate_triangles":sum(t.area<1e-12 for t in obj.data.loop_triangles),
                          "weight_errors":errors,"max_influences":influences}
        assert errors==0,(obj.name,errors)
    return result


def supplement():
    scene=bpy.context.scene
    camera=scene.camera
    location,target,scale=VIEWS["head"]
    camera.location=location
    camera.rotation_euler=(Vector(target)-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.ortho_scale=scale
    for percent in (25,50,100,150):
        scene.render.resolution_x=scene.render.resolution_y=round(640*percent/100)
        scene.render.filepath=str(REVIEW/f"head_scale_{percent}.png")
        bpy.ops.render.render(write_still=True)
    scene.render.resolution_x=scene.render.resolution_y=640
    loc,target,scale=VIEWS["chest_port"]
    camera.location=loc
    camera.rotation_euler=(Vector(target)-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.ortho_scale=scale
    key=bpy.data.objects["Key"]
    original=key.location.copy()
    original_rotation=key.rotation_euler.copy()
    key.location=(-3,-.5,2)
    key.rotation_euler=(Vector((.175,0,1.3))-key.location).to_track_quat("-Z","Y").to_euler()
    scene.render.filepath=str(REVIEW/"port_raking_light.png")
    bpy.ops.render.render(write_still=True)
    key.location, key.rotation_euler=original,original_rotation
    scene.view_layers[0].material_override=material("Detail_Clay",(.43,.46,.49),.65)
    loc,target,scale=VIEWS["front"]
    camera.location=loc
    camera.rotation_euler=(Vector(target)-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.ortho_scale=scale
    scene.render.filepath=str(REVIEW/"detailed_clay_front.png")
    bpy.ops.render.render(write_still=True)
    scene.view_layers[0].material_override=None


def main():
    REVIEW.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    before=measure()
    if "--after-only" not in sys.argv:
        render("previous")
    belly()
    shoulder_pivots()
    hands()
    leg_weights()
    face_contact()
    port()
    vinyl_panels()
    rig=bpy.data.objects["Bagusmax_Rig"]
    for obj in meshes():
        finish_skin(obj,rig)
    reset(rig)
    mesh_audit=audit(rig)
    after=measure()
    bpy.context.preferences.filepaths.save_version=0
    camera=bpy.context.scene.camera
    camera.location=(0,-5,1.02)
    camera.rotation_euler=(Vector((0,0,.845))-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.ortho_scale=2.04
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes()+[rig]:
        obj.select_set(True)
    start=time.perf_counter()
    bpy.ops.export_scene.gltf(filepath=str(GLB),export_format="GLB",use_selection=True,
        export_yup=True,export_animations=False,export_skins=True,export_all_influences=False)
    export_seconds=time.perf_counter()-start
    render("detailed")
    tests=pose_tests(rig)
    supplement()
    assert not bpy.data.actions
    report={"before":before,"after":after,"meshes":mesh_audit,"temporary_poses":tests,
            "joint_count":len(rig.data.bones),"actions":0,"export_seconds":round(export_seconds,3),
            "renderer_fps":None,"runtime_gpu_memory":None,"collision_certified":False,
            "surface_transfer":"nearest mesh vertex weights for seam/port geometry",
            "finger_articulation":"No finger joints; Hand joint only"}
    (REVIEW/"asset_audit.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"triangles":sum(m["triangles"] for m in mesh_audit.values()),
                      "mesh_count":len(mesh_audit),"joints":len(rig.data.bones),
                      "defects":{n:m for n,m in mesh_audit.items() if m["nonmanifold_edges"] or m["degenerate_triangles"]}},indent=2))


if __name__=="__main__":
    main()
