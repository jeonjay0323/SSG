#!/usr/bin/env python3
"""
체인 프레임 얼굴 교정 — 세대 드리프트 보정

문제:
    Veo 체이닝은 씬 N-1 의 '끝부분' 프레임을 씬 N 의 시작으로 쓴다.
    그런데 그 프레임은 해당 클립에서 가장 많이 틀어진 프레임이라,
    드리프트를 그대로 물려주며 누적된다. 배경은 버티는데 얼굴이 밀린다.

    Veo 는 시작 프레임과 ASSET 레퍼런스를 함께 못 받는다
    ("Image and reference images cannot be both set").

해법:
    이미지 모델(gemini-2.5-flash-image)은 레퍼런스를 여러 장 받을 수 있다.
    체인 프레임을 Veo 에 넘기기 '전에' 인물 시트로 얼굴만 되돌린다.
    구도·배경·조명·포즈·의상은 건드리지 않는다.

사용법:
    python3 fix_face.py scenes/chain/after_scene3.png            # 제자리 교정
    python3 fix_face.py <입력> <출력>
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 01_Product/Theater
REFS_DIR = ROOT / "static" / "scenes" / "refs"
MODEL = "gemini-2.5-flash-image"
REGIONS = ["us-central1", "us-east4", "us-west1", "us-west4"]

INSTRUCTION = (
    "You are given reference photographs of a man, followed by a film still.\n\n"
    "TASK: in the film still, correct ONLY the man's face so that it matches the "
    "reference photographs exactly — same bone structure, same short narrow chin and "
    "slim V-line jaw, same eye shape, same nose, same hairline and hairstyle.\n\n"
    "KEEP EVERYTHING ELSE EXACTLY AS IT IS IN THE FILM STILL:\n"
    "the camera angle, framing and crop; his body pose, position and scale in frame; "
    "his clothing and the bag; the entire background and set; the lighting direction "
    "and intensity; the color grade, contrast and film grain.\n"
    "Do not re-stage the shot. Do not change his expression more than necessary. "
    "Do not clean up, beautify, sharpen or upscale the image — it must still look like "
    "a frame from the same film.\n"
    "IGNORE the reference photographs' plain gray studio background and studio lighting "
    "entirely; they are provided only to identify the face.\n\n"
    "Output the corrected film still at the same aspect ratio."
)


def fix(in_path, out_path=None, refs_dir=REFS_DIR):
    from google import genai
    from google.genai import types
    from PIL import Image

    in_path = Path(in_path)
    out_path = Path(out_path) if out_path else in_path
    refs = sorted(Path(refs_dir).glob("*.png"))
    if not refs:
        raise FileNotFoundError(f"인물 레퍼런스 없음: {refs_dir}")

    project_id = subprocess.check_output(
        ["gcloud", "config", "get-value", "project"], text=True).strip()

    src = Image.open(str(in_path))
    ratio = "16:9" if src.width >= src.height else "9:16"
    parts = [Image.open(str(r)) for r in refs] + [src, INSTRUCTION]

    last = None
    for region in REGIONS:
        try:
            client = genai.Client(vertexai=True, project=project_id, location=region)
            res = client.models.generate_content(
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
    raise RuntimeError(f"얼굴 교정 실패: {last}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src
    print(f"✓ {fix(src, dst)}")
