"""Recover local anatomy and standard-joint deformation from the detailed asset."""

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import bpy
import bmesh
from mathutils import Euler, Quaternion, Vector
from mathutils.kdtree import KDTree

sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_white import ASSETS, REPORTS, material
from detail_white_anatomy import smoothstep, activate
from refine_white_anatomy import VIEWS

SOURCE=ASSETS/"source/bagusmax_white_anatomy_detailed.blend"
OUTPUT=ASSETS/"source/bagusmax_white_anatomy_v3.blend"
GLB=ASSETS/"runtime/bagusmax_white_anatomy_v3.glb"
REVIEW=REPORTS/"white_v3"
HELPERS={f"{kind}Volume_{side}":f"{primary}_{side}" for side in ("L","R")
         for kind,primary in (("Shoulder","UpperArm"),("Elbow","Forearm"))}


def reset(rig):
    for bone in rig.pose.bones:
        bone.rotation_mode="QUATERNION"
        bone.rotation_quaternion=Quaternion()
        bone.scale=(1,1,1)
    bpy.context.view_layer.update()


def visible_meshes():
    return [o for o in bpy.context.scene.objects if o.type=="MESH" and
            o.name!="Studio_Floor" and not o.hide_render and o.visible_get()]


def world_rotation(rig,name,angles):
    bone=rig.pose.bones[name]
    basis=bone.bone.matrix_local.to_quaternion()
    bone.rotation_mode="QUATERNION"
    bone.rotation_quaternion=basis.inverted() @ Euler(angles).to_quaternion() @ basis


def update_volume_helpers(rig):
    for name,primary in HELPERS.items():
        if name not in rig.pose.bones:
            continue
        source=rig.pose.bones[primary]
        q=source.rotation_quaternion if source.rotation_mode=="QUATERNION" else source.rotation_euler.to_quaternion()
        rest=source.bone.matrix_local.to_quaternion()
        delta=rest @ q @ rest.inverted()
        half=Quaternion().slerp(delta,.5)
        helper=rig.pose.bones[name]
        if rig.animation_data and rig.animation_data.drivers:
            helper.rotation_mode="QUATERNION"
            helper.rotation_quaternion=Quaternion()
            continue
        basis=helper.bone.matrix_local.to_quaternion()
        helper.rotation_mode="QUATERNION"
        helper.rotation_quaternion=basis.inverted() @ half @ basis
    bpy.context.view_layer.update()


