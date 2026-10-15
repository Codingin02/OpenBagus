"""Modular armored art authoring on the unchanged White skeleton."""

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Euler, Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from mathutils.geometry import closest_point_on_tri

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_white import mesh_object, material, sweep
import recover_white_anatomy as recovery
from refine_white_deformation import studio_signature
from gltf_skinning import GLBSkin, BLENDER_TO_GLTF
B=BLENDER_TO_GLTF

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets/bagusmax"
REPORT = ROOT / "reports/bagusmax_3d/armored_v1"
DATA = ASSETS / "armor"
SOURCE = ASSETS / "source/bagusmax_armored_v1.blend"
GLB = ASSETS / "runtime/bagusmax_armored_v1.glb"
WHITE = ASSETS / "source/bagusmax_white_anatomy_v4_1.blend"
FACE = ("White_Head", "Eye_L", "Eye_R", "Eye_ContourBridge")
PARTS, ROOTS, REST, REST_WORLD = {}, {}, {}, {}
RIG = None
STAGE = "detail"
REVISION = False
ELBOW_REPAIR = False
SHOULDER_REPAIR = False
B4 = Matrix.Identity(4)
for i in range(3):
    for j in range(3):
        B4[i][j] = BLENDER_TO_GLTF[i, j]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected():
    paths = list((ASSETS / "source").glob("*white*.blend"))
    paths += list((ASSETS / "runtime").glob("*white*.glb"))
    paths += [ROOT / "assets/models/bagusmax_armored.glb", ROOT / "assets/models/source/bagusmax_armored.blend",
              ROOT / "docs/bagusmax_3d/WHITE_LIGHTING_SPEC.md"]
    if REVISION:
        paths += [ASSETS/"source/bagusmax_armored_v1.blend",ASSETS/"runtime/bagusmax_armored_v1.glb",
                  ASSETS/"runtime/bagusmax_armored_v1_quality.glb"]
        paths += list((ASSETS/"armor").glob("*.json"))+list((ASSETS/"armor").glob("*.bin"))
        paths += [ROOT/"docs/bagusmax_3d"/n for n in ("ARMORED_V1_ART_DIRECTION.md","ARMORED_V1_ASSEMBLY_CONTRACT.md",
                 "ARMORED_V1_RUNTIME_HANDOFF.md","ARMORED_V1_ACCEPTANCE_REPORT.md")]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): {"sha256": sha(p), "bytes": p.stat().st_size}
            for p in paths if p.is_file()}


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def soften(obj, width=.002, segments=2):
    if STAGE == "blockout":
        return obj
    activate(obj)
    mod = obj.modifiers.new("ManufacturedEdge", "BEVEL")
    mod.width, mod.segments = width, segments
    mod.limit_method = "ANGLE"
    mod.angle_limit = .48
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def bind(obj, parent, bone=None):
    world = obj.matrix_world.copy()
    obj.parent = parent
    if bone:
        obj.parent_type, obj.parent_bone = "BONE", bone
    bpy.context.view_layer.update()
    obj.matrix_world = world
    bpy.context.view_layer.update()
    assert max(abs(obj.matrix_world[i][j]-world[i][j]) for i in range(4) for j in range(4)) < 1e-5


def group(name, bone, pivot, phase, offset, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.empty_display_type, obj.empty_display_size = "PLAIN_AXES", .035
    obj.location = pivot
    bpy.context.view_layer.update()
    bind(obj, parent or RIG, None if parent else bone)
    obj["assembly_id"], obj["anchor_joint"] = name, bone
    ROOTS[name] = {"object": obj, "bone": bone, "phase": phase, "offset": Vector(offset)}
    return obj


def part(obj, parent, refs, role="shell"):
    obj.name = "ARMOR_" + obj.name
    # Put the node origin at the manufactured part's own pivot, without moving its surface.
    center = sum((v.co for v in obj.data.vertices), Vector()) / max(1, len(obj.data.vertices))
    obj.data.transform(Matrix.Translation(-center))
    obj.location = center
    bpy.context.view_layer.update()
    bind(obj, parent)
    obj["part_id"], obj["source_reference"], obj["mechanical_role"] = obj.name, ",".join(refs), role
    PARTS[obj.name] = {"object": obj, "refs": refs, "role": role, "assembly": parent.name}
    return obj


def patch(name, fn, nu, nv, mat, thickness=.009, bevel=.002):
    periodic=all((Vector(fn(0,v))-Vector(fn(1,v))).length<1e-7 for v in (0,.5,1))
    stride=nu if periodic else nu+1
    vertices = [Vector(fn(i/nu, j/nv)) for j in range(nv+1) for i in range(stride)]
    faces = []
    for j in range(nv):
        for i in range(nu):
            a = j*stride+i
            b = j*stride+(i+1)%stride
            faces.append((a,b,b+stride,a+stride))
    obj = mesh_object(name, vertices, faces, mat)
    bm=bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.000001)
    bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=.000001)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    activate(obj)
    solid = obj.modifiers.new("PlateGauge", "SOLIDIFY")
    solid.thickness, solid.offset, solid.use_even_offset = thickness, 0, True
    bpy.ops.object.modifier_apply(modifier=solid.name)
    return soften(obj, bevel)


def profile(rows,t):
    k=min(len(rows)-2,max(0,int(t)))
    f=t-k
    p0,p1,p2,p3=map(np.asarray,(rows[max(0,k-1)],rows[k],rows[k+1],rows[min(len(rows)-1,k+2)]))
    return .5*((2*p1)+(-p0+p2)*f+(2*p0-5*p1+4*p2-p3)*f*f+(-p0+3*p1-3*p2+p3)*f*f*f)


def loft(name, rows, mat, count=48, thickness=.008, notch=0, lower_notch=0, outer_side=None):
    def surface(u, v):
        t = v*(len(rows)-1)
        cx,cy,z,rx,ry=profile(rows,t)
        a = (u-.5)*math.pi if outer_side else 2*math.pi*u
        z -= notch*(v**7)*max(0, -math.sin(a))**2
        z += lower_notch*((1-v)**7)*max(0,-math.sin(a))**2
        return cx+(outer_side or 1)*rx*math.cos(a), cy+ry*math.sin(a), z
    obj = patch(name, surface, count, (len(rows)-1)*7, mat, thickness)
    # Weld the periodic boundary so every shell has one coherent wall.
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=.000005)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    return obj


def box(name, center, size, mat, bevel=.01):
    c, h = Vector(center), Vector(size)/2
    vertices = [c+Vector((x*h.x, y*h.y, z*h.z)) for x, y, z in
                ((-1,-1,-1), (1,-1,-1), (1,1,-1), (-1,1,-1),
                 (-1,-1,1), (1,-1,1), (1,1,1), (-1,1,1))]
    obj = mesh_object(name, vertices, [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)], mat)
    return soften(obj, bevel, 3)


def bearing(name, center, radius, width, mat, axis="X", hole=.52):
    c = Vector(center)
    ax = Vector((1,0,0) if axis == "X" else (0,1,0) if axis == "Y" else (0,0,1))
    u = Vector((0,1,0)) if axis == "X" else Vector((1,0,0))
    v = ax.cross(u)
    vertices, faces = [], []
    n = 40
    for r, d in ((radius, -width/2), (radius, width/2), (radius*hole, width/2), (radius*hole, -width/2)):
        for i in range(n):
            a = i*2*math.pi/n
            vertices.append(c+d*ax+r*(math.cos(a)*u+math.sin(a)*v))
    for j in range(4):
        for i in range(n):
            a, b = j*n+i, j*n+(i+1)%n
            faces.append((a,b,((j+1)%4)*n+(i+1)%n,((j+1)%4)*n+i))
    return soften(mesh_object(name, vertices, faces, mat), .0012)


def palette():
    specs = {"Red": ((.56,.022,.009),.30,.32), "RedTrim": ((.27,.009,.005),.36,.25),
             "Violet": ((.085,.042,.23),.40,.12), "Graphite": ((.018,.022,.028),.41,.30),
             "Metal": ((.32,.35,.39),.30,.82)}
    result = {}
    for key, (color, rough, metal) in specs.items():
        result[key] = material("Armor_"+key, color, rough)
        result[key].node_tree.nodes.get("Principled BSDF").inputs["Metallic"].default_value = metal
    return result


def torso(m):
    root = group("ASM_CHEST", "Chest", (0,0,1.25), "torso", (0,-.58,.12))
    def chest(u,v):
        a = (u-.5)*math.radians(151)
        side = abs(math.sin(a))
        z0, z1 = 1.085+.11*side**1.5, 1.493-.095*side
        rx = .332+.125*math.sin(v*math.pi*.86)+.022*v
        ry = .287+.024*math.sin(v*math.pi)
        return rx*math.sin(a), -.012-ry*math.cos(a), z0+(z1-z0)*v
    part(patch("CHEST_FRONT", chest, 52, 22, m["Red"],.012), root, ["R02","R10","R11"])
    def collar(u,v):
        a=2*math.pi*u
        rx=.132*(1-v)+.405*v
        ry=.106*(1-v)+.287*v
        return rx*math.sin(a),-.004-ry*math.cos(a),1.480*(1-v)+(1.493-.095*abs(math.sin(a)))*v
    part(patch("CHEST_COLLAR",collar,64,12,m["Red"],.009,.001),root,["R02","R15"])
    part(loft("NECK_SEAL",[(0,.005,1.425,.130,.105),(0,.005,1.485,.127,.101)],m["Graphite"],48,.010),root,["R15"],"neck_seal")
    rear = group("ASM_BACK", "Chest", (0,.25,1.18), "torso", (0,.55,.06))
    part(patch("CHEST_REAR", lambda u,v: ((.33+.07*math.sin(v*math.pi))*math.sin((u-.5)*2.7),
        .01+(.24+.015*v)*math.cos((u-.5)*2.7), 1.00+.39*v), 40,18,m["Red"],.01), rear,["R14"])
    for s, side in ((1,"L"),(-1,"R")):
        part(patch("CHEST_FLANK_"+side, lambda u,v,s=s: (s*(.322+.093*v)*math.sin(1.22+u*1.45),
            -.01-(.278-.025*v)*math.cos(1.22+u*1.45), .73+.60*v), 25,26,m["Red"],.01),root,["R02","R09"])
    for j in range(4):
        z = .747+j*.105
        anchor = group(f"ASM_ABDOMEN_{j+1}", "Spine",(0,-.15,z),"torso",(0,-.48-.025*j,0))
        def abdomen(u,v,z=z,j=j):
            a = (u-.5)*2.63
            x = (.319+.005*j)*math.sin(a)
            step = .010*math.exp(-((abs(x)-.13)/.027)**4)
            return x, -.012-(.278+.003*j)*math.cos(a), z+.109*v+.012*abs(math.sin(a))-step
        part(patch(f"ABDOMEN_SEGMENT_{j+1}",abdomen,48,7,m["Violet"],.01,.0015),anchor,["R02","R10","R13"])
        part(patch(f"ABDOMEN_BACK_{j+1}",lambda u,v,z=z,j=j:
            ((.319+.005*j)*math.sin(math.radians(104+152*u)),
             -.006-(.267+.003*j)*math.cos(math.radians(104+152*u)),z+.107*v),38,7,m["Violet"],.01,.0015),anchor,["R14"])
        if STAGE != "blockout":
            for s in (-1,1):
                part(bearing(f"ABDOMEN_LOCK_{j+1}_{'L' if s==1 else 'R'}",(s*.12,-.281,z+.048),.007,.003,m["Metal"],"Y",.65),anchor,["R02"],"lock")
    hip = group("ASM_PELVIS", "Hips",(0,0,.56),"lower",(0,-.46,-.10))
    for rearward in (False,True):
        part(patch("PELVIS_"+("REAR" if rearward else "FRONT"), lambda u,v,r=rearward:
            ((.265+.065*math.sin(v*math.pi*.7))*math.sin((u-.5)*3.05), (.245 if r else -.255)*math.cos((u-.5)*3.05),
             .464+.105*abs(math.sin((u-.5)*2.6)) + (.72-.464-.08*abs(math.sin((u-.5)*2.6)))*v),
            40,12,m["Red"],.011),hip,["R02","R14"])
    if STAGE != "blockout":
        part(bearing("CHEST_ACCESS_RING",(.164,-.306,1.352),.030,.006,m["RedTrim"],"Y",.82),root,["R02","R15"],"access_port")
        part(bearing("CHEST_ACCESS_LID",(.164,-.308,1.352),.023,.004,m["Red"],"Y",.01),root,["R02"],"access_port")
        for s,side in ((1,"L"),(-1,"R")):
            points=[(s*(.19+.13*t),-.288+.088*t,1.428-.184*t) for t in np.linspace(0,1,24)]
            part(sweep("CHEST_SEAM_"+side,points,.0013,m["RedTrim"],6),root,["R02"],"seam")


