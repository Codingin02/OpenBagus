"""Assemble anatomical comparison sheets and validate authored derivatives."""

import hashlib
import json
import struct
import subprocess
import sys

from review_white import ROOT, REPORTS, TEMP, board, validate_glb


def review_attachment():
    from gltf_skinning import GLBSkin
    from PIL import Image
    import numpy as np
    folder = REPORTS/"white_v4_1"
    def item(label,name):
        return label,folder/f"{name}.png"
    def sheet(name,entries,columns=2,size=(650,710)):
        board(f"white_v4_1/{name}.png",entries,columns,cell_size=size)
    for side in ("L","R"):
        sheet(f"shoulder_{'left' if side=='L' else 'right'}_continuity_sheet",
            [item(f"{version} {side} {angle} degrees",f"{prefix}_shoulder_{side}_{angle:03}")
             for angle in (0,30,60,90,120,145,160) for version,prefix in (("V4","v4"),("V4.1","v4_1"))])
        sheet(f"shoulder_{side}_incremental_sequence",
            [item(f"{version} {side} {angle} degrees",f"{prefix}_sequence_{side}_{angle:03}")
             for angle in range(0,161,5) for version,prefix in (("V4","v4"),("V4.1","v4_1"))],6,(360,410))
    sheet("shoulder_attachment_closeup",[item(f"{version} {angle} degrees",f"{prefix}_shoulder_L_{angle:03}")
        for angle in (0,90,145) for version,prefix in (("V4","v4"),("V4.1","v4_1"))])
    sheet("shoulder_side_silhouette",[item(f"{version} {angle} {view}",f"{prefix}_attachment_{angle}_{view}")
        for view in ("front","side","back","quarter") for angle in (0,145)
        for version,prefix in (("V4","v4"),("V4.1","v4_1"))],4)
    sheet("shoulder_weight_diagnostic",[item(f"{version} {kind}",f"{prefix}_diagnostic_{kind}")
        for kind in ("Chest","ShoulderVolume_L","UpperArm_L","NORMAL")
        for version,prefix in (("V4","v4"),("V4.1","v4_1"))])
    sheet("shoulder_wireframe_comparison",[item(version,f"{prefix}_wireframe")
        for version,prefix in (("V4","v4"),("V4.1","v4_1"))])
    sheet("palm_inward_comparison",[item(f"{version} {view}",f"{prefix}_hands_{view}")
        for view in ("front","left","right","back","three_quarter")
        for version,prefix in (("V4","v4"),("V4.1","v4_1"))])
    sheet("elbow_deformation_comparison",[item(f"{version} {side} {angle} degrees",f"{prefix}_elbow_{side}_{angle:03}")
        for side in ("L","R") for angle in (90,130)
        for version,prefix in (("V4","v4"),("V4.1","v4_1"))])
    sheet("elbow_panel_integrity",[item(f"{version} {side} {angle} degrees",f"{prefix}_panel_{side}_{angle}")
        for side in ("L","R") for angle in (0,45,90,110,130,145)
        for version,prefix in (("V4","v4"),("V4.1","v4_1"))],4,(500,560))
    sheet("shoulder_deformation_glb_validation",[item(f"{version} {side} {angle}",f"{prefix}_shoulder_{side}_{angle:03}")
        for side in ("L","R") for angle in (0,60,90,120,145)
        for version,prefix in (("Blender","source"),("GLB independent LBS","glb"))])
    names = [f"elbow_{side}_{angle:03}" for side in ("L","R") for angle in (0,45,90,110,130)]
    names += ["combined_L","combined_R","C2","C5","F1_point"]
    sheet("morph_verification",[item(f"{version} {name}",f"{prefix}_{name}") for name in names
        for version,prefix in (("Blender","source"),("GLB independent LBS","glb"))])
    sheet("forward_corrective_justification",[item("V4 baseline C4","v4_C4"),
        item("V4.1 without forward corrective","C4_without_forward_corrective"),item("V4.1 with forward corrective","v4_1_C4")],3)
    sheet("final_neutral_character",[item(f"V4.1 {view}",f"v4_1_neutral_{view}")
        for view in ("front","left","back","three_quarter")],4)
    references = (("Neutral shoulder / hanging arms","d82dc637-53e9-432c-a3cb-e3cdb5c85730","v4_1_neutral_front"),
                  ("Soft arm attachment / elbow volume","75bf4c89-72af-429c-9226-13c5b7f5a664","v4_1_panel_L_130"),
                  ("Wrist / palm / thumb silhouette","da4cbc5f-a900-4bd7-a34d-02e69620a4d0","v4_1_hands_left"),
                  ("Side shoulder contour","208c48a1-64d8-45da-903d-2f39c37d50bf","v4_1_neutral_left"))
    rows = []
    for label,identifier,model in references:
        reference = TEMP/f"codex-clipboard-{identifier}.jpg"
        assert reference.exists(),reference
        rows.append(f'<h2>{label}</h2><section><figure><img src="{reference.as_uri()}"><figcaption>Original supplied film reference, external file</figcaption></figure><figure><img src="{model}.png"><figcaption>V4.1 diagnostic studio; not a matched film camera</figcaption></figure></section>')
    html = '<!doctype html><meta charset="utf-8"><title>Private Film Reference Comparison</title><style>body{font:16px sans-serif;background:#e9ecef;color:#20262c;margin:24px}section{display:grid;grid-template-columns:1fr 1fr;gap:20px}figure{margin:0}img{width:100%;height:600px;object-fit:contain;background:#222}h2{font-size:20px;margin-top:32px}</style><h1>Private Film Reference Comparison</h1><p>Film files are linked from their original local locations, never copied or embedded. Not for publication. Pose and camera differ from film; this is qualitative shape evidence only.</p>'+'\n'.join(rows)
    (folder/"film_reference_comparison.html").write_text(html,encoding="utf-8")
    sheet("approval_comparison",[item(f"{version} {label}",f"{prefix}_{name}")
        for label,name in (("Neutral","neutral_front"),("Shoulder 90","shoulder_L_090"),
                           ("Shoulder 145","shoulder_L_145"),("Hand rest","hands_front"),("Elbow 130","elbow_L_130"))
        for version,prefix in (("V4","v4"),("V4.1","v4_1"))],4,(540,620))
    for view in ("front","left","right","back","three_quarter"):
        Image.open(folder/f"v4_1_hands_{view}.png").save(folder/f"neutral_hands_{view}.png")
    for view in ("front","left","back"):
        first = np.array(Image.open(folder/f"v4_mask_{view}.png").convert("RGBA"))[:,:,3]>.5*255
        second = np.array(Image.open(folder/f"v4_1_mask_{view}.png").convert("RGBA"))[:,:,3]>.5*255
        overlay = np.zeros((*first.shape,3),dtype=np.uint8)+25
        overlay[first] = (70,190,225)
        overlay[second] = (230,105,80)
        overlay[first&second] = (220,225,225)
        Image.fromarray(overlay).save(folder/f"silhouette_overlay_{view}.png")
    sheet("full_body_silhouette_overlay",[item(f"{view}: V4 cyan, V4.1 red",f"silhouette_overlay_{view}")
        for view in ("front","left","back")],3)
    glb = ROOT/"assets/bagusmax/runtime/bagusmax_white_anatomy_v4_1.glb"
    validate_glb(glb,expected=set(),output=folder/"glb_structure.json",joint_count=32)
    exported = GLBSkin(glb)
    stats = json.loads((folder/"glb_structure.json").read_text())
    stats.pop("estimated_vertex_index_memory_mb",None)
    stats.update(morph_target_count=sum(len(p["targets"]) for p in exported.primitives),
        max_vertex_influences=max(int((p["weights"]>1e-7).sum(1).max()) for p in exported.primitives),
        draw_primitives=len(exported.primitives))
    (folder/"glb_structure.json").write_text(json.dumps(stats,indent=2),encoding="utf-8")
    module = TEMP/"openbagus-gltf-validator/node_modules/gltf-validator"
    script = "const fs=require('fs'),v=require(process.argv[1]); v.validateBytes(new Uint8Array(fs.readFileSync(process.argv[2])),{uri:process.argv[2]}).then(r=>{fs.writeFileSync(process.argv[3],JSON.stringify(r,null,2));console.log(JSON.stringify(r.issues));if(r.issues.numErrors||r.issues.numWarnings)process.exitCode=1;});"
    for path,name in ((ROOT/"assets/bagusmax/runtime/bagusmax_white_anatomy_v4.glb","baseline_khronos.json"),(glb,"khronos_validation.json")):
        subprocess.run(["D:/Program Files/nodejs/node.exe","-e",script,str(module),str(path),str(folder/name)],check=True)
    audit = json.loads((folder/"asset_audit.json").read_text())
    hashes = {"preserved":[],"created":{}}
    for path,before in audit["preserved_sha256"].items():
        after = hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
        assert before==after,path
        hashes["preserved"].append({"path":path,"before":before,"after":after,"unchanged":True})
    for path,expected in audit["created_sha256"].items():
        actual = hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
        assert expected==actual,path
        hashes["created"][path] = actual
    (folder/"asset_hashes.json").write_text(json.dumps(hashes,indent=2),encoding="utf-8")
    print("V4_1_REVIEW_COMPLETE",json.dumps(stats),flush=True)