def add_controls(rig):
    activate(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    for side,sign in (("L",1),("R",-1)):
        pivot=Vector((sign*.29,0,1.27))
        rig.data.edit_bones[f"UpperArm_{side}"].head=pivot
        rig.data.edit_bones[f"Shoulder_{side}"].tail=pivot
    for name,primary in HELPERS.items():
        original=rig.data.edit_bones[primary]
        helper=rig.data.edit_bones.new(name)
        helper.head=original.head
        helper.tail=original.head+(original.tail-original.head).normalized()*.12
        helper.roll=original.roll
        helper.parent=original.parent
    for side,sign in (("L",1),("R",-1)):
        for name,x,y,top,tip in (("Thumb",.413,-.102,.495,.416),
                               ("Index",.445,-.082,.478,.360),
                               ("Middle",.504,-.090,.477,.348),
                               ("Ring",.563,-.071,.480,.374)):
            bone=rig.data.edit_bones.new(f"{name}_{side}")
            bone.head=(sign*x,y,top)
            bone.tail=(sign*x,y-.008,tip)
            bone.parent=rig.data.edit_bones[f"Hand_{side}"]
    bpy.ops.object.mode_set(mode="OBJECT")
    for name,primary in HELPERS.items():
        helper=rig.pose.bones[name]
        helper.rotation_mode="QUATERNION"
        for component in range(4):
            driver=helper.driver_add("rotation_quaternion",component).driver
            for variable,index in (("w",0),("v",component)):
                item=driver.variables.new()
                item.name=variable
                item.type="SINGLE_PROP"
                item.targets[0].id=rig
                item.targets[0].data_path=f'pose.bones["{primary}"].rotation_quaternion[{index}]'
            driver.expression="sqrt((1+abs(w))/2)" if component==0 else "v*(1 if w>=0 else -1)/sqrt(2*(1+abs(w)))"


def repair_wrist_and_hand(obj,sign):
    profiles=[(1.07,.506),(1.20,.440),(1.30,.385),(1.367,.310),(1.405,.235)]
    for vertex in obj.data.vertices:
        p=vertex.co
        x=sign*p.x
        if p.z>1.18:
            for (za,xa),(zb,xb) in zip(profiles,profiles[1:]):
                if za<=p.z<=zb:
                    center=.205+((xa+(xb-xa)*(p.z-za)/(zb-za))-.205)*.86
                    fullness=math.exp(-((p.z-1.32)/.105)**2)
                    p.x=sign*(center+(x-center)*(1+.36*fullness))
                    p.y=.015+(p.y-.015)*(1+.25*fullness)
                    break
        if p.z<.445:
            amount=1-smoothstep(.36,.445,p.z)
            p.y-=.014*amount
            if x<.43:
                p.x+=sign*.008*amount
                p.z+=.006*amount
    obj.data.update()


def wrist_strip(obj):
    obj.data.use_fake_user=True
    obj.data=obj.data.copy()
    bm=bmesh.new()
    bm.from_mesh(obj.data)
    low,high=.525,.665
    for height in (low,high):
        bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                               dist=1e-7,plane_co=(0,0,height),plane_no=(0,0,1))
    band=[f for f in bm.faces if low+1e-6<f.calc_center_median().z<high-1e-6]
    bmesh.ops.delete(bm,geom=band,context="FACES_ONLY")
    loose=[v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm,geom=loose,context="VERTS")

    def boundary(height):
        return [e for e in bm.edges if e.is_boundary and
                all(abs(v.co.z-height)<1e-5 for v in e.verts)]

    bottom,top=boundary(low),boundary(high)
    assert bottom and top, "Missing wrist boundaries"
    target=max(len(bottom),len(top))
    for height in (low,high):
        while len(boundary(height))<target:
            edges=boundary(height)
            count=min(target-len(edges),len(edges))
            selected=sorted(edges,key=lambda e:e.calc_length(),reverse=True)[:count]
            bmesh.ops.subdivide_edges(bm,edges=selected,cuts=1,use_grid_fill=False)

    def ring(height):
        vertices=list({v for e in boundary(height) for v in e.verts})
        center=sum((v.co for v in vertices),Vector())/len(vertices)
        return sorted(vertices,key=lambda v:math.atan2(v.co.y-center.y,v.co.x-center.x))

    bottom,top=ring(low),ring(high)
    assert len(bottom)==len(top), (len(bottom),len(top))
    count=len(bottom)
    rows=[bottom]
    for row in range(1,9):
        t=row/9
        rows.append([bm.verts.new(a.co.lerp(b.co,t)) for a,b in zip(bottom,top)])
    rows.append(top)
    for a,b in zip(rows,rows[1:]):
        for i in range(count):
            j=(i+1)%count
            bm.faces.new((a[i],a[j],b[j],b[i]))
    zone=[v for v in bm.verts if .515<v.co.z<.675]
    for _ in range(3):
        bmesh.ops.smooth_vert(bm,verts=zone,factor=.2,use_axis_x=True,use_axis_y=True,use_axis_z=True)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    for poly in obj.data.polygons:
        poly.use_smooth=True
    obj.data.update()

