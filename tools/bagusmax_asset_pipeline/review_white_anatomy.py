"""Review static White anatomy export and aligned Blender comparison renders."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from review_white import ROOT, validate_glb


REVIEW = ROOT / "reports/bagusmax_3d/anatomy"
GLB = ROOT / "assets/bagusmax/runtime/bagusmax_white_anatomy_refined.glb"


def font():
    try:
        return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 19)
    except OSError:
        return ImageFont.load_default()


def comparison(name):
    left = Image.open(REVIEW/f"before_{name}.png").convert("RGB")
    right = Image.open(REVIEW/f"refined_{name}.png").convert("RGB")
    assert left.size == right.size
    canvas = Image.new("RGB",(left.width*2,left.height+42),"#e9ecef")
    canvas.paste(left,(0,42))
    canvas.paste(right,(left.width,42))
    draw = ImageDraw.Draw(canvas)
    draw.text((16,10),"BEFORE | original White source",fill="#23313b",font=font())
    draw.text((left.width+16,10),"REFINED | neutral anatomy",fill="#23313b",font=font())
    canvas.save(REVIEW/f"{name}_comparison.png")


def normalized_mask(label, view, target_height=500):
    mask = Image.open(REVIEW/f"{label}_mask_{view}.png").convert("RGBA").getchannel("A")
    bbox = mask.getbbox()
    assert bbox
    crop = mask.crop(bbox)
    width = round(crop.width * target_height/crop.height)
    crop = crop.resize((width,target_height),Image.Resampling.LANCZOS)
    result = Image.new("L", mask.size, 0)
    result.paste(crop,((mask.width-width)//2,580-target_height))
    return result


def silhouette_overlay(view):
    old = normalized_mask("before",view)
    refined = normalized_mask("refined",view)
    canvas = Image.new("RGB", old.size, "#f2f4f6")
    old_color = Image.new("RGB",old.size,"#bc6d63")
    refined_color = Image.new("RGB",old.size,"#308ba1")
    canvas.paste(old_color,(0,0),old.point(lambda value: round(value*.55)))
    canvas.paste(refined_color,(0,0),refined.point(lambda value: round(value*.55)))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0,0,640,40), fill="#f2f4f6")
    draw.text((12,10),"NORMALIZED HEIGHT  |  BEFORE: coral  |  REFINED: teal",
              fill="#23313b",font=font())
    canvas.save(REVIEW/f"{view}_silhouette_overlay.png")


def main():
    validate_glb(GLB, expected=set(), output=REVIEW/"glb_validation.json")
    for name in ("front","left","right","back","three_quarter","head",
                 "shoulder","elbow","belly_profile","chest_port","legs"):
        comparison(name)
    for name in ("front","left"):
        silhouette_overlay(name)


if __name__ == "__main__":
    main()
