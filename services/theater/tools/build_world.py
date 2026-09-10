#!/usr/bin/env python3
"""
월드 자산 생성 — 배우 레퍼런스 + 도입 이미지

월드(worlds/<id>.json)의 character·wardrobe·grade·director 를 그대로 써서
그 세계의 배우 시트와 도입 장면을 만든다. 코드에 프롬프트를 두지 않는다.

사용법:
    python3 build_world.py <world_id> refs           # 배우 레퍼런스 3장
    python3 build_world.py <world_id> intro "<장면 설명>"
"""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # services/theater
MODEL = "gemini-2.5-flash-image"
REGIONS = ["us-central1", "us-east4", "us-west1", "us-west4"]

# 레퍼런스 각도 — 이름은 restage.py 의 우선순위와 맞춘다
REF_ANGLES = {
    "ref_closeup": "A tight portrait of the face only, filling the frame from forehead to "
                   "chin, at a slight three-quarter angle. Every facial feature is clearly "
                   "readable. Plain dark uncluttered backdrop.",
    "ref_quarter": "A head-and-shoulders portrait at a three-quarter angle, body turned "
                   "about 40 degrees. Plain dark uncluttered backdrop.",
    "ref_full":    "A medium shot from the waist up, facing forward, showing the full "
                   "wardrobe clearly. Plain dark uncluttered backdrop.",
}


def project():
    return subprocess.check_output(
        ["gcloud", "config", "get-value", "project"], text=True).strip()


def load(world_id):
    return json.loads((ROOT / "config" / "worlds" / f"{world_id}.json").read_text(encoding="utf-8"))


def generate(parts, out_path, ratio="16:9"):
    from google import genai
    from google.genai import types
    pid = project()
    last = None
    for region in REGIONS:
        try:
            c = genai.Client(vertexai=True, project=pid, location=region)
            res = c.models.generate_content(
                model=MODEL, contents=parts,
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio=ratio)),
            )
            for cand in res.candidates or []:
                for part in cand.content.parts or []:
                    blob = getattr(part, "inline_data", None)
                    if blob and blob.data:
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_bytes(blob.data)
                        return out_path
            last = RuntimeError("이미지 파트 없음")
        except Exception as e:
            last = e
        time.sleep(1)
    raise RuntimeError(f"생성 실패: {last}")


def world_block(w):
    """월드 파일의 서술을 프롬프트 블록으로."""
    return (f"CHARACTER:\n{w['character']}\n\n"
            f"WARDROBE:\n{w['wardrobe']}\n\n"
            f"LOOK AND GRADE:\n{w['grade']}\n\n"
            f"{w['director']}\n")


def build_refs(world_id):
    """배우 레퍼런스 시트. 첫 장을 앵커로 나머지를 뽑아 얼굴을 맞춘다."""
    from PIL import Image
    w = load(world_id)
    out = ROOT / "static" / w["refsDir"]
    anchor = None
    for i, (key, angle) in enumerate(REF_ANGLES.items()):
        parts = []
        prompt = world_block(w)
        if anchor is not None:
            parts.append(Image.open(str(anchor)))
            prompt = ("IDENTITY REFERENCE: the provided image shows the exact same character. "
                      "Match the face, hair and wardrobe precisely. IGNORE its framing and "
                      "camera angle — this is a new angle described below.\n\n") + prompt
        prompt += f"\nTHIS SHOT:\n{angle}\nThe character does not look at the camera."
        parts.append(prompt)
        p = generate(parts, out / f"{key}.png")
        if anchor is None:
            anchor = p
        print(f"  ✓ {key}")
    print(f"  → {out}")


def build_intro(world_id, scene_desc, ratio="9:16"):
    from PIL import Image
    w = load(world_id)
    refs = sorted((ROOT / "static" / w["refsDir"]).glob("*.png"))
    if not refs:
        print("[Error] 먼저 refs 를 만드세요")
        sys.exit(1)
    parts = [Image.open(str(r)) for r in refs[:2]]
    parts.append(
        "IDENTITY REFERENCE: the provided images show the exact character to draw. "
        "Match face, hair and wardrobe precisely. IGNORE their backgrounds and framing.\n\n"
        + world_block(w)
        + f"\nTHIS SHOT:\n{scene_desc}\n"
        "The character does not look at the camera."
    )
    p = generate(parts, ROOT / "static" / w["refsDir"].replace("/refs", "") / "intro.png", ratio)
    print(f"  ✓ {p}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    wid, cmd = sys.argv[1], sys.argv[2]
    if cmd == "refs":
        build_refs(wid)
    elif cmd == "intro":
        build_intro(wid, sys.argv[3])
    else:
        print(__doc__)