def arms(m):
    for s, side in ((1,"L"),(-1,"R")):
        root = group("ASM_PAULDRON_"+side,"Chest",(s*.37,0,1.36),"arms",(s*.48,0,.20))
        def cap(u,v,s=s):
            a = (u-.5)*math.pi*1.33
            t = v*math.pi*.49
            return s*(.418+.321*math.sin(t)*math.cos(a)), .243*math.sin(t)*math.sin(a), 1.286+.276*math.cos(t)
        part(patch("PAULDRON_"+side,cap,40,24,m["Red"],.012),root,["R02","R12"])
        if STAGE != "blockout":
            def inlay(u,v,s=s):
                a=2*math.pi*u
                r=.015+.985*v
                az=.54*r*math.cos(a)
                t=.66+.24*r*math.sin(a)
                p=Vector((s*(.418+.321*math.sin(t)*math.cos(az)),.243*math.sin(t)*math.sin(az),1.286+.276*math.cos(t)))
                n=Vector((s*math.sin(t)*math.cos(az)/.321,math.sin(t)*math.sin(az)/.243,math.cos(t)/.276)).normalized()
                return p+.007*n
            part(patch("PAULDRON_INLAY_"+side,inlay,48,8,m["Violet"],.003,.0007),root,["R01","R12"],"inlay")
        upper = group("ASM_UPPERARM_"+side,"UpperArm_"+side,(s*.43,0,1.17),"arms",(s*.46,.05,.06))
        rows=[(s*.475,-.01,.975,.112,.12),(s*.469,-.008,1.015,.145,.151),
              (s*.447,0,1.105,.154,.16),(s*.424,0,1.22,.147,.15),(s*.405,0,1.285,.117,.125)]
        rows=[(x+s*.045,y,z,rx,ry) for x,y,z,rx,ry in rows]
        part(loft("UPPERARM_"+side,rows,m["Red"],40,.010,lower_notch=.095,outer_side=s),upper,["R02","R09"])
        part(bearing("SHOULDER_RECESS_"+side,(s*.475,0,1.28),.121,.038,m["Graphite"],"Z"),upper,["R02"],"bearing")
        elbow = group("ASM_ELBOW_"+side,"Forearm_"+side,(s*.4888,-.02,.90),"arms",(s*.49,.05,0))
        part(bearing("ELBOW_SOCKET_"+side,(s*.489,-.02,.90),.074,.19,m["Graphite"],"X",.55),elbow,["R09"],"bearing")
        part(bearing("ELBOW_METAL_"+side,(s*.592,-.02,.90),.068,.023,m["Metal"],"X",.52),elbow,["R02","R09"],"bearing")
        part(bearing("ELBOW_HUB_"+side,(s*.607,-.02,.90),.032,.014,m["Graphite"],"X",.01),elbow,["R09"],"hub")
        lower=group("ASM_FOREARM_"+side,"Forearm_"+side,(s*.498,-.04,.74),"arms",(s*.49,-.04,-.10))
        rows=[(s*.502,-.065,.555,.100,.106),(s*.510,-.059,.595,.126,.132),
              (s*.521,-.043,.68,.159,.162),(s*.519,-.026,.764,.164,.171),
              (s*.506,-.016,.842,.139,.145)]
        part(loft("FOREARM_"+side,rows,m["Red"],56,.011,notch=.081),lower,["R01","R02","R09"])
        if STAGE != "blockout":
            part(loft("FOREARM_CUFF_"+side,[(s*.502,-.065,.55,.105,.111),(s*.505,-.063,.578,.115,.122)],m["RedTrim"],48,.006),lower,["R02"],"cuff")
            def inlay(u,v,s=s,rows=rows):
                a=2*math.pi*u
                r=.01+.99*v
                az=.69*r*math.cos(a)
                cx,cy,z,rx,ry=profile(rows,1.55+.68*r*math.sin(a))
                n=Vector((s*math.cos(az),math.sin(az),0)).normalized()
                return Vector((cx+s*rx*math.cos(az),cy+ry*math.sin(az),z))+.007*n
            part(patch("FOREARM_INLAY_"+side,inlay,40,7,m["Violet"],.003,.0006),lower,["R01","R09"],"inlay")
        hands(m,s,side)


def hands(m,s,side):
    palm=group("ASM_HAND_"+side,"Hand_"+side,(s*.502,-.066,.50),"arms",(s*.48,-.10,-.18))
    part(box("PALM_"+side,(s*.502,-.066,.487),(.106,.187,.128),m["Graphite"],.026),palm,["R01","R02"],"palm")
    part(bearing("WRIST_"+side,(s*.502,-.066,.55),.058,.042,m["Graphite"],"Z",.7),palm,["R02"],"wrist")
    for digit, y, z in (("Index",-.1227,.478),("Middle",-.0637,.477),("Ring",-.0047,.480)):
        x=s*{"Index":.5177,"Middle":.5257,"Ring":.5067}[digit]
        parent=group(f"CTRL_{digit.upper()}_{side}_0",digit+"_"+side,(x,y,z),"arms",(s*.48,-.10,-.18))
        for k,length in enumerate((.036,.030,.027)):
            if k:
                parent=group(f"CTRL_{digit.upper()}_{side}_{k}",digit+"_"+side,(x,y,z),"inherit",(0,0,0),parent)
            part(box(f"{digit.upper()}_{side}_{k}",(x,y,z-length/2),(.070,.049,length-.003),m["Graphite"],.009),parent,["R01","R12"],"finger_segment")
            if k==0:
                part(bearing(f"KNUCKLE_{digit.upper()}_{side}",(x+s*.037,y,z-.012),.017,.008,m["Metal"],"X",.48),parent,["R01"],"knuckle")
            z-=length
    thumb=group("CTRL_THUMB_"+side+"_0","Thumb_"+side,(s*.538,-.155,.495),"arms",(s*.48,-.10,-.18))
    part(box("THUMB_"+side,(s*.54,-.158,.470),(.064,.057,.066),m["Graphite"],.017),thumb,["R02"],"finger_segment")
    tip=group("CTRL_THUMB_"+side+"_1","Thumb_"+side,(s*.54,-.158,.447),"inherit",(0,0,0),thumb)
    part(box("THUMB_TIP_"+side,(s*.54,-.158,.432),(.059,.052,.036),m["Graphite"],.013),tip,["R02"],"finger_segment")


def legs(m):
    for s,side in ((1,"L"),(-1,"R")):
        thigh=group("ASM_THIGH_"+side,"Thigh_"+side,(s*.171,0,.47),"lower",(s*.38,.04,-.12))
        rows=[(s*.19,0,.271,.112,.133),(s*.19,-.006,.315,.154,.18),
              (s*.185,-.009,.405,.181,.197),(s*.179,0,.49,.174,.178),(s*.174,.006,.555,.121,.13)]
        rows=[(x+s*.014,y,z,rx,ry) for x,y,z,rx,ry in rows]
        part(loft("THIGH_"+side,rows,m["Red"],52,.010),thigh,["R02","R10"])
        if STAGE != "blockout":
            def ridge(u,v,s=s,rows=rows):
                a=math.pi*2*u;r=.01+.99*v
                cx,cy,z,rx,ry=profile(rows,2.0+1.25*r*math.sin(a))
                az=-math.pi/2+.34*r*math.cos(a)
                return cx+s*rx*math.cos(az),cy+(ry+.007)*math.sin(az),z
            part(patch("THIGH_RIDGE_"+side,ridge,40,12,m["Red"],.003,.0007),thigh,["R02"],"inset")
        shin=group("ASM_SHIN_"+side,"Shin_"+side,(s*.171,0,.24),"lower",(s*.37,.06,-.16))
        part(bearing("KNEE_RECESS_"+side,(s*.171,0,.247),.073,.19,m["Graphite"],"X",.4),shin,["R02","R10"],"bearing")
        part(loft("SHIN_"+side,[(s*.171,.005,.075,.124,.128),(s*.171,.008,.105,.139,.146),
             (s*.175,.009,.17,.146,.151),(s*.175,.002,.223,.129,.130)],m["Red"],48,.010),shin,["R02"])
        foot=group("ASM_BOOT_"+side,"Foot_"+side,(s*.171,-.03,.08),"lower",(s*.35,-.12,-.24))
        part(loft("BOOT_"+side,[(s*.171,-.052,.028,.145,.198),(s*.171,-.060,.046,.154,.212),
             (s*.171,-.063,.085,.148,.205),(s*.171,-.035,.115,.111,.132)],m["Red"],56,.009),foot,["R02","R10"])
        part(loft("BOOT_SOLE_"+side,[(s*.171,-.058,.003,.142,.198),(s*.171,-.058,.026,.146,.202)],m["Graphite"],56,.009),foot,["R02"],"sole")


def helmet(m):
    root=group("ASM_HELMET","Head",(0,-.02,1.585),"helmet",(0,0,.44))
    def sphere(u,v,amin,amax,lmin,lmax):
        a=math.radians(amin+(amax-amin)*u)
        t=math.radians(lmin+(lmax-lmin)*v)
        return .235*math.cos(t)*math.sin(a), -.020-.188*math.cos(t)*math.cos(a), 1.585+.145*math.sin(t)
    part(patch("HELMET_REAR",lambda u,v:sphere(u,v,65,295,-65,31),56,24,m["Red"],.009),root,["R15"])
    part(patch("HELMET_CROWN",lambda u,v:sphere(u,v,-180,180,31.5,89.5),64,18,m["Red"],.009),root,["R15"])
    part(patch("HELMET_CHIN",lambda u,v:sphere(u,v,-58,58,-69,-30),40,15,m["Red"],.011),root,["R15"])
    def frame(u,v):
        a=2*math.pi*u
        rx=.162*(1-v)+.234*v
        rz=.047*(1-v)+.143*v
        x=rx*math.cos(a)
        z=1.580+.005*v+rz*math.sin(a)+.005*(1-v)*abs(math.cos(a))
        z-=.018*(1-v)*max(0,math.sin(a))*math.exp(-(x/.085)**2)
        y=-.022-.190*math.sqrt(max(.005,1-(x/.235)**2-((z-1.585)/.145)**2))
        return x,y,z
    part(patch("HELMET_FACE_FRAME",frame,72,18,m["Red"],.010,.0014),root,["R15","R12"])
    if STAGE != "blockout":
        def gasket(u,v):
            x,y,z=frame(u,0)
            return x*(1-.007*v),y-.001,z+.0015*v*math.sin(2*math.pi*u)
        part(patch("VISOR_GASKET",gasket,72,2,m["Graphite"],.002,.0004),root,["R15"],"gasket")
    for s,side in ((1,"L"),(-1,"R")):
        part(bearing("HELMET_EAR_"+side,(s*.235,-.005,1.588),.071,.016,m["Violet"],"X",.01),root,["R15"],"ear")
        part(patch("HELMET_FIN_"+side,lambda u,v,s=s:(s*(.209+.040*u+.012*v),-.035+.045*u,
              1.557+.150*v-.045*u*v),8,14,m["Red"],.008,.001),root,["R15"])


def back_wings(m):
    pack=group("ASM_BACKPACK","Chest",(0,.31,1.16),"torso",(0,.62,.06))
    part(box("BACKPACK_CORE",(0,.307,1.17),(.58,.25,.44),m["Red"],.047),pack,["R14"],"propulsion")
    for s,side in ((1,"L"),(-1,"R")):
        for k,z in enumerate((1.065,1.285)):
            part(bearing(f"REAR_VENT_{side}_{k}",(s*.123,.439,z),.044,.022,m["Graphite"],"Y",.67),pack,["R14"],"vent")
            part(bearing(f"REAR_NOZZLE_{side}_{k}",(s*.123,.447,z),.025,.017,m["Metal"],"Y",.72),pack,["R14"],"nozzle")
        wing=group("ASM_WING_ROOT_"+side,"Chest",(s*.267,.455,1.355),"inherit",(0,0,0),pack)
        part(bearing("WING_ROOT_HINGE_"+side,(s*.267,.455,1.355),.067,.052,m["Graphite"],"Y",.5),wing,["R14"],"hinge")
        part(bearing("WING_ROOT_PIN_"+side,(s*.267,.486,1.355),.034,.016,m["Metal"],"Y",.01),wing,["R14"],"pin")
        def blade(u,v,start,length,s=s):
            x=start+length*u
            chord=max(.008,.35*(1-(x/1.11)**1.35))
            return s*(.267+x),.455+.015*math.sin(math.pi*v)*(1-.5*x),1.355+.15*x-.03*x*x+(v-.5)*chord
        part(patch("WING_MAIN_"+side,lambda u,v:blade(u,v,.015,.635),32,12,m["Red"],.026,.003),wing,["R01","R13","R14"],"wing")
        tip=group("ASM_WING_TIP_"+side,"Chest",(s*.925,.455,1.4407),"inherit",(0,0,0),wing)
        part(bearing("WING_TIP_HINGE_"+side,(s*.925,.455,1.4407),.037,.035,m["RedTrim"],"Y",.52),tip,["R14"],"hinge")
        part(patch("WING_TIP_"+side,lambda u,v:blade(u,v,.665,.43),26,12,m["Red"],.021,.0025),tip,["R01","R14"],"wing")
        if STAGE != "blockout":
            for parent,start,length in ((wing,.07,.53),(tip,.71,.34)):
                pts=[blade(t,.28,start,length) for t in np.linspace(0,1,30)]
                pts=[(x,y+.014,z) for x,y,z in pts]
                part(sweep("WING_PANEL_LINE_"+side+str(start),pts,.0014,m["RedTrim"],6),parent,["R14"],"seam")


def capture_rest():
    bpy.context.view_layer.update()
    REST.update({name: row["object"].matrix_basis.copy() for name,row in ROOTS.items()})
    REST_WORLD.update({name: row["object"].matrix_world.copy() for name,row in ROOTS.items()})


def local_world_delta(name, rotation=(0,0,0), translation=(0,0,0)):
    obj=ROOTS[name]["object"]
    rest=REST[name]
    # Conjugate world anatomical axes into the parent frame, preserving the part pivot.
    basis=REST_WORLD[name].to_3x3()
    r=Euler(rotation).to_matrix()
    obj.matrix_basis=rest @ (basis.inverted() @ r @ basis).to_4x4()
    obj.location=rest.translation + rest.to_3x3() @ Vector(translation)


def pose(changes=None, wing=0, gesture="relaxed"):
    recovery.reset(RIG)
    for name,angles in (changes or {}).items():
        recovery.world_rotation(RIG,name,angles)
    recovery.update_volume_helpers(RIG)
    for name,mat in REST.items():
        ROOTS[name]["object"].matrix_basis=mat.copy()
    bpy.context.view_layer.update()
    for s,side in ((1,"L"),(-1,"R")):
        a=abs((changes or {}).get("UpperArm_"+side,(0,0,0))[1])
        bend=abs((changes or {}).get("Forearm_"+side,(0,0,0))[0])
        f=max(0,min(1,(math.degrees(bend)-55)/75))
        relief=max(0,min(1,(math.degrees(a)-30)/60))*f if ELBOW_REPAIR else 0
        local_world_delta("ASM_PAULDRON_"+side,(0,-s*a*.64,0),
            (s*(.07*math.sin(a/2)+.06*relief),.10*relief,.025*math.sin(a)))
        local_world_delta("ASM_FOREARM_"+side,translation=(0,0,-.055*f))
        shoulder_comp=max(0,min(1,(math.degrees(a)-60)/85)) if ELBOW_REPAIR else 0
        local_world_delta("ASM_UPPERARM_"+side,translation=(0,0,.105*f*(1-.6*shoulder_comp)))
        if ELBOW_REPAIR:
            local_world_delta("ASM_ELBOW_"+side,rotation=(-.10*bend,0,0))
        # Root folds down behind the pack; tip folds back up through its own hinge.
        local_world_delta("ASM_WING_ROOT_"+side,(0,s*math.radians(89*(1-wing)),0))
        local_world_delta("ASM_WING_TIP_"+side,(0,-s*math.radians(154*(1-wing)),0))
        for digit in ("INDEX","MIDDLE","RING","THUMB"):
            for k in range(2 if digit=="THUMB" else 3):
                curl=10 if gesture=="relaxed" else (5 if gesture=="point" and digit=="INDEX" else 65)
                if digit=="THUMB": curl*=.65
                local_world_delta(f"CTRL_{digit}_{side}_{k}",(0,s*math.radians(curl),0))
    bpy.context.view_layer.update()