def assign_arm_weights(obj,side):
    obj.vertex_groups.clear()
    names=[f"ShoulderVolume_{side}",f"UpperArm_{side}",
           f"ElbowVolume_{side}",f"Forearm_{side}",f"Hand_{side}"]
    names += [f"{digit}_{side}" for digit in ("Thumb","Index","Middle","Ring")]
    groups={n:obj.vertex_groups.new(name=n) for n in names}
    sign=1 if side=="L" else -1
    for v in obj.data.vertices:
        z=v.co.z
        hand=1-smoothstep(.49,.61,z)
        elbow_u=smoothstep(.76,1.04,z)
        elbow=4*elbow_u*(1-elbow_u)
        shoulder=smoothstep(1.02,1.405,z)
        weights={f"ShoulderVolume_{side}":shoulder,
                 f"UpperArm_{side}":(1-shoulder)*elbow_u*(1-elbow),
                 f"ElbowVolume_{side}":elbow*(1-shoulder),
                 f"Forearm_{side}":(1-elbow_u)*(1-elbow)*(1-hand),f"Hand_{side}":hand}
        if z<.515:
            x=sign*v.co.x
            thumb=(1-smoothstep(.415,.445,x))*(1-smoothstep(.475,.515,z))
            finger=(1-smoothstep(.40,.515,z))*(1-thumb)
            spread=.018+.027*smoothstep(.40,.49,z)
            distribution={digit:math.exp(-((x-center)/spread)**2)
                          for digit,center in (("Index",.445),("Middle",.504),("Ring",.563))}
            total=sum(distribution.values())
            weights[f"Thumb_{side}"]=thumb*hand
            for digit,value in distribution.items():
                weights[f"{digit}_{side}"]=finger*hand*value/total
            weights[f"Hand_{side}"]=hand*(1-thumb-finger)
        nonzero=sorted(((name,w) for name,w in weights.items() if w>1e-5),key=lambda item:-item[1])[:4]
        total=sum(w for _,w in nonzero)
        for name,w in nonzero:
            groups[name].add([v.index],w/total,"REPLACE")
    for name,low,high in (("Shoulder",1.15,1.42),("Elbow",.76,1.04),("Wrist",.51,.65),("Hand",0,.515)):
        group=obj.vertex_groups.new(name=f"Edit_{name}")
        group.add([v.index for v in obj.data.vertices if low<v.co.z<high],1,"REPLACE")


def integrated_panels(obj,cy,cz,ry,rz,panel,side_limit,relief=.001):
    bm=bmesh.new()
    bm.from_mesh(obj.data)
    band=[]
    for face in bm.faces:
        p=face.calc_center_median()
        d=math.hypot((p.y-cy)/ry,(p.z-cz)/rz)
        if .80<d<1.20 and abs(p.x)>side_limit-.04:
            band.extend(face.edges)
    if band:
        bmesh.ops.subdivide_edges(bm,edges=list(set(band)),cuts=1,use_grid_fill=True)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    mat=bpy.data.materials.get("Recovery_VertexVinyl")
    if mat is None:
        mat=material("Recovery_VertexVinyl",(1,1,1),.46)
        color=mat.node_tree.nodes.new("ShaderNodeVertexColor")
        color.layer_name="VinylSurface"
        mat.node_tree.links.new(color.outputs["Color"],mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.material_index=0
    colors=obj.data.color_attributes.new(name="VinylSurface",type="FLOAT_COLOR",domain="POINT")
    for v in obj.data.vertices:
        p=v.co
        d=math.hypot((p.y-cy)/ry,(p.z-cz)/rz)
        side=smoothstep(side_limit-.035,side_limit+.015,abs(p.x))
        amount=(1-smoothstep(.94,1.06,d))*side
        base=(.79,.79,.765)
        target=panel
        colors.data[v.index].color=tuple(a*(1-amount)+b*amount for a,b in zip(base,target))+(1,)
        if d<1:
            p.x-=math.copysign(relief*(1-smoothstep(.82,1,d))*side,p.x)
    obj.data.update()
    obj.data.calc_loop_triangles()
    problem_faces={t.polygon_index for t in obj.data.loop_triangles if t.area<1e-12}
    if problem_faces:
        bm=bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.triangulate(bm,faces=[bm.faces[i] for i in problem_faces])
        bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-5)
        bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=1e-5)
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()


