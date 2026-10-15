"""Assemble private Gate A visual evidence and validate the static GLB."""

import hashlib
import json
from pathlib import Path

from review_white import ROOT, REPORTS, board, validate_glb

REVIEW=REPORTS/"white_detail"
TEMP=Path("C:/Users/bagus/AppData/Local/Temp")


def main():
    validate_glb(ROOT/"assets/bagusmax/runtime/bagusmax_white_anatomy_detailed.glb",
                 expected=set(),output=REVIEW/"glb_structure.json")
    refs={
        "front":("64673f8b-a03d-4e1d-8a92-afc220a8e869","Film: posed, perspective"),
        "left":("2f9ea725-0510-4ceb-bd8b-d93bd6f2919d","Film: side/three-quarter"),
        "head":("e7dba100-0cee-4af1-b8ad-14d031cc52ba","Film: head and port"),
        "chest_port":("c5f748ac-7152-445c-aaa2-e24c16ad150f","Film: lid/latch detail"),
        "hand":("33c26188-f4d2-482a-a3b2-c182e6a36d30","Film: open palms"),
        "elbow":("3ee98153-b869-4d6b-8d12-446a11ec2407","Film: elbow panel"),
    }
    for view,(identifier,label) in refs.items():
        board(f"white_detail/compare_{view}.png",[
            ("Previous refined | same studio",REVIEW/f"previous_{view}.png"),
            ("Detailed White | same studio",REVIEW/f"detailed_{view}.png"),
            (label,TEMP/f"codex-clipboard-{identifier}.jpg")])
    board("white_detail/neutral_sheet.png",[(view.replace("_"," "),REVIEW/f"detailed_{view}.png")
          for view in ("front","left","right","three_quarter","three_quarter_right","back")])
    board("white_detail/pose_sheet.png",[(path.stem.replace("pose_",""),path)
          for path in sorted(REVIEW.glob("pose_T*.png"))],columns=4)
    board("white_detail/detail_sheet.png",[(view.replace("_"," "),REVIEW/f"detailed_{view}.png")
          for view in ("head","chest_port","elbow","hand","shoulder","legs")])
    sources=[ROOT/"assets/bagusmax/source"/name for name in
             ("bagusmax_white.blend","bagusmax_white_before_anatomy_refinement.blend",
              "bagusmax_white_anatomy_refined.blend","bagusmax_white_anatomy_detailed.blend")]
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    assert hashes[sources[0].name]==hashes[sources[1].name]
    (REVIEW/"source_hashes.json").write_text(json.dumps(hashes,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