def render(name, view="three_quarter", scale=2.10, target=(0,0,.86), size=800):
    views={"front":(0,-5,.86),"back":(0,5,.86),"left":(5,0,.86),"right":(-5,0,.86),
           "three_quarter":(3,-5,1.7),"rear_quarter":(3,5,1.7)}
    recovery.REVIEW=REPORT
    recovery.render_frame(name,views.get(view,view),target,scale)


def baseline():
    saved=REPORT/"preservation_before.json"
    live=protected()
    if saved.exists():
        assert json.loads(saved.read_text())==live,"A protected asset changed since the armor baseline"
    else:
        write_json(saved,live)
    bpy.ops.wm.open_mainfile(filepath=str(WHITE))
    global RIG
    RIG=bpy.data.objects["Bagusmax_Rig"]
    recovery.reset(RIG)
    data={"blender":bpy.app.version_string,"coordinate_system":"meters; +Z up; -Y forward; +X anatomical left",
          "joints":[{"name":b.name,"parent":b.parent.name if b.parent else None,"head":list(b.head_local),
                     "tail":list(b.tail_local),"matrix":[list(r) for r in b.matrix_local]} for b in RIG.data.bones],
          "meshes":[{"name":o.name,"matrix_world":[list(r) for r in o.matrix_world],
                     "shape_keys":[k.name for k in o.data.shape_keys.key_blocks] if o.data.shape_keys else [],
                     "vertices":len(o.data.vertices)} for o in recovery.visible_meshes()],"studio":studio_signature()}
    assert len(RIG.data.bones)==32
    write_json(REPORT/"baseline_inventory.json",data)
    return data


def clearance():
    skin=bpy.data.objects["White_SoftSkin"]
    key=skin.shape_key_add(name="ArmorClearance")
    attr=skin.data.attributes["AnatomicalRegion"]
    for i,v in enumerate(key.data):
        if attr.data[i].value != 0:
            continue
        z=v.co.z
        f=max(0,min(1,(z-.43)/.19))*max(0,min(1,(1.30-z)/.24))
        f=f*f*(3-2*f)
        v.co.x*=1-.36*f
        v.co.y=-.015+(v.co.y+.015)*(1-.39*f)
    key.value=0
    return key


def assembly(progress):
    pose()
    phases={"lower":(.20,.95),"torso":(.55,1.75),"arms":(1.0,2.35),"helmet":(1.90,2.85)}
    t=3.4*progress
    for name,row in ROOTS.items():
        if row["phase"]=="inherit": continue
        start,end=phases[row["phase"]]
        u=max(0,min(1,(t-start)/(end-start)))
        u=u*u*(3-2*u)
        # A curved approach has zero displacement at the seated endpoint.
        shift=row["offset"]*(1-u)+Vector((0,0,.08))*math.sin(math.pi*u)
        obj=row["object"]
        parent=obj.matrix_world @ obj.matrix_basis.inverted()
        obj.location += parent.to_3x3().inverted() @ shift
    bpy.context.view_layer.update()


def export_asset(path,reset_pose=True,replace=False):
    path=Path(path).resolve()
    if REVISION:assert path.resolve()==GLB.resolve(),"Revision export must not overwrite a baseline"
    if not SHOULDER_REPAIR and path.exists():raise FileExistsError("Baseline export protected; use a new candidate destination")
    temporary=path
    if SHOULDER_REPAIR:
        assert path.name=="bagusmax_armored_v1_2.glb" and path.parent==(ASSETS/"runtime").resolve(),"Resolved export destination must be the V1.2 runtime file"
        assert path== (ASSETS/"runtime/bagusmax_armored_v1_2.glb").resolve()
        if path.exists() and not replace:raise FileExistsError("Use --replace-candidate explicitly for V1.2 only")
        temporary=path.with_name(".bagusmax_armored_v1_2.exporting.glb")
        assert not temporary.exists() and not temporary.is_symlink(),"Unfinished export exists; inspect it before replacing"
    if reset_pose:pose()
    bpy.ops.object.select_all(action="DESELECT")
    for obj in [RIG]+[r["object"] for r in ROOTS.values()]+[p["object"] for p in PARTS.values()]+[bpy.data.objects[n] for n in FACE]:
        obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(temporary),export_format="GLB",use_selection=True,
        export_skins=True,export_animations=False,export_morph=False,export_yup=True,
        export_all_influences=False,export_extras=True,export_apply=False)
    asset=GLBSkin(temporary)
    if ELBOW_REPAIR:
        asset.doc["asset"].setdefault("extras",{})["armor_profile"]="1.1"
    if SHOULDER_REPAIR:asset.doc["asset"]["extras"]["armor_profile"]="1.2"
    # glTF skinning ignores mesh-node parent transforms; keep skinned faces at scene roots.
    for i,node in enumerate(asset.doc["nodes"]):
        if "skin" in node and i in asset.parents:
            asset.doc["nodes"][asset.parents[i]]["children"].remove(i)
            for scene in asset.doc["scenes"]:
                if i not in scene["nodes"]: scene["nodes"].append(i)
    asset.replace_normal_targets({})
    if SHOULDER_REPAIR:
        from review_armored import validate
        import review_armored
        review_armored.REPORT=REPORT
        issues=validate(temporary)
        assert issues["numErrors"]==0 and issues["numWarnings"]==0,issues
        assert len(asset.doc.get("animations",[]))==0
        assert shoulder_protected()==json.loads((REPORT/"preservation_before.json").read_text())
        if replace:os.replace(temporary,path)
        else:
            os.link(temporary,path)
            temporary.unlink()
        assert shoulder_protected()==json.loads((REPORT/"preservation_before.json").read_text())


def desktop_profile():
    rows=[]
    for name,row in PARTS.items():
        obj=row["object"]
        original=obj.data
        original.calc_loop_triangles()
        before=len(original.loop_triangles)
        keep_surface=any(k in name for k in ("CHEST_","ABDOMEN_","PELVIS_","HELMET_"))
        if keep_surface or len(original.vertices)<240 or row["role"] in ("seam","lock","pin","knuckle"):
            continue
        original.name="QUALITY_"+name
        original.use_fake_user=True
        obj.data=original.copy()
        obj.data.name=name+"_Desktop"
        obj["quality_mesh_datablock"]=original.name
        activate(obj)
        mod=obj.modifiers.new("DesktopCurvatureBudget","DECIMATE")
        mod.ratio=.53
        mod.use_collapse_triangulate=True
        bpy.ops.object.modifier_apply(modifier=mod.name)
        obj.data.calc_loop_triangles()
        tree=BVHTree.FromPolygons([v.co for v in obj.data.vertices],[list(p.vertices) for p in obj.data.polygons])
        ids=np.linspace(0,len(original.vertices)-1,min(512,len(original.vertices)),dtype=int)
        errors=[tree.find_nearest(original.vertices[int(i)].co)[3] for i in ids]
        rows.append({"part":name,"quality_triangles":before,"desktop_triangles":len(obj.data.loop_triangles),
                     "quality_to_desktop_surface_samples":len(ids),"max_sampled_surface_error_mm":max(errors)*1000,
                     "rms_sampled_surface_error_mm":float(np.sqrt(np.mean(np.square(errors)))*1000)})
    write_json(REPORT/"quality_desktop_profile.json",{"ratio":.53,"measure":"quality vertices to desktop triangle surface; not Hausdorff bound",
        "parts":rows,"quality_meshes_retained_in_source":True,"status":"MEASURED; visual review required"})


def manifests():
    asset=GLBSkin(GLB)
    assembly_nodes=[]
    for name,row in ROOTS.items():
        i=asset.names[name]
        target=asset.local[i]
        parent=asset.rest[asset.parents[i]] if i in asset.parents else np.eye(4)
        offset=BLENDER_TO_GLTF @ np.asarray(row["offset"])
        start=target.copy()
        start[:3,3]+=np.linalg.inv(parent[:3,:3]) @ offset
        assembly_nodes.append({"node":name,"node_index":i,"anchor_joint":row["bone"],
            "phase":row["phase"],"inherits_assembly":row["phase"]=="inherit",
            "parent_node":asset.nodes[asset.parents[i]].get("name") if i in asset.parents else None,
            "target_local_matrix":target.T.ravel().tolist(),"start_local_matrix":start.T.ravel().tolist(),
            "approach_offset_world_gltf":offset.tolist(),"arc_height_m":.08 if row["phase"]!="inherit" else 0})
    parts=[]
    for name,row in PARTS.items():
        i=asset.names[name]
        node=asset.nodes[i]
        mesh=asset.doc["meshes"][node["mesh"]]
        parent=asset.nodes[asset.parents[i]]["name"]
        world=asset.rest[i]
        lo,hi=np.full(3,np.inf),np.full(3,-np.inf)
        mats=[]
        for prim in mesh["primitives"]:
            p=asset.accessor(prim["attributes"]["POSITION"])
            p=p@world[:3,:3].T+world[:3,3]
            lo=np.minimum(lo,p.min(axis=0));hi=np.maximum(hi,p.max(axis=0))
            mats.append(asset.doc["materials"][prim["material"]]["name"])
        tr,qr,sc=Matrix(asset.local[i].tolist()).decompose()
        parts.append({"part_id":name,"mesh_name":mesh["name"],"gltf_node_name":name,"node_index":i,
            "assembly_node":parent,"material_id":mats,"local_bind_matrix":asset.local[i].T.ravel().tolist(),
            "parent_bone_or_anchor":ROOTS[parent]["bone"],
            "assembly_start_transform":asset.local[i].T.ravel().tolist(),
            "assembly_target_transform":asset.local[i].T.ravel().tolist(),
            "inherits_approach_from_assembly_node":True,
            "local_pivot":[0,0,0],"world_pivot_gltf":world[:3,3].tolist(),
            "rest_translation":list(tr),"rest_rotation_xyzw":[qr.x,qr.y,qr.z,qr.w],
            "rest_scale":list(sc),"bounds_world_gltf":[lo.tolist(),hi.tolist()],
            "mechanical_role":row["role"],"collision_group":name.split("_")[1],
            "clearance":{"design_air_gap_m":.005,"measurement":"see collision_samples.json; not a signed-distance guarantee"},
            "nominal_shell_gauge_m":.009 if row["role"]=="shell" else None,
            "render_order":None,"visibility_group":parent,"animation_group":parent,"lod_group":"DESKTOP_RUNTIME",
            "source_reference":row["refs"]})
        if ELBOW_REPAIR:
            parts[-1].update(parent_node=parent,rest_transform=asset.local[i].T.ravel().tolist(),
                attachment_point={"space":"parent local","translation":list(tr)},
                mount_target={"white_joint":ROOTS[parent]["bone"],"assembly_node":parent},
                visibility_state="INSTALLED_VISIBLE",default_installed_position=asset.local[i].T.ravel().tolist(),
                dependency_list=[parent,ROOTS[parent]["bone"]],
                required_articulation_mapping={"contract":"armor_attachment_map.json","control_node":parent,"rigid":True})
            parts[-1]["clearance"]={"nominal_swept_cutter_margin_m":.004 if name in ("ARMOR_FOREARM_L","ARMOR_FOREARM_R","ARMOR_FOREARM_INLAY_L","ARMOR_FOREARM_INLAY_R") else None,
                "certification":"NOT_CERTIFIED; per-pose contacts in reports/bagusmax_3d/armored_v1_1/clearance_matrix.json; nominal construction tolerance is not a measured minimum air gap"}
    write_json(DATA/"armor_assembly_manifest.json",{"version":"1.1-review" if ELBOW_REPAIR else "1.0-review","asset":str(GLB.relative_to(ROOT)).replace("\\","/"),
        "asset_sha256":sha(GLB),"coordinates":"glTF meters; Y up; +Z forward; +X anatomical left",
        "matrix_layout":"column-major; column vectors; world=parent_world*local",
        "neutral":"seated armor, relaxed hands, folded wings; 0 animation clips",
        "assembly_nodes":assembly_nodes,"parts":parts})
    write_json(DATA/"armor_materials.json",asset.doc["materials"])
    write_json(DATA/"armor_attachment_map.json",{"white_sha256":sha(ASSETS/"runtime/bagusmax_white_anatomy_v4_1.glb"),
        "rig_joints":[{"name":b.name,"parent":b.parent.name if b.parent else None,
           "rest_global_matrix_gltf":asset.rest[asset.names[b.name]].T.ravel().tolist()} for b in RIG.data.bones],
        "armor_nodes":assembly_nodes,"shoulder_control":{"fraction":.64,"lateral_slide_m":.07,"lift_m":.025},
        "elbow_shell_clearance":{"start_deg":55,"end_deg":130,"forearm_distal_m":.055,"upperarm_proximal_m":.105},
        "wing_states":{"folded":{"root_y_deg":89,"root_x_deg":0,"tip_y_deg":-154},
             "partial":{"progress":.5},"deployed":{"progress":1}},
        "finger_controls":"CTRL_{INDEX|MIDDLE|RING|THUMB}_{L|R}_{segment}; rotate in anatomical world Y conjugated into rest basis",
        "contract_status":"REVIEW_REQUIRED; no runtime controller included"})
    if ELBOW_REPAIR:
        mapping=json.loads((DATA/"armor_attachment_map.json").read_text())
        mapping.update(elbow_cup={"L":"ElbowVolume_L","R":"ElbowVolume_R","rule":"helper = 0.5 * Forearm rest-axis delta; ASM_ELBOW additional rotation = -0.10 * abs(flexion) around anatomical X; total 0.60 flexion; no extra bone"},
            combined_pauldron_clearance={"elevation_start_deg":30,"elevation_end_deg":90,"flexion_start_deg":55,"flexion_end_deg":130,
                "rule":"r=clamp((E-30)/60)*clamp((B-55)/75); add s*0.06*r X, +0.10*r Y in Blender anatomical rest axes", "lateral_m":.06,"rearward_m":.10},
            upperarm_stroke_rule="f=clamp((B-55)/75); c=clamp((E-60)/85); proximal stroke=0.105*f*(1-0.6*c) meters",
            geometry="Original forearm/inlay split by upper-arm swept volume at 5deg increments; removed material becomes articulated guard on existing elbow helper. Guard edge clearance is geometric, not a hidden filler; no corrective morph.")
        write_json(DATA/"armor_attachment_map.json",mapping)
    write_json(DATA/"armor_transformation_timeline.json",{"duration_seconds":3.4,"default_wing_state":"folded",
        "phases":{"prepare":[0,.20],"lower":[.20,.95],"torso":[.55,1.75],"arms":[1.,2.35],"helmet":[1.9,2.85],"final_lock":[2.7,3.4]},
        "easing":"u=clamp((3.4*p-start)/(end-start)); e=u*u*(3-2*u)",
        "path":"target_translation + inverse(parent_world_3x3)*(offset_world*(1-e) + gltf_up*.08*sin(pi*e))",
        "rotation":"seated rotation maintained; no arbitrary spin; mechanical hinge controls independent",
        "reverse":"evaluate the same absolute progress p in descending order; never integrate deltas",
        "idempotence":"requesting current target must not restart; interruption continues from current progress",
        "visibility":"cover-to-mask per anatomical region requires Antigravity integration; do not hide entire White on first frame",
        "runtime_implemented":False})
    return asset