def anatomy():
    rig=bpy.data.objects["Bagusmax_Rig"]
    add_controls(rig)
    panel=(.50,.53,.51)
    for side,sign in (("L",1),("R",-1)):
        obj=bpy.data.objects[f"White_Arm_{side}"]
        wrist_strip(obj)
        repair_wrist_and_hand(obj,sign)
        assign_arm_weights(obj,side)
        integrated_panels(obj,-.006,.967,.137,.214,panel,.505)
        old=bpy.data.objects[f"Elbow_Panel_Seam_{side}"]
        old.hide_render=True
        old.hide_set(True)
    torso=bpy.data.objects["White_Torso"]
    for v in torso.data.vertices:
        p=v.co
        lower=1-smoothstep(.43,.65,p.z)
        curve=.055*min(abs(p.x)/.42,1)**2-.035*math.exp(-(p.x/.24)**2)
        p.z+=lower*curve
    torso.data.update()
    body_panel=(.60,.64,.61)
    integrated_panels(torso,.09,.740,.235,.280,body_panel,.27,relief=.0004)
    torso.shape_key_add(name="Basis")
    variant=torso.shape_key_add(name="TorsoSide_Relief_Optional")
    for v in variant.data:
        p=v.co
        d=math.hypot((p.y-.09)/.235,(p.z-.740)/.280)
        if abs(p.x)>.27 and d<1:
            p.x+=math.copysign(.0015*(1-smoothstep(.75,1,d)),p.x)
    variant.value=0
    for side in ("L","R"):
        leg=bpy.data.objects[f"White_Leg_{side}"]
        hips=leg.vertex_groups.get("Hips") or leg.vertex_groups.new(name="Hips")
        bones={g.index:g for g in leg.vertex_groups if g.name in rig.data.bones}
        for v in leg.data.vertices:
            blend=.85*smoothstep(.35,.49,v.co.z)
            if blend:
                old=[(bones[g.group],g.weight) for g in v.groups if g.group in bones and g.group!=hips.index]
                for group,w in old:
                    group.add([v.index],w*(1-blend),"REPLACE")
                hips.add([v.index],blend,"REPLACE")
    reset(rig)
    return rig


def poses():
    output={"S0":{}}
    for side,sign in (("L",1),("R",-1)):
        for i,angle in enumerate((30,60,90),1):
            output[f"S{i}_{side}"]={f"UpperArm_{side}":(-math.radians(angle),0,0)}
        for i,angle in ((4,45),(5,90),(6,110)):
            output[f"S{i}_{side}"]={f"UpperArm_{side}":(0,-sign*math.radians(angle),0)}
        for i,angle in enumerate((0,30,60,90,115)):
            output[f"E{i}_{side}"]={f"Forearm_{side}":(-math.radians(angle),0,0)}
    output.update({
        "C1": {"UpperArm_L":(-1.0,0,0)},
        "C2": {"UpperArm_L":(0,-1.0,0),"Forearm_L":(0,-1.2,0)},
        "C3": {"UpperArm_L":(0,-1.1,0),"UpperArm_R":(0,1.1,0)},
        "C4": {"UpperArm_L":(-1.1,0,0),"UpperArm_R":(-1.1,0,0),"Forearm_L":(-.4,0,0),"Forearm_R":(-.4,0,0)},
        "C5": {"UpperArm_L":(-.9,0,-.20),"UpperArm_R":(-.9,0,.20),"Forearm_L":(-.6,0,-.35),"Forearm_R":(-.6,0,.35)},
        "C6": {"UpperArm_R":(-.2,.15,0)},
        "C7": {"Spine":(.3,0,0)}, "C8":{"Spine":(0,.25,0)},
        "C9": {"Thigh_L":(-.35,0,0),"Shin_L":(.25,0,0)},
        "C10":{"Head":(0,.22,0),"UpperArm_L":(0,-1.0,0),"Forearm_L":(-1.0,0,0)},
        "F1_point":{"Middle_L":(-.8,0,0),"Ring_L":(-.8,0,0),"Thumb_L":(0,0,-.25)},
    })
    return output


