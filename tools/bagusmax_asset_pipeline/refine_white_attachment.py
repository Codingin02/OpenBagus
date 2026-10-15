"""Repair White's existing shoulder skin and anatomical hand rest orientation."""

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
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refine_white_deformation as prior
import recover_white_anatomy as recovery
from detail_white_anatomy import activate, smoothstep
from gltf_skinning import GLBSkin, BLENDER_TO_GLTF

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets/bagusmax/source/bagusmax_white_anatomy_v4.blend"
OUTPUT = SOURCE.with_name("bagusmax_white_anatomy_v4_1.blend")
GLB = ROOT / "assets/bagusmax/runtime/bagusmax_white_anatomy_v4_1.glb"
FOLDER = ROOT / "reports/bagusmax_3d/white_v4_1"
recovery.REVIEW = FOLDER
prior.FOLDER = FOLDER


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected():
    paths = list((ROOT / "assets/bagusmax/source").glob("*.blend"))
    paths += list((ROOT / "assets/bagusmax/runtime").glob("*.glb"))
    paths += [ROOT / "docs/bagusmax_3d/WHITE_LIGHTING_SPEC.md"]
    return {str(p.relative_to(ROOT)): digest(p) for p in paths if p not in (OUTPUT, GLB)}


def write_json(name, value):
    (FOLDER / name).write_text(json.dumps(value, indent=2), encoding="utf-8")