def source_snapshot():
    result={}
    for name,row in PARTS.items():
        obj=row["object"]
        indices=np.linspace(0,len(obj.data.vertices)-1,24,dtype=int)
        points=[list(B4 @ obj.matrix_world @ obj.data.vertices[int(i)].co) for i in indices]
        result[name]={"matrix":np.asarray(B4 @ obj.matrix_world @ B4.inverted()).tolist(),"probes":points}
    return result


def inspection():
    tests=[("neutral",{},0,"relaxed")]
    for side,s in (("L",1),("R",-1)):
        for a in (30,60,90,120,145): tests.append((f"shoulder_{side}_{a}",{f"UpperArm_{side}":(0,-s*math.radians(a),0)},0,"relaxed"))
        for a in (45,90,110,120,130): tests.append((f"elbow_{side}_{a}",{f"Forearm_{side}":(-math.radians(a),0,0)},0,"relaxed"))
    tests += [("forward_fist",{"UpperArm_L":(-1.0,0,0),"Forearm_L":(-1.0,0,0)},0,"fist"),
              ("head_turn",{"Head":(0,0,.44)},0,"relaxed"),("head_nod",{"Head":(.26,0,0)},0,"relaxed"),
              ("leg_step",{"Thigh_L":(-.44,0,0),"Shin_L":(.70,0,0),"Foot_L":(-.17,0,0)},0,"relaxed"),
              ("point",{},0,"point"),("wings_partial",{},.5,"relaxed"),("wings_deployed",{},1,"fist"),
              ("finger_anchor_L",{"Index_L":(0,.52,0)},0,"relaxed"),
              ("finger_anchor_R",{"Index_R":(0,-.52,0)},0,"relaxed"),
              ("combined",{"UpperArm_L":(0,-1.57,0),"Forearm_L":(-1.57,0,0),"UpperArm_R":(-.52,0,0),"Forearm_R":(-1.57,0,0)},1,"fist")]
    rows=[]
    for name,changes,wing,gesture in tests:
        pose(changes,wing,gesture)
        rows.append({"name":name,"joint_deltas_blender_xyz":changes,"wing_progress":wing,"gesture":gesture,
                     "nodes":source_snapshot()})
    write_json(REPORT/"blender_pose_matrices.json",rows)
    pose()
    return tests


def fitting_data():
    original=GLBSkin(ASSETS/"runtime/bagusmax_white_anatomy_v4_1.glb")
    skin=bpy.data.objects["White_SoftSkin"]
    region=skin.data.attributes["AnatomicalRegion"]
    key=skin.data.shape_keys.key_blocks["ArmorClearance"]
    tree=KDTree(len(skin.data.vertices))
    basis=skin.data.shape_keys.key_blocks["Basis"]
    for i,v in enumerate(basis.data):tree.insert(B4@skin.matrix_world@v.co,i)
    tree.balance()
    prim=next(p for p in original.primitives if p["name"]==skin.name)
    mapping=np.asarray([tree.find(Vector(p))[1] for p in prim["position"]],dtype=int)
    errors=np.asarray([tree.find(Vector(p))[2] for p in prim["position"]])
    assert errors.max()<.00001
    delta=np.asarray([list(B4.to_3x3()@(key.data[int(i)].co-basis.data[int(i)].co)) for i in mapping],dtype="<f4")
    selected=np.flatnonzero(np.linalg.norm(delta,axis=1)>1e-8).astype("<u4")
    data=bytearray(selected.tobytes())
    values_offset=len(data);data.extend(delta[selected].tobytes())
    regions=[]
    labels=[]
    for i in mapping:
        z=basis.data[int(i)].co.z
        r=region.data[int(i)].value
        if r==0:
            label="chest" if z>1.13 else "abdomen" if z>.73 else "pelvis"
        else:
            side="L" if r==1 else "R"
            label=("shoulder" if z>1.25 else "upperarm" if z>.965 else "elbow" if z>.835 else "forearm" if z>.55 else "hand")+"_"+side
        labels.append(label)
    labels=np.asarray(labels)
    triangle_labels=[]
    for tri in prim["indices"]:
        names,counts=np.unique(labels[tri],return_counts=True)
        triangle_labels.append(names[np.argmax(counts)])
    triangle_labels=np.asarray(triangle_labels)
    for name in sorted(set(triangle_labels)):
        ids=prim["indices"][triangle_labels==name].astype("<u4").ravel()
        offset=len(data);data.extend(ids.tobytes())
        regions.append({"region":name,"index_buffer_offset":offset,"index_count":len(ids),"component_type":"UNSIGNED_INT"})
    path=DATA/"armor_white_fit.bin"
    path.write_bytes(data)
    write_json(DATA/"armor_white_fit.json",{"white_glb_sha256":sha(original.path),"target_mesh":"White_SoftSkin",
        "binary":path.name,"binary_sha256":sha(path),"little_endian":True,"original_vertex_count":len(mapping),
        "mapping_max_error_m":float(errors.max()),"clearance":{"default":0,"armored":1,"indices_offset":0,
            "count":len(selected),"indices_component_type":"UNSIGNED_INT","position_delta_offset":values_offset,
            "position_delta_type":"FLOAT_VEC3","coordinates":"mesh bind space glTF; apply before White morphs and skinning",
            "normal_policy":"recompute vertex normals after applying clearance; renderer integration NOT_TESTED"},
        "coverage_regions":regions,"visibility_policy":"keep uncovered regions; mask a region only after its armor is seated and fully occludes it",
        "reversal":"clearance=0 and restore all original index regions; never mutate original buffers in place",
        "status":"DATA_VERIFIED; staged occlusion and renderer integration REVIEW_REQUIRED"})


def collision_pairs():
    pairs=[]
    for side in ("L","R"):
        for h in ("HELMET_FACE_FRAME","HELMET_CROWN","HELMET_REAR"):
            pairs.append((h,"PAULDRON_"+side))
        pairs.extend([("UPPERARM_"+side,"FOREARM_"+side),("FOREARM_"+side,"CHEST_FRONT"),
                      ("UPPERARM_"+side,"CHEST_FRONT"),("WING_MAIN_"+side,"PAULDRON_"+side),
                      ("WING_TIP_"+side,"PAULDRON_"+side),("WING_MAIN_"+side,"BACKPACK_CORE"),
                      ("WING_TIP_"+side,"BACKPACK_CORE")])
        for j in range(1,5):pairs.append(("FOREARM_"+side,f"ABDOMEN_SEGMENT_{j}"))
    pairs.append(("THIGH_L","THIGH_R"))
    return [("ARMOR_"+a,"ARMOR_"+b) for a,b in pairs]


def core_preview(progress):
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Diagnostic_WhiteCore"):
            bpy.data.objects.remove(obj,do_unlink=True)
    fit=json.loads((DATA/"armor_white_fit.json").read_text())
    blob=(DATA/fit["binary"]).read_bytes()
    original=GLBSkin(ASSETS/"runtime/bagusmax_white_anatomy_v4_1.glb")
    clear=fit["clearance"]
    ids=np.frombuffer(blob,dtype="<u4",count=clear["count"],offset=clear["indices_offset"])
    delta=np.frombuffer(blob,dtype="<f4",count=clear["count"]*3,offset=clear["position_delta_offset"]).reshape(-1,3)
    t=3.4*progress
    for prim in original.evaluate({}):
        name=prim["name"]
        if name in FACE:continue
        p=prim["position"].copy()
        indices=prim["indices"]
        if name=="White_SoftSkin":
            w=np.clip(t/.20,0,1)
            p[ids]+=delta*w*w*(3-2*w)
            chunks=[]
            for region in fit["coverage_regions"]:
                label=region["region"]
                seated=.95 if label=="pelvis" else 1.75 if label in ("chest","abdomen") else 2.35
                if t>=seated:continue
                chunks.append(np.frombuffer(blob,dtype="<u4",count=region["index_count"],offset=region["index_buffer_offset"]).reshape(-1,3))
            if not chunks:continue
            indices=np.concatenate(chunks)
        elif name.startswith("White_Leg_"):
            if t>=.95:continue
        elif t>=1.75:continue
        mat=bpy.data.materials[original.doc["materials"][prim["material"]]["name"]]
        obj=mesh_object("Diagnostic_WhiteCore",p@B,indices,mat)
        # White's source shader reads panel tint attributes; preserve the actual GLB COLOR_0.
        colors=prim["colors"]
        if colors is not None:
            if colors.shape[1]==3:colors=np.column_stack((colors,np.ones(len(colors))))
            names={"Color"}
            for node in mat.node_tree.nodes:
                if node.type=="VERTEX_COLOR":names.add(node.layer_name)
                if node.type=="ATTRIBUTE":names.add(node.attribute_name)
            for name in names:
                if not name:continue
                attr=obj.data.color_attributes.new(name=name,type="FLOAT_COLOR",domain="POINT")
                attr.data.foreach_set("color",colors.ravel())


def clear_core_preview():
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Diagnostic_WhiteCore"):
            bpy.data.objects.remove(obj,do_unlink=True)


def render_assembly_preview():
    for p in (0,.2,.4,.7,1):
        assembly(p)
        core_preview(p)
        render(f"assembly_{int(p*100):03}","three_quarter",3.15)
    clear_core_preview()
    pose()
    for row in PARTS.values():row["object"].hide_render=True
    core_preview(0)
    render("white_before","three_quarter")
    clear_core_preview()
    for row in PARTS.values():row["object"].hide_render=False
    pose()


def collision_sample():
    pairs=collision_pairs()
    names=set(n for p in pairs for n in p)
    trees={}
    for name in names:
        obj=PARTS[name]["object"]
        vertices=[obj.matrix_world@v.co for v in obj.data.vertices]
        trees[name]=BVHTree.FromPolygons(vertices,[list(p.vertices) for p in obj.data.polygons],epsilon=.00001)
    hits=[]
    for a,b in pairs:
        count=len(trees[a].overlap(trees[b]))
        if count:hits.append({"a":a,"b":b,"intersecting_surface_triangle_pairs":count})
    return hits


def load_existing(source,manifest_path):
    global RIG,ELBOW_REPAIR
    PARTS.clear();ROOTS.clear();REST.clear();REST_WORLD.clear()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    RIG=bpy.data.objects["Bagusmax_Rig"]
    ELBOW_REPAIR=RIG.get("armor_revision")=="1.1" or Path(source).stem.endswith("_v1_1")
    manifest=json.loads(manifest_path.read_text())
    for row in manifest["assembly_nodes"]:
        name=row["node"]
        obj=bpy.data.objects[name]
        ROOTS[name]={"object":obj,"bone":row["anchor_joint"],"phase":row["phase"],
                     "offset":Vector(B.T@np.asarray(row["approach_offset_world_gltf"]))}
        rotation=(0,0,0)
        if name.startswith("ASM_WING_ROOT_"):
            rotation=(0,(1 if name.endswith("L") else -1)*math.radians(89),0)
        elif name.startswith("ASM_WING_TIP_"):
            rotation=(0,(-1 if name.endswith("L") else 1)*math.radians(154),0)
        elif name.startswith("CTRL_"):
            side=name.split("_")[-2]
            rotation=(0,(1 if side=="L" else -1)*math.radians(6.5 if "THUMB" in name else 10),0)
        obj.matrix_basis=obj.matrix_basis@Euler(rotation).to_matrix().to_4x4().inverted()
    for row in manifest["parts"]:
        PARTS[row["part_id"]]={"object":bpy.data.objects[row["part_id"]],"refs":row["source_reference"],
                               "role":row["mechanical_role"],"assembly":row["assembly_node"]}
    capture_rest()