def apply_pose(rig,changes):
    reset(rig)
    for name,angles in changes.items():
        if name in rig.pose.bones:
            world_rotation(rig,name,angles)
    update_volume_helpers(rig)


def render_frame(name,location=(3,-5,1.8),target=(0,0,1.0),scale=2.6):
    if "--validate-only" in sys.argv:
        return
    scene=bpy.context.scene
    camera=scene.camera
    camera.location=location
    camera.rotation_euler=(Vector(target)-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.type="ORTHO"
    camera.data.ortho_scale=scale
    scene.render.resolution_x=scene.render.resolution_y=720
    scene.render.filepath=str(REVIEW/f"{name}.png")
    bpy.ops.render.render(write_still=True)


def neutral_views(label,names=None):
    views={name:VIEWS[name] for name in ("front","left","right","three_quarter","back","legs","hand") if name in VIEWS}
    views.update(hand=((1.7,-4,.8),(.50,-.075,.475),.36),
        elbow_left=((5,-1,1.2),(.50,-.01,.96),.65),
        elbow_right=((-5,-1,1.2),(-.50,-.01,.96),.65),
        torso_left=((5,1,1.2),(0,.08,.73),1.0),
        torso_right=((-5,1,1.2),(0,.08,.73),1.0),
        rear_quarter=((3,5,1.6),(0,0,.85),2.04))
    for name,(location,target,scale) in views.items():
        if names is not None and name not in names:
            continue
        hidden=[]
        if name.startswith("torso_"):
            for side in ("L","R"):
                arm=bpy.data.objects[f"White_Arm_{side}"]
                arm.hide_render=True
                hidden.append(arm)
            for obj in bpy.context.scene.objects:
                if obj.name.startswith("Elbow_Panel_Seam") and not obj.hide_render:
                    obj.hide_render=True
                    hidden.append(obj)
        render_frame(f"{label}_{name}",location,target,scale)
        for obj in hidden:
            obj.hide_render=False


def sampled_surface(step=3):
    result=[]
    graph=bpy.context.evaluated_depsgraph_get()
    for obj in visible_meshes():
        evaluated=obj.evaluated_get(graph)
        mesh=evaluated.to_mesh()
        result.extend(tuple(obj.matrix_world @ mesh.vertices[i].co) for i in range(0,len(mesh.vertices),step))
        evaluated.to_mesh_clear()
    return result


def audit(rig):
    result={}
    for obj in visible_meshes():
        bm=bmesh.new()
        bm.from_mesh(obj.data)
        obj.data.calc_loop_triangles()
        names={g.index for g in obj.vertex_groups if g.name in rig.data.bones}
        invalid=0
        maximum=0
        for v in obj.data.vertices:
            weights=[g.weight for g in v.groups if g.group in names and g.weight>0]
            maximum=max(maximum,len(weights))
            invalid+=not weights or abs(sum(weights)-1)>.001
        record={"triangles":len(obj.data.loop_triangles),"nonmanifold":sum(not e.is_manifold for e in bm.edges),
                "degenerate":sum(t.area<1e-12 for t in obj.data.loop_triangles),
                "weight_errors":invalid,"max_influences":maximum}
        bm.free()
        assert not record["nonmanifold"] and not record["degenerate"] and not invalid and maximum<=4, (obj.name,record)
        result[obj.name]=record
    return result


def export(rig):
    reset(rig)
    update_volume_helpers(rig)
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in visible_meshes()+[rig]:
        obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(GLB),export_format="GLB",use_selection=True,
        export_skins=True,export_animations=False,export_morph=False,export_yup=True,export_all_influences=False)


