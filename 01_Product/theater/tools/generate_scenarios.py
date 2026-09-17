#!/usr/bin/env python3
"""
시나리오 도입부 생성 — 〈보낸 적 없는 메일〉, 〈아무도 없는 층〉

같은 배우·같은 의상·같은 톤(미생)으로 시작 이미지를 만든다.
이미지가 곧 선택 화면의 포스터이자 도입 영상의 첫 프레임이 된다.

사용법:
    python3 generate_scenarios.py            # 전부
    python3 generate_scenarios.py mail       # 하나만
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 01_Product/theater
OUT = ROOT / "static" / "scenes"
ACTOR = OUT / "actor" / "anchor.png"

MODEL = "gemini-2.5-flash-image"
REGIONS = ["us-central1", "us-east4", "us-west1", "us-west4"]

CHARACTER = (
    "The man is the actor shown in the reference photograph — match his face exactly: "
    "slim V-line jaw, short narrow chin, large dark eyes, straight nose, full lips, "
    "thick straight brows, black hair with a soft fringe over the forehead. "
    "Extremely handsome Korean man in his late twenties, a tired office worker deep into "
    "overtime. Bare face, no makeup, no contouring, no nose highlight. "
    "Wearing a plain white dress shirt, sleeves rolled to the forearm, top button undone, "
    "no tie, dark charcoal trousers. A worn brown leather laptop bag is nearby. "
    "The shirt is slightly creased — ordinary, not styled or glamorous."
)

LOOK = (
    "A frame from a Korean office drama in the visual style of Misaeng. "
    "Observational and unglamorous — the camera is a witness in the room. "
    "Real photograph, natural skin texture with visible pores, not retouched. "
    "Photorealistic, not CGI, not illustration, not AI art.\n"
    "Flat overhead fluorescent light, faintly green, ordinary and unflattering. "
    "Desaturated cool grey-blue, low contrast, milky blacks. "
    "NO teal-and-orange grade, no warm amber accents, no rim light, no lens flare, "
    "nothing glossy or advertising-like.\n"
    "Keep him off-centre, partially framed by the architecture or by foreground objects. "
    "He NEVER looks into the lens — his gaze stays inside the scene. "
    "Longer lens, shallow focus, fine 35mm grain. 16:9. "
    "No text, no captions, no watermarks, no on-screen graphics. "
    "Do not resemble any real celebrity or public figure."
)

SCENARIOS = {
    "mail": {
        "label": "보낸 적 없는 메일",
        "file": "mail_intro.png",
        "prompt": (
            "A wide-ish medium shot of an open-plan Korean office at three in the morning. "
            "Every desk is empty except his. Most ceiling lights are off; only the bank "
            "above him is lit, so the rest of the floor falls away into dim grey. "
            + CHARACTER +
            " He sits at his desk seen from a three-quarter rear angle over his shoulder, "
            "the monitor glowing pale in front of him. "
            "GAZE: he is staring at the screen, leaning slightly forward, gone completely "
            "still — he has just noticed something there. His face is only partly visible.\n"
            "The screen's content is NOT readable — it is a soft pale glow, no legible text. "
            "Foreground: the edge of a partition or a monitor rim cuts across the frame, "
            "out of focus.\n"
            + LOOK
        ),
    },
    "floor": {
        "label": "아무도 없는 층",
        "file": "floor_intro.png",
        "prompt": (
            "An office corridor during a power cut, seen from one end. "
            "The overhead fluorescents are dead; only the green emergency exit sign and a "
            "weak emergency lamp light the space, so most of the corridor is deep grey. "
            + CHARACTER +
            " He stands small and off-centre near the middle of the corridor, "
            "seen from behind in three-quarter rear, one hand still resting on a door frame. "
            "GAZE: his head is tilted up toward the ceiling — he is listening to something "
            "on the floor above. His face is barely visible.\n"
            "Foreground: a doorway edge or a pillar cuts into the near side of the frame, "
            "out of focus. The far end of the corridor dissolves into darkness.\n"
            + LOOK
        ),
    },
}

IDENTITY = (
    "IDENTITY REFERENCE: the provided photograph shows the actor to reproduce. "
    "Match his face exactly. IGNORE the reference photograph's clothing, background, "
    "lighting and framing — this shot has its own, described below.\n\n"
)


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    keys = [k for k in SCENARIOS if not only or only in k]
    if not keys:
        print(f"[Error] '{only}' 매칭 없음. 가능: {list(SCENARIOS)}")
        sys.exit(1)

    from google import genai
    from google.genai import types
    from PIL import Image

    project_id = subprocess.check_output(
        ["gcloud", "config", "get-value", "project"], text=True).strip()
    print(f"GCP 프로젝트: {project_id}")
    OUT.mkdir(parents=True, exist_ok=True)

    clients = [(r, genai.Client(vertexai=True, project=project_id, location=r))
               for r in REGIONS]
    actor = Image.open(str(ACTOR))

    for i, key in enumerate(keys):
        s = SCENARIOS[key]
        parts = [actor, IDENTITY + s["prompt"]]
        for region, client in clients:
            print(f"[{i+1}/{len(keys)}] {s['label']} [{region}] ", end="", flush=True)
            try:
                res = client.models.generate_content(
                    model=MODEL, contents=parts,
                    config=types.GenerateContentConfig(
                        image_config=types.ImageConfig(aspect_ratio="16:9")),
                )
                saved = False
                for cand in res.candidates or []:
                    for part in cand.content.parts or []:
                        blob = getattr(part, "inline_data", None)
                        if blob and blob.data:
                            (OUT / s["file"]).write_bytes(blob.data)
                            print(f"✓ {s['file']} ({len(blob.data)//1024}KB)")
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