def verify_existing(no_renders=False):
    load_existing(SOURCE,DATA/"armor_assembly_manifest.json")
    manifests()
    fitting_data()
    if "--preview-assembly" in sys.argv:
        render_assembly_preview()
        assert protected()==json.loads((REPORT/"preservation_before.json").read_text())
        print("ARMORED_ASSEMBLY_PREVIEW_COMPLETE",flush=True)
        return
    tests=inspection()
    results=[]
    for name,changes,wing,gesture in tests:
        pose(changes,wing,gesture)
        hits=collision_sample()
        results.append({"pose":name,"status":"LIMIT" if hits else "PASS","surface_intersections":hits,
                        "scope":"selected critical armor pairs; excludes intended mating, fasteners, and hidden White core"})
    write_json(REPORT/"collision_samples.json",results)
    # Sweep intermediate rotations in both directions; absolute evaluation must be reversible.
    continuity=[]
    for side,s in (("L",1),("R",-1)):
        previous=None;max_step=0
        for a in list(range(0,146,5))+list(range(145,-1,-5)):
            pose({"UpperArm_"+side:(0,-s*math.radians(a),0)})
            p=np.asarray(ROOTS["ASM_PAULDRON_"+side]["object"].matrix_world.translation)
            if previous is not None:max_step=max(max_step,float(np.linalg.norm(p-previous)))
            previous=p
        continuity.append({"side":side,"sample_step_degrees":5,"max_pivot_step_m":max_step,"tested_range":[0,145]})
    pose();before=source_snapshot()
    states=[]
    for p in (0,.2,.4,.7,1,.7,.4,.2,0,1):
        assembly(p)
        states.append((p,{n:np.asarray(r["object"].matrix_world).tolist() for n,r in ROOTS.items()}))
    deterministic=all(np.allclose(list(a[1].values()),list(b[1].values()),atol=1e-7)
                      for i,a in enumerate(states) for b in states[i+1:] if a[0]==b[0])
    pose();after=source_snapshot()
    write_json(REPORT/"assembly_determinism.json",{"status":"PASS" if deterministic and before==after else "FAIL",
        "repeated_progress_sequence":[s[0] for s in states],"neutral_return_exact":before==after,"shoulder_continuity":continuity,
        "coverage_occlusion":"NOT_TESTED in runtime; exploded previews do not prove collision-free full assembly"})
    if not no_renders:
        pose()
        for view in ("front","back","left","right","three_quarter"):
            render("armored_"+view,view)
        render_assembly_preview()
        for side,s in (("L",1),("R",-1)):
            for a in (0,30,60,90,120,145):
                pose({"UpperArm_"+side:(0,-s*math.radians(a),0)})
                render(f"shoulder_{side}_{a}_closeup",(s*3,-5,1.6),1.1,(s*.40,0,1.33))
            for a in (0,45,90,110,130):
                pose({"Forearm_"+side:(-math.radians(a),0,0)})
                render(f"elbow_{side}_{a}_closeup",(s*4,-4,1.4),.85,(s*.49,-.08,1.03))
        pose({"UpperArm_L":(0,-math.pi/2,0),"Forearm_L":(-math.pi/2,0,0)})
        render("blender_export_pose","three_quarter",2.5)
        from review_armored import evaluate
        asset=GLBSkin(GLB)
        test={"joint_deltas_blender_xyz":{"UpperArm_L":(0,-math.pi/2,0),"Forearm_L":(-math.pi/2,0,0)},"wing_progress":0,"gesture":"relaxed"}
        matrices=evaluate(asset,test)
        originals=[p["object"] for p in PARTS.values()]+[bpy.data.objects[n] for n in FACE]
        for o in originals:o.hide_render=True
        created=[]
        skinned=asset.evaluate(test["joint_deltas_blender_xyz"])
        for i,node in enumerate(asset.nodes):
            if "mesh" not in node:continue
            for p in asset.doc["meshes"][node["mesh"]]["primitives"]:
                if "skin" in node:
                    pp=next(x for x in skinned if x["node"]==i)
                    coords=pp["position"]@B
                else:
                    coords=(asset.accessor(p["attributes"]["POSITION"])@matrices[i,:3,:3].T+matrices[i,:3,3])@B
                ids=asset.accessor(p["indices"]).astype(int).reshape(-1,3)
                mat=bpy.data.materials[asset.doc["materials"][p["material"]]["name"]]
                created.append(mesh_object("Diagnostic_GLBSurface",coords,ids,mat))
        render("independent_glb_export_pose","three_quarter",2.5)
        for o in created:bpy.data.objects.remove(o,do_unlink=True)
        for o in originals:o.hide_render=False
    pose()
    prior=set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(GLB))
    imported=set(bpy.data.objects)-prior
    probe=source_snapshot()
    differences=[]
    for obj in imported:
        if obj.type!="MESH" or obj.get("part_id") not in probe:continue
        tree=KDTree(len(obj.data.vertices))
        for i,v in enumerate(obj.data.vertices):tree.insert(B4@obj.matrix_world@v.co,i)
        tree.balance()
        e=max(tree.find(Vector(p))[2] for p in probe[obj["part_id"]]["probes"])
        differences.append({"part":obj["part_id"],"max_probe_distance_mm":e*1000})
    write_json(REPORT/"neutral_reimport.json",{"status":"PASS" if len(differences)==len(PARTS) and max(r["max_probe_distance_mm"] for r in differences)<.1 else "FAIL","parts":differences})
    if not no_renders:
        originals=[p["object"] for p in PARTS.values()]+[bpy.data.objects[n] for n in FACE]
        for o in originals:o.hide_render=True
        render("neutral_glb_reimport","three_quarter")
        for o in originals:o.hide_render=False
    for o in imported:bpy.data.objects.remove(o,do_unlink=True)
    pose()
    saved={"animation_clips":len(bpy.data.actions),"neutral":"relaxed palms inward, seated armor, folded wings",
           "source_morph_clearance_default":bpy.data.objects["White_SoftSkin"].data.shape_keys.key_blocks["ArmorClearance"].value,
           "studio_unchanged":studio_signature()==json.loads((REPORT/"baseline_inventory.json").read_text())["studio"]}
    write_json(REPORT/"saved_source_state.json",saved)
    topology=[]
    for name,row in PARTS.items():
        obj=row["object"]
        bm=bmesh.new();bm.from_mesh(obj.data)
        topology.append({"part":name,"vertices":len(bm.verts),"faces":len(bm.faces),
            "nonmanifold_edges":sum(not e.is_manifold for e in bm.edges),"signed_volume_m3":bm.calc_volume(signed=True),
            "world_determinant":obj.matrix_world.determinant(),"scale":list(obj.scale)})
        bm.free()
    write_json(REPORT/"source_geometry_audit.json",topology)
    assert protected()==json.loads((REPORT/"preservation_before.json").read_text())
    print("ARMORED_ADDITIONAL_VERIFICATION_COMPLETE",flush=True)


def revision_paths():
    global REVISION,REPORT,DATA,SOURCE,GLB
    REVISION=True
    REPORT=ROOT/"reports/bagusmax_3d/armored_v1_1"
    DATA=ASSETS/"armor/v1_1"
    SOURCE=ASSETS/"source/bagusmax_armored_v1_1.blend"
    GLB=ASSETS/"runtime/bagusmax_armored_v1_1.glb"
    REPORT.mkdir(parents=True,exist_ok=True)
    DATA.mkdir(parents=True,exist_ok=True)


def articulation_tests():
    tests=[("neutral",{},0,"relaxed")]
    for side,s in (("L",1),("R",-1)):
        for a in (0,30,60,90,100,110,120,130):
            tests.append((f"elbow_{side}_{a}",{f"Forearm_{side}":(-math.radians(a),0,0)},0,"relaxed"))
        for a in (0,45,90,120,145):
            tests.append((f"shoulder_{side}_{a}",{f"UpperArm_{side}":(0,-s*math.radians(a),0)},0,"relaxed"))
        for e,b in ((45,90),(90,110),(90,130),(120,110),(145,90)):
            tests.append((f"combined_{side}_S{e}_E{b}",{f"UpperArm_{side}":(0,-s*math.radians(e),0),f"Forearm_{side}":(-math.radians(b),0,0)},0,"relaxed"))
        tests.extend([(f"forward_{side}",{f"UpperArm_{side}":(-.60,0,0),f"Forearm_{side}":(-math.pi/2,0,0)},0,"relaxed"),
            (f"inward_{side}",{f"UpperArm_{side}":(-.5,0,-s*.32),f"Forearm_{side}":(-1.75,0,0)},0,"relaxed"),
            (f"near_chest_{side}",{f"UpperArm_{side}":(-.35,-s*.28,-s*.35),f"Forearm_{side}":(-1.92,0,0)},0,"relaxed")])
    tests.extend([("wings_partial",{},.5,"relaxed"),("wings_open",{},1,"relaxed")])
    return tests


def arm_pairs(side):
    suffix="_"+side
    pieces=["UPPERARM","SHOULDER_RECESS","ELBOW_SOCKET","ELBOW_METAL","ELBOW_HUB","FOREARM","FOREARM_CUFF","FOREARM_INLAY","WRIST","PALM","PAULDRON"]
    pieces += ["ELBOW_GUARD","ELBOW_GUARD_INLAY"]
    names=["ARMOR_"+n+suffix for n in pieces if "ARMOR_"+n+suffix in PARTS]
    pairs=[(a,b) for i,a in enumerate(names) for b in names[i+1:]]
    for n in names:
        for body in ("CHEST_FRONT","CHEST_COLLAR",f"CHEST_FLANK_{side}","HELMET_FACE_FRAME","HELMET_REAR"):
            pairs.append((n,"ARMOR_"+body))
    return pairs


def intersection_point(va,fa,vb,fb):
    for ia in range(1,len(fa)-1):
        a=[va[fa[i]] for i in (0,ia,ia+1)]
        for ib in range(1,len(fb)-1):
            b=[vb[fb[i]] for i in (0,ib,ib+1)]
            points=[]
            for one,two in ((a,b),(b,a)):
                n=(two[1]-two[0]).cross(two[2]-two[0])
                for k in range(3):
                    p,q=one[k],one[(k+1)%3]
                    d=n.dot(q-p)
                    if abs(d)<1e-12:continue
                    t=n.dot(two[0]-p)/d
                    if -.00001<=t<=1.00001:
                        x=p+t*(q-p)
                        if (closest_point_on_tri(x,*two)-x).length<.00002:points.append(x)
            if len(points)>=2:return sum(points,Vector())/len(points)
    return None


def fixed_mating(a,b):
    # Only explicitly manufactured, co-moving inset/fastener pairs are exempt.
    for side in ("L","R"):
        for one,two in (("ELBOW_SOCKET","ELBOW_METAL"),("ELBOW_METAL","ELBOW_HUB"),
            ("FOREARM","FOREARM_CUFF"),("FOREARM","FOREARM_INLAY"),("WRIST","PALM"),
            ("ELBOW_GUARD","ELBOW_GUARD_INLAY")):
            if {a,b}=={"ARMOR_"+one+"_"+side,"ARMOR_"+two+"_"+side}:return True
    return False


def pair_contacts(pairs,details=False,classify=False):
    trees={};verts={};polys={};bounds={}
    for name in set(n for p in pairs for n in p):
        obj=PARTS[name]["object"]
        vv=[obj.matrix_world@v.co for v in obj.data.vertices]
        ff=[list(p.vertices) for p in obj.data.polygons]
        a=np.asarray(vv)
        bounds[name]=(a.min(axis=0),a.max(axis=0))
        trees[name]=BVHTree.FromPolygons(vv,ff)
        verts[name],polys[name]=vv,ff
    scene_tree=None
    if classify:
        allv=[];allf=[]
        for obj in [p["object"] for p in PARTS.values()]+[bpy.data.objects[n] for n in FACE]:
            offset=len(allv)
            allv.extend(obj.matrix_world@v.co for v in obj.data.vertices)
            allf.extend([offset+i for i in p.vertices] for p in obj.data.polygons)
        scene_tree=BVHTree.FromPolygons(allv,allf)
    hits=[]
    for a,b in pairs:
        if np.any(bounds[a][0]>bounds[b][1]) or np.any(bounds[b][0]>bounds[a][1]):continue
        overlap=trees[a].overlap(trees[b])
        if not overlap:continue
        row={"a":a,"b":b,"polygon_pairs":len(overlap)}
        if details:
            for key,name,column in (("a",a,0),("b",b,1)):
                points=np.asarray([verts[name][v] for f in {p[column] for p in overlap} for v in polys[name][f]])
                row[key+"_contact_bounds_blender"]=[points.min(axis=0).tolist(),points.max(axis=0).tolist()]
        if classify:
            if fixed_mating(a,b):row["classification"]="FIXED_MATING"
            else:
                samples=[]
                for k in np.linspace(0,len(overlap)-1,min(12,len(overlap)),dtype=int):
                    ia,ib=overlap[int(k)]
                    p=intersection_point(verts[a],polys[a][ia],verts[b],polys[b][ib])
                    if p is not None:samples.append(p)
                exposed=0
                for p in samples:
                    for j in range(32):
                        z=1-2*(j+.5)/32;r=math.sqrt(max(0,1-z*z));t=j*2.3999632297
                        direction=Vector((r*math.cos(t),r*math.sin(t),z))
                        hit,normal,index,distance=scene_tree.ray_cast(p+3*direction,-direction,3.01)
                        if hit is not None and (hit-p).length<.0007:
                            exposed+=1;break
                row.update(classification="EXPOSED_INTERSECTION" if exposed else "HIDDEN_INTERNAL" if samples else "UNRESOLVED_CONTACT",
                    contact_samples=len(samples),exposed_samples=exposed,view_rays_per_sample=32)
        hits.append(row)
    return hits


def cut_swept_elbow():
    pose()
    changes=[];originals={}
    for side in ("L","R"):
        upper=PARTS["ARMOR_UPPERARM_"+side]["object"]
        fore=ROOTS["ASM_FOREARM_"+side]["object"]
        rest=fore.matrix_world.copy()
        source=[v.co.copy() for v in upper.data.vertices]
        points=[]
        for a in range(0,131,5):
            for elevation in (0,145):
                s=1 if side=="L" else -1
                pose({"Forearm_"+side:(-math.radians(a),0,0),"UpperArm_"+side:(0,-s*math.radians(elevation),0)})
                to_rest=rest@fore.matrix_world.inverted()
                points.extend(to_rest@upper.matrix_world@p for p in source)
        pose()
        bm=bmesh.new()
        for p in points:bm.verts.new(p)
        hull=bmesh.ops.convex_hull(bm,input=list(bm.verts),use_existing_faces=False)
        discard=set(hull["geom_interior"]+hull["geom_unused"])
        bmesh.ops.delete(bm,geom=list(discard),context="VERTS")
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.normal_update()
        for v in bm.verts:v.co+=.004*v.normal
        data=bpy.data.meshes.new("Elbow_Swept_Clearance")
        bm.to_mesh(data);bm.free()
        cutter=bpy.data.objects.new("Diagnostic_ClearanceCutter",data)
        bpy.context.collection.objects.link(cutter)
        guard_data=data.copy()
        bm=bmesh.new();bm.from_mesh(guard_data);bm.normal_update()
        for v in bm.verts:v.co-=.001*v.normal
        bm.to_mesh(guard_data);bm.free()
        guard_cutter=bpy.data.objects.new("Diagnostic_GuardCutter",guard_data)
        bpy.context.collection.objects.link(guard_cutter)
        for name in ("ARMOR_FOREARM_"+side,"ARMOR_FOREARM_INLAY_"+side):
            obj=PARTS[name]["object"]
            originals[name]=[obj.matrix_world@v.co for v in obj.data.vertices]
            before=len(obj.data.vertices)
            guard_mesh=obj.data.copy()
            guard_mesh.transform(obj.matrix_world)
            guard_name="ELBOW_GUARD_INLAY_"+side if "INLAY" in name else "ELBOW_GUARD_"+side
            guard=bpy.data.objects.new(guard_name,guard_mesh)
            bpy.context.collection.objects.link(guard)
            activate(guard)
            keep=guard.modifiers.new("OriginalShellGuardSegment","BOOLEAN")
            keep.operation="INTERSECT";keep.solver="EXACT";keep.object=guard_cutter
            bpy.ops.object.modifier_apply(modifier=keep.name)
            if guard.data.vertices:
                soften(guard,.0015,2)
                part(guard,ROOTS["ASM_ELBOW_"+side]["object"],["R02","R09"],
                     "guard_inlay" if "INLAY" in name else "articulated_elbow_guard")
            else:bpy.data.objects.remove(guard,do_unlink=True)
            activate(obj)
            mod=obj.modifiers.new("ElbowSweptRelief","BOOLEAN")
            mod.operation="DIFFERENCE";mod.solver="EXACT";mod.object=cutter
            bpy.ops.object.modifier_apply(modifier=mod.name)
            soften(obj,.0015,2)
            if "quality_mesh_datablock" in obj:del obj["quality_mesh_datablock"]
            changes.append({"part":name,"vertices_before":before,"vertices_after":len(obj.data.vertices),
                "method":"subtract 0..130 deg upper-arm convex swept volume plus 4mm clearance; 1.5mm rim bevel"})
        bpy.data.objects.remove(cutter,do_unlink=True)
        bpy.data.objects.remove(guard_cutter,do_unlink=True)
    pose()
    write_json(REPORT/"local_geometry_changes.json",changes)
    return originals