def review_deformation():
    from gltf_skinning import GLBSkin
    folder = REPORTS / "white_v4"
    def item(label, name):
        return label, folder / f"{name}.png"
    def sheet(name, entries, columns=3):
        board(f"white_v4/{name}.png", entries, columns, cell_size=(540, 620))
    entries = []
    for view in ("front", "left", "right", "back", "three_quarter", "rear_quarter"):
        entries.extend(item(f"{label}: {view}", f"{prefix}_{view}") for label, prefix in
                       (("Detailed", "detailed"), ("V3", "v3"), ("V4", "after")))
    sheet("sheet_A_anatomy", entries)
    for side in ("L", "R"):
        entries = []
        for angle, view in ((0, "front"), (0, "back"), (0, "outside"), (0, "inside"),
                            (0, "quarter"), (60, "outside"), (130, "outside"), (130, "inside"), (130, "back")):
            entries.extend(item(f"{label}: {side} {angle} {view}", f"{prefix}_panel_{side}_{angle:03}_{view}")
                           for label, prefix in (("Detailed", "detailed"), ("V3", "v3"), ("V4", "v4")))
        sheet(f"sheet_B_elbow_{side}_isolated", entries)
    entries = []
    for view in ("torso_left", "torso_right", "waist_front", "waist_side", "hip_flex"):
        after = "after" if view.startswith("torso_") else "v4"
        entries.extend((item(f"V3: {view}", f"v3_{view}"), item(f"V4: {view}", f"{after}_{view}")))
    sheet("sheet_C_torso_waist", entries, 2)
    for kind, angles, letter in (("shoulder", (0, 30, 60, 90, 120, 145, 160), "D"),
                                ("elbow", (0, 30, 60, 90, 110, 130, 145), "E")):
        entries = []
        for angle in angles:
            for side in ("L", "R"):
                name = f"{kind}_{side}_{angle:03}"
                entries.extend((item(f"V3: {side} {angle}", f"v3_{name}"), item(f"V4: {side} {angle}", name)))
        sheet(f"sheet_{letter}_{kind}_progression", entries, 4)
    entries = []
    for side in ("L", "R"):
        for pose in (("neutral", "point", "closed", "hold") if side == "L" else ("neutral", "closed", "hold")):
            entries.extend((item(f"V3 {side}: {pose}", f"v3_hand_{side}_{pose}"),
                            item(f"V4 {side}: {pose}", f"v4_hand_{side}_{pose}")))
    sheet("sheet_F_hands", entries, 4)
    sheet("sheet_G_full_body", [item(f"V4: {v}", f"after_{v}") for v in
                               ("front", "left", "back", "three_quarter")], 4)
    names = ("shoulder_L_120", "shoulder_L_145", "shoulder_R_145", "elbow_L_110", "elbow_L_130", "elbow_R_130")
    sheet("sheet_H_export", [item(f"{label}: {name}", f"{prefix}_{name}") for name in names
                            for label, prefix in (("Blender", "source"), ("GLB NumPy", "glb"))], 2)
    sheet("sheet_H_residuals", [item(f"{label}: {name}", f"{prefix}_{name}") for name in ("C2", "C5", "F1_point")
                               for label, prefix in (("Blender", "source"), ("GLB NumPy", "glb"))], 2)
    entries = []
    for label, before, after in (("Elbow outside", "v3_panel_L_000_outside", "v4_panel_L_000_outside"),
                                  ("Torso side", "v3_torso_left", "after_torso_left"),
                                  ("Shoulder 145", "v3_shoulder_L_145", "shoulder_L_145"),
                                  ("Elbow 130", "v3_elbow_L_130", "elbow_L_130"),
                                  ("Hand / wrist", "v3_hand_L_neutral", "v4_hand_L_neutral"),
                                  ("Full body", "v3_front", "after_front")):
        entries.extend((item(f"V3: {label}", before), item(f"V4: {label}", after)))
    sheet("approval_comparison", entries, 4)
    glb = ROOT / "assets/bagusmax/runtime/bagusmax_white_anatomy_v4.glb"
    target = folder / "glb_structure.json"
    validate_glb(glb, expected=set(), output=target, joint_count=32)
    exported = GLBSkin(glb)
    doc = exported.doc
    report = json.loads(target.read_text(encoding="utf-8"))
    report.pop("estimated_vertex_index_memory_mb", None)
    def payload(accessors):
        indices = set()
        for i in accessors:
            accessor = doc["accessors"][i]
            if "bufferView" in accessor:
                indices.add(accessor["bufferView"])
            if "sparse" in accessor:
                indices.update(accessor["sparse"][k]["bufferView"] for k in ("indices", "values"))
        return sum(doc["bufferViews"][i]["byteLength"] for i in indices)
    base, morph, targets = [], [], []
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            base.extend(primitive["attributes"].values())
            base.append(primitive["indices"])
            for t in primitive.get("targets", []):
                assert {"POSITION", "NORMAL"} <= t.keys()
                morph.extend(t.values())
        if "weights" in mesh:
            assert all(w == 0 for w in mesh["weights"])
        targets.extend({"mesh": mesh["name"], "name": name} for name in mesh.get("extras", {}).get("targetNames", []))
    report.update(draw_primitives=sum(len(m["primitives"]) for m in doc["meshes"]), morph_targets=targets,
                  morph_target_count=len(targets), base_geometry_buffer_bytes=payload(base), morph_buffer_bytes=payload(morph),
                  max_vertex_influences=max(int((p["weights"] > 1e-5).sum(axis=1).max()) for p in exported.primitives))
    report["not_tested"].extend(["Runtime FPS", "Runtime VRAM", "GPU skinning time"])
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    audit = json.loads((folder / "asset_audit.json").read_text(encoding="utf-8"))
    hashes = {"preserved": [], "created": {}}
    for path, before in audit["preserved_sha256"].items():
        path = ROOT / path
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        assert after == before
        hashes["preserved"].append({"path": str(path.relative_to(ROOT)), "before": before, "after": after, "unchanged": True})
    for path in (ROOT / "assets/bagusmax/source/bagusmax_white_anatomy_v4.blend", glb):
        hashes["created"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (folder / "asset_hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def main():
    if "--attachment" in sys.argv:
        review_attachment()
        return
    if "--v4" in sys.argv:
        review_deformation()
        return
    folder = REPORTS / "white_v3"
    comparisons = (
        "front", "left", "right", "three_quarter", "elbow_left", "elbow_right",
        "torso_left", "torso_right", "S5_L", "E3_L", "E3_R", "C2", "C4",
        "legs", "hand", "C9", "rear_quarter",
    )
    for view in comparisons:
        board(f"white_v3/compare_{view}.png", [
            (f"Detailed: {view}", folder / f"before_{view}.png"),
            (f"V3: {view}", folder / f"after_{view}.png"),
        ], columns=2)
    overview = []
    for view in ("elbow_left", "elbow_right", "torso_left", "torso_right", "S5_L", "E3_L", "legs", "hand"):
        overview.extend([(f"Detailed: {view}", folder / f"before_{view}.png"),
                         (f"V3: {view}", folder / f"after_{view}.png")])
    board("white_v3/anatomy_overview.png", overview, columns=4)
    for name, poses in (
        ("shoulders", [f"S{i}_{side}" for side in ("L", "R") for i in range(1, 7)]),
        ("elbows", [f"E{i}_{side}" for side in ("L", "R") for i in range(5)]),
        ("combined", [f"C{i}" for i in range(1, 11)] + ["F1_point"]),
        ("panels", ["elbow_left", "elbow_right", "E3_L_panel", "E3_R_panel", "torso_left", "torso_right"]),
    ):
        board(f"white_v3/poses_{name}.png", [(p, folder / f"after_{p}.png") for p in poses], columns=4 if name == "shoulders" else 3)
    board("white_v3/torso_variants.png", [(f"{side}: {variant}", folder / f"{label}_torso_{side}.png")
          for side in ("left", "right") for variant,label in (("A material", "after"), ("B relief +1.5 mm", "variant_b"))], columns=2)
    board("white_v3/finger_controls.png", [("Rest hand", folder / "after_hand.png"),
          ("Independent finger test", folder / "after_F1_hand.png")], columns=2)
    refs = [
        ("Film: side hug", "75bf4c89-72af-429c-9226-13c5b7f5a664", "E3_L_panel"),
        ("Film: elbow oval", "cb51ef92-c080-40dc-a4be-fd1e4830a913", "elbow_left"),
        ("Film: body side (ambiguous)", "da4cbc5f-a900-4bd7-a34d-02e69620a4d0", "torso_left"),
        ("Film: open hand", "cfbaa5ef-4dbd-4163-8e99-f47489ac9bcf", "hand"),
    ]
    entries = []
    for label, identifier, view in refs:
        path = TEMP / f"codex-clipboard-{identifier}.jpg"
        if path.exists():
            entries.extend([(label, path), (f"V3: {view}", folder / f"after_{view}.png")])
    board("white_v3/film_comparison_private.png", entries, columns=2)
    glb = ROOT / "assets/bagusmax/runtime/bagusmax_white_anatomy_v3.glb"
    target = folder / "glb_structure.json"
    validate_glb(glb, expected=set(), output=target, joint_count=32)
    blob = glb.read_bytes()
    size = struct.unpack_from("<I", blob, 12)[0]
    doc = json.loads(blob[20:20+size])
    report = json.loads(target.read_text(encoding="utf-8"))
    report.pop("estimated_vertex_index_memory_mb", None)
    report["geometry_buffer_bytes"] = sum(v["byteLength"] for v in doc["bufferViews"] if v.get("target") in (34962, 34963))
    report["draw_primitives"] = sum(len(m["primitives"]) for m in doc["meshes"])
    report["colored_meshes"] = [m.get("name") for m in doc["meshes"] if any("COLOR_0" in p["attributes"] for p in m["primitives"])]
    report["not_tested"].extend(["Runtime FPS", "Runtime VRAM"])
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    files = ["assets/bagusmax/source/bagusmax_white_anatomy_detailed.blend",
             "assets/bagusmax/runtime/bagusmax_white_anatomy_detailed.glb",
             "assets/bagusmax/source/bagusmax_white_before_anatomy_refinement.blend",
             "assets/bagusmax/source/bagusmax_white_anatomy_v3.blend",
             "assets/bagusmax/runtime/bagusmax_white_anatomy_v3.glb"]
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files}
    assert hashes[files[0]] == "dbfb5e734c37a101c969872668214e91d1b9ff615c389b0b2fa03ee994671a04"
    assert hashes[files[2]] == "1edb34fd517a8c58e51fc251ce56adc5eb71931d385cc4594fafad6691da6dfa"
    (folder / "asset_hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
