#!/usr/bin/env python3
"""
인물 ASSET 레퍼런스 시트 생성 — 영상 일관성용

Veo 3.1 의 reference_images(ASSET) 에 넣을 인물 사진을 만든다.
시작 프레임 한 장만으로는 환경이 바뀔 때 얼굴이 흔들리는데,
인물만 따로 여러 각도로 물려주면 고정력이 크게 올라간다.

배경은 반드시 무지(無地) — 엘리베이터가 배경으로 들어가면
모델이 '이 사람 = 엘리베이터'로 묶어버려서 다른 장소에서 깨진다.

사용법:
    python3 generate_refs.py
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 01_Product/MultiTool
OUT = ROOT / "Static" / "scenes" / "refs"
ANCHOR = ROOT / "Static" / "scenes" / "actor" / "anchor.png"

MODEL = "gemini-2.5-flash-image"
REGIONS = ["us-central1", "us-east4", "us-west1", "us-west4"]

IDENTITY = (
    "IDENTITY REFERENCE: the provided photograph shows the actor to reproduce. "
    "Match his face EXACTLY — same bone structure, same slim V-line jaw and short narrow chin, "
    "same large dark eyes with the same eyelid shape, same straight nose, same full lips, "
    "same thick straight eyebrows, same black hair with a soft fringe falling over the forehead. "
    "He is an extremely handsome Korean man in his late twenties.\n"
    "IGNORE the reference photograph's clothing, background, lighting and framing completely — "
    "he is dressed and lit for a different production, described below.\n\n"
    "WARDROBE FOR THIS PRODUCTION (not from the reference photo):\n"
    "A plain white dress shirt with the sleeves rolled up to the forearm, top button undone, "
    "no tie; dark charcoal suit trousers; a worn brown leather laptop bag. "
    "An ordinary office worker at the end of a long night shift — the shirt slightly creased, "
    "not styled or glamorous.\n\n"
)

# 레퍼런스는 '교정 대상 프레임과 같은 세계'로 보여야 한다.
# 스튜디오 정면 조명 + 회색 배경 시트는 어둡고 색보정된 영화 프레임과 괴리가 커서
# 얼굴 교정이 잘 붙지 않았다. 그래서 시트 자체를 영화 톤으로 맞춘다.
# 톤은 드라마 〈미생〉 기준 — 형광등 사무실, 저채도 회청색, 다큐멘터리적.
# 헐리우드식 teal&orange 가 아니다.
COMMON = (
    "A frame from a Korean office drama in the visual style of 〈Misaeng〉. "
    "Real photograph, natural skin texture with visible pores, unretouched. "
    "Photorealistic, not CGI, not illustration, not AI art.\n"
    "COLOR: desaturated, cool grey-blue and pale green, the colour of overhead "
    "fluorescent tubes in a night office. Low contrast, milky blacks, no orange "
    "accents, no teal-and-orange grade, nothing glossy or advertising-like.\n"
    "LIGHT: flat overhead fluorescent light, slightly greenish, unflattering and ordinary. "
    "Faint shadows under the brow and nose. Not dramatic, not sculpted, not studio-lit.\n"
    "BACKDROP: a plain, dim, out-of-focus office wall — no furniture, no props, "
    "no recognizable location.\n"
    "Bare face, no makeup, no contouring, no nose highlight. Slightly tired skin. "
    "Sharp focus on the eyes. Fine 35mm grain. "
    "No text, no captions, no watermarks. "
    "Do not resemble any real celebrity or public figure."
)

REFS = {
    "ref_front": (
        "Head-and-shoulders portrait, facing the camera straight on, neutral expression, "
        "eyes looking directly into the lens. " + COMMON
    ),
    "ref_quarter": (
        "Head-and-shoulders portrait at a three-quarter angle, body turned about 40 degrees, "
        "face toward the camera, neutral expression. " + COMMON
    ),
    "ref_full": (
        "Medium shot from the waist up, facing the camera, arms relaxed at his sides, "
        "holding the worn leather laptop bag in his right hand. "
        "The shirt, trousers and bag are clearly visible. " + COMMON
    ),
    "ref_closeup": (
        "Tight close-up of the face only, filling the frame from forehead to chin, "
        "facing the camera, neutral expression, eyes into the lens. "
        "Every facial feature is clearly legible. " + COMMON
    ),
    "ref_profile": (
        "Side profile portrait, head and shoulders, looking off-camera to the left. "
        "The jawline, chin and nose silhouette are clearly readable. " + COMMON
    ),
}


def main():
    try:
        from google import genai
        from google.genai import types
        from PIL import Image
    except ImportError as e:
        print(f"[Error] pip install google-genai pillow ({e})")
        sys.exit(1)

    if not ANCHOR.exists():
        print(f"[Error] 앵커 이미지 없음: {ANCHOR}")
        print("        먼저 generate_intro.py 를 실행하세요.")
        sys.exit(1)

    project_id = subprocess.check_output(
        ["gcloud", "config", "get-value", "project"], text=True).strip()
    print(f"GCP 프로젝트: {project_id}")
    OUT.mkdir(parents=True, exist_ok=True)

    clients = [(r, genai.Client(vertexai=True, project=project_id, location=r))
               for r in REGIONS]
    anchor_img = Image.open(str(ANCHOR))

    for i, (key, body) in enumerate(REFS.items()):
        for region, client in clients:
            print(f"[{i+1}/{len(REFS)}] {key} [{region}] ", end="", flush=True)
            try:
                res = client.models.generate_content(
                    model=MODEL,
                    contents=[anchor_img, IDENTITY + body],
                    config=types.GenerateContentConfig(
                        image_config=types.ImageConfig(aspect_ratio="16:9")),
                )
                saved = False
                for cand in res.candidates or []:
                    for part in cand.content.parts or []:
                        blob = getattr(part, "inline_data", None)
                        if blob and blob.data:
                            (OUT / f"{key}.png").write_bytes(blob.data)
                            print(f"✓ ({len(blob.data)//1024}KB)")
                            saved = True
                            break
                    if saved:
                        break
                if saved:
                    break
                print("실패: 이미지 파트 없음")
            except Exception as e:
                print(f"실패: {type(e).__name__}: {str(e)[:100]}")
            time.sleep(1)

    print(f"\n출력: {OUT}")


if __name__ == "__main__":
    main()