def trim_guard_edges():
    records=[]
    for side in ("L","R"):
        red=PARTS["ARMOR_ELBOW_GUARD_"+side]["object"]
        accent=PARTS.get("ARMOR_ELBOW_GUARD_INLAY_"+side,{}).get("object")
        pose()
        rest=ROOTS["ASM_ELBOW_"+side]["object"].matrix_world.copy()
        for angle in range(0,131,5):
            for piece in ("FOREARM","FOREARM_CUFF","WRIST","PALM","UPPERARM"):
                pose({"Forearm_"+side:(-math.radians(angle),0,0)})
                name="ARMOR_"+piece+"_"+side
                hits=pair_contacts([(red.name,name)])
                if not hits:continue
                obj=PARTS[name]["object"]
                transform=rest@ROOTS["ASM_ELBOW_"+side]["object"].matrix_world.inverted()@obj.matrix_world
                data=obj.data.copy();data.transform(transform)
                bm=bmesh.new();bm.from_mesh(data)
                bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.normal_update()
                bm.to_mesh(data);bm.free()
                cutter=bpy.data.objects.new("Diagnostic_GuardEdgeClearance",data)
                bpy.context.collection.objects.link(cutter)
                pose()
                for guard in (red,accent):
                    if guard is None:continue
                    backup=guard.data.copy()
                    activate(guard)
                    mod=guard.modifiers.new("MovingPlateEdgeClearance","BOOLEAN")
                    mod.operation="DIFFERENCE";mod.solver="MANIFOLD";mod.object=cutter
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                    if len(guard.data.vertices)<12 or len(guard.data.vertices)>12000:
                        guard.data=backup
                        records.append({"side":side,"elbow_deg":angle,"counterpart":name,"rejected":"empty or excessive topology; original segment retained"})
                    else:bpy.data.meshes.remove(backup)
                bpy.data.objects.remove(cutter,do_unlink=True)
                records.append({"side":side,"elbow_deg":angle,"counterpart":name,"operation":"trim actual occupied rigid shell, not convex volume"})
                print("GUARD_EDGE",side,angle,piece,len(red.data.vertices),flush=True)
        pose()
        for guard in (red,accent):
            if guard is None:continue
            bm=bmesh.new();bm.from_mesh(guard.data)
            bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.normal_update()
            for v in bm.verts:v.co-=.0005*v.normal
            bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=.000001)
            bm.to_mesh(guard.data);bm.free()
    write_json(REPORT/"guard_edge_clearance.json",records)


def finish_clearance_surfaces(originals):
    pose()
    records=[]
    for name,points in originals.items():
        names=[name]
        guard=name.replace("FOREARM","ELBOW_GUARD")
        if guard in PARTS:names.append(guard)
        for target in names:
            obj=PARTS[target]["object"]
            inv=obj.matrix_world.inverted()
            tree=KDTree(len(points))
            for i,p in enumerate(points):tree.insert(inv@p,i)
            tree.balance()
            bm=bmesh.new();bm.from_mesh(obj.data)
            rim=[v for v in bm.verts if tree.find(v.co)[2]>.00002]
            for _ in range(10):
                bmesh.ops.smooth_vert(bm,verts=rim,factor=.65,use_axis_x=True,use_axis_y=True,use_axis_z=True)
            bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.000003)
            bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=.000003)
            bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
            if "ELBOW_GUARD" in target:
                bm.normal_update()
                for v in bm.verts:v.co-=.0007*v.normal
            bm.to_mesh(obj.data);bm.free()
            records.append({"part":target,"smoothed_cut_vertices":len(rim),"iterations":10,"factor":.65,
                "guard_post_finish_allowance_m":.0007 if "ELBOW_GUARD" in target else 0,
                "scope":"smooth new Boolean rim vertices only; guard solid eroded 0.7mm after smoothing for intermediate-angle clearance"})
    write_json(REPORT/"clearance_edge_finish.json",records)


def refine_elbow(audit_only,no_renders):
    global ELBOW_REPAIR
    revision_paths()
    if SOURCE.exists() and not audit_only:raise FileExistsError("Existing V1.1 source is protected from overwrite")
    preservation=REPORT/"preservation_before.json"
    if preservation.exists():assert json.loads(preservation.read_text())==protected()
    else:write_json(preservation,protected())
    load_existing(ASSETS/"source/bagusmax_armored_v1.blend",ASSETS/"armor/armor_assembly_manifest.json")
    studio=studio_signature()
    inventory={"blender":bpy.app.version_string,"studio":studio,"joints":[{"name":b.name,"parent":b.parent.name if b.parent else None,
        "matrix":[list(r) for r in b.matrix_local],"head":list(b.head_local),"tail":list(b.tail_local)} for b in RIG.data.bones]}
    write_json(REPORT/"baseline_inventory.json",inventory)
    if not (REPORT/"v1_contact_diagnosis.json").exists():
        rows=[]
        for name,changes,wing,gesture in articulation_tests():
            pose(changes,wing,gesture)
            hits=pair_contacts(arm_pairs("L")+arm_pairs("R"),details=True)
            rows.append({"name":name,"joint_deltas_blender_xyz":changes,"wing_progress":wing,"gesture":gesture,"contacts":hits})
        write_json(REPORT/"v1_contact_diagnosis.json",rows)
    pose()
    if audit_only:
        print("ARMORED_ELBOW_AUDIT_COMPLETE",flush=True)
        return
    ELBOW_REPAIR=True
    originals=cut_swept_elbow()
    RIG["armor_revision"]="1.1"
    for s,side in ((1,"L"),(-1,"R")):
        node=ROOTS["ASM_ELBOW_"+side]["object"]
        bind(node,RIG,"ElbowVolume_"+side)
        ROOTS[node.name]["bone"]="ElbowVolume_"+side
        node["anchor_joint"]="ElbowVolume_"+side
        REST[node.name]=node.matrix_basis.copy()
        REST_WORLD[node.name]=node.matrix_world.copy()
        obj=PARTS["ARMOR_ELBOW_SOCKET_"+side]["object"]
        inv=obj.matrix_world.inverted()
        for v in obj.data.vertices:
            p=obj.matrix_world@v.co
            t=max(0,min(1,(s*p.x-.3945)/.1895))
            bulge=1+.14*math.sin(math.pi*t)
            p.y=-.02+(p.y+.02)*(1+.035*math.sin(math.pi*t))
            p.z=.90+(p.z-.90)*bulge
            v.co=inv@p
        obj.data.update()
        if "quality_mesh_datablock" in obj:del obj["quality_mesh_datablock"]
        liner=PARTS["ARMOR_SHOULDER_RECESS_"+side]["object"]
        inv=liner.matrix_world.inverted()
        for v in liner.data.vertices:
            p=liner.matrix_world@v.co
            p.x=s*.525+(p.x-s*.475)*.82;p.y*=.82
            v.co=inv@p
        bind(liner,ROOTS["ASM_PAULDRON_"+side]["object"])
        PARTS[liner.name]["assembly"]="ASM_PAULDRON_"+side
        PARTS[liner.name]["role"]="pauldron_mount_liner"
        liner["mechanical_role"]="pauldron_mount_liner"
        if "quality_mesh_datablock" in liner:del liner["quality_mesh_datablock"]
    trim_guard_edges()
    finish_clearance_surfaces(originals)
    rows=[]
    for name,changes,wing,gesture in articulation_tests():
        pose(changes,wing,gesture)
        hits=pair_contacts(arm_pairs("L")+arm_pairs("R"),details=True)
        rows.append({"name":name,"joint_deltas_blender_xyz":changes,"wing_progress":wing,"gesture":gesture,
            "contacts":hits,"nodes":source_snapshot()})
        if not no_renders and (name.startswith("elbow_") or name.startswith("combined_")):
            side="L" if "_L_" in name else "R"
            s=1 if side=="L" else -1
            render("v1_1_"+name,(s*4,-4,1.4),1.15,(s*.49,-.08,1.08))
    write_json(REPORT/"v1_1_contact_diagnosis.json",[{k:v for k,v in r.items() if k!="nodes"} for r in rows])
    write_json(REPORT/"blender_pose_matrices.json",[{k:v for k,v in r.items() if k!="contacts"} for r in rows])
    pose()
    if not no_renders:
        for view in ("front","left","right","back","three_quarter"):
            render("neutral_"+view,view)
    assert studio_signature()==studio
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE))
    export_asset(GLB)
    manifests()
    write_json(REPORT/"preservation_after.json",protected())
    assert protected()==json.loads(preservation.read_text())
    print("ARMORED_ELBOW_REFINEMENT_COMPLETE",flush=True)


def review_pose_image(prefix,name):
    if name.startswith("elbow_"):
        s=1 if "_L_" in name else -1
        render(prefix+name,(s*4,-4,1.4),1.15,(s*.49,-.08,1.08))
    elif name.startswith("shoulder_"):
        s=1 if "_L_" in name else -1
        render(prefix+name,(s*3,-5,1.6),1.65,(s*.43,0,1.25))
    elif name.startswith("wings_"):
        render(prefix+name,"rear_quarter",3.35)
    else:
        render(prefix+name,"three_quarter",2.6)


def revision_export_evidence(tests):
    import review_armored as review
    review.REPORT=REPORT
    asset=GLBSkin(GLB)
    originals=[p["object"] for p in PARTS.values()]+[bpy.data.objects[n] for n in FACE]
    for test in tests:
        name=test["name"]
        pose(test["joint_deltas_blender_xyz"],test["wing_progress"],test["gesture"])
        review_pose_image("blender_",name)
        matrices=review.evaluate(asset,test)
        skinned=asset.evaluate(test["joint_deltas_blender_xyz"])
        for o in originals:o.hide_render=True
        created=[]
        for i,node,p in review.primitives(asset):
            if "skin" in node:
                coords=next(x for x in skinned if x["node"]==i)["position"]@B
            else:
                coords=(asset.accessor(p["attributes"]["POSITION"])@matrices[i,:3,:3].T+matrices[i,:3,3])@B
            ids=asset.accessor(p["indices"]).astype(int).reshape(-1,3)
            mat=bpy.data.materials[asset.doc["materials"][p["material"]]["name"]]
            created.append(mesh_object("Diagnostic_GLBSurface",coords,ids,mat))
        review_pose_image("glb_",name)
        for o in created:bpy.data.objects.remove(o,do_unlink=True)
        for o in originals:o.hide_render=False
    pose()
    prior=set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(GLB))
    imported=set(bpy.data.objects)-prior
    differences=[]
    for obj in imported:
        name=obj.get("part_id")
        if obj.type!="MESH" or name not in PARTS:continue
        source=PARTS[name]["object"]
        a=[source.matrix_world@v.co for v in source.data.vertices]
        b=[obj.matrix_world@v.co for v in obj.data.vertices]
        def distance(one,two):
            tree=KDTree(len(two))
            for k,p in enumerate(two):tree.insert(p,k)
            tree.balance()
            return max(tree.find(p)[2] for p in one)
        error=max(distance(a,b),distance(b,a))*1000
        differences.append({"part":name,"max_all_vertex_bidirectional_mm":error})
    write_json(REPORT/"neutral_reimport.json",{"status":"PASS" if len(differences)==len(PARTS) and max(r["max_all_vertex_bidirectional_mm"] for r in differences)<.1 else "FAIL",
        "scope":"all rigid armor vertices, bidirectional nearest vertex; not a surface Hausdorff bound","parts":differences})
    for o in originals:o.hide_render=True
    render("neutral_glb_reimport","three_quarter")
    for o in originals:o.hide_render=False
    for o in imported:bpy.data.objects.remove(o,do_unlink=True)
    pose()


