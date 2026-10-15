"""Validate the exported GLB and assemble private reference comparisons."""

import json
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports/bagusmax_3d"
REFERENCES = ROOT / "assets/bagusmax/reference"
TEMP = Path("C:/Users/bagus/AppData/Local/Temp")
REFERENCE_IDS = {
    "front": "714cfebc-46c3-467f-b1ee-2d90f754dd0d",
    "back_toy": "c83babd7-3db1-49bf-ac34-9381f8deda9e",
    "three_quarter": "cd88f139-712d-4bff-b426-0707cd6b4322",
    "side_film": "19971a51-107b-42e1-bbea-4f9d8ece51c0",
    "gesture": "9d27532e-835c-4fdf-8851-1e4225457a73",
    "front_film": "523437bf-603e-46ec-9a28-e90c64c4751f",
    "side_profile": "240f500c-9de1-4c18-8da2-1bf968de484d",
}


def validate_glb(path=None, expected=None, output=None, joint_count=20):
    path = path or ROOT / "assets/bagusmax/runtime/bagusmax_white.glb"
    blob = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", blob)
    assert (magic, version, length) == (b"glTF", 2, len(blob))
    size, kind = struct.unpack_from("<II", blob, 12)
    assert kind == 0x4E4F534A
    doc = json.loads(blob[20:20+size])
    if expected is None:
        expected = {"IDLE", "LISTEN", "SPEAK", "WAVE", "THINK", "RETURN_TO_IDLE"}
    assert {a["name"] for a in doc.get("animations", [])} == expected
    assert len(doc["skins"]) == 1 and len(doc["skins"][0]["joints"]) == joint_count
    assert not doc.get("images") and not doc.get("textures")
    offset = 20+size
    binary_size, binary_type = struct.unpack_from("<II", blob, offset)
    assert binary_type == 0x004E4942
    binary = memoryview(blob)[offset+8:offset+8+binary_size]

    def values(index):
        accessor = doc["accessors"][index]
        view = doc["bufferViews"][accessor["bufferView"]]
        count = {"SCALAR":1,"VEC2":2,"VEC3":3,"VEC4":4,"MAT4":16}[accessor["type"]]
        fmt = {5126:"f",5123:"H",5125:"I",5121:"B"}[accessor["componentType"]]
        width = struct.calcsize("<"+fmt)*count
        stride = view.get("byteStride",width)
        start = view.get("byteOffset",0)+accessor.get("byteOffset",0)
        for i in range(accessor["count"]):
            yield struct.unpack_from("<"+fmt*count, binary, start+i*stride)

    triangles, vertices = 0,0
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            attrs = primitive["attributes"]
            assert {"POSITION","NORMAL","TEXCOORD_0","JOINTS_0","WEIGHTS_0"} <= attrs.keys()
            vertex_count = doc["accessors"][attrs["POSITION"]]["count"]
            vertices += vertex_count
            triangles += doc["accessors"][primitive["indices"]]["count"]//3
            for weights in values(attrs["WEIGHTS_0"]):
                assert all(math.isfinite(w) and w>=0 for w in weights)
                assert abs(sum(weights)-1)<.001
            for joints in values(attrs["JOINTS_0"]):
                assert max(joints)<joint_count
            for position in values(attrs["POSITION"]):
                assert all(math.isfinite(x) for x in position)
            for index in values(primitive["indices"]):
                assert index[0]<vertex_count
    result = {"result":"GLB_STRUCTURE_SKIN_ANIMATION_PASS" if expected else "GLB_STRUCTURE_SKIN_STATIC_PASS",
              "bytes":len(blob),
              "meshes":len(doc["meshes"]),"materials":len(doc["materials"]),
              "triangles":triangles,"exported_vertices":vertices,"joint_count":joint_count,
              "animation_names":sorted(expected),"external_textures":False,
              "estimated_vertex_index_memory_mb":round(vertices*(12+12+8+8+16)/1048576+triangles*3*4/1048576,2),
              "not_tested":["OpenBagus runtime loader", "All-pose collision checks", "User visual acceptance"]}
    (output or REPORTS/"white_glb_validation.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


def board(name, entries, columns=3, cell_size=(380,480)):
    width, height = cell_size
    canvas = Image.new("RGB", (columns*width, math.ceil(len(entries)/columns)*height), "#e9ecef")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf",16)
    except OSError:
        font = ImageFont.load_default()
    for i,(label,path) in enumerate(entries):
        x,y = (i%columns)*width,(i//columns)*height
        image = Image.open(path).convert("RGB")
        image.thumbnail((width-20,height-58),Image.Resampling.LANCZOS)
        canvas.paste(image,(x+(width-image.width)//2,y+43+(height-58-image.height)//2))
        draw.text((x+12,y+12),label,fill="#20262c",font=font)
    canvas.save(REPORTS/name)


def main():
    REFERENCES.mkdir(parents=True,exist_ok=True)
    for name,identifier in REFERENCE_IDS.items():
        target = REFERENCES/(name+".jpg")
        if not target.exists():
            target.write_bytes((TEMP/f"codex-clipboard-{identifier}.jpg").read_bytes())
    board("white_reference_board.png",[(name.replace("_"," "),REFERENCES/(name+".jpg")) for name in REFERENCE_IDS])
    validate_glb()
    if (REPORTS/"white_material_front.png").exists():
        old = ROOT/"reports/screenshots/bagusmax_white_front.png"
        board("white_front_comparison.png",[("Existing application model",old),
            ("New authored mesh - Blender",REPORTS/"white_material_front.png"),
            ("User front reference",REFERENCES/"front.jpg")])
    if (REPORTS/"white_material_three_quarter.png").exists():
        board("white_turnaround.png",[(name.replace("_"," "),REPORTS/f"white_material_{name}.png")
              for name in ("front","left","three_quarter","back","right","head")])
    if (REPORTS/"baseline_clay_front.png").exists():
        board("white_geometry_comparison.png", [("Existing GLB - normalized height",REPORTS/"baseline_clay_front.png"),
              ("New runtime GLB - same camera",REPORTS/"white_runtime_clay_front.png"),
              ("New material render",REPORTS/"white_runtime_front.png")])


if __name__ == "__main__":
    main()
