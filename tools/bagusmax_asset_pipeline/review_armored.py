"""Review modular armor transforms, preserved rig, and actual export buffers."""

import hashlib
import html
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from gltf_skinning import GLBSkin, BLENDER_TO_GLTF, rotation_xyz

ROOT=Path(__file__).resolve().parents[2]
REPORT=ROOT/"reports/bagusmax_3d/armored_v1"
DATA=ROOT/"assets/bagusmax/armor"
GLB=ROOT/"assets/bagusmax/runtime/bagusmax_armored_v1.glb"
B=BLENDER_TO_GLTF
REF_IDS=("059aa4ad-a564-435a-bda4-cb31c08401ac","437991c8-f6a7-4e7c-a52f-28cb897f839b",
 "c879b479-5aea-4cf9-8eb3-63d54ec98fa4","838af715-9a4c-433a-9b7a-8f14373329c1",
 "c60eb315-fe1a-44af-89cf-0b11f0c37f80","cf0aa463-130e-4198-8d83-3b00bcd32f06",
 "1a61eb1a-6293-4ba8-adb2-202248bef4af","85eb0772-c548-4f5f-a288-da3fe82555f6",
 "3c4610b3-75c6-4ae8-a59a-f736d12e0600","f16d7ad1-2f8b-4845-b150-79d0ed7e4115",
 "b9803f85-ef53-49c2-81e2-2d0fd27e0db5","030e7559-1242-486f-a10f-44c5c557c6f8",
 "f1742fb2-b140-447d-9f2e-4e9380be1869","9b832c61-033c-4797-9d92-66aecf0f70e4",
 "11319f29-e790-4e1a-934e-f94bb2f054fc")


def write(name,data,folder=None):
    folder=folder or REPORT
    (folder/name).write_text(json.dumps(data,indent=2),encoding="utf-8")


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def control_rotation(xyz):
    return B@rotation_xyz(xyz)@B.T


def evaluate(asset,test):
    local=[m.copy() for m in asset.local]
    posed=asset.posed_globals(test["joint_deltas_blender_xyz"])
    bones=json.loads((REPORT/"baseline_inventory.json").read_text())["joints"]
    for bone in bones:
        i=asset.names[bone["name"]]
        parent=asset.parents.get(i)
        local[i]=np.linalg.inv(posed[parent])@posed[i] if parent is not None else posed[i].copy()
    for s,side in ((1,"L"),(-1,"R")):
        a=abs(test["joint_deltas_blender_xyz"].get("UpperArm_"+side,(0,0,0))[1])
        i=asset.names["ASM_PAULDRON_"+side]
        local[i][:3,:3]=asset.local[i][:3,:3]@control_rotation((0,-s*a*.64,0))
        shift=B@np.array((s*.07*math.sin(a/2),0,.025*math.sin(a)))
        local[i][:3,3]+=asset.local[i][:3,:3]@shift
        bend=abs(test["joint_deltas_blender_xyz"].get("Forearm_"+side,(0,0,0))[0])
        f=np.clip((math.degrees(bend)-55)/75,0,1)
        if asset.doc.get("asset",{}).get("extras",{}).get("armor_profile")=="1.1":
            relief=np.clip((math.degrees(a)-30)/60,0,1)*f
            local[asset.names["ASM_PAULDRON_"+side]][:3,3]+=asset.local[asset.names["ASM_PAULDRON_"+side]][:3,:3]@(B@np.array((s*.06*relief,.10*relief,0)))
            i=asset.names["ASM_ELBOW_"+side]
            local[i][:3,:3]=asset.local[i][:3,:3]@control_rotation((-.10*bend,0,0))
        slide=.055*f
        i=asset.names["ASM_FOREARM_"+side]
        local[i][:3,3]+=asset.local[i][:3,:3]@(B@np.array((0,0,-slide)))
        i=asset.names["ASM_UPPERARM_"+side]
        comp=np.clip((math.degrees(a)-60)/85,0,1) if asset.doc.get("asset",{}).get("extras",{}).get("armor_profile")=="1.1" else 0
        local[i][:3,3]+=asset.local[i][:3,:3]@(B@np.array((0,0,.105*f*(1-.6*comp))))
        wing=test["wing_progress"]
        for name,default,current in (
            ("ASM_WING_ROOT_"+side,(0,s*math.radians(89),0),
             (0,s*math.radians(89*(1-wing)),0)),
            ("ASM_WING_TIP_"+side,(0,-s*math.radians(154),0),(0,-s*math.radians(154*(1-wing)),0))):
            i=asset.names[name]
            local[i][:3,:3]=asset.local[i][:3,:3]@control_rotation(default).T@control_rotation(current)
        for digit in ("INDEX","MIDDLE","RING","THUMB"):
            for k in range(2 if digit=="THUMB" else 3):
                curl=10 if test["gesture"]=="relaxed" else (5 if test["gesture"]=="point" and digit=="INDEX" else 65)
                mult=.65 if digit=="THUMB" else 1
                i=asset.names[f"CTRL_{digit}_{side}_{k}"]
                local[i][:3,:3]=asset.local[i][:3,:3]@control_rotation((0,s*math.radians(10*mult),0)).T@control_rotation((0,s*math.radians(curl*mult),0))
    return asset.globals(local)


def primitives(asset):
    for i,node in enumerate(asset.nodes):
        if "mesh" not in node: continue
        for p in asset.doc["meshes"][node["mesh"]]["primitives"]:
            yield i,node,p


def independent(asset,source=None,label="independent_transforms.json"):
    source=source if source is not None else json.loads((REPORT/"blender_pose_matrices.json").read_text())
    geometry={}
    for i,node,prim in primitives(asset):
        if "skin" in node:continue
        pos=asset.accessor(prim["attributes"]["POSITION"])
        geometry.setdefault(node["name"],[]).append(pos@asset.rest[i,:3,:3].T+asset.rest[i,:3,3])
    geometry={name:np.concatenate(parts) for name,parts in geometry.items()}
    neutral=source[0]
    mapping={}
    for name,row in neutral["nodes"].items():
        probes=np.asarray(row["probes"])
        verts=geometry[name]
        nearest=np.argmin(np.sum((probes[:,None]-verts[None])**2,axis=2),axis=1)
        points=verts[nearest]
        i=asset.names[name]
        mapping[name]=(points-asset.rest[i,:3,3])@np.linalg.inv(asset.rest[i,:3,:3]).T
    records=[]
    for test in source:
        start=time.perf_counter()
        matrices=evaluate(asset,test)
        errors=[]
        matrix_error=0
        for name,row in test["nodes"].items():
            i=asset.names[name]
            matrix_error=max(matrix_error,float(np.max(abs(matrices[i]-np.asarray(row["matrix"])))))
            p=mapping[name]@matrices[i,:3,:3].T+matrices[i,:3,3]
            errors.extend(np.linalg.norm(p-np.asarray(row["probes"]),axis=1))
        error=max(errors)*1000
        records.append({"name":test["name"],"sampled_vertices":len(errors),"max_position_error_mm":float(error),
            "rms_position_error_mm":float(np.sqrt(np.mean(np.square(errors)))*1000),
            "max_matrix_element_error":matrix_error,
            "matrix_and_probe_eval_ms":(time.perf_counter()-start)*1000,"status":"PASS" if error<.1 and matrix_error<1e-5 else "FAIL",
            "scope":"rigid nodes plus original joint matrices; not a collision or visual acceptance result"})
    write(label,records)
    return records


def stats(asset):
    triangles=vertices=degenerate=0
    influence=0
    normals_bad=0
    for i,node,p in primitives(asset):
        attrs=p["attributes"]
        pos=asset.accessor(attrs["POSITION"])
        ids=asset.accessor(p["indices"]).astype(int).reshape(-1,3)
        vertices+=len(pos);triangles+=len(ids)
        areas=np.linalg.norm(np.cross(pos[ids[:,1]]-pos[ids[:,0]],pos[ids[:,2]]-pos[ids[:,0]]),axis=1)
        degenerate+=int((areas<1e-12).sum())
        n=asset.accessor(attrs["NORMAL"])
        normals_bad+=int((abs(np.linalg.norm(n,axis=1)-1)>1e-4).sum())
        if "WEIGHTS_0" in attrs:
            influence=max(influence,int((asset.accessor(attrs["WEIGHTS_0"])>0).sum(axis=1).max()))
    return {"triangles":triangles,"vertices_exported":vertices,"mesh_count":len(asset.doc["meshes"]),
        "draw_primitives":sum(len(m["primitives"]) for m in asset.doc["meshes"]),
        "material_count":len(asset.doc["materials"]),"joint_counts":[len(s["joints"]) for s in asset.doc["skins"]],
        "max_influences_skinned_face":influence,"rigid_armor_vertex_weights":0,
        "morph_targets":sum(len(m["primitives"][0].get("targets",[])) for m in asset.doc["meshes"]),
        "animation_clips":len(asset.doc.get("animations",[])),"glb_bytes":asset.path.stat().st_size,
        "texture_bytes":0,"texture_count":len(asset.doc.get("images",[])),
        "geometry_buffer_bytes":len(asset.binary),"degenerate_triangles":degenerate,"nonunit_normals":normals_bad,
        "runtime_fps":"NOT_TESTED","runtime_vram":"NOT_TESTED","app_renderer_changes":False}