def verify_revision(no_renders):
    revision_paths()
    protected_before=json.loads((REPORT/"preservation_before.json").read_text())
    assert protected()==protected_before
    tests=articulation_tests()
    for version,source,data in (("v1_",ASSETS/"source/bagusmax_armored_v1.blend",ASSETS/"armor"),("v1_1_",SOURCE,DATA)):
        if version=="v1_" and (REPORT/"v1_classified_contacts.json").exists() and all((REPORT/(version+t[0]+".png")).exists() for t in tests):
            continue
        load_existing(source,data/"armor_assembly_manifest.json")
        rows=[]
        for name,changes,wing,gesture in tests:
            pose(changes,wing,gesture)
            pairs=list(dict.fromkeys(arm_pairs("L")+arm_pairs("R")+collision_pairs()))
            hits=pair_contacts(pairs,details=True,classify=True)
            rows.append({"name":name,"joint_deltas_blender_xyz":changes,"wing_progress":wing,"gesture":gesture,
                "contacts":hits,"nodes":source_snapshot()})
            if not no_renders:review_pose_image(version,name)
            print("VERIFIED",version,name,len(hits),flush=True)
        write_json(REPORT/(version+"classified_contacts.json"),[{k:v for k,v in r.items() if k!="nodes"} for r in rows])
        pose()
        if not no_renders:
            for view in ("front","left","right","back","three_quarter"):
                render(version+"neutral_"+view,view)
            render(version+"wings_folded","rear_quarter")
        if version=="v1_1_":
            write_json(REPORT/"blender_pose_matrices.json",[{k:v for k,v in r.items() if k!="contacts"} for r in rows])
    sweep=[]
    for side,s in (("L",1),("R",-1)):
        for joint,end in (("Forearm",130),("UpperArm",145)):
            samples=[];states={};return_error=0
            for angle in list(range(0,end+1,5))+list(range(end,-1,-5)):
                delta=(-math.radians(angle),0,0) if joint=="Forearm" else (0,-s*math.radians(angle),0)
                pose({joint+"_"+side:delta})
                matrix=np.asarray([r["object"].matrix_world for r in ROOTS.values()])
                if angle in states:return_error=max(return_error,float(np.max(abs(matrix-states[angle]))))
                else:
                    states[angle]=matrix
                    hits=pair_contacts(arm_pairs(side)+collision_pairs())
                    samples.append({"degrees":angle,"contacts":hits})
            sweep.append({"side":side,"joint":joint,"step_degrees":5,"max_return_matrix_error":return_error,"samples":samples})
    write_json(REPORT/"intermediate_angle_sweep.json",sweep)
    pose();neutral=source_snapshot()
    if not no_renders:
        for p in (0,.4,1):
            assembly(p)
            render(f"modular_exploded_{int(p*100):03}","three_quarter",3.15)
        pose()
        chosen=[r for r in rows if r["name"] in ("elbow_L_130","elbow_R_130","shoulder_L_145","shoulder_R_145","combined_L_S90_E130","combined_R_S90_E130")]
        revision_export_evidence(chosen)
    topology=[]
    for name,row in PARTS.items():
        obj=row["object"]
        bm=bmesh.new();bm.from_mesh(obj.data)
        topology.append({"part":name,"vertices":len(bm.verts),"faces":len(bm.faces),
            "nonmanifold_edges":sum(not e.is_manifold for e in bm.edges),"signed_volume_m3":bm.calc_volume(signed=True),
            "world_determinant":obj.matrix_world.determinant(),"scale":list(obj.scale)})
        bm.free()
    write_json(REPORT/"source_geometry_audit.json",topology)
    pose()
    write_json(REPORT/"saved_source_state.json",{"animation_clips":len(bpy.data.actions),"neutral_return_exact":source_snapshot()==neutral,
        "studio_unchanged":studio_signature()==json.loads((REPORT/"baseline_inventory.json").read_text())["studio"],
        "neutral":"relaxed palms inward, seated armor, folded wings; source saved before disposable pose tests"})
    manifests()
    assert protected()==protected_before
    write_json(REPORT/"preservation_after.json",protected())
    print("ARMORED_REVISION_VERIFICATION_COMPLETE",flush=True)


def contact_evidence():
    revision_paths()
    before=json.loads((REPORT/"preservation_before.json").read_text())
    assert protected()==before
    records=[]
    for version,source,data in (("v1_",ASSETS/"source/bagusmax_armored_v1.blend",ASSETS/"armor"),("v1_1_",SOURCE,DATA)):
        if version=="v1_" and (REPORT/"contact_evidence.json").exists() and all((REPORT/f"v1_contact_{s}_{a}.png").exists() for s in ("L","R") for a in ("outside","inside")):
            records.extend(r for r in json.loads((REPORT/"contact_evidence.json").read_text()) if r["version"]=="v1_")
            continue
        load_existing(source,data/"armor_assembly_manifest.json")
        if version=="v1_1_":manifests()
        for side,s in (("L",1),("R",-1)):
            pose({"Forearm_"+side:(-math.radians(130),0,0)})
            visible={"ARMOR_"+p+"_"+side for p in ("UPPERARM","ELBOW_SOCKET","ELBOW_METAL","ELBOW_HUB","FOREARM","FOREARM_INLAY","ELBOW_GUARD")}
            for name,row in PARTS.items():row["object"].hide_render=name not in visible
            for name in FACE:bpy.data.objects[name].hide_render=True
            one=PARTS["ARMOR_UPPERARM_"+side]["object"]
            two=PARTS["ARMOR_FOREARM_"+side]["object"]
            av=[one.matrix_world@v.co for v in one.data.vertices];af=[list(p.vertices) for p in one.data.polygons]
            bv=[two.matrix_world@v.co for v in two.data.vertices];bf=[list(p.vertices) for p in two.data.polygons]
            overlaps=BVHTree.FromPolygons(av,af).overlap(BVHTree.FromPolygons(bv,bf))
            markers=[]
            for k in np.linspace(0,len(overlaps)-1,min(70,len(overlaps)),dtype=int):
                a,b=overlaps[int(k)]
                point=intersection_point(av,af[a],bv,bf[b])
                if point is None:continue
                bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,radius=.0025,location=point)
                marker=bpy.context.object
                marker.name="Diagnostic_BVHContact"
                marker.data.materials.append(bpy.data.materials.get("White_Vinyl") or bpy.data.materials[0])
                markers.append(marker)
            for label,view in (("outside",(s*4,-4,1.4)),("inside",(-s*4,4,1.4))):
                render(version+f"contact_{side}_{label}",view,1.08,(s*.52,-.04,1.12))
            records.append({"version":version,"side":side,"elbow_deg":130,"pair":[one.name,two.name],"bvh_polygon_pairs":len(overlaps),
                "markers":len(markers),"interpretation":"isolated engineering diagnostic; small markers locate actual surface intersections, not a beauty render"})
            for o in markers:bpy.data.objects.remove(o,do_unlink=True)
    write_json(REPORT/"contact_evidence.json",records)
    wings=[]
    for progress in (0,.5,1):
        pose(wing=progress)
        pairs=[]
        for side in ("L","R"):
            for wing in ("ARMOR_WING_MAIN_"+side,"ARMOR_WING_TIP_"+side):
                for body in ("ARMOR_PAULDRON_"+side,"ARMOR_BACKPACK_CORE","ARMOR_HELMET_FACE_FRAME","ARMOR_HELMET_CROWN","ARMOR_HELMET_REAR"):
                    pairs.append((wing,body))
        hits=pair_contacts(pairs,details=True,classify=True)
        wings.append({"progress":progress,"status":"FAIL" if any(h["classification"]=="EXPOSED_INTERSECTION" for h in hits) else "LIMIT" if hits else "PASS","contacts":hits,
            "scope":"main/tip wings against pauldrons, backpack and helmet at static folded/partial/open; no full continuous sweep"})
    write_json(REPORT/"wing_clearance.json",wings)
    assert protected()==before
    print("ARMORED_CONTACT_EVIDENCE_COMPLETE",flush=True)


def shoulder_protected():
    paths=list((ASSETS/"source").glob("*.blend"))+list((ASSETS/"runtime").glob("*.glb"))
    paths += [ROOT/"assets/models/bagusmax_armored.glb",ROOT/"assets/models/source/bagusmax_armored.blend",ROOT/"docs/bagusmax_3d/WHITE_LIGHTING_SPEC.md"]
    paths += list((ASSETS/"armor").glob("*.json"))+list((ASSETS/"armor/v1_1").glob("*.json"))
    paths += list((ROOT/"reports/bagusmax_3d/armored_v1_1").glob("*"))
    paths += list((ROOT/"docs/bagusmax_3d").glob("ARMORED_V1*.md"))
    return {str(p.relative_to(ROOT)).replace("\\","/"):{"sha256":sha(p),"bytes":p.stat().st_size}
            for p in sorted(set(paths)) if p.is_file() and "v1_2" not in p.name.lower()}