def main():
    REVIEW.mkdir(parents=True,exist_ok=True)
    source_hash=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    checks=poses()
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    old_skeleton=[{"name":b.name,"parent":b.parent.name if b.parent else None,
                   "head":list(b.head_local),"tail":list(b.tail_local),
                   "rest_matrix":[list(r) for r in b.matrix_local]}
                  for b in bpy.data.objects["Bagusmax_Rig"].data.bones]
    if "--after-only" not in sys.argv and "--validate-only" not in sys.argv:
        neutral_views("before")
        for name in ("S5_L","E3_L","E3_R","C2","C4","C9"):
            apply_pose(bpy.data.objects["Bagusmax_Rig"],checks[name])
            render_frame(f"before_{name}")
        reset(bpy.data.objects["Bagusmax_Rig"])
    rig=anatomy()
    geometry=audit(rig)
    weighted_controls={}
    new_names=set(rig.data.bones.keys())-{b["name"] for b in old_skeleton}
    for name in sorted(new_names):
        count=0
        for obj in visible_meshes():
            group=obj.vertex_groups.get(name)
            if group:
                count+=sum(any(g.group==group.index and g.weight>1e-5 for g in v.groups) for v in obj.data.vertices)
        weighted_controls[name]=count
    assert all(weighted_controls.values())
    source_state={"actions":len(bpy.data.actions),"nla_tracks":sum(len(o.animation_data.nla_tracks) for o in bpy.context.scene.objects if o.animation_data),
                  "driver_channels":len(rig.animation_data.drivers),"torso_relief_value":0,"neutral_pose":all(b.rotation_quaternion.angle<1e-5 for b in rig.pose.bones)}
    assert source_state["actions"]==0 and source_state["nla_tracks"]==0 and source_state["neutral_pose"]
    skeleton=[{"name":b.name,"parent":b.parent.name if b.parent else None,
               "head":list(b.head_local),"tail":list(b.tail_local),"rest_matrix":[list(r) for r in b.matrix_local]}
              for b in rig.data.bones]
    export(rig)
    neutral_views("after")
    variant=bpy.data.objects["White_Torso"].data.shape_keys.key_blocks["TorsoSide_Relief_Optional"]
    variant.value=1
    neutral_views("variant_b",names={"torso_left","torso_right"})
    variant.value=0
    saved={}
    for name,changes in checks.items():
        apply_pose(rig,changes)
        render_frame(f"after_{name}")
        if name in ("S5_L","E3_L","E3_R","C2","C4","C9"):
            saved[name]=sampled_surface()
        if name in ("E3_L","E3_R"):
            sign=1 if name.endswith("L") else -1
            render_frame(f"after_{name}_panel",(sign*5,-1,1.25),(sign*.5,-.08,.9),1.1)
        if name=="F1_point":
            render_frame("after_F1_hand",(1.7,-4,.8),(.50,-.075,.475),.36)
    reset(rig)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    started=time.perf_counter()
    bpy.ops.import_scene.gltf(filepath=str(GLB))
    imported_seconds=time.perf_counter()-started
    imported=next(o for o in bpy.context.scene.objects if o.type=="ARMATURE")
    roundtrip={}
    for name,expected in saved.items():
        apply_pose(imported,checks[name])
        points=sampled_surface(step=1)
        tree=KDTree(len(points))
        for i,p in enumerate(points):
            tree.insert(p,i)
        tree.balance()
        max_distance=max(tree.find(p)[2] for p in expected)
        roundtrip[name]={"max_sample_distance_m":max_distance,"pass":max_distance<.0005}
    assert not bpy.data.actions
    assert all(value["pass"] for value in roundtrip.values()), roundtrip
    assert source_hash==hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    report={"baseline_sha256":source_hash,"new_sha256":hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
            "mesh_audit":geometry,"baseline_skeleton":old_skeleton,"skeleton":skeleton,"roundtrip":roundtrip,
            "weighted_new_controls":weighted_controls,"source_state":source_state,
            "glb_import_seconds":imported_seconds,"joint_count":len(imported.data.bones),"animations":0,
            "helper_rule":"half parent-relative primary rotation, conjugated through rest bases",
            "supported_by_application":False,"collision_certified":False}
    (REVIEW/"recovery_audit.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"joints":len(imported.data.bones),"roundtrip":roundtrip,"meshes":len(geometry)},indent=2))


if __name__=="__main__":
    main()