def baseline_audit(rig):
    result = prior.inspect_asset(rig)
    result["sha256"] = protected()
    result["transforms"] = {o.name: {"scale": list(o.scale), "determinant": o.matrix_world.determinant(),
        "matrix": [list(r) for r in o.matrix_world], "modifiers": [(m.name, m.type) for m in o.modifiers]}
        for o in recovery.visible_meshes()+[rig]}
    result["correctives"] = []
    for side in ("L", "R"):
        obj = bpy.data.objects[f"White_Arm_{side}"]
        basis = prior.coordinates(obj.data)
        for key in list(obj.data.shape_keys.key_blocks)[1:]:
            value = np.empty(len(basis)*3)
            key.data.foreach_get("co", value)
            delta = value.reshape(-1, 3)-basis
            result["correctives"].append({"name": key.name, "mesh": obj.name, "default": key.value,
                "changed_vertices": int(np.count_nonzero(np.linalg.norm(delta, axis=1)>1e-7)),
                "max_delta_m": float(np.linalg.norm(delta, axis=1).max())})
        result[f"arm_{side}_sections"] = []
        for z in (.42,.48,.52,.60,.80,1.0,1.15,1.25,1.35,1.40,1.44):
            mask = abs(basis[:,2]-z)<.012
            if mask.any():
                result[f"arm_{side}_sections"].append({"z":z,"bounds":[basis[mask].min(0).tolist(),basis[mask].max(0).tolist()]})
        result[f"weights_{side}"] = [{"co": list(v.co), "weights": {obj.vertex_groups[g.group].name:g.weight for g in v.groups}}
            for v in list(obj.data.vertices)[::max(1,len(obj.data.vertices)//140)] if v.co.z>1.1]
    glb = GLBSkin(SOURCE.parent.parent / "runtime/bagusmax_white_anatomy_v4.glb")
    result["glb"] = {"triangles":sum(len(p["indices"]) for p in glb.primitives),
        "vertices":sum(len(p["position"]) for p in glb.primitives), "meshes":len(glb.doc["meshes"]),
        "materials":len(glb.doc["materials"]),"joints":len(glb.doc["skins"][0]["joints"]),
        "morphs":sum(len(p["targets"]) for p in glb.primitives), "clips":len(glb.doc.get("animations",[])),
        "bytes":glb.path.stat().st_size,
        "max_influences":max(int((p["weights"]>1e-7).sum(1).max()) for p in glb.primitives)}
    torso = bpy.data.objects["White_Torso"]
    for side in ("L","R"):
        arm = bpy.data.objects[f"White_Arm_{side}"]
        a = BVHTree.FromObject(torso,bpy.context.evaluated_depsgraph_get())
        b = BVHTree.FromObject(arm,bpy.context.evaluated_depsgraph_get())
        result[f"torso_arm_{side}_intersecting_face_pairs"] = len(a.overlap(b))
    write_json("baseline_audit.json",result)
    print("BASELINE",json.dumps(result["glb"]),flush=True)
    print("BONES",[(b.name,tuple(round(v,4) for v in b.head_local)) for b in rig.data.bones],flush=True)
    print("SECTIONS",json.dumps(result["arm_L_sections"]),flush=True)
    return result


def neutral_views(rig,label):
    recovery.reset(rig)
    for view,position in {"front":(0,-5,.9),"left":(5,0,.9),"right":(-5,0,.9),
                          "back":(0,5,.9),"three_quarter":(3,-5,1.3)}.items():
        recovery.render_frame(f"{label}_neutral_{view}",position,(0,0,.85),2.04)
        recovery.render_frame(f"{label}_hands_{view}",position,(0,-.05,.48),1.4)


def source_samples(objects):
    points,weights,colors,deltas,owners = [],[],[],[],[]
    key_names = [f"{kind}_{angle}_{side}" for side in ("L","R")
                 for kind,angle in (("Shoulder",90),("Shoulder",145),("Elbow",90),("Elbow",130))]
    names = list(bpy.data.objects["Bagusmax_Rig"].data.bones.keys())
    for owner,obj in enumerate(objects):
        rest = prior.coordinates(obj.data)
        points.extend(rest)
        owners.extend([owner]*len(rest))
        matrix = np.zeros((len(rest),len(names)))
        for v in obj.data.vertices:
            for g in v.groups:
                name = obj.vertex_groups[g.group].name
                if name in names:
                    matrix[v.index,names.index(name)] = g.weight
        weights.extend(matrix)
        attr = obj.data.color_attributes["VinylSurface"]
        values = np.empty(len(attr.data)*4)
        attr.data.foreach_get("color",values)
        colors.extend(values.reshape(-1,4))
        shapes = np.zeros((len(rest),8,3))
        if obj.data.shape_keys:
            for i,name in enumerate(key_names):
                key = obj.data.shape_keys.key_blocks.get(name)
                if key:
                    values = np.empty(len(rest)*3)
                    key.data.foreach_get("co",values)
                    shapes[:,i] = values.reshape(-1,3)-rest
        deltas.extend(shapes)
    return np.array(points),np.array(weights),np.array(colors),np.array(deltas),names,key_names,np.array(owners)


def relax(points,edges,mask,iterations=25,factor=.4):
    a = np.concatenate((edges[:,0],edges[:,1]))
    b = np.concatenate((edges[:,1],edges[:,0]))
    count = np.maximum(1,np.bincount(a,minlength=len(points)))
    result = points.copy()
    for _ in range(iterations):
        total = np.column_stack([np.bincount(a,weights=result[b,i],minlength=len(points)) for i in range(3)])
        result += factor*mask[:,None]*(total/count[:,None]-result)
    return result


def attachment_mask(points,side=None,low=1.12):
    x = abs(points[:,0]) if side is None else points[:,0]*(1 if side=="L" else -1)
    return np.array([smoothstep(.16,.27,v) for v in x])*np.array([
        smoothstep(low,1.22,z)*(1-smoothstep(1.40,1.47,z)) for z in points[:,2]])


def connect_skin(rig):
    originals = [bpy.data.objects[n] for n in ("White_Torso","White_Arm_L","White_Arm_R")]
    samples = source_samples(originals)
    search = samples[0].copy()
    for owner,sign in ((1,1),(2,-1)):
        selected = samples[6]==owner
        search[selected,0] += sign*.22*np.array([1-smoothstep(1.10,1.24,z) for z in search[selected,2]])
    torso = originals[0]
    skin = torso.copy()
    skin.data = torso.data.copy()
    skin.name = "White_SoftSkin"
    bpy.context.collection.objects.link(skin)
    skin.modifiers.clear()
    operands = []
    for source,sign in zip(originals[1:],(1,-1)):
        obj = source.copy()
        obj.data = source.data.copy()
        bpy.context.collection.objects.link(obj)
        obj.shape_key_clear()
        obj.modifiers.clear()
        for v in obj.data.vertices:
            v.co.x += sign*.22*(1-smoothstep(1.10,1.24,v.co.z))
        operands.append(obj)
        activate(skin)
        modifier = skin.modifiers.new("Shoulder skin union","BOOLEAN")
        modifier.operation = "UNION"
        modifier.solver = "EXACT"
        modifier.object = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    bm = bmesh.new()
    bm.from_mesh(skin.data)
    bmesh.ops.triangulate(bm,faces=[f for f in bm.faces if len(f.verts)>4])
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
    bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=1e-6)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(skin.data)
    bm.free()
    points = prior.coordinates(skin.data)
    tree = KDTree(len(samples[0]))
    for i,p in enumerate(search):
        tree.insert(p,i)
    tree.balance()
    nearest = np.array([tree.find(p)[1] for p in points])
    owners = samples[6][nearest]
    for owner,sign in ((1,1),(2,-1)):
        selected = owners==owner
        points[selected,0] -= sign*.22*np.array([1-smoothstep(1.10,1.24,z) for z in points[selected,2]])
    attribute = skin.data.attributes.new(name="AnatomicalRegion",type="INT",domain="POINT")
    attribute.data.foreach_set("value",owners)
    weights = samples[1][nearest]
    colors = samples[2][nearest]
    deltas = samples[3][nearest]
    edges = np.array([e.vertices[:] for e in skin.data.edges])
    mask = attachment_mask(points)
    smoothed = relax(points,edges,mask,90,.5)
    skin.data.vertices.foreach_set("co",smoothed.ravel())
    skin.vertex_groups.clear()
    for name in samples[4]:
        skin.vertex_groups.new(name=name)
    for i,p in enumerate(smoothed):
        if p[2]>1.10:
            sign = 1 if p[0]>=0 else -1
            side = "L" if sign==1 else "R"
            x = abs(p[0])
            # A broad spatial anchor continues into the torso, not only the old arm cap.
            mobile = smoothstep(.10,.55,x+.75*(1.40-p[2]))*smoothstep(.22,.40,x)
            helper = .8*4*mobile*(1-mobile)
            primary = max(0,mobile-helper*.5)
            anchor = 1-helper-primary
            blend = smoothstep(1.10,1.25,p[2])*smoothstep(.12,.22,x)
            weights[i] *= 1-blend
            weights[i,samples[4].index("Chest")] += blend*anchor
            weights[i,samples[4].index(f"ShoulderVolume_{side}")] += blend*helper
            weights[i,samples[4].index(f"UpperArm_{side}")] += blend*primary
        values = weights[i]
        values[np.argsort(values)[:-4]] = 0
        values /= max(values.sum(),1e-8)
        for j in np.flatnonzero(values>1e-7):
            skin.vertex_groups[j].add([i],float(values[j]),"REPLACE")
    attr = skin.data.color_attributes.get("VinylSurface")
    attr.data.foreach_set("color",colors.ravel())
    for face in skin.data.polygons:
        face.use_smooth = True
    for obj in originals+operands:
        bpy.data.objects.remove(obj,do_unlink=True)
    modifier = skin.modifiers.new("Skin","ARMATURE")
    modifier.object = rig
    modifier.use_deform_preserve_volume = False
    skin.data.update()
    skin.shape_key_add(name="Basis")
    for i,name in enumerate(samples[5]):
        key = skin.shape_key_add(name=name)
        key.data.foreach_set("co",(smoothed+deltas[:,i]).ravel())
    return skin


def natural_hands(skin,rig):
    rest = prior.coordinates(skin.data)
    owners = np.empty(len(rest),dtype=np.int32)
    skin.data.attributes["AnatomicalRegion"].data.foreach_get("value",owners)
    edges = np.array([e.vertices[:] for e in skin.data.edges])
    mask = (owners>0)*np.array([smoothstep(.47,.50,z)*(1-smoothstep(.58,.62,z)) for z in rest[:,2]])
    for key in skin.data.shape_keys.key_blocks:
        values = np.empty(len(rest)*3)
        key.data.foreach_get("co",values)
        points = values.reshape(-1,3)
        points = relax(points,edges,mask,16,.35)
        for side,sign,owner in (("L",1,1),("R",-1,2)):
            center = np.array((sign*.5017,-.066,0))
            selected = (owners==owner)&(rest[:,2]<.76)
            angle = sign*math.pi/2*np.array([1-smoothstep(.55,.76,z) for z in rest[selected,2]])
            offset = points[selected]-center
            x = np.cos(angle)*offset[:,0]-np.sin(angle)*offset[:,1]
            y = np.sin(angle)*offset[:,0]+np.cos(angle)*offset[:,1]
            points[selected,0] = x+center[0]
            points[selected,1] = y+center[1]
        key.data.foreach_set("co",points.ravel())
    activate(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    targets = {}
    for side,sign in (("L",1),("R",-1)):
        center = Vector((sign*.5017,-.066,0))
        transform = Matrix.Translation(center) @ Matrix.Rotation(sign*math.pi/2,4,"Z") @ Matrix.Translation(-center)
        for kind in ("Hand","Thumb","Index","Middle","Ring"):
            bone = rig.data.edit_bones[f"{kind}_{side}"]
            targets[bone.name] = (transform @ bone.head,transform @ bone.tail,
                                  transform.to_3x3() @ bone.matrix.to_3x3().col[2])
    for name,(head,tail,normal) in targets.items():
        bone = rig.data.edit_bones[name]
        bone.head,bone.tail = head,tail
        bone.align_roll(normal)
    bpy.ops.object.mode_set(mode="OBJECT")
    skin.data.update()


def quaternion_product(a,b):
    w = a[...,0]*b[...,0]-np.sum(a[...,1:]*b[...,1:],axis=-1)
    v = a[...,0,None]*b[...,1:]+b[...,0,None]*a[...,1:]+np.cross(a[...,1:],b[...,1:])
    return np.concatenate((w[...,None],v),axis=-1)


def dq_target(skin,rig,points):
    names = list(rig.data.bones.keys())
    real,dual = [],[]
    for name in names:
        matrix = rig.pose.bones[name].matrix @ rig.data.bones[name].matrix_local.inverted()
        q = np.array(matrix.to_quaternion())
        if q[0]<0:
            q *= -1
        real.append(q)
        dual.append(.5*quaternion_product(np.array((0,*matrix.translation)),q))
    weights = np.zeros((len(points),len(names)))
    for v in skin.data.vertices:
        for g in v.groups:
            name = skin.vertex_groups[g.group].name
            if name in names:
                weights[v.index,names.index(name)] = g.weight
    q = weights @ np.array(real)
    d = weights @ np.array(dual)
    norm = np.linalg.norm(q,axis=1,keepdims=True)
    q /= norm
    d /= norm
    conjugate = q.copy()
    conjugate[:,1:] *= -1
    rotation = quaternion_product(quaternion_product(q,np.column_stack((np.zeros(len(points)),points))),conjugate)
    translation = 2*quaternion_product(d,conjugate)
    return rotation[:,1:]+translation[:,1:]


def rebuild_correctives(skin,rig):
    keys = skin.data.shape_keys
    rest = prior.coordinates(skin.data)
    edges = np.array([e.vertices[:] for e in skin.data.edges])
    records = []
    for key in list(keys.key_blocks)[1:]:
        kind,degree,side = key.name.split("_")
        angle = int(degree)
        sign = 1 if side=="L" else -1
        primary = f"{'UpperArm' if kind=='Shoulder' else 'Forearm'}_{side}"
        changes = {primary:(0,-sign*math.radians(angle),0) if kind=="Shoulder" else (-math.radians(angle),0,0)}
        recovery.apply_pose(rig,changes)
        matrices = prior.lbs_matrices(skin,rig)
        current = np.einsum("nij,nj->ni",matrices[:,:3,:3],rest)+matrices[:,:3,3]
        if kind=="Shoulder":
            mask = attachment_mask(rest,side,1.04)
            desired = current+(dq_target(skin,rig,rest)-current)*mask[:,None]
            desired = relax(desired,edges,mask,120,.45)
        else:
            # Rebuild the existing curved elbow on only the corresponding arm band.
            selected = (rest[:,0]*sign>.34)&(rest[:,2]>.63)&(rest[:,2]<1.13)
            existing = np.empty(len(rest)*3)
            key.data.foreach_get("co",existing)
            desired = np.einsum("nij,nj->ni",matrices[:,:3,:3],existing.reshape(-1,3))+matrices[:,:3,3]
            mask = selected.astype(float)*np.array([smoothstep(.64,.73,z)*(1-smoothstep(1.03,1.12,z)) for z in rest[:,2]])
            desired += .25*mask[:,None]*(dq_target(skin,rig,rest)-desired)
            desired = relax(desired,edges,mask,60,.4)
        delta = np.linalg.solve(matrices[:,:3,:3],(desired-current)[...,None])[...,0]
        key.data.foreach_set("co",(rest+delta).ravel())
        key.value = 0
        records.append({"name":key.name,"mesh":skin.name,"kind":kind,"angle_deg":angle,"primary":primary,
            "default":0,"changed_vertices":int(np.count_nonzero(np.linalg.norm(delta,axis=1)>1e-7)),
            "max_delta_m":float(np.linalg.norm(delta,axis=1).max())})
    recovery.reset(rig)
    fit_shoulder_targets(skin,rig)
    records.extend(forward_correctives(skin,rig))
    for record in records:
        values = np.empty(len(rest)*3)
        keys.key_blocks[record["name"]].data.foreach_get("co",values)
        delta = values.reshape(-1,3)-rest
        record["changed_vertices"] = int(np.count_nonzero(np.linalg.norm(delta,axis=1)>1e-7))
        record["max_delta_m"] = float(np.linalg.norm(delta,axis=1).max())
    return records


def fit_shoulder_targets(skin,rig):
    rest = prior.coordinates(skin.data)
    edges = np.array([e.vertices[:] for e in skin.data.edges])
    for side,sign in (("L",1),("R",-1)):
        mask = attachment_mask(rest,side,1.04)
        selected = np.flatnonzero(mask>1e-8)
        system = np.zeros((len(selected),6,6))
        rhs = np.zeros((len(selected),6))
        for angle,importance in ((20,1),(40,1),(60,3),(75,1),(90,3),(120,2),(145,4)):
            changes = {f"UpperArm_{side}":(0,-sign*math.radians(angle),0)}
            recovery.apply_pose(rig,changes)
            matrices = prior.lbs_matrices(skin,rig)
            current = np.einsum("nij,nj->ni",matrices[:,:3,:3],rest)+matrices[:,:3,3]
            desired = current+(dq_target(skin,rig,rest)-current)*mask[:,None]
            desired = relax(desired,edges,mask,180,.45)
            values = morph_inputs(changes)
            u,v = values[f"Shoulder_90_{side}"],values[f"Shoulder_145_{side}"]
            matrix = matrices[selected,:3,:3]
            design = np.concatenate((matrix*u,matrix*v),axis=2)
            system += importance*np.einsum("nki,nkj->nij",design,design)
            rhs += importance*np.einsum("nki,nk->ni",design,(desired-current)[selected])
        solution = np.linalg.solve(system+np.eye(6)[None]*1e-9,rhs[...,None])[...,0]
        for i,name in enumerate((f"Shoulder_90_{side}",f"Shoulder_145_{side}")):
            delta = np.zeros_like(rest)
            delta[selected] = solution[:,i*3:i*3+3]
            skin.data.shape_keys.key_blocks[name].data.foreach_set("co",(rest+delta).ravel())
    recovery.reset(rig)


def forward_correctives(skin,rig):
    rest = prior.coordinates(skin.data)
    edges = np.array([e.vertices[:] for e in skin.data.edges])
    records = []
    for side in ("L","R"):
        primary = f"UpperArm_{side}"
        name = f"ShoulderForward_90_{side}"
        mask = attachment_mask(rest,side,1.04)
        system = np.zeros((len(rest),3,3))
        rhs = np.zeros_like(rest)
        for angle,importance in ((30,1),(60,3),(90,3)):
            changes = {primary:(-math.radians(angle),0,0)}
            recovery.apply_pose(rig,changes)
            matrices = prior.lbs_matrices(skin,rig)
            current = np.einsum("nij,nj->ni",matrices[:,:3,:3],rest)+matrices[:,:3,3]
            desired = current+(dq_target(skin,rig,rest)-current)*mask[:,None]
            desired = relax(desired,edges,mask,240,.5)
            u = (1-math.cos(math.radians(angle)/2))/(1-math.cos(math.pi/4))
            design = matrices[:,:3,:3]*u
            system += importance*np.einsum("nki,nkj->nij",design,design)
            rhs += importance*np.einsum("nki,nk->ni",design,desired-current)
        delta = np.linalg.solve(system+np.eye(3)[None]*1e-9,rhs[...,None])[...,0]
        key = skin.shape_key_add(name=name)
        key.data.foreach_set("co",(rest+delta).ravel())
        records.append({"name":name,"mesh":skin.name,"kind":"ShoulderForward","angle_deg":90,
            "primary":primary,"default":0,"inspection_pose":{primary:(-math.pi/2,0,0)}})
    recovery.reset(rig)
    return records


def add_drivers(skin,rig,records):
    old = json.loads((ROOT/"reports/bagusmax_3d/white_v4/asset_audit.json").read_text())
    expressions = {r["name"]:r["driver_expression"] for r in old["morphs"]}
    for record in records:
        driver = skin.data.shape_keys.key_blocks[record["name"]].driver_add("value").driver
        expression = expressions.get(record["name"],"0")
        if record["kind"]=="Shoulder" and record["angle_deg"]==90:
            sign = 1 if record["name"].endswith("_L") else -1
            row = np.array(rig.data.bones[record["primary"]].matrix_local.to_3x3())[1]
            projection = "+".join(f"({-sign*c:.9f}*{v})" for c,v in zip(row,("x","y","z")))
            angle = f"(2*atan2(max(0,{projection}),abs(w)))"
            low = f"((1-cos(min({math.pi/2:.10f},{angle})/2))/{1-math.cos(math.pi/4):.10f})"
            high = f"min(1,max(0,({angle}-{math.pi/2:.10f})/{math.radians(55):.10f}))"
            expression = low+f"*(1-{high})"
        if record["kind"]=="ShoulderForward":
            row = np.array(rig.data.bones[record["primary"]].matrix_local.to_3x3())[0]
            projection = "+".join(f"({-c:.9f}*{v})" for c,v in zip(row,("x","y","z")))
            angle = f"(2*atan2(max(0,{projection}),abs(w)))"
            row = np.array(rig.data.bones[record["primary"]].matrix_local.to_3x3())[1]
            sign = 1 if record["name"].endswith("_L") else -1
            side_projection = "+".join(f"({-sign*c:.9f}*{v})" for c,v in zip(row,("x","y","z")))
            elevation = f"(2*atan2(max(0,{side_projection}),abs(w)))"
            gate = f"(1-min(1,max(0,({elevation}-{math.radians(30):.10f})/{math.radians(60):.10f})))"
            expression = f"((1-cos(min({math.pi/2:.10f},{angle})/2))/{1-math.cos(math.pi/4):.10f})*{gate}"
        driver.expression = expression
        for i,name in enumerate(("w","x","y","z")):
            variable = driver.variables.new()
            variable.name = name
            variable.type = "SINGLE_PROP"
            variable.targets[0].id = rig
            variable.targets[0].data_path = f'pose.bones["{record["primary"]}"].rotation_quaternion[{i}]'


def morph_inputs(changes):
    values = prior.morph_inputs(changes)
    for side,sign in (("L",1),("R",-1)):
        x,y,z = [v/2 for v in changes.get(f"UpperArm_{side}",(0,0,0))]
        w = math.cos(x)*math.cos(y)*math.cos(z)+math.sin(x)*math.sin(y)*math.sin(z)
        component = -sign*(math.cos(x)*math.sin(y)*math.cos(z)+math.sin(x)*math.cos(y)*math.sin(z))
        angle = 2*math.atan2(max(0,component),abs(w))
        low = (1-math.cos(min(math.pi/2,angle)/2))/(1-math.cos(math.pi/4))
        values[f"Shoulder_90_{side}"] = low*(1-values[f"Shoulder_145_{side}"])
        forward = 2*math.atan2(max(0,-(math.sin(x)*math.cos(y)*math.cos(z)-math.cos(x)*math.sin(y)*math.sin(z))),abs(w))
        gate = 1-min(1,max(0,(angle-math.radians(30))/math.radians(60)))
        values[f"ShoulderForward_90_{side}"] = (1-math.cos(min(math.pi/2,forward)/2))/(1-math.cos(math.pi/4))*gate
    return values


def pose(rig,changes):
    recovery.apply_pose(rig,changes)
    values = morph_inputs(changes)
    obj = bpy.data.objects.get("White_SoftSkin")
    if obj:
        for key in list(obj.data.shape_keys.key_blocks)[1:]:
            key.value = values[key.name]
        bpy.context.view_layer.update()


def tests():
    checks = prior.checks()
    for side,sign in (("L",1),("R",-1)):
        checks[f"elbow_{side}_045"] = {f"Forearm_{side}":(-math.radians(45),0,0)}
        checks[f"combined_{side}"] = {f"UpperArm_{side}":(0,-sign*math.radians(90),0),
                                     f"Forearm_{side}":(-math.radians(110),0,0)}
    return checks


def anatomical_changes(changes):
    result = dict(changes)
    for name,(x,y,z) in list(result.items()):
        if name.startswith(("Thumb_","Index_","Middle_","Ring_","Hand_")):
            sign = 1 if name.endswith("_L") else -1
            result[name] = (-sign*y,sign*x,z)
    return result


def evaluated_geometry(skin):
    evaluated = skin.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    points = prior.coordinates(mesh)
    indices = np.array([t.vertices[:] for t in mesh.loop_triangles])
    vertices = points[indices]
    areas = np.linalg.norm(np.cross(vertices[:,1]-vertices[:,0],vertices[:,2]-vertices[:,0]),axis=1)*.5
    evaluated.to_mesh_clear()
    return points,{"near_zero_triangles":int(np.count_nonzero(areas<1e-12)),
                   "surface_area_m2":float(areas.sum())}


def validation_camera(kind,side):
    sign = 1 if side=="L" else -1
    if kind=="shoulder":
        return ((sign*2.5,-5,1.9),(sign*.32,0,1.30),.85)
    return ((sign*3,-5,1.5),(sign*.46,-.05,.94),.8)


def evidence(rig,label,skin=None,sequence=True):
    neutral_views(rig,label)
    metrics = {}
    for name,changes in tests().items():
        changes = anatomical_changes(changes) if skin else changes
        pose(rig,changes)
        if skin:
            _,metrics[name] = evaluated_geometry(skin)
        if name.startswith(("shoulder_","elbow_")):
            kind,side,angle = name.split("_")
            recovery.render_frame(f"{label}_{name}",*validation_camera(kind,side))
        else:
            recovery.render_frame(f"{label}_{name}")
            if skin and name=="C4":
                drivers = [d for d in skin.data.shape_keys.animation_data.drivers if "ShoulderForward" in d.data_path]
                for driver in drivers:
                    driver.mute = True
                for side in ("L","R"):
                    skin.data.shape_keys.key_blocks[f"ShoulderForward_90_{side}"].value = 0
                bpy.context.view_layer.update()
                recovery.render_frame("C4_without_forward_corrective")
                for driver in drivers:
                    driver.mute = False
                pose(rig,changes)
    if sequence:
        for side,sign in (("L",1),("R",-1)):
            previous = None
            increments = []
            for angle in range(0,161,5):
                pose(rig,{f"UpperArm_{side}":(0,-sign*math.radians(angle),0)})
                if skin:
                    points,geometry = evaluated_geometry(skin)
                    increments.append({"degrees":angle,**geometry,"max_step_m":float(np.linalg.norm(points-previous,axis=1).max()) if previous is not None else 0})
                    previous = points
                recovery.render_frame(f"{label}_sequence_{side}_{angle:03}",*validation_camera("shoulder",side))
            if skin:
                for angle in range(160,-1,-5):
                    pose(rig,{f"UpperArm_{side}":(0,-sign*math.radians(angle),0)})
                    current,_ = evaluated_geometry(skin)
                    pose(rig,{})
                    pose(rig,{f"UpperArm_{side}":(0,-sign*math.radians(angle),0)})
                    repeated,_ = evaluated_geometry(skin)
                    assert np.max(abs(current-repeated))<1e-7
                write_json(f"continuity_{side}.json",increments)
    for view,location in {"front":(0,-5,1.3),"side":(5,-.01,1.3),"back":(0,5,1.3),"quarter":(3,-5,1.8)}.items():
        for angle in (0,145):
            pose(rig,{"UpperArm_L":(0,-math.radians(angle),0)})
            recovery.render_frame(f"{label}_attachment_{angle}_{view}",location,(.30,0,1.29),.85)
    for side in ("L","R"):
        for angle in (0,45,90,110,130,145):
            pose(rig,{f"Forearm_{side}":(-math.radians(angle),0,0)})
            recovery.render_frame(f"{label}_panel_{side}_{angle}",(5 if side=="L" else -5,-.5,1.2),
                                  (.48 if side=="L" else -.48,-.02,.95),.75)
    pose(rig,{})
    if skin:
        write_json("pose_metrics.json",metrics)


def diagnostic_material(name):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    color = nodes.new("ShaderNodeVertexColor")
    color.layer_name = "InspectionColor"
    emission = nodes.new("ShaderNodeEmission")
    output = nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(color.outputs["Color"],emission.inputs["Color"])
    material.node_tree.links.new(emission.outputs[0],output.inputs["Surface"])
    return material


def diagnostics(rig,label):
    pose(rig,{})
    objects = recovery.visible_meshes()
    targets = [o for o in objects if o.name in ("White_Torso","White_Arm_L","White_Arm_R","White_SoftSkin")]
    material = diagnostic_material("Inspection only")
    saved = {}
    for obj in targets:
        saved[obj.name] = list(obj.data.materials)
        obj.data.materials.clear()
        obj.data.materials.append(material)
        for face in obj.data.polygons:
            face.material_index = 0
        if obj.data.color_attributes.get("InspectionColor"):
            obj.data.color_attributes.remove(obj.data.color_attributes["InspectionColor"])
        obj.data.color_attributes.new(name="InspectionColor",type="FLOAT_COLOR",domain="POINT")
    for kind in ("Chest","ShoulderVolume_L","UpperArm_L","NORMAL"):
        for obj in targets:
            values = []
            group = obj.vertex_groups.get(kind)
            for v in obj.data.vertices:
                w = next((g.weight for g in v.groups if group and g.group==group.index),0)
                rgb = tuple((v.normal+Vector((1,1,1)))*.5) if kind=="NORMAL" else (w,.15+.7*(1-abs(2*w-1)),1-w)
                values.extend((*rgb,1))
            obj.data.color_attributes["InspectionColor"].data.foreach_set("color",values)
        recovery.render_frame(f"{label}_diagnostic_{kind}",*validation_camera("shoulder","L"))
    for obj in targets:
        obj.data.materials.clear()
        for m in saved[obj.name]:
            obj.data.materials.append(m)
        obj.data.color_attributes.remove(obj.data.color_attributes["InspectionColor"])
        modifier = obj.modifiers.new("Inspection wire","WIREFRAME")
        modifier.thickness = .00035
        modifier.use_replace = False
    wire = bpy.data.materials.new("Inspection wire only")
    wire.diffuse_color = (.025,.035,.04,1)
    wire.use_nodes = True
    wire.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (.025,.035,.04,1)
    for obj in targets:
        obj.data.materials.append(wire)
        obj.modifiers["Inspection wire"].material_offset = len(obj.data.materials)-1
    recovery.render_frame(f"{label}_wireframe",*validation_camera("shoulder","L"))
    for obj in targets:
        obj.modifiers.remove(obj.modifiers["Inspection wire"])
        obj.data.materials.pop(index=len(obj.data.materials)-1)
    bpy.data.materials.remove(material)
    bpy.data.materials.remove(wire)


def export_asset(rig,skin,records):
    pose(rig,{})
    for obj in recovery.visible_meshes():
        world = obj.matrix_world.copy()
        obj.parent = rig
        obj.matrix_world = world
    bpy.context.view_layer.update()
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in recovery.visible_meshes()+[rig]:
        obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(GLB),export_format="GLB",use_selection=True,
        export_skins=True,export_animations=False,export_morph=True,export_yup=True,
        export_all_influences=False,export_morph_normal=True,export_try_sparse_sk=True,export_morph_animation=False)
    prior.GLB = GLB
    normal_report = fit_normal_targets(rig,skin)
    pose(rig,{})
    return normal_report


def fit_normal_targets(rig,skin):
    pose(rig,{})
    exported = GLBSkin(GLB)
    mapping = prior.export_correspondence(exported)
    part,indices = next((p,i) for p,i in zip(exported.primitives,mapping) if p["name"]==skin.name)
    overrides,records = {},[]
    for side,sign in (("L",1),("R",-1)):
        for kind,angles in (("Shoulder",(20,40,60,75,90,120,145)),("Elbow",(60,90,110,130)),("ShoulderForward",(30,60,90))):
            names = [f"{kind}_{a}_{side}" for a in ((90,) if kind=="ShoulderForward" else ((90,145) if kind=="Shoulder" else (90,130)))]
            size = len(names)*3
            system = np.zeros((len(indices),size,size))
            rhs = np.zeros((len(indices),size))
            for angle in angles:
                primary = f"{'Forearm' if kind=='Elbow' else 'UpperArm'}_{side}"
                rotation = (0,-sign*math.radians(angle),0) if kind=="Shoulder" else (-math.radians(angle),0,0)
                changes = {primary:rotation}
                pose(rig,changes)
                matrix = exported.blend(part,exported.skin_matrices(changes))[:,:3,:3]
                desired = prior.source_normals(skin.name)[indices]
                delta = desired-np.einsum("nij,nj->ni",matrix,part["normal"])
                values = morph_inputs(changes)
                design = np.concatenate([matrix*values[n] for n in names],axis=2)
                importance = 3 if angle in (60,90,130,145) else 1
                system += importance*np.einsum("nki,nkj->nij",design,design)
                rhs += importance*np.einsum("nki,nk->ni",design,delta)
            solution = np.linalg.solve(system+np.eye(size)[None]*1e-8,rhs[...,None])[...,0]
            assert np.isfinite(solution).all()
            for i,name in enumerate(names):
                accessor = part["target_accessors"][part["target_names"].index(name)]["NORMAL"]
                overrides[accessor] = solution[:,i*3:i*3+3]
                records.append({"name":name,"angles":list(angles),"max_normal_delta":float(np.linalg.norm(overrides[accessor],axis=1).max())})
    mesh_nodes = {p["node"] for p in exported.primitives}
    assert all(np.allclose(exported.rest[i],np.eye(4),atol=1e-6) for i in mesh_nodes)
    for node in exported.doc["nodes"]:
        if "children" in node:
            node["children"] = [i for i in node["children"] if i not in mesh_nodes]
    assert len(exported.doc["scenes"])==1
    scene = exported.doc["scenes"][0]
    scene["nodes"] = list(dict.fromkeys(scene["nodes"]+sorted(mesh_nodes)))
    exported.replace_normal_targets(overrides)
    pose(rig,{})
    return {"convention":"multi-pose least-squares rigid per-joint LBS NORMAL morph deltas","targets":records}


def verify_export(rig,skin):
    pose(rig,{})
    exported = GLBSkin(GLB)
    mapping = prior.export_correspondence(exported)
    names = [f"{kind}_{side}_{angle:03}" for side in ("L","R")
        for kind,angles in (("shoulder",(0,60,90,120,145)),("elbow",(0,45,90,110,130))) for angle in angles]
    names += ["combined_L","combined_R","C2","C5","F1_point","S3_L","S3_R","C4"]
    reports = {}
    for name in names:
        changes = anatomical_changes(tests()[name])
        pose(rig,changes)
        expected = prior.source_positions()
        result = exported.evaluate(changes,morph_inputs(changes))
        error = np.concatenate([np.linalg.norm(p["position"]-expected[p["name"]][inds],axis=1) for p,inds in zip(result,mapping)])
        normal = []
        for p,inds in zip(result,mapping):
            if p["name"]==skin.name:
                desired = prior.source_normals(p["name"])[inds]
                normal.extend(np.degrees(np.arccos(np.clip(np.sum(desired*p["normal"],axis=1),-1,1))))
        reports[name] = {"max_position_error_m":float(error.max()),"rms_position_error_m":float(np.sqrt(np.mean(error**2))),
            "pass":bool(error.max()<.0001),"normal_p95_degrees":float(np.percentile(normal,95)),
            "normal_max_degrees":float(np.max(normal)),"normal_over_90":int(np.count_nonzero(np.array(normal)>90))}
        assert reports[name]["pass"],(name,reports[name])
        if name.startswith(("shoulder_","elbow_")):
            kind,side,_ = name.split("_")
            camera = validation_camera(kind,side)
        else:
            camera = ((3,-5,1.5),(0,0,1),2.0)
        prior.CURRENT_CAMERA = camera
        recovery.render_frame(f"source_{name}",*camera)
        prior.render_independent(f"glb_{name}",result)
    duration = []
    for _ in range(5):
        start = time.perf_counter()
        exported.evaluate(tests()["shoulder_L_145"],morph_inputs(tests()["shoulder_L_145"]))
        duration.append(1000*(time.perf_counter()-start))
    pose(rig,{})
    assert not exported.doc.get("animations")
    assert all(not any(p["defaults"]) for p in exported.primitives)
    write_json("independent_skinning.json",{"poses":reports,"position_tolerance_m":.0001,
        "cpu_numpy_ms":{"median":statistics.median(duration),"min":min(duration),"max":max(duration),"samples":5}})


def reimport_check(rig):
    pose(rig,{})
    expected = np.concatenate(list(prior.source_positions().values())) @ BLENDER_TO_GLTF
    originals = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(GLB))
    bpy.context.view_layer.update()
    imported = set(bpy.data.objects)-originals
    imported_rig = next(o for o in imported if o.type=="ARMATURE")
    joint_count = len(imported_rig.data.bones)
    imported_meshes = [o for o in imported if o.type=="MESH" and
                       any(m.type=="ARMATURE" and m.object==imported_rig for m in o.modifiers)]
    points = []
    details = {}
    for obj in imported_meshes:
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        world_points = np.array([tuple(evaluated.matrix_world @ v.co) for v in mesh.vertices])
        points.extend(world_points)
        details[obj.name] = {"bounds":[world_points.min(0).tolist(),world_points.max(0).tolist()],
            "matrix":[list(row) for row in evaluated.matrix_world]}
        evaluated.to_mesh_clear()
    tree = KDTree(len(expected))
    for i,p in enumerate(expected):
        tree.insert(p,i)
    tree.balance()
    error = max(tree.find(p)[2] for p in points)
    write_json("reimport_diagnostic.json",{"meshes":details,"expected_bounds":[expected.min(0).tolist(),expected.max(0).tolist()],
        "error":error,"armature_matrix":[list(r) for r in imported_rig.matrix_world]})
    assert error<.0001,error
    hidden = [o for o in originals if o.type=="MESH" and o.name!="Studio_Floor" and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    recovery.render_frame("neutral_glb_reimport",(0,-5,.9),(0,0,.85),2.04)
    for o in hidden:
        o.hide_render = False
    for o in imported:
        bpy.data.objects.remove(o,do_unlink=True)
    write_json("reimport.json",{"neutral_max_surface_error_m":error,"joints":joint_count,
                                "posed_check":"Independent corresponding-vertex evaluation, not importer driver logic"})


def silhouettes(rig,label):
    pose(rig,{})
    scene = bpy.context.scene
    floor = bpy.data.objects.get("Studio_Floor")
    old_floor = floor.hide_render if floor else None
    if floor:
        floor.hide_render = True
    scene.render.film_transparent = True
    scene.render.image_settings.color_mode = "RGBA"
    material = bpy.data.materials.new("Silhouette inspection")
    material.use_nodes = True
    material.node_tree.nodes.clear()
    emission = material.node_tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (1,1,1,1)
    output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(emission.outputs[0],output.inputs[0])
    old = scene.view_layers[0].material_override
    scene.view_layers[0].material_override = material
    for view,location in {"front":(0,-5,.9),"left":(5,0,.9),"back":(0,5,.9)}.items():
        recovery.render_frame(f"{label}_mask_{view}",location,(0,0,.85),2.04)
    scene.view_layers[0].material_override = old
    scene.render.film_transparent = False
    if floor:
        floor.hide_render = old_floor
    bpy.data.materials.remove(material)


def palm_debug(rig):
    objects = []
    record = {}
    baseline = json.loads((FOLDER/"baseline_audit.json").read_text())
    original = {b["name"]:np.array(b["matrix"])[:3,:3] for b in baseline["joints"]}
    for side,sign in (("L",1),("R",-1)):
        bone = rig.data.bones[f"Hand_{side}"]
        center = bone.head_local
        rotation = np.array(bone.matrix_local)[:3,:3] @ original[bone.name].T
        direction = Vector(rotation @ np.array((0,1,0)))
        curve = bpy.data.curves.new("Palm axis inspection","CURVE")
        curve.dimensions = "3D"
        curve.bevel_depth = .003
        spline = curve.splines.new("POLY")
        spline.points.add(1)
        for point,co in zip(spline.points,(center,center+direction*.13)):
            point.co = (*co,1)
        obj = bpy.data.objects.new("Palm axis inspection",curve)
        bpy.context.collection.objects.link(obj)
        material = bpy.data.materials.new("Palm axis diagnostic")
        material.diffuse_color = (.9,.05,.04,1)
        curve.materials.append(material)
        objects.append((obj,curve,material))
        thumb = rig.data.bones[f"Thumb_{side}"].head_local-center
        record[side] = {"palm_axis":list(direction),"inward_dot":direction.dot(Vector((-sign,0,0))),
                        "thumb_root_offset":list(thumb),"thumb_anterior":thumb.y<0}
    recovery.render_frame("neutral_palm_axis_debug",(1.5,-5,1.2),(0,-.05,.50),1.40)
    for obj,curve,material in objects:
        bpy.data.objects.remove(obj,do_unlink=True)
        bpy.data.curves.remove(curve)
        bpy.data.materials.remove(material)
    write_json("palm_axes.json",record)


def complete_proofs():
    baseline = json.loads((FOLDER/"baseline_audit.json").read_text())
    for label,path in (("v4",SOURCE),("v4_1",OUTPUT)):
        bpy.ops.wm.open_mainfile(filepath=str(path))
        rig = bpy.data.objects["Bagusmax_Rig"]
        pose(rig,{})
        silhouettes(rig,label)
    skin = bpy.data.objects["White_SoftSkin"]
    after = prior.inspect_asset(rig)
    geometry = recovery.audit(rig)
    records = []
    rest = prior.coordinates(skin.data)
    for key in list(skin.data.shape_keys.key_blocks)[1:]:
        kind,angle,side = key.name.split("_")
        values = np.empty(len(rest)*3)
        key.data.foreach_get("co",values)
        delta = values.reshape(-1,3)-rest
        records.append({"name":key.name,"mesh":skin.name,"kind":kind,"angle_deg":int(angle),
            "primary":f"{'UpperArm' if kind=='Shoulder' else 'Forearm'}_{side}","default":key.value,
            "changed_vertices":int(np.count_nonzero(np.linalg.norm(delta,axis=1)>1e-7)),
            "max_delta_m":float(np.linalg.norm(delta,axis=1).max())})
    assert protected()==baseline["sha256"]
    for name in ("White_Head","White_Leg_L","White_Leg_R"):
        assert after["meshes"][name]["bounds"]==baseline["meshes"][name]["bounds"]
    assert after["actions"]==0 and after["nla_tracks"]==0
    write_json("asset_audit.json",{"baseline":baseline["glb"],"after":after,"geometry":geometry,"morphs":records,
        "studio":prior.studio_signature(),"preserved_sha256":baseline["sha256"],
        "created_sha256":{str(OUTPUT.relative_to(ROOT)):digest(OUTPUT),str(GLB.relative_to(ROOT)):digest(GLB)}})
    palm_debug(rig)
    reimport_check(rig)
    print("V4_1_PROOFS_COMPLETE",flush=True)


def inspect_saved():
    hashes = (digest(OUTPUT),digest(GLB))
    bpy.ops.wm.open_mainfile(filepath=str(OUTPUT))
    rig = bpy.data.objects["Bagusmax_Rig"]
    skin = bpy.data.objects["White_SoftSkin"]
    keys = {k.name:k.value for k in list(skin.data.shape_keys.key_blocks)[1:]}
    actions = len(bpy.data.actions)
    nla = sum(len(o.animation_data.nla_tracks) for o in bpy.context.scene.objects if o.animation_data)
    max_pose = max(b.rotation_quaternion.angle for b in rig.pose.bones)
    assert actions==0 and nla==0 and max_pose<1e-5 and max(abs(v) for v in keys.values())<1e-6
    bm = bmesh.new()
    bm.from_mesh(skin.data)
    pending = set(bm.verts)
    components = 0
    while pending:
        queue = [pending.pop()]
        components += 1
        while queue:
            for edge in queue.pop().link_edges:
                for v in edge.verts:
                    if v in pending:
                        pending.remove(v)
                        queue.append(v)
    bm.free()
    assert components==1,components
    transforms = {o.name:{"scale":list(o.scale),"determinant":o.matrix_world.determinant(),
                         "parent":o.parent.name if o.parent else None} for o in recovery.visible_meshes()+[rig]}
    assert all(v["determinant"]>0 and max(abs(s-1) for s in v["scale"])<1e-5 for v in transforms.values())
    fingers = {}
    for side in ("L","R"):
        for kind in ("Thumb","Index","Middle","Ring"):
            name = f"{kind}_{side}"
            group = skin.vertex_groups[name].index
            count = sum(any(g.group==group and g.weight>.01 for g in v.groups) for v in skin.data.vertices)
            assert count>0,name
            fingers[name] = count
    write_json("saved_source_state.json",{"actions":actions,"nla_tracks":nla,"max_pose_angle_rad":max_pose,
        "morph_defaults":keys,"skin_connected_components":components,"transforms":transforms,"finger_influenced_vertices":fingers})
    assert hashes==(digest(OUTPUT),digest(GLB))
    print("SAVED_SOURCE_NEUTRAL_PASS",components,len(keys),flush=True)


def main():
    assert ROOT.name in ("OpenBagus", "OpenBagus-3D")
    for path in (SOURCE, SOURCE.parent.parent/"runtime/bagusmax_white_anatomy_v4.glb",
                 ROOT/"docs/bagusmax_3d/WHITE_ANATOMY_V4_HANDOFF.md",
                 ROOT/"reports/bagusmax_3d/white_v4",ROOT/"docs/bagusmax_3d/WHITE_LIGHTING_SPEC.md"):
        assert path.exists(),path
    FOLDER.mkdir(parents=True,exist_ok=True)
    if "--inspect-saved" in sys.argv:
        inspect_saved()
        return
    if "--repair-export" in sys.argv:
        bpy.ops.wm.open_mainfile(filepath=str(OUTPUT))
        rig = bpy.data.objects["Bagusmax_Rig"]
        skin = bpy.data.objects["White_SoftSkin"]
        source_hash = digest(OUTPUT)
        normal_report = fit_normal_targets(rig,skin)
        verify_export(rig,skin)
        reimport_check(rig)
        report = json.loads((FOLDER/"asset_audit.json").read_text())
        report["normal_bake"] = normal_report
        report["created_sha256"][str(GLB.relative_to(ROOT))] = digest(GLB)
        write_json("asset_audit.json",report)
        assert digest(OUTPUT)==source_hash
        print("EXPORT_REPAIR_VERIFIED",flush=True)
        return
    if "--proof-only" in sys.argv:
        complete_proofs()
        return
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    rig = bpy.data.objects["Bagusmax_Rig"]
    recovery.reset(rig)
    if "--audit" in sys.argv:
        baseline_audit(rig)
        return
    before = protected()
    baseline = baseline_audit(rig)
    studio = prior.studio_signature()
    if "--preview" not in sys.argv and "--after-only" not in sys.argv:
        evidence(rig,"v4")
        diagnostics(rig,"v4")
        silhouettes(rig,"v4")
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    rig = bpy.data.objects["Bagusmax_Rig"]
    skin = connect_skin(rig)
    natural_hands(skin,rig)
    records = rebuild_correctives(skin,rig)
    if "--preview" not in sys.argv:
        add_drivers(skin,rig,records)
        geometry = recovery.audit(rig)
        after = prior.inspect_asset(rig)
        for name in ("White_Head","White_Leg_L","White_Leg_R"):
            assert after["meshes"][name]["bounds"]==baseline["meshes"][name]["bounds"]
        normal_report = export_asset(rig,skin,records)
        verify_export(rig,skin)
        evidence(rig,"v4_1",skin)
        diagnostics(rig,"v4_1")
        silhouettes(rig,"v4_1")
        palm_debug(rig)
        reimport_check(rig)
        pose(rig,{})
        assert prior.studio_signature()==studio
        assert protected()==before
        write_json("asset_audit.json",{"baseline":baseline["glb"],"after":after,"geometry":geometry,"morphs":records,
            "studio":studio,"normal_bake":normal_report,"preserved_sha256":before,
            "created_sha256":{str(OUTPUT.relative_to(ROOT)):digest(OUTPUT),str(GLB.relative_to(ROOT)):digest(GLB)}})
        print("V4_1_EXPORT_COMPLETE",GLB,flush=True)
        return
    for side,sign in (("L",1),("R",-1)):
        for angle in (0,30,60,90,145):
            pose(rig,{f"UpperArm_{side}":(0,-sign*math.radians(angle),0)})
            recovery.render_frame(f"candidate_shoulder_{side}_{angle:03}",(sign*2.5,-5,1.9),(sign*.32,0,1.30),.85)
    for side in ("L","R"):
        pose(rig,{f"Forearm_{side}":(-math.radians(130),0,0)})
        recovery.render_frame(f"candidate_elbow_{side}_130",(3 if side=="L" else -3,-5,1.5),(.46 if side=="L" else -.46,-.05,.94),.8)
    pose(rig,tests()["C4"])
    recovery.render_frame("candidate_C4")
    pose(rig,{})
    neutral_views(rig,"candidate")
    write_json("candidate_audit.json",{"meshes":recovery.audit(rig),"morphs":records})
    assert protected()==before


if __name__ == "__main__":
    main()