def shoulder_paths():
    global REPORT,DATA,SOURCE,GLB,REVISION,SHOULDER_REPAIR
    REVISION=True
    SHOULDER_REPAIR=True
    REPORT=ROOT/"reports/bagusmax_3d/armored_v1_2"
    DATA=ASSETS/"armor/v1_2"
    SOURCE=ASSETS/"source/bagusmax_armored_v1_2.blend"
    assert ROOT.resolve() in (Path("E:/Projects/OpenBagus").resolve(), Path("E:/Projects/OpenBagus-3D").resolve())
    branch=subprocess.run(["git","branch","--show-current"],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    assert branch in ("feat/bagusmax-3d-art", "integrate/openbagus-single-repository", "main"), branch
    REPORT.mkdir(exist_ok=True,parents=True)
    live=shoulder_protected()
    saved=REPORT/"preservation_before.json"
    if saved.exists():assert json.loads(saved.read_text())==live,"Protected baseline changed"
    else:write_json(saved,live)
    (REPORT/"git_status.txt").write_text(subprocess.run(["git","status","--short","--branch"],cwd=ROOT,capture_output=True,text=True,check=True).stdout)


def shoulder_pose_tests(side="L"):
    s=1 if side=="L" else -1
    tests=[]
    for e in (0,15,30,45,60,75,90,110,120,135,145):
        tests.append((f"side_{side}_S{e}_E0",{f"UpperArm_{side}":(0,-s*math.radians(e),0)},e,0,"side"))
    for e,b in ((45,90),(45,130),(75,110),(90,90),(90,110),(90,130),(110,120),(120,110),(120,130),(135,110),(145,90),(145,130)):
        tests.append((f"combined_{side}_S{e}_E{b}",{f"UpperArm_{side}":(0,-s*math.radians(e),0),f"Forearm_{side}":(-math.radians(b),0,0)},e,b,"side"))
    for e in (30,60,90,120,145):
        tests.append((f"forward_{side}_S{e}_E90",{f"UpperArm_{side}":(-math.radians(e),0,0),f"Forearm_{side}":(-math.pi/2,0,0)},e,90,"forward"))
    tests.append((f"near_chest_{side}",{f"UpperArm_{side}":(-.35,-s*.28,-s*.35),f"Forearm_{side}":(-1.92,0,0)},16.04,110,"mixed"))
    return tests


def shoulder_pairs(side):
    pairs=arm_pairs(side)
    moving=[n for n in PARTS if n.endswith("_"+side) and any(p in n for p in ("PAULDRON","SHOULDER","UPPERARM","ELBOW","FOREARM","WRIST","PALM"))]
    bodies=[n for n in PARTS if any(p in n for p in ("CHEST_","HELMET_","BACKPACK","WING_ROOT_HINGE"))]
    pairs.extend((a,b) for a in moving for b in bodies if a!=b)
    return list(dict.fromkeys(tuple(sorted(p)) for p in pairs))


def evaluated_contacts(pairs,details=False,classify=False):
    deps=bpy.context.evaluated_depsgraph_get()
    originals={}
    meshes=[]
    try:
        for name in set(n for p in pairs for n in p):
            obj=PARTS[name]["object"]
            if not obj.modifiers:continue
            data=bpy.data.meshes.new_from_object(obj.evaluated_get(deps))
            originals[name]=obj.data;obj.data=data;meshes.append(data)
        return pair_contacts(pairs,details=details,classify=classify)
    finally:
        for name,data in originals.items():PARTS[name]["object"].data=data
        for data in meshes:bpy.data.meshes.remove(data)


def rebase_control_pivot(name,pivot):
    obj=ROOTS[name]["object"]
    children={child:child.matrix_world.copy() for child in obj.children}
    mat=obj.matrix_world.copy();mat.translation=Vector(pivot)
    obj.matrix_world=mat
    bpy.context.view_layer.update()
    for child,world in children.items():child.matrix_world=world
    bpy.context.view_layer.update()
    REST[name]=obj.matrix_basis.copy();REST_WORLD[name]=obj.matrix_world.copy()


def cut_pauldron_chest(side):
    pose()
    points=[]
    for name in ("ARMOR_CHEST_FRONT","ARMOR_CHEST_COLLAR",f"ARMOR_CHEST_FLANK_{side}"):
        obj=PARTS[name]["object"]
        points.extend(obj.matrix_world@v.co for v in obj.data.vertices)
    bm=bmesh.new()
    for p in points:bm.verts.new(p)
    hull=bmesh.ops.convex_hull(bm,input=list(bm.verts),use_existing_faces=False)
    bmesh.ops.delete(bm,geom=list(set(hull["geom_interior"]+hull["geom_unused"])),context="VERTS")
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.normal_update()
    for v in bm.verts:v.co+=.004*v.normal
    data=bpy.data.meshes.new("Diagnostic_ChestEnvelope");bm.to_mesh(data);bm.free()
    cutter=bpy.data.objects.new("Diagnostic_ChestEnvelope",data);bpy.context.collection.objects.link(cutter)
    changes=[]
    for name in (f"ARMOR_PAULDRON_{side}",f"ARMOR_SHOULDER_RECESS_{side}"):
        obj=PARTS[name]["object"]
        before=len(obj.data.vertices)
        activate(obj)
        mod=obj.modifiers.new("InnerLipClearance","BOOLEAN");mod.operation="DIFFERENCE";mod.solver="MANIFOLD";mod.object=cutter
        bpy.ops.object.modifier_apply(modifier=mod.name)
        assert len(obj.data.vertices)>50,"Clearance removes the important part"
        soften(obj,.0015,2)
        changes.append({"part":name,"vertices_before":before,"vertices_after":len(obj.data.vertices)})
    bpy.data.objects.remove(cutter,do_unlink=True)
    return changes


def prototype_shoulder():
    shoulder_paths()
    load_existing(ASSETS/"source/bagusmax_armored_v1_1.blend",ASSETS/"armor/v1_1/armor_assembly_manifest.json")
    pose()
    studio=studio_signature()
    write_json(REPORT/"baseline_inventory.json",{"studio":studio,"unit_system":bpy.context.scene.unit_settings.system,
        "unit_scale_length":bpy.context.scene.unit_settings.scale_length,"length_convention":"one Blender unit is one exported glTF meter; design scale, not film metrology",
        "joints":[{"name":b.name,"parent":b.parent.name if b.parent else None,"matrix":[list(r) for r in b.matrix_local]} for b in RIG.data.bones]})
    results=[]
    for option in ("baseline","pivot_only","pivot_inner_lip"):
        if option=="pivot_only":rebase_control_pivot("ASM_PAULDRON_L",(.52,0,1.36))
        if option=="pivot_inner_lip":
            pose();write_json(REPORT/"prototype_geometry.json",cut_pauldron_chest("L"))
        rows=[]
        for name,changes,e,b,plane in shoulder_pose_tests():
            pose(changes)
            hits=evaluated_contacts(shoulder_pairs("L"),details=True,classify=True)
            objects={}
            for obj_name in {n for h in hits for n in (h["a"],h["b"])}:
                obj=PARTS[obj_name]["object"];anchor=ROOTS[PARTS[obj_name]["assembly"]]
                objects[obj_name]={"parent":obj.parent.name,"control_node":PARTS[obj_name]["assembly"],"joint":anchor["bone"],
                    "pivot_world":list(anchor["object"].matrix_world.translation),"control_axes_world":[list(r) for r in anchor["object"].matrix_world.to_3x3()],
                    "local_matrix":[list(r) for r in obj.matrix_local],"world_matrix":[list(r) for r in obj.matrix_world]}
            rows.append({"pose_id":name,"side":"L","shoulder_deg":e,"elbow_deg":b,"plane":plane,"joint_deltas_blender_xyz":changes,
                "contacts":hits,"objects":objects,"result":"FAIL" if any(h["classification"]=="EXPOSED_INTERSECTION" for h in hits) else "LIMIT" if any(h["classification"]!="FIXED_MATING" for h in hits) else "PASS"})
            if name in ("side_L_S0_E0","side_L_S90_E0","side_L_S145_E0","combined_L_S90_E130"):
                render(option+"_"+name,(3,-5,1.6),1.6,(.40,0,1.30))
        results.append({"option":option,"poses":rows})
        write_json(REPORT/"prototype_results.json",results)
        pose()
        print("SHOULDER_PROTOTYPE",option,"FAIL",sum(r["result"]=="FAIL" for r in rows),"LIMIT",sum(r["result"]=="LIMIT" for r in rows),flush=True)
    assert studio_signature()==studio
    assert shoulder_protected()==json.loads((REPORT/"preservation_before.json").read_text())
    print("SHOULDER_PROTOTYPE_COMPLETE; no source or GLB exported",flush=True)


def solve_shoulder_clearance():
    shoulder_paths()
    load_existing(ASSETS/"source/bagusmax_armored_v1_1.blend",ASSETS/"armor/v1_1/armor_assembly_manifest.json")
    pose();rebase_control_pivot("ASM_PAULDRON_L",(.52,0,1.36));cut_pauldron_chest("L");pose()
    moving=[n for n in PARTS if PARTS[n]["assembly"]=="ASM_PAULDRON_L"]
    pairs=shoulder_pairs("L")
    external=list({n for a,b in pairs if (a in moving)!=(b in moving) for n in (a,b) if n not in moving})
    root=ROOTS["ASM_PAULDRON_L"]["object"]
    local={n:[root.matrix_world.inverted()@PARTS[n]["object"].matrix_world@v.co for v in PARTS[n]["object"].data.vertices] for n in moving}
    faces={n:[list(p.vertices) for p in PARTS[n]["object"].data.polygons] for n in moving}
    candidates=sorted([(x,y,z,f) for x in (0,.04,.08,.12) for y in (0,.04,.08) for z in (0,.04,.08,.12,.16) for f in (0,.25,-.15)],key=lambda c:c[0]**2+c[1]**2+c[2]**2+.001*c[3]**2)
    records=[]
    tests=[t for t in shoulder_pose_tests() if t[0] in ("side_L_S0_E0","side_L_S90_E0","side_L_S145_E0","combined_L_S90_E130","combined_L_S145_E130","forward_L_S90_E90")]
    for name,changes,e,b,plane in tests:
        pose(changes)
        fixed={};bounds={}
        for n in external:
            obj=PARTS[n]["object"];v=[obj.matrix_world@p.co for p in obj.data.vertices];f=[list(p.vertices) for p in obj.data.polygons]
            fixed[n]=BVHTree.FromPolygons(v,f);points=np.asarray(v);bounds[n]=(points.min(0),points.max(0))
        best=None;best_count=math.inf;solved=False;tried=0
        for x,y,z,factor in candidates:
            rotation=tuple(-factor*a for a in changes.get("UpperArm_L",(0,0,0)))
            mat=Euler(rotation).to_matrix().to_4x4();mat.translation=Vector((.52+x,y,1.36+z))
            hits=[]
            for n in moving:
                vv=[mat@p for p in local[n]];a=np.asarray(vv);lo,hi=a.min(0),a.max(0)
                tree=None
                for other in external:
                    if np.any(lo>bounds[other][1]) or np.any(bounds[other][0]>hi):continue
                    if tree is None:tree=BVHTree.FromPolygons(vv,faces[n])
                    overlap=tree.overlap(fixed[other])
                    if overlap:hits.append({"a":n,"b":other,"polygon_pairs":len(overlap)})
            tried+=1
            count=sum(h["polygon_pairs"] for h in hits)
            if count<best_count:
                best_count=count;best={"translation_m":[x,y,z],"rotation_fraction":factor,"rotation_blender_xyz":rotation,"root_world_matrix":[list(r) for r in mat],"contacts":hits}
            if count==0:solved=True;break
        records.append({"pose_id":name,"joint_deltas_blender_xyz":changes,"shoulder_deg":e,"elbow_deg":b,"tested_candidates":tried,"clear_cap_sample_found":solved,"best":best,
            "scope":"bounded one-sided pauldron/liner/inlay envelope only; independent upperarm/chest contacts are not solved by this search",
            "score":"minimum sampled surface-pair count; not penetration depth or minimum physical clearance"})
        root.matrix_world=Matrix(best["root_world_matrix"]);bpy.context.view_layer.update()
        render("slide_search_"+name,(3,-5,1.6),1.6,(.40,0,1.30))
        write_json(REPORT/"clearance_search.json",records)
        print("CLEARANCE_SEARCH",name,solved,tried,best,flush=True)
    assert shoulder_protected()==json.loads((REPORT/"preservation_before.json").read_text())


def diagnose_shoulder():
    from unittest.mock import patch as mock_patch
    shoulder_paths()
    load_existing(ASSETS/"source/bagusmax_armored_v1_1.blend",ASSETS/"armor/v1_1/armor_assembly_manifest.json")
    pose()
    safety=[]
    for path in (ASSETS/"source/bagusmax_white_anatomy_v4_1.blend",ASSETS/"runtime/bagusmax_armored_v1.glb",ASSETS/"runtime/bagusmax_armored_v1_1.glb"):
        try:export_asset(path)
        except AssertionError as error:safety.append({"case":str(path.relative_to(ROOT)),"status":"PASS","rejected_before_export":str(error)})
        else:raise AssertionError("Protected destination accepted")
    try:export_asset()
    except TypeError:safety.append({"case":"omitted destination","status":"PASS"})
    else:raise AssertionError("Implicit export accepted")
    with mock_patch.object(Path,"exists",return_value=True):
        try:export_asset(GLB,replace=False)
        except FileExistsError:safety.append({"case":"existing V1.2 without explicit replacement (mocked existence, no file created)","status":"PASS"})
        else:raise AssertionError("Implicit replacement accepted")
    write_json(REPORT/"export_policy_tests.json",{"negative_destination_tests":safety,"successful_atomic_export":"NOT_TESTED; local mechanical gate failed; no candidate promoted"})
    diagnostics=[]
    cases=[("neutral",{},"ARMOR_PAULDRON_L","ARMOR_CHEST_FRONT"),
        ("side90",{"UpperArm_L":(0,-math.pi/2,0)},"ARMOR_PAULDRON_L","ARMOR_CHEST_COLLAR"),
        ("combined90_130",{"UpperArm_L":(0,-math.pi/2,0),"Forearm_L":(-math.radians(130),0,0)},"ARMOR_UPPERARM_L","ARMOR_CHEST_COLLAR"),
        ("combined145_130",{"UpperArm_L":(0,-math.radians(145),0),"Forearm_L":(-math.radians(130),0,0)},"ARMOR_UPPERARM_L","ARMOR_HELMET_EAR_L")]
    for i,(label,changes,a,b) in enumerate(cases):
        pose(changes)
        hits=evaluated_contacts(shoulder_pairs("L"),details=True,classify=True)
        metadata={}
        for name in {n for h in hits for n in (h["a"],h["b"])}:
            obj=PARTS[name]["object"];node=ROOTS[PARTS[name]["assembly"]]
            metadata[name]={"joint":node["bone"],"control_node":node["object"].name,"parent":obj.parent.name,
                "pivot_world":list(node["object"].matrix_world.translation),"axes_world":[list(r) for r in node["object"].matrix_world.to_3x3()],
                "local_matrix":[list(r) for r in obj.matrix_local],"world_matrix":[list(r) for r in obj.matrix_world]}
        diagnostics.append({"pose_id":label,"joint_deltas_blender_xyz":changes,"contacts":hits,"objects":metadata,
            "unit_scale_length":bpy.context.scene.unit_settings.scale_length,"source_actions":len(bpy.data.actions),"screenshot":f"failure_{label}.png",
            "method":"evaluated mesh positions in Blender world coordinates, AABB broad-phase then BVH polygon overlap; sampled visibility; bounds are not penetration depth"})
        hit=next(h for h in hits if {h["a"],h["b"]}=={a,b})
        target=sum((Vector(v) for k in ("a_contact_bounds_blender","b_contact_bounds_blender") for v in hit[k]),Vector())/4
        saved={}
        for name,row in PARTS.items():row["object"].hide_render=name not in (a,b)
        for name in FACE:bpy.data.objects[name].hide_render=True
        for name,color in ((a,((.02,.65,.82),(.92,.23,.08),(.15,.68,.20),(.67,.17,.77))[i]),(b,((.88,.24,.58),(.04,.60,.80),(.77,.21,.54),(.83,.57,.03))[i])):
            obj=PARTS[name]["object"]
            saved[name]=(list(obj.data.materials),[p.material_index for p in obj.data.polygons])
            mat=material("Diagnostic_Pair_"+name,color,.55)
            obj.data.materials.clear();obj.data.materials.append(mat)
            for p in obj.data.polygons:p.material_index=0
        render("failure_"+label,(4,-5,1.9),.9,tuple(target))
        for name,(mats,indices) in saved.items():
            obj=PARTS[name]["object"];obj.data.materials.clear()
            for mat in mats:obj.data.materials.append(mat)
            for p,idx in zip(obj.data.polygons,indices):p.material_index=idx
    write_json(REPORT/"failure_diagnostics.json",diagnostics)
    assert shoulder_protected()==json.loads((REPORT/"preservation_before.json").read_text())
    write_json(REPORT/"preservation_after.json",shoulder_protected())
    print("SHOULDER_FAILURE_DIAGNOSIS_COMPLETE; final source/GLB NOT_CREATED",flush=True)


def run():
    global STAGE
    args=argparse.ArgumentParser()
    args.add_argument("--stage",choices=("blockout","detail"),default="detail")
    args.add_argument("--no-renders",action="store_true")
    args.add_argument("--verify-existing",action="store_true")
    args.add_argument("--preview-assembly",action="store_true")
    args.add_argument("--refine-elbow",action="store_true")
    args.add_argument("--verify-revision",action="store_true")
    args.add_argument("--contact-evidence",action="store_true")
    args.add_argument("--audit-only",action="store_true")
    args.add_argument("--prototype-shoulder",action="store_true")
    args.add_argument("--replace-candidate",action="store_true")
    args.add_argument("--solve-shoulder",action="store_true")
    args.add_argument("--legacy-build",action="store_true")
    args.add_argument("--diagnose-shoulder",action="store_true")
    opt=args.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    STAGE=opt.stage
    if opt.diagnose_shoulder:
        diagnose_shoulder()
        return
    if opt.solve_shoulder:
        solve_shoulder_clearance()
        return
    if opt.prototype_shoulder:
        prototype_shoulder()
        return
    if opt.contact_evidence:
        contact_evidence()
        return
    if opt.verify_revision:
        verify_revision(opt.no_renders)
        return
    if opt.refine_elbow:
        if (ASSETS/"source/bagusmax_armored_v1_1.blend").exists():raise FileExistsError("V1.1 source is protected; continue through V1.2 prototype")
        refine_elbow(opt.audit_only,opt.no_renders)
        return
    if opt.verify_existing or opt.preview_assembly:
        verify_existing(opt.no_renders)
        return
    if not opt.legacy_build:raise ValueError("Select an explicit review/refinement command; default V1 rebuild is disabled")
    if SOURCE.exists():raise FileExistsError("Legacy source already exists; overwrite is forbidden")
    REPORT.mkdir(parents=True,exist_ok=True)
    DATA.mkdir(parents=True,exist_ok=True)
    before=baseline()
    key=clearance()
    for obj in recovery.visible_meshes():
        if obj.name not in FACE:
            obj.hide_render=True
            obj.hide_set(True)
    m=palette()
    torso(m);arms(m);legs(m);helmet(m);back_wings(m)
    capture_rest();pose()
    assert before["studio"]==studio_signature(),"Diagnostic studio changed"
    if not opt.no_renders:
        for view in ("front","left","back","three_quarter"):
            render(f"{STAGE}_{view}",view)
    if STAGE=="blockout":
        write_json(REPORT/"blockout_inventory.json",{"parts":list(PARTS),"status":"INTERNAL_VISUAL_REVIEW"})
        return
    export_asset(GLB.with_name("bagusmax_armored_v1_quality.glb"))
    desktop_profile()
    tests=inspection()
    export_asset(GLB)
    manifests()
    if not opt.no_renders:
        for view in ("front","back","left","right","three_quarter"):
            render("armored_"+view,view)
        render("helmet_detail","three_quarter",.60,(0,-.03,1.59))
        render("abdominal_armor","front",.90,(0,-.12,.95))
        render("shoulder_detail","three_quarter",.85,(.40,0,1.30))
        render("mechanical_hands","left",.39,(.52,-.07,.46))
        render("legs_detail","three_quarter",.85,(0,0,.29))
        render("wings_folded","rear_quarter")
        for name,changes,wing,gesture in tests:
            if name in ("shoulder_L_90","shoulder_L_145","elbow_L_130","elbow_R_130","forward_fist","leg_step","head_turn","point","wings_partial","wings_deployed","combined"):
                pose(changes,wing,gesture)
                render(name,"rear_quarter" if name.startswith("wings") else "three_quarter",3.35 if wing else 2.4)
        for p in (0,.2,.4,.7,1):
            assembly(p)
            render(f"assembly_{int(p*100):03}","three_quarter",3.15)
    pose()
    for name in FACE:
        obj=bpy.data.objects[name]
        if obj.data.shape_keys:
            for k in obj.data.shape_keys.key_blocks: k.value=0
    assert key.value==0
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE))
    after=protected()
    assert json.loads((REPORT/"preservation_before.json").read_text())==after
    write_json(REPORT/"preservation_after.json",after)
    write_json(REPORT/"asset_hashes.json",{str(p.relative_to(ROOT)).replace("\\","/"):{"sha256":sha(p),"bytes":p.stat().st_size} for p in [SOURCE,GLB]})
    print("ARMORED_BUILD_COMPLETE",len(PARTS),len(ROOTS),str(GLB),flush=True)


if __name__=="__main__":
    run()