def rig_check(armor):
    white=GLBSkin(ROOT/"assets/bagusmax/runtime/bagusmax_white_anatomy_v4_1.glb")
    joint_ids=white.doc["skins"][0]["joints"]
    errors=[]
    armor_joints=armor.doc["skins"][0]["joints"]
    armor_order={armor.nodes[j]["name"]:k for k,j in enumerate(armor_joints)}
    for k,j in enumerate(joint_ids):
        name=white.nodes[j]["name"]
        error=float(np.max(abs(white.rest[j]-armor.rest[armor.names[name]])))
        bind_error=float(np.max(abs(white.bind[0][k]-armor.bind[0][armor_order[name]])))
        wp=white.nodes[white.parents[j]]["name"] if j in white.parents else None
        ai=armor.names[name]
        ap=armor.nodes[armor.parents[ai]]["name"] if ai in armor.parents else None
        errors.append({"joint":name,"max_matrix_error":error,"max_inverse_bind_error":bind_error,"parent_matches":wp==ap})
    passed=max(max(e["max_matrix_error"],e["max_inverse_bind_error"]) for e in errors)<1e-5 and all(e["parent_matches"] for e in errors)
    write("rig_compatibility.json",{"status":"PASS" if passed else "FAIL","joints":errors})


def board(name,entries,columns=3,size=520):
    from PIL import Image, ImageDraw, ImageFont
    font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",19)
    canvas=Image.new("RGB",(columns*size,math.ceil(len(entries)/columns)*(size+38)),"#202326")
    draw=ImageDraw.Draw(canvas)
    for i,(filename,label) in enumerate(entries):
        p=REPORT/(filename+".png")
        if not p.exists():continue
        image=Image.open(p).convert("RGB")
        image.thumbnail((size,size))
        x=(i%columns)*size;y=(i//columns)*(size+38)
        canvas.paste(image,(x+(size-image.width)//2,y+(size-image.height)//2))
        draw.text((x+14,y+size+8),label,font=font,fill="#ffffff")
    canvas.save(REPORT/(name+".png"))


def references():
    rows=[]
    notes=("Flight / foreshortening; fist, wing sweep", "Standing low angle; torso, hands, legs", "Exploded toy; module allocation, not film topology",
        "Flight; wing sweep and chest", "White exposed; fitting evidence, not final silhouette", "White plus lower apparatus; assembly mood",
        "Near duplicate of R01", "Near duplicate of R02", "Toy side; elbow bearing, forearm inset", "Film lab; grounded silhouette",
        "Standing frontal toy; expanded wings", "Flight close; helmet and pauldron", "Flight frontal; abdomen and wing roots",
        "Toy rear; backpack and root hinges", "Helmet close-up; aperture, cheek, ear fin")
    cards=[]
    for i,(uid,note) in enumerate(zip(REF_IDS,notes),1):
        p=Path("C:/Users/bagus/AppData/Local/Temp")/("codex-clipboard-"+uid+".jpg")
        rows.append({"id":f"R{i:02}","path":str(p),"exists":p.exists(),"sha256":digest(p) if p.exists() else None,"observation":note})
        cards.append(f'<figure><img src="{p.as_uri()}"><figcaption>R{i:02}: {html.escape(note)}</figcaption></figure>')
    write("reference_index.json",rows)
    content='<!doctype html><meta charset="utf-8"><title>Private reference review</title><style>body{background:#26292b;color:white;font:16px Arial}main{display:grid;grid-template-columns:repeat(3,1fr)}figure{margin:10px}img{max-width:100%;height:350px;object-fit:contain}h1{font-size:24px}</style><h1>Private working references: external originals, not embedded or distributable</h1><main>'+''.join(cards)+'</main><h2>Candidate</h2><img src="armored_front.png"><img src="armored_three_quarter.png"><img src="helmet_detail.png">'
    if REPORT.name=="armored_v1_1":
        content=content.replace("armored_front.png","v1_1_neutral_front.png").replace("armored_three_quarter.png","v1_1_neutral_three_quarter.png").replace('<img src="helmet_detail.png">','<img src="v1_1_elbow_L_130.png">')
    (REPORT/"private_reference_review.html").write_text(content,encoding="utf-8")


def validate(path=None,label="khronos_validator.json"):
    path=path or GLB
    module="C:/Users/bagus/AppData/Local/Temp/openbagus-gltf-validator/node_modules/gltf-validator"
    script="const fs=require('fs'),v=require(process.argv[1]);v.validateBytes(new Uint8Array(fs.readFileSync(process.argv[2])),{uri:process.argv[2]}).then(r=>{fs.writeFileSync(process.argv[3],JSON.stringify(r,null,2));console.log(JSON.stringify(r.issues));if(r.issues.numErrors)process.exitCode=1})"
    subprocess.run(["D:/Program Files/nodejs/node.exe","-e",script,module,str(path),str(REPORT/label)],capture_output=True,text=True,check=True)
    report=json.loads((REPORT/label).read_text())
    return {k:v for k,v in report["issues"].items() if k!="messages"}


def review_revision():
    global REPORT,DATA,GLB
    REPORT=ROOT/"reports/bagusmax_3d/armored_v1_1"
    DATA=ROOT/"assets/bagusmax/armor/v1_1"
    GLB=ROOT/"assets/bagusmax/runtime/bagusmax_armored_v1_1.glb"
    asset=GLBSkin(GLB)
    report=stats(asset)
    baseline=stats(GLBSkin(GLB.with_name("bagusmax_armored_v1.glb")))
    report["asset_sha256"]=digest(GLB)
    report["validator"]=validate()
    report["independent_evaluations"]=independent(asset)
    rig_check(asset)
    before=json.loads((REPORT/"v1_classified_contacts.json").read_text())
    after=json.loads((REPORT/"v1_1_classified_contacts.json").read_text())
    for filename,rows in (("v1_classified_contacts.json",before),("v1_1_classified_contacts.json",after)):
        write(filename,[{k:v for k,v in row.items() if k!="nodes"} for row in rows])
    def result(row):
        groups={kind:[h for h in row["contacts"] if h["classification"]==kind] for kind in ("EXPOSED_INTERSECTION","UNRESOLVED_CONTACT","HIDDEN_INTERNAL","FIXED_MATING")}
        state="FAIL" if groups["EXPOSED_INTERSECTION"] else "LIMIT" if groups["UNRESOLVED_CONTACT"] or groups["HIDDEN_INTERNAL"] else "PASS"
        elbow_parts=("UPPERARM","ELBOW_SOCKET","ELBOW_METAL","ELBOW_HUB","FOREARM","FOREARM_CUFF","FOREARM_INLAY","ELBOW_GUARD","ELBOW_GUARD_INLAY","WRIST","PALM")
        local=[h for h in row["contacts"] if all(n.rsplit("_",1)[0].removeprefix("ARMOR_") in elbow_parts for n in (h["a"],h["b"])) and h["classification"]!="FIXED_MATING"]
        elbow="FAIL" if any(h["classification"]=="EXPOSED_INTERSECTION" for h in local) else "LIMIT" if local else "PASS"
        return {"pose":row["name"],"status":state,"elbow_local_status":elbow,"elbow_local_contacts":local,"groups":groups}
    old={r["name"]:result(r) for r in before}
    diagnosis={}
    for row in before:
        for hit in row["contacts"]:
            if hit["classification"]=="FIXED_MATING":continue
            key=" / ".join(sorted((hit["a"],hit["b"])))
            if key not in diagnosis:
                if "SHOULDER_RECESS" in key:
                    cause="Rigid parent and clearance: liner inherited upper-arm stroke rather than pauldron mount; residual neutral contact still measured."
                    categories=[2,5]
                elif "UPPERARM" in key and "FOREARM" in key:
                    cause="Shell profile and swept clearance: proximal forearm and upper-arm occupy the same inside-fold envelope; distal slide alone is insufficient."
                    categories=[4,5]
                elif "PAULDRON" in key:
                    cause="Physical swept clearance: chest lap or moving arm component reaches hard cap. Bounded cap guide does not certify separation."
                    categories=[5]
                else:
                    cause="Measured occupied-volume clearance failure. Incorrect joint axis, skin weight or rest hierarchy not demonstrated for this pair."
                    categories=[5]
                diagnosis[key]={"parts":[hit["a"],hit["b"]],"root_cause_categories":categories,"diagnosis":cause,"poses":[]}
            diagnosis[key]["poses"].append({"pose":row["name"],"classification":hit["classification"],"evidence":"v1_"+row["name"]+".png"})
    write("intersection_diagnosis.json",list(diagnosis.values()))
    matrix=[]
    for row in after:
        r=result(row)
        r["v1_status"]=old[r["pose"]]["status"]
        r["v1_elbow_local_status"]=old[r["pose"]]["elbow_local_status"]
        r["v1_exposed_pairs"]=len(old[r["pose"]]["groups"]["EXPOSED_INTERSECTION"])
        r["v1_1_exposed_pairs"]=len(r["groups"]["EXPOSED_INTERSECTION"])
        matrix.append(r)
    write("clearance_matrix.json",{"status":"REVIEW_REQUIRED","method":"BVH polygon surface pairs; up to 12 exact contact samples, 32 exterior rays each. Occlusion sampling is not exhaustive visibility certification.","poses":matrix})
    sweep=json.loads((REPORT/"intermediate_angle_sweep.json").read_text())
    fixed={frozenset((h["a"],h["b"])) for row in after for h in row["contacts"] if h["classification"]=="FIXED_MATING"}
    intermediate=[]
    for row in sweep:
        if row["joint"]!="Forearm":continue
        names={"ARMOR_"+p+"_"+row["side"] for p in ("UPPERARM","ELBOW_SOCKET","ELBOW_METAL","ELBOW_HUB","FOREARM","FOREARM_CUFF","FOREARM_INLAY","ELBOW_GUARD","WRIST","PALM")}
        contacts=[{"degrees":s["degrees"],"contact":h} for s in row["samples"] for h in s["contacts"] if h["a"] in names and h["b"] in names and frozenset((h["a"],h["b"])) not in fixed]
        intermediate.append({"side":row["side"],"status":"LIMIT" if contacts else "PASS","sample_step_degrees":5,"range_degrees":[0,130],"contacts":contacts,
            "max_return_matrix_error":row["max_return_matrix_error"],"scope":"local elbow shell pairs, not shoulder or mathematically continuous collision proof"})
    write("intermediate_elbow_clearance.json",intermediate)
    protected=json.loads((REPORT/"preservation_before.json").read_text())
    preservation=all(digest(ROOT/p)==v["sha256"] for p,v in protected.items())
    write("preservation_after.json",{p:{"sha256":digest(ROOT/p),"bytes":(ROOT/p).stat().st_size} for p in protected})
    rig=json.loads((REPORT/"rig_compatibility.json").read_text())
    reimport=json.loads((REPORT/"neutral_reimport.json").read_text())
    state=json.loads((REPORT/"saved_source_state.json").read_text())
    top=json.loads((REPORT/"source_geometry_audit.json").read_text())
    wing_clearance=json.loads((REPORT/"wing_clearance.json").read_text())
    all_independent=all(r["status"]=="PASS" for r in report["independent_evaluations"])
    manifest=json.loads((DATA/"armor_assembly_manifest.json").read_text())
    original_manifest=json.loads((DATA.parent/"armor_assembly_manifest.json").read_text())
    stable=set(r["part_id"] for r in original_manifest["parts"])<=set(r["part_id"] for r in manifest["parts"])
    report.update(status="REVIEW_REQUIRED",v1=baseline,armor_parts=len(manifest["parts"]),control_nodes=len(manifest["assembly_nodes"]),
        original_stable_ids_preserved=stable,white_and_rollback_integrity="PASS" if preservation else "FAIL",
        max_independent_error_mm=max(r["max_position_error_mm"] for r in report["independent_evaluations"]),
        source_nonmanifold_edges=sum(r["nonmanifold_edges"] for r in top))
    write("validation_report.json",report)
    for side in ("L","R"):
        board("elbow_"+side+"_comparison",[(v+f"elbow_{side}_{a}",f"{'V1' if v=='v1_' else 'V1.1'} / {side} elbow {a} deg") for a in (90,110,120,130) for v in ("v1_","v1_1_")],2,650)
        board("shoulder_"+side+"_comparison",[(v+f"shoulder_{side}_{a}",f"{'V1' if v=='v1_' else 'V1.1'} / {side} shoulder {a} deg") for a in (0,45,90,120,145) for v in ("v1_","v1_1_")],2,550)
    board("neutral_comparison",[(v+"neutral_"+view,version+" / "+view) for view in ("front","left","right","back","three_quarter") for v,version in (("v1_","V1"),("v1_1_","V1.1"))],2,550)
    board("final_neutral",[("v1_1_neutral_"+v,v) for v in ("front","left","right","back","three_quarter")],3,550)
    board("combined_comparison",[(v+f"combined_{side}_S{e}_E{b}",f"{version} {side}: S{e} / E{b}") for side in ("L","R") for e,b in ((45,90),(90,110),(90,130),(120,110),(145,90)) for v,version in (("v1_","V1"),("v1_1_","V1.1"))],2,550)
    board("export_verification",[(v+name,kind+" / "+name) for name in ("elbow_L_130","elbow_R_130","shoulder_L_145","shoulder_R_145","combined_L_S90_E130","combined_R_S90_E130") for v,kind in (("blender_","Blender"),("glb_","Independent GLB"))]+[("neutral_glb_reimport","GLB neutral reimport")],2,550)
    board("wing_states",[("v1_1_wings_folded","Folded default"),("v1_1_wings_partial","Static partial"),("v1_1_wings_open","Static open")],3,550)
    board("modular_exploded",[(f"modular_exploded_{p:03}",f"Static assembly {p}%") for p in (0,40,100)],3,550)
    board("contact_diagnostic",[(v+f"contact_{s}_{angle}",f"{label} {s} / {angle}: isolated BVH diagnostic") for s in ("L","R") for angle in ("outside","inside") for v,label in (("v1_","V1"),("v1_1_","V1.1"))],2,650)
    references()
    critical=[r for r in matrix if r["pose"].startswith(("elbow_","shoulder_","combined_"))]
    gate="FAIL" if any(r["status"]=="FAIL" for r in critical) else "LIMIT" if any(r["status"]=="LIMIT" for r in critical) else "PASS"
    tests=[("Elbow and shoulder clearance",gate,"See per-pose clearance_matrix.json; no silent rotation clamp"),
        ("Local elbow 5-degree sweep","PASS" if all(r["status"]=="PASS" for r in intermediate) else "LIMIT","Both arms 0..130; excludes shoulder and intentional co-moving mating"),
        ("Static wing clearance","PASS" if all(r["status"]=="PASS" for r in wing_clearance) else "LIMIT","Folded / partial / open against helmet, pauldron and backpack; not full continuous swept volume"),
        ("Rigid modular articulation","PASS" if stable else "FAIL",f"{len(manifest['parts'])} armor parts; all original IDs retained; {len(manifest['assembly_nodes'])} controls"),
        ("GLB structural validation","PASS" if not report["validator"]["numErrors"] and not report["validator"]["numWarnings"] else "FAIL",str(report["validator"])),
        ("Independent GLB transforms","PASS" if all_independent else "FAIL",f"{len(report['independent_evaluations'])} poses; max {report['max_independent_error_mm']:.6f} mm"),
        ("Neutral round-trip",reimport["status"],"All rigid vertices, both directions"),
        ("White rig contract",rig["status"],"32 joint names, parents, rest and inverse bind matrices"),
        ("Geometry integrity","PASS" if not report["degenerate_triangles"] and not report["source_nonmanifold_edges"] else "LIMIT",f"{report['degenerate_triangles']} degenerate triangles; {report['source_nonmanifold_edges']} nonmanifold edges"),
        ("White / V1 / rollback preserved","PASS" if preservation else "FAIL","SHA-256 equality"),
        ("Neutral return / unchanged studio","PASS" if state["neutral_return_exact"] and state["studio_unchanged"] else "FAIL","Folded wings, relaxed hands, original diagnostic studio"),
        ("No animation clips","PASS" if report["animation_clips"]==0 and state["animation_clips"]==0 else "FAIL","Static disposable inspections only"),
        ("Runtime FPS / VRAM","NOT_TESTED","No renderer or companion changes"),
        ("Visual approval","NOT_TESTED","User review required; no production-ready claim")]
    write("acceptance_matrix.json",{"status":"REVIEW_REQUIRED","asset_sha256":report["asset_sha256"],"criteria":[{"name":n,"status":s,"evidence":e} for n,s,e in tests]})
    git_status=subprocess.run(["git","status","--short","--branch"],cwd=ROOT,capture_output=True,text=True,check=True)
    (REPORT/"git_status.txt").write_text(git_status.stdout,encoding="utf-8")
    revision_handoff(report,matrix,tests,protected,manifest)
    print(json.dumps({k:v for k,v in report.items() if k!="independent_evaluations"},indent=2))


def revision_handoff(report,matrix,tests,protected,manifest):
    lines=["# BAGUSMAX Armored V1.1 Handoff","","Status: **REVIEW_REQUIRED**. Kandidat refinement lokal, bukan production-ready. STOP setelah paket ini; menunggu visual approval. Tidak ada perubahan runtime, animasi atau lighting.","",
        "## A. Verified Root Causes","",
        "- Upper-arm C-shell dan bibir proksimal forearm menyapu volume yang sama mulai sekitar 100 derajat. Parenting rigid utama benar; ini bukan kegagalan skin weights. Forearm distal slide saja tidak cukup untuk ukuran kedua shell.",
        "- Elbow socket V1 mengikuti seluruh Forearm, sehingga cup tidak membagi sudut antarsegmen. Liner shoulder V1 ikut upper-arm stroke dan mendekati chest/collar pada elevation tinggi.",
        "- Audit pasangan lebih luas menemukan upperarm/pauldron, socket/pauldron, dan forearm/wrist/palm terhadap pauldron pada pose gabungan. Klaim V1 pada selected pairs tidak mewakili envelope gabungan penuh.",
        "- BVH mendeteksi perpotongan permukaan, bukan kedalaman penetrasi atau seluruh containment. Fixed mating hanya dikecualikan untuk pasangan co-moving yang eksplisit. HIDDEN_INTERNAL berarti sampel ray terhalang, bukan bukti semua sudut pandang bersih. Diagnosis setiap pasangan, kategori penyebab 1..8, pose dan gambar: intersection_diagnosis.json.","",
        "![Actual contact diagnostic](../../reports/bagusmax_3d/armored_v1_1/contact_diagnostic.png)","",
        "## B. Mechanical Changes","",
        "Forearm dan purple inlay asli dipotong hanya di sweep upper-arm 0..130 setiap 5 derajat (elevation 0/145), dengan margin cutter nominal 4 mm, bukan minimum air gap terukur. Bagian permukaan merah yang dipisahkan menjadi articulated inner guard, bukan mesh filler untuk menutupi clipping. Rim bevel lokal 1.5 mm; trimming guard memakai occupied shell aktual dan solver Manifold, toleransi tepi 0.5 mm, smoothing lokal cut vertices, lalu allowance guard tambahan 0.7 mm untuk kontak intermediate 105 derajat. Tidak ada global subdivision.","",
        "Cup/guard rigid dipasang ke existing ElbowVolume_L/R, bukan skin elastis. Cup diberi dome lokal; shoulder liner diperkecil dan dipasang ke pauldron. Joint dasar White tidak berubah. Forearm, gauntlet, wrist dan finger control tetap terpisah.","",
        "## C. V1 Versus V1.1","","Semua pasangan gambar memakai pose, kamera, skala, material dan studio diagnostik yang sama. Tidak ada film pixels di aset atau PNG ini.","",
        "![Elbow left](../../reports/bagusmax_3d/armored_v1_1/elbow_L_comparison.png)",
        "![Elbow right](../../reports/bagusmax_3d/armored_v1_1/elbow_R_comparison.png)",
        "![Neutral](../../reports/bagusmax_3d/armored_v1_1/neutral_comparison.png)","",
        "## D. Elbow Clearance Matrix","","Status mempertimbangkan seluruh pasangan yang diuji, bukan hanya upperarm/forearm. FAIL = exposed sampled surface crossing; LIMIT = hidden or unresolved contact; PASS = no non-mating BVH surface crossing in this tested pose.","",
        "| Pose | V1 local elbow | V1.1 local elbow | V1.1 all tested pairs |","|---|---|---|---|"]
    lines.extend(f"| {r['pose']} | {r['v1_elbow_local_status']} | {r['elbow_local_status']} | {r['status']} |" for r in matrix if r["pose"].startswith("elbow_"))
    lines.extend(["","## E. Shoulder And Combined Matrix","","| Pose | V1 | V1.1 | Exposed V1.1 pairs |","|---|---|---|---:|"])
    lines.extend(f"| {r['pose']} | {r['v1_status']} | {r['status']} | {r['v1_1_exposed_pairs']} |" for r in matrix if not r["pose"].startswith("elbow_"))
    lines.extend(["","5-degree out-and-back elbow and shoulder sweeps: intermediate_angle_sweep.json. Local elbow result: intermediate_elbow_clearance.json. Raw contacts retained, not silently waived. Same-angle return matrices are checked; no motion/animation authored. This is discrete sampling, not proof for every real-valued angle.","",
        "![Combined](../../reports/bagusmax_3d/armored_v1_1/combined_comparison.png)","",
        "## F. Modular Manifest And Articulation Contract","",
        "Canonical candidate data: assets/bagusmax/armor/v1_1/armor_assembly_manifest.json and armor_attachment_map.json. Every part has stable ID, actual exported parent/local rest transform, attachment point, White mount joint, installed state, dependencies and control mapping. Original IDs retained; new guard IDs are additive. Matrices are column-major glTF meters, Y-up, +Z forward, +X anatomical left. No Blender driver or constraint is assumed exported.","",
        "Let E=abs(UpperArm anatomical rest-axis Y delta) in degrees, B=abs(Forearm rest-axis X delta) in degrees, s=+1 left/-1 right; clamp means [0,1]. These are absolute evaluations from exported neutral, never accumulated deltas:","",
        "```text\nf = clamp((B-55)/75)\nc = clamp((E-60)/85)\nr = clamp((E-30)/60) * f\nASM_FOREARM translation += (0,0,-0.055*f) meters\nASM_UPPERARM translation += (0,0,0.105*f*(1-0.6*c)) meters\nElbowVolume helper rotation = 0.5 * Forearm anatomical delta\nASM_ELBOW extra rotation X = -0.10*B degrees (total flexion phase 0.60)\nASM_PAULDRON rotation Y = -s*0.64*E degrees\nASM_PAULDRON translation += (s*(0.07*sin(E/2)+0.06*r),0.10*r,0.025*sin(E)) meters\n```","",
        "Formula vectors are Blender anatomical rest axes (+Z up, -Y forward). Convert with B=[[1,0,0],[0,0,1],[0,-1,0]] to glTF and conjugate rotations into the exported local rest basis. Trig uses radians. Apply offsets on control nodes only; child parts inherit. Runtime implementation belongs to Antigravity and is NOT included. Tests evaluate these exact rules independently from GLB.","",
        "## G. Wing Rest Geometry","","Original two-hinge wings and meshes unchanged. Default folded: root Y=s*89 degrees, tip Y=-s*154 degrees; deployed progress1, partial0.5 are disposable static inspections. No opening clip. wing_clearance.json checks main/tip against helmet, pauldron and backpack at all three static states. Complete continuous wing swept-volume certification is NOT_TESTED.","",
        "![Wing states](../../reports/bagusmax_3d/armored_v1_1/wing_states.png)",
        "![Exploded](../../reports/bagusmax_3d/armored_v1_1/modular_exploded.png)","",
        "## H. Export Validation","",
        f"Khronos: {report['validator']['numErrors']} errors / {report['validator']['numWarnings']} warnings. {len(report['independent_evaluations'])} independent exported-joint/control/probe evaluations; max position error {report['max_independent_error_mm']:.6f} mm. Neutral round-trip checks every rigid vertex bidirectionally. All 32 original rest and inverse-bind matrices compared with White. Rendered GLB geometry uses exported buffers/matrices at the same pose/camera; normals recalculated for diagnostic rendering, not GPU shader parity certification.","",
        "![Export](../../reports/bagusmax_3d/armored_v1_1/export_verification.png)","",
        "| Metric | V1 | V1.1 |","|---|---:|---:|"])
    for label,key in (("Triangles","triangles"),("Exported vertices","vertices_exported"),("Meshes","mesh_count"),("Draw primitives","draw_primitives"),("Materials","material_count"),("Morph targets in armor GLB","morph_targets"),("Animation clips","animation_clips"),("GLB bytes","glb_bytes"),("Geometry buffer bytes","geometry_buffer_bytes"),("Degenerate triangles","degenerate_triangles")):
        lines.append(f"| {label} | {report['v1'][key]:,} | {report[key]:,} |")
    lines.extend(["",f"{report['armor_parts']} armor parts, {report['control_nodes']} control nodes, 32 joints. Rigid armor has no blended weights; skinned head/face maximum {report['max_influences_skinned_face']} influence. Local split/clearance topology adds {report['triangles']-report['v1']['triangles']:,} triangles ({100*(report['triangles']/report['v1']['triangles']-1):.2f}%); no global subdivision. Source nonmanifold edges: {report['source_nonmanifold_edges']}. See per-object audit for exact locations.","",
        "## I. FPS / VRAM","","**NOT_TESTED**. File and buffer bytes are measured, not GPU allocation. No renderer changes or invented 60 FPS claim.","",
        "## J. Foundation And Rollback Integrity","",f"SHA-256 preservation: **{report['white_and_rollback_integrity']}**. All original White, V1, legacy rollback, lighting spec and V1 handoff/manifest files checked before/after.","",
        "A wrong captured default export path briefly replaced V1 GLB during refinement. It was restored byte-identically from untouched V1 saved source through the original exporter; the exporter now rejects any non-candidate path in revision mode. Recovery hash verified against the pre-edit baseline, not a newly invented baseline.","",
        "```text\n"+"\n".join(p+"\n"+v["sha256"] for p,v in protected.items() if p.endswith(("bagusmax_armored_v1.glb","bagusmax_armored_v1.blend","bagusmax_white_anatomy_v4_1.glb","bagusmax_white_anatomy_v4_1.blend")))+"\n```","",
        "## K. Git And Exact Files","","No stage, commit, merge, push, branch change or other-worktree edit. Existing art folders were already untracked. Only White-related read-only inspections and Armored art pipeline/candidate outputs are involved. deliverable_inventory.json records exact candidate files and SHA-256. Git status captured separately in git_status.txt.","",
        "## L. Review Package And Remaining Limits","","| Criterion | Status | Evidence |","|---|---|---|"])
    lines.extend(f"| {n} | {s} | {e} |" for n,s,e in tests)
    failures=[r for r in matrix if r["status"]=="FAIL"]
    lines.extend(["","Remaining exposed intersections (not hidden or relabelled):"])
    for r in failures:
        lines.append("- "+r["pose"]+": "+", ".join(h["a"]+" / "+h["b"] for h in r["groups"]["EXPOSED_INTERSECTION"]))
    if not failures:lines.append("- No exposed intersection found in the sampled required poses; hidden/unresolved contacts remain LIMIT wherever listed.")
    lines.extend(["","Missing collision tests: full mesh containment, exact signed clearance, contact with all White vinyl vertices, complete finger/hand/body pairs, continuous combined-angle sweep and renderer integration. Neutral guard seam remains uneven and purple inlay boundary needs further local finishing; do not treat it as visually approved. Folded wing interpretation needs human approval. Film references remain external read-only, with no copied pixels in public assets.","",
        "Next local repair option, not performed automatically: clearance-profile pauldron underside/medial lip against chest and combined arm sweep, then make the guard rim a regular manufactured split line. No White or global proportion changes, silent rotation clamp or darker shading workaround.","",
        "Please review final_neutral.png, elbow_L/R_comparison.png, shoulder_L/R_comparison.png, combined_comparison.png and export_verification.png. **REVIEW_REQUIRED remains until user approval and critical exposed contacts are resolved.** No further stage starts automatically."])
    handoff=ROOT/"docs/bagusmax_3d/ARMORED_V1_1_HANDOFF.md"
    handoff.write_text("\n".join(lines)+"\n",encoding="utf-8")
    page='<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bagusmax Armored V1.1 Review</title><style>body{margin:0;background:#202326;color:#f4f4f4;font:16px Arial;line-height:1.5}main{max-width:1200px;margin:auto;padding:24px}h1{font-size:28px}h2{font-size:21px}a{color:#a6dce7}img{display:block;width:100%;height:auto}section{border-top:1px solid #555;margin-top:24px;padding-top:12px}nav{display:flex;gap:20px;flex-wrap:wrap}.fail{color:#ffaaa5}</style><main><h1>BAGUSMAX Armored V1.1</h1><p class="fail">REVIEW_REQUIRED: full shoulder / combined clearance FAIL.</p>'
    page+=f'<p>Khronos: {report["validator"]["numErrors"]} errors / {report["validator"]["numWarnings"]} warnings. Independent GLB: {len(report["independent_evaluations"])} poses; max {report["max_independent_error_mm"]:.6f} mm.</p>'
    page+='<nav><a href="../../../docs/bagusmax_3d/ARMORED_V1_1_HANDOFF.md">Handoff A-L</a><a href="clearance_matrix.json">Clearance matrix</a><a href="acceptance_matrix.json">Acceptance</a><a href="../../../assets/bagusmax/source/bagusmax_armored_v1_1.blend">Blender</a><a href="../../../assets/bagusmax/runtime/bagusmax_armored_v1_1.glb">GLB</a></nav>'
    for title,filename in (("Neutral","final_neutral"),("Elbow L: V1 vs V1.1","elbow_L_comparison"),("Elbow R: V1 vs V1.1","elbow_R_comparison"),("Actual intersections / isolated diagnostic","contact_diagnostic"),("Combined poses / residual contacts","combined_comparison"),("Blender vs independent GLB","export_verification"),("Folded / open wings","wing_states"),("Modular parts","modular_exploded")):
        page+='<section><h2>'+title+'</h2><a href="'+filename+'.png"><img loading="lazy" src="'+filename+'.png" alt="'+title+'"></a></section>'
    (REPORT/"index.html").write_text(page+'</main></html>',encoding="utf-8")
    paths=[GLB,ROOT/"assets/bagusmax/source/bagusmax_armored_v1_1.blend",handoff,Path(__file__),ROOT/"tools/bagusmax_asset_pipeline/build_armored.py"]+list(DATA.glob("*"))+list(REPORT.glob("*"))
    write("deliverable_inventory.json",[{"path":str(p.relative_to(ROOT)).replace("\\","/"),"bytes":p.stat().st_size,"sha256":digest(p)} for p in sorted(set(paths)) if p.is_file() and p.name!="deliverable_inventory.json"])


def review_shoulder_prototype():
    global REPORT
    REPORT=ROOT/"reports/bagusmax_3d/armored_v1_2"
    trials=json.loads((REPORT/"prototype_results.json").read_text())
    search=json.loads((REPORT/"clearance_search.json").read_text())
    diagnostic=json.loads((REPORT/"failure_diagnostics.json").read_text())
    baseline=json.loads((REPORT/"baseline_validation.json").read_text())
    protected=json.loads((REPORT/"preservation_before.json").read_text())
    preservation=all(digest(ROOT/p)==r["sha256"] for p,r in protected.items())
    assert preservation,"An input changed"
    current={p:{"sha256":digest(ROOT/p),"bytes":(ROOT/p).stat().st_size} for p in protected}
    rollback=ROOT/"assets/bagusmax/source/bagusmax_white.blend1"
    if rollback.exists():current[str(rollback.relative_to(ROOT)).replace("\\","/")]={"sha256":digest(rollback),"bytes":rollback.stat().st_size,
        "capture_phase":"diagnostic closeout before any asset save/export; pre-code-edit hash was not captured"}
    write("asset_hashes.json",{"protected":current,"final_candidate_source":None,"final_candidate_glb":None})
    write("preservation_after.json",{p:current[p] for p in protected})
    final=trials[-1]["poses"]
    matrix=[]
    for side in ("L","R"):
        for e in (0,15,30,45,60,75,90,110,120,135,145):
            for b in (0,30,60,90,100,110,120,130):
                found=next((r for r in final if side=="L" and r["plane"]=="side" and r["shoulder_deg"]==e and r["elbow_deg"]==b),None)
                matrix.append({"pose_id":f"grid_{side}_S{e}_E{b}","arm_side":side,"shoulder_angle":e,"elbow_angle":b,
                    "additional_joint_parameters":found["joint_deltas_blender_xyz"] if found else {},"collision_pairs":found["contacts"] if found else [],
                    "result":found["result"] if found else "NOT_TESTED","visible_collision":any(h["classification"]=="EXPOSED_INTERSECTION" for h in found["contacts"]) if found else None,
                    "clearance_or_penetration_metric":None,"method":"AABB then evaluated world-space BVH; sampled external visibility; no penetration-depth measurement",
                    "blender_result":found["result"] if found else "NOT_TESTED","glb_result":"NOT_TESTED",
                    "screenshot_reference":"pivot_inner_lip_"+found["pose_id"]+".png" if found and (REPORT/("pivot_inner_lip_"+found["pose_id"]+".png")).exists() else None})
    for r in final:
        if r["plane"]=="side":continue
        matrix.append({"pose_id":r["pose_id"],"arm_side":"L","shoulder_angle":r["shoulder_deg"] if r["plane"]!="mixed" else None,"elbow_angle":r["elbow_deg"],"additional_joint_parameters":r["joint_deltas_blender_xyz"],
            "collision_pairs":r["contacts"],"result":r["result"],"visible_collision":any(h["classification"]=="EXPOSED_INTERSECTION" for h in r["contacts"]),
            "clearance_or_penetration_metric":None,"method":"evaluated world-space BVH","blender_result":r["result"],"glb_result":"NOT_TESTED","screenshot_reference":None})
    write("pose_matrix.json",{"status":"REVIEW_REQUIRED","stage":"B_LOCAL_PROTOTYPE_FAILED","poses":matrix,"note":"NOT_TESTED grid rows are coverage requirements, not passing results. Mirroring/full export deliberately gated off."})
    write("collision_report.json",{"status":"FAIL","trials":trials,"bounded_clearance_search":search,"failure_diagnostics":diagnostic,
        "first_contact_note":"Neutral intersections start at tested 0 degrees. Other thresholds are sampled bounds, not exact time of first contact; adaptive full-trajectory sweep not performed.",
        "metric_note":"Polygon-pair count is not depth. No pairs were waived to obtain a passing trial."})
    rows=[("AC01","NOT_TESTED","V1.2 elbow regression not run; V1.1 geometry unchanged"),
        ("AC02","FAIL","Left side combined pose retains outer contact"),("AC03","NOT_TESTED","No mirror before successful left prototype"),
        ("AC04","FAIL","Last local profile forward poses retain contact"),("AC05","FAIL","90 degree side elevation fails"),
        ("AC06","LIMIT","12 required combined poses tested on left; right and larger grid NOT_TESTED"),
        ("AC07","NOT_TESTED","No accepted continuous mechanism exists"),("AC08","FAIL","Pivot-only and large discrete slide samples do not establish plausible articulation"),
        ("AC09","NOT_TESTED","Guard finishing deferred until shoulder prototype succeeds"),
        ("AC10","PASS","White V4.1 source/GLB SHA-256 identical"),("AC11","PASS","V1 and V1.1 source/GLB SHA-256 identical"),
        ("AC12","NOT_TESTED","V1.2 not exported; baseline V1.1 validator and 45 independent evaluations rerun"),
        ("AC13","NOT_TESTED","No accepted shoulder transform contract; trial matrices are diagnostic only"),
        ("AC14","NOT_TESTED","V1.2 wings regression not run"),("AC15","PASS","Only dedicated 3D art pipeline and reports touched"),
        ("AC16","LIMIT","Disposable source inspections have zero actions; final V1.2 GLB not created"),
        ("AC17","PASS","Protected destination/default/implicit replacement negative tests passed; no baseline export attempted"),
        ("AC18","LIMIT","Neutral inner-lip contact improves but required raised/combined poses remain rejected")]
    validation={"status":"REVIEW_REQUIRED","delivery_state":"UNRESOLVED_MECHANICAL_BLOCKER; no final V1.2 assets",
        "baseline_actual":baseline,"baseline_preservation":"PASS" if preservation else "FAIL",
        "prototype_evaluations":sum(len(t["poses"]) for t in trials),"search_pose_samples":len(search),"search_trial_count":sum(r["tested_candidates"] for r in search),
        "final_glb_validator":"NOT_TESTED","final_roundtrip":"NOT_TESTED","runtime_fps":"NOT_TESTED","runtime_vram":"NOT_TESTED",
        "criteria":[{"id":i,"status":s,"evidence":e} for i,s,e in rows]}
    write("validation_report.json",validation)
    board("sheet_a_failure_localization",[("failure_"+x["pose_id"],x["pose_id"]+" / isolated colored pair") for x in diagnostic],2,620)
    board("sheet_b_left_prototype",[(v+"_"+pose,label+" / "+pose) for pose in ("side_L_S0_E0","side_L_S90_E0","side_L_S145_E0","combined_L_S90_E130") for v,label in (("baseline","V1.1"),("pivot_inner_lip","Rejected prototype"))],2,620)
    board("slide_search_samples",[("slide_search_"+r["pose_id"],r["pose_id"]+" / "+("cap sample clear" if r["clear_cap_sample_found"] else "FAIL")) for r in search],2,620)
    git=subprocess.run(["git","status","--short","--branch"],cwd=ROOT,capture_output=True,text=True,check=True).stdout
    (REPORT/"git_status.txt").write_text(git)
    lines=["# BAGUSMAX Armored V1.2 Prototype Handoff","","**REVIEW_REQUIRED / UNRESOLVED MECHANICAL BLOCKER**. Stage B did not pass. No final V1.2 .blend or GLB was created. These are rejected engineering prototypes, not a finished candidate.","",
        "## A. Root Cause","","V1.1 pauldron is Chest-parented, pivot x=0.37m, z=1.36m. Its medial/lower rim intersects chest/collar already at neutral. Its existing -0.64*elevation rotation sweeps into the chest/helmet; shifting the pivot alone changes the swept envelope but does not remove intersections. Shoulder liner also crosses upperarm, and the broader audit finds backpack/cap contact.","",
        "Independent of the cap, UpperArm_L shell crosses CHEST_COLLAR at S90/E130 and HELMET_EAR_L at S145/E130. A pauldron-only transform cannot remove those independent contacts. Actual object names, anchors, parent, local/world matrices, axes and contact bounds are in failure_diagnostics.json. Bounds and polygon pairs are not penetration depth.","",
        "## B. Geometry Trials","","Local 4mm-expanded convex chest envelope trims medial pauldron/liner lips; 1.5mm rim bevel. Chest/White/helmet/legs/wings unchanged. Neutral cap/chest contact is removed, but raised poses fail. No guard deletion or global subdivision. Geometry edits exist only in disposable Blender memory.","",
        "## C. Mechanical Trials","","Rebased left pauldron pivot to (0.52,0,1.36)m preserving neutral child world geometry. Evaluated pivot only, then pivot plus lip relief. Bounded search then tested X0..0.12m, Y0..0.08m, Z0..0.16m and three rest-axis rotation fractions (0,+0.25,-0.15). Values are explicit search bounds, not an approved runtime motion. Selection minimizes sampled intersecting polygon pairs, not penetration. Some isolated cap samples clear; no continuous full-arm mapping was obtained.","",
        "## D. Comparison","","![Left prototype](../../reports/bagusmax_3d/armored_v1_2/sheet_b_left_prototype.png)","",
        "## E. Shoulder Results","","| Option | Evaluated left poses | FAIL | LIMIT |","|---|---:|---:|---:|"]
    lines.extend(f"| {t['option']} | {len(t['poses'])} | {sum(r['result']=='FAIL' for r in t['poses'])} | {sum(r['result']=='LIMIT' for r in t['poses'])} |" for t in trials)
    lines.extend(["","## F. Combined Matrix","","All 12 required combined pairs were tested for the left side in each trial. See pose_matrix.json and collision_report.json. Right-side, dense full grid, symmetric/asymmetric full-body and adaptive continuous sweeps are **NOT_TESTED**, deliberately deferred by the Stage B gate.","",
        "## G. Elbow Regression","","V1.1 standalone elbow result remains historical baseline evidence, not a new V1.2 PASS. No elbow geometry was changed or rebuilt. New full elbow regression was not run after failed shoulder prototype.","",
        "## H. Guard Finishing","","NOT_TESTED / deferred. The V1.1 guard remains unchanged. No cosmetic cleanup used to hide failed articulation.","",
        "## I. Wing/Backpack","","New diagnostic reveals cap/backpack contact in V1.1 neutral. Complete V1.2 wing regression not run. No wing or backpack geometry edited.","",
        "## J. Export Validation","",f"V1.1 re-evaluated from actual GLB: Khronos {baseline['validator']['numErrors']} errors / {baseline['validator']['numWarnings']} warnings; {len(baseline['independent_evaluations'])} independent poses, max {max(r['max_position_error_mm'] for r in baseline['independent_evaluations']):.9f}mm. This is not validation of an unexported V1.2.","",
        "Export now requires explicit destination; existing baseline outputs are rejected. Default V1 rebuild is disabled; explicit legacy build rejects an existing source. V1.2-only replacement requires explicit replace and stages to a temporary GLB before validator/hash checks and os.replace. Negative overwrite tests were exercised; successful atomic export branch is **NOT_TESTED** because local mechanical acceptance failed. No final source save was attempted.","",
        "## K. Statistics","",f"Actual V1.1 baseline: {baseline['triangles']:,} triangles; {baseline['vertices_exported']:,} exported vertices; {baseline['mesh_count']} meshes; {baseline['draw_primitives']} primitives; {baseline['material_count']} materials; joints {baseline['joint_counts']}; {baseline['glb_bytes']:,} bytes; {baseline['animation_clips']} clips. V1.2 statistics/load/CPU/FPS/VRAM NOT_TESTED. No claims from an in-memory cap trial are presented as final asset metrics.","",
        "## L. Integrity","","All initially protected hashes unchanged; see asset_hashes.json and preservation_before/after.json. Extra rollback .blend1 hash captured at closeout before any asset save/export, not before code edits; this limitation is explicit. No reference film pixels copied.","",
        "## M. Known Blocker And Next Operation","","Exact reproducible failure: load V1.1, anatomical rest-axis UpperArm_L=(0,-pi/2,0), Forearm_L=(-130deg,0,0), evaluate existing helpers and armor controls. Upperarm/collar and pauldron/arm contacts remain. Bounded cap search still cannot clear S90/E130. This is not proof that no different mechanical design can work.","",
        "Next operation: evaluate a two-piece hinged medial pauldron leaf together with localized proximal upper-arm C-shell clearance. Both remain untested options, not implemented runtime features. Keep neutral silhouette and existing elbow swept relief; prove on left S90/E130 and S145/E130 before mirror. Do not repeat V1 construction or full renders.","",
        "![Failure pairs](../../reports/bagusmax_3d/armored_v1_2/sheet_a_failure_localization.png)","",
        "## N. Git","","```text",git.strip(),"```","","Only build_armored.py / review_armored.py and V1.2 diagnostic reports/docs changed. No stage, commit, merge, branch change or push. No Voice/Data/AgentHarness/CLI/renderer/lighting edits.","",
        "## O. Review Files","","Review index: reports/bagusmax_3d/armored_v1_2/index.html. Prototype source and GLB outputs: NOT_CREATED. CHECKPOINT.md contains exact resume commands. Private film references remain in V1.1 external-reference index; no public stills copied.","",
        "## P. Visual Decision","","User review requested: may the trimmed medial inner-lip silhouette shown in the neutral prototype remain as the visual direction for a future segmented mechanism? This is not approval of the failing raised poses or a production asset."])
    handoff=ROOT/"docs/bagusmax_3d/ARMORED_V1_2_HANDOFF.md";handoff.write_text("\n".join(lines)+"\n",encoding="utf-8")
    acceptance=["# Armored V1.2 Acceptance","","**REVIEW_REQUIRED. Local prototype failed; no final asset.**","","| Criterion | Status | Evidence |","|---|---|---|"]
    acceptance.extend(f"| {i} | {s} | {e} |" for i,s,e in rows)
    (ROOT/"docs/bagusmax_3d/ARMORED_V1_2_ACCEPTANCE_REPORT.md").write_text("\n".join(acceptance)+"\n",encoding="utf-8")
    checkpoint=["# Armored V1.2 Checkpoint","","Branch: feat/bagusmax-3d-art","Current files: build_armored.py, review_armored.py; V1.2 report folder and two requested V1.2 docs. Input remains original V1.1; no candidate .blend/GLB.","Baseline hashes: preservation_before.json and asset_hashes.json.","Last passing test: actual V1.1 Khronos 0/0 and 45 independent pose evaluations; negative destination safety tests.","Last failing test: left S90/E130 local pivot/lip profile and bounded pauldron search.","Unresolved pairs: ARMOR_PAULDRON_L vs ARMOR_UPPERARM_L / FOREARM_L; ARMOR_UPPERARM_L vs ARMOR_CHEST_COLLAR; at S145/E130 UpperArm vs HELMET_EAR_L.","Next operation: prototype segmented medial cap leaf plus proximal upperarm clearance on one side, then test retained fail poses. No full rebuild.","","```powershell"]
    checkpoint.extend(["Set-Location E:\\Projects\\OpenBagus-3D","& 'C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe' --background --python tools/bagusmax_asset_pipeline/build_armored.py -- --prototype-shoulder","& 'C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe' --background --python tools/bagusmax_asset_pipeline/build_armored.py -- --solve-shoulder","& 'C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe' --background --python tools/bagusmax_asset_pipeline/build_armored.py -- --diagnose-shoulder","& 'E:\\Projects\\OpenBagus\\.venv\\Scripts\\python.exe' -B tools/bagusmax_asset_pipeline/review_armored.py --revision 1.2","```"])
    (REPORT/"CHECKPOINT.md").write_text("\n".join(checkpoint)+"\n",encoding="utf-8")
    page='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Armored V1.2 Blocker Review</title><style>body{background:#24272a;color:#eee;font:16px Arial;line-height:1.5;margin:24px auto;max-width:1200px;padding:16px}h1{font-size:28px}h2{font-size:21px}a{color:#9de0ed}img{width:100%;height:auto}.fail{color:#ffb0a5}section{border-top:1px solid #777;margin-top:24px}</style><h1>BAGUSMAX Armored V1.2 Prototype</h1><p class="fail">REVIEW_REQUIRED / LOCAL MECHANICAL FAILURE. No final V1.2 Blender or GLB file created.</p><p>Neutral lip contact improves. Raised/combined poses still fail. No right-side mirror, guard finishing or full export validation claimed.</p><p><a href="../../../docs/bagusmax_3d/ARMORED_V1_2_HANDOFF.md">Handoff A-P</a> | <a href="../../../docs/bagusmax_3d/ARMORED_V1_2_ACCEPTANCE_REPORT.md">Acceptance</a> | <a href="pose_matrix.json">Pose matrix</a> | <a href="collision_report.json">Collision data</a> | <a href="CHECKPOINT.md">Resume checkpoint</a></p>'
    for title,name in (("Actual failed pairs / isolated colored geometry","sheet_a_failure_localization"),("V1.1 vs rejected local prototype","sheet_b_left_prototype"),("Discrete cap search / not a safe motion contract","slide_search_samples")):
        page+='<section><h2>'+title+'</h2><img src="'+name+'.png" alt="'+title+'"></section>'
    page+='<p><a href="../armored_v1_1/private_reference_review.html">Private existing film-reference index (external originals)</a></p>'
    (REPORT/"index.html").write_text(page,encoding="utf-8")
    files=list(REPORT.glob("*"))+[handoff,ROOT/"docs/bagusmax_3d/ARMORED_V1_2_ACCEPTANCE_REPORT.md",Path(__file__),ROOT/"tools/bagusmax_asset_pipeline/build_armored.py"]
    write("deliverable_inventory.json",[{"path":str(p.relative_to(ROOT)).replace("\\","/"),"bytes":p.stat().st_size,"sha256":digest(p)} for p in sorted(set(files)) if p.is_file() and p.name!="deliverable_inventory.json"])
    print(json.dumps({"status":"REVIEW_REQUIRED","final_assets":"NOT_CREATED","prototype_evaluations":validation["prototype_evaluations"],"sampled_slide_trials":validation["search_trial_count"],"preservation":preservation},indent=2))


def main():
    if "--revision" in sys.argv:
        version=sys.argv[sys.argv.index("--revision")+1]
        if version=="1.2":review_shoulder_prototype()
        else:
            assert version=="1.1"
            review_revision()
        return
    started=time.perf_counter();asset=GLBSkin(GLB);load=(time.perf_counter()-started)*1000
    report=stats(asset);report["numpy_glb_parse_ms"]=load
    report["asset_sha256"]=digest(GLB)
    report["validator"]=validate()
    report["independent_evaluations"]=independent(asset)
    samples=[]
    tests=json.loads((REPORT/"blender_pose_matrices.json").read_text())
    for test in (tests[0],next(t for t in tests if t["name"]=="shoulder_L_145"),next(t for t in tests if t["name"]=="combined")):
        for _ in range(5):
            start=time.perf_counter()
            matrices=evaluate(asset,test)
            count=0
            for i,node,p in primitives(asset):
                if "skin" in node:continue
                points=asset.accessor(p["attributes"]["POSITION"])
                transformed=points@matrices[i,:3,:3].T+matrices[i,:3,3]
                assert np.isfinite(transformed).all()
                count+=len(points)
            asset.evaluate(test["joint_deltas_blender_xyz"])
            samples.append({"pose":test["name"],"rigid_vertices":count,"cpu_ms":(time.perf_counter()-start)*1000})
    report["cpu_geometry_evaluation"]={"scope":"NumPy CPU on execution host; buffers decoded each evaluation; not renderer FPS or GPU cost",
        "samples":samples,"median_ms":float(np.median([s["cpu_ms"] for s in samples]))}
    rig_check(asset)
    quality_path=GLB.with_name("bagusmax_armored_v1_quality.glb")
    quality=stats(GLBSkin(quality_path))
    quality["validator"]=validate(quality_path,"khronos_validator_quality.json")
    write("quality_statistics.json",quality)
    report["status"]="REVIEW_REQUIRED"
    write("validation_report.json",report)
    references()
    board("comparison_sheet",[("armored_front","Front / folded default"),("armored_three_quarter","Three-quarter"),("armored_left","Left"),("armored_back","Back"),("wings_deployed","Wings deployed"),("mechanical_hands","Mechanical hand")])
    board("assembly_preview",[(f"assembly_{p:03}",f"Assembly progress {p}%") for p in (0,20,40,70,100)])
    board("pose_validation",[(n,n.replace("_"," ")) for n in ("shoulder_L_90","shoulder_L_145","elbow_L_130","elbow_R_130","forward_fist","leg_step","head_turn","point","combined")])
    board("white_to_armored",[("white_before","White V4.1 / unchanged original"),("armored_three_quarter","Armored / same camera and studio")],2,650)
    board("export_verification",[("blender_export_pose","Blender evaluated desktop geometry"),("independent_glb_export_pose","GLB independent matrices and positions"),("neutral_glb_reimport","GLB neutral reimport")])
    for side in ("L","R"):
        board(f"shoulder_{side}_continuity",[(f"shoulder_{side}_{a}_closeup",f"Shoulder {side}: {a} deg") for a in (0,30,60,90,120,145)])
        board(f"elbow_{side}_articulation",[(f"elbow_{side}_{a}_closeup",f"Elbow {side}: {a} deg") for a in (0,45,90,110,130)])
    write("asset_hashes.json",{str(p.relative_to(ROOT)).replace("\\","/"):{"sha256":digest(p),"bytes":p.stat().st_size}
        for p in [GLB,quality_path,ROOT/"assets/bagusmax/source/bagusmax_armored_v1.blend"]})
    acceptance(report,quality)
    print(json.dumps({k:v for k,v in report.items() if k!="independent_evaluations"},indent=2))


def acceptance(report,quality):
    collisions=json.loads((REPORT/"collision_samples.json").read_text())
    rig=json.loads((REPORT/"rig_compatibility.json").read_text())
    reimport=json.loads((REPORT/"neutral_reimport.json").read_text())
    deterministic=json.loads((REPORT/"assembly_determinism.json").read_text())
    protected=json.loads((REPORT/"preservation_before.json").read_text())
    preservation=all((ROOT/p).is_file() and digest(ROOT/p)==row["sha256"] for p,row in protected.items())
    write("preservation_after.json",{p:{"sha256":digest(ROOT/p),"bytes":(ROOT/p).stat().st_size} for p in protected})
    independent_pass=all(r["status"]=="PASS" for r in report["independent_evaluations"])
    tests=[("T01","PASS" if preservation else "FAIL","Original White, rollback, legacy Armored dan lighting spec SHA-256 tidak berubah"),
        ("T02","PASS","124 armor parts dan 51 controls dapat dialamatkan melalui actual exported node IDs"),
        ("T03","LIMIT","Silhouette 4 arah tersedia; proporsi kepala/leg mengikuti White dan fidelity film belum disetujui user"),
        ("T04","LIMIT","Helmet putih/merah terbaca; head turn/nod diuji, full helmet/face contact certification belum lengkap"),
        ("T05","PASS","Chest/collar/flank berketebalan dan 4 front/rear segmented purple bands tersedia"),
        ("T06","LIMIT","Shoulder 0/30/60/90/120/145 kiri-kanan bersih untuk selected critical pairs; bukan full swept self-collision certification"),
        ("T07","LIMIT","Elbow 0/45/90 bersih; 110/120/130 FAIL upperarm/forearm overlap. Deep flexion belum usable"),
        ("T08","LIMIT","Relaxed/fist/point dan existing finger anchor tests tersedia; seluruh contact/holding poses belum diuji"),
        ("T09","LIMIT","Neutral dan satu leg-step sample tersedia; full hip/knee/ankle envelope belum disertifikasi"),
        ("T10","PASS","Default folded wings dan hinges bertahan setelah export/reimport; desain folded merupakan interpretasi"),
        ("T11","PASS","Deployed dan partial wings terhubung secara rigid pada dua hinge per sisi; selected critical pairs tidak beririsan"),
        ("T12",deterministic["status"],"Actual start/target matrices; progress berulang menghasilkan transforms sama"),
        ("T13","LIMIT","Reverse transforms dan neutral reset exact; coverage occlusion/pop sepanjang motion masih NOT_TESTED"),
        ("T14","PASS" if independent_pass and reimport["status"]=="PASS" else "FAIL","Actual GLB hierarchy, independent transformed geometry dan neutral reimport"),
        ("T15","PASS" if report["material_count"]==7 else "FAIL","7 material PBR diekspor; tidak ada texture atau permanent flame"),
        ("T16",rig["status"],"32 existing White joints dan global rest matrices cocok"),
        ("T17","PASS","Matched neutral/details/assembly/pose/export review images tersedia, tidak berarti user approval"),
        ("T18","LIMIT","Triangle/vertex/material/node/buffer/CPU metrics diukur; runtime FPS/VRAM NOT_TESTED"),
        ("T19","PASS" if preservation else "FAIL","Hanya additive 3D art changes; no runtime/Voice/Data/lighting edits"),
        ("T20","PASS","Manifest per-node, articulation formulas, visibility contract dan event specification tersedia; controller tidak dibuat")]
    write("acceptance_matrix.json",{"status":"REVIEW_REQUIRED","asset_sha256":report["asset_sha256"],
        "tests":[{"id":t,"status":s,"evidence":e} for t,s,e in tests],
        "pose_tests":[{"pose":r["pose"],"status":"FAIL" if r["surface_intersections"] else "PASS",
                       "scope":r["scope"],"surface_intersections":r["surface_intersections"]} for r in collisions]})
    top=json.loads((REPORT/"source_geometry_audit.json").read_text())
    profile=json.loads((REPORT/"quality_desktop_profile.json").read_text())
    maxerror=max(x["max_position_error_mm"] for x in report["independent_evaluations"])
    lines=["# BAGUSMAX Armored V1 Acceptance Report","","Status: **REVIEW_REQUIRED / REVISION_REQUIRED for deep elbow clearance**. Tidak production-ready. STOP untuk visual review; tidak lanjut runtime, animation atau lighting.","",
        "## A. Baseline Preserved","",f"White/rollback/legacy/lighting protected files: {'PASS' if preservation else 'FAIL'}. Lihat preservation_before.json / preservation_after.json.","",
        "White V4.1 source SHA-256: `"+protected['assets/bagusmax/source/bagusmax_white_anatomy_v4_1.blend']['sha256']+"`.",
        "White V4.1 GLB SHA-256: `"+protected['assets/bagusmax/runtime/bagusmax_white_anatomy_v4_1.glb']['sha256']+"`.","",
        "## B. New Armor Construction","","124 rigid armor geometry parts, 51 assembly/mechanical controls, existing 32-joint rig. Chest/collar/flanks, helmet, 4 abdominal bands, pauldrons, medial-open C-shell upperarms, elbow bearings, gauntlets/inlays, gloves, pelvis/legs/boots, rear pack dan two-hinge wings. Modular geometry tidak di-skin menjadi rubber.","",
        "## C. Visual Reference Fidelity","","Interpretasi film-inspired, bukan measured film reconstruction. Semua 15 original references diindeks read-only. Folded wings LOW confidence. White skeleton/head constraints menyebabkan proporsi berbeda dari sebagian toy/flight references. Tidak ada pixel film dalam GLB/source/textures atau PNG model review.","",
        "![Neutral review](../../reports/bagusmax_3d/armored_v1/comparison_sheet.png)","",
        "## D. Modular Assembly","","Part names, pivots, bounds, material IDs, parents, local bind, start/target dan visibility/animation/LOD groups berasal dari actual GLB. Offset diterapkan pada assembly root saja; child parts mewarisinya.","",
        "## E. Transformation Concept","","Curved deterministic 3.4-second phase specification dan disposable static previews. Repeated .40/.70/.40 serta neutral return PASS. White coverage dan clearance data tersedia, tetapi continuous path collision/pop-free occlusion belum lulus integrasi.","",
        "![Assembly](../../reports/bagusmax_3d/armored_v1/assembly_preview.png)","",
        "## F. Rig And Articulation","",f"{len(report['independent_evaluations'])} independent GLB rigid-transform/vertex probe evaluations: {'PASS' if independent_pass else 'FAIL'}; maximum error {maxerror:.6f} mm. Original 32-joint rest comparison: {rig['status']}. Neutral reimport: {reimport['status']}.","",
        "Shoulder samples kiri/kanan sampai 145 bersih pada selected pairs. Elbow 0/45/90 bersih; **110/120/130 FAIL** upperarm/forearm surface overlap. Jangan mengintegrasikan deep elbow atau menyebutnya supported. Individual hand contact, full lower-body envelope dan seluruh swept pairs belum disertifikasi.","",
        "Independent render memakai geometry/matrices dari GLB pada camera/studio sama. Diagnostic baked mesh normals dihitung ulang oleh Blender; parity shader OpenGL dan GPU normal pipeline aplikasi **NOT_TESTED**.","",
        "![Export verification](../../reports/bagusmax_3d/armored_v1/export_verification.png)","",
        "## G. Runtime Integration Contract","","Lihat ARMORED_V1_ASSEMBLY_CONTRACT.md dan ARMORED_V1_RUNTIME_HANDOFF.md. Canonical assets berada di assets/bagusmax/armor/. Tidak ada IPC handler, controller, companion renderer, ASR/TTS, voice atau data-provider edit. GLB menyertakan head/face; hindari duplicate face saat memuat White bersama armor.","",
        "## H. Performance","","| Measurement | DESKTOP_RUNTIME | QUALITY |","|---|---:|---:|"]
    for label,key in (("Triangles","triangles"),("Exported vertices","vertices_exported"),("Meshes / draw primitives","draw_primitives"),("Materials","material_count"),("GLB bytes","glb_bytes"),("Geometry buffer bytes","geometry_buffer_bytes"),("Animation clips","animation_clips"),("Morph targets in armor GLB","morph_targets")):
        lines.append(f"| {label} | {report[key]:,} | {quality[key]:,} |")
    issues=report["validator"]
    lines.extend(["",f"Khronos desktop: {issues['numErrors']} errors / {issues['numWarnings']} warnings / {issues['numInfos']} infos. Quality: {quality['validator']['numErrors']} errors / {quality['validator']['numWarnings']} warnings. Texture count/memory: 0. Max skin influences on face: 1; armor rigid, 0 skin influences. Source includes original White corrective keys plus default-zero clearance on its private copy; these are not armor GLB morphs.","",
        f"Sampled quality-to-desktop surface deviation max {max(x['max_sampled_surface_error_mm'] for x in profile['parts']):.4f} mm, not a Hausdorff bound. Median NumPy CPU full geometry evaluation {report['cpu_geometry_evaluation']['median_ms']:.3f} ms on execution host; includes decoded buffers/array allocation, **not runtime FPS**. GLB parse {report['numpy_glb_parse_ms']:.3f} ms, not GPU upload.","",
        f"Geometry audit: {sum(x['nonmanifold_edges'] for x in top)} nonmanifold edges across armor parts; {report['degenerate_triangles']} degenerate exported triangles. Runtime FPS, VRAM/RAM and OpenGL behavior **NOT_TESTED**. 128 draw primitives remain a performance risk pending integration.","",
        "## I. Known Imperfections","","- Deep elbow plate intersection remains. Limit candidate to tested 0/45/90 samples until revised; no continuous safe-envelope guarantee.",
        "- Shape/fidelity, helmet scale, C-shell medial treatment, hand contact and folded wing design need visual approval.",
        "- White compression/index masks are assembly data, not a completed occlusion solution. Motion pop/cancel/hidden-window behavior require Antigravity integration tests.",
        "- Selected critical BVH pairs are not exhaustive. One leg-step and head samples do not certify every hip/knee/neck pose.",
        "- No public redistribution rights cleared for the film-inspired character or original film references.","",
        "## Acceptance Matrix","","| Test | Status | Evidence / Limitation |","|---|---|---|"])
    lines.extend(f"| {t} | {s} | {e} |" for t,s,e in tests)
    lines.extend(["","## J. Git And Exact Files","","Branch `feat/bagusmax-3d-art`; work remains untracked/uncommitted. No stage, commit, merge or push. Previous White and legacy Armored candidates remain unchanged. New canonical implementation: `tools/bagusmax_asset_pipeline/build_armored.py` and `review_armored.py`. New source/runtime/armor data and explicit user-requested art docs/reports only. Exact generated files are listed in `reports/bagusmax_3d/armored_v1/deliverable_inventory.json`.","",
        "## K. Visual Approval","","Review neutral four directions, helmet/hand details, folded/deployed wings and matched export sheet. Mohon tentukan persetujuan arah visual atau koreksi proporsi. **Deep elbow limitation tetap memerlukan revisi meskipun arah visual disetujui.** Tidak ada tahap runtime atau lighting yang dimulai."])
    (ROOT/"docs/bagusmax_3d/ARMORED_V1_ACCEPTANCE_REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    paths=list((DATA).glob("*"))+list(REPORT.glob("*"))
    paths += [GLB,GLB.with_name("bagusmax_armored_v1_quality.glb"),ROOT/"assets/bagusmax/source/bagusmax_armored_v1.blend"]
    paths += list((ROOT/"docs/bagusmax_3d").glob("ARMORED_V1_*.md"))
    paths += [ROOT/"tools/bagusmax_asset_pipeline/build_armored.py",Path(__file__)]
    write("deliverable_inventory.json",[{"path":str(p.relative_to(ROOT)).replace("\\","/"),"bytes":p.stat().st_size,"sha256":digest(p)} for p in sorted(set(paths)) if p.is_file() and p.name!="deliverable_inventory.json"])


if __name__=="__main__":main()
