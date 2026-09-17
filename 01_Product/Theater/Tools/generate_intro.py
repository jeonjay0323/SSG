#!/usr/bin/env python3
"""
도입부 씬 1·2 이미지 생성 — 〈지하 1층〉

  씬 1  야근 끝. 텅 빈 엘리베이터. 지하 1층 버튼을 누른다.
  씬 2  문이 열리기 시작한다. 새어 들어오는 빛이 얼굴을 때린다.
        → 문 밖은 절대 보이지 않는다. 그게 관람객이 쓸 자리다.

씬 2 의 마지막 프레임이 관람객 씬(씬 3)의 시작 프레임이 되므로,
'문이 열리는 중 + 정체불명의 빛'에서 멈추는 게 이 도입부의 핵심이다.

사용법:
    python3 generate_intro.py            # 씬 1·2 생성
    python3 generate_intro.py scene1     # 하나만
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 01_Product/Theater
OUT = ROOT / "Static" / "scenes"
ACTOR = ROOT / "Static" / "scenes" / "actor" / "anchor.png"

MODEL = "gemini-2.5-flash-image"
REGIONS = ["us-central1", "us-east4", "us-west1", "us-west4",
           "europe-west4", "asia-northeast1"]

# ── 전 씬 공통 ──
# 인물 묘사는 단순하게. 세부 특징을 과하게 적으면 오히려 기형적으로 나온다.
CHARACTER = (
    "The man is the actor shown in the reference photographs — match his face exactly: "
    "slim V-line jaw, short narrow chin, large dark eyes, straight nose, full lips, "
    "thick straight brows, black hair with a soft fringe over the forehead. "
    "Extremely handsome Korean man in his late twenties, a tired office worker after "
    "overtime. Bare face, no makeup, no contouring, no nose highlight. "
    "Wearing a plain white dress shirt, sleeves rolled to the forearm, top button undone, "
    "no tie, dark charcoal trousers. Carrying a worn brown leather laptop bag. "
    "The shirt is slightly creased — ordinary, not styled or glamorous."
)

# 톤은 드라마 〈미생〉 — 형광등, 저채도 회청색, 다큐멘터리적.
LOOK = (
    "A frame from a Korean office drama in the visual style of Misaeng. "
    "Observational and unglamorous — the camera is a witness in the room. "
    "Real photograph, natural skin texture with visible pores, not retouched. "
    "Photorealistic, not CGI, not illustration, not AI art.\n"
    "Flat overhead fluorescent light, faintly green, ordinary and unflattering. "
    "Desaturated cool grey-blue, low contrast, milky blacks. "
    "NO teal-and-orange grade, no warm amber accents, no rim light, no lens flare, "
    "nothing glossy or advertising-like.\n"
    "Keep him off-centre, partially framed by the architecture. He never looks into the "
    "lens — his gaze stays inside the scene. Longer lens, shallow focus, fine 35mm grain. "
    "16:9. No text, no captions, no watermarks, no on-screen graphics. "
    "Do not resemble any real celebrity or public figure."
)

SCENES = {
    "scene1": {
        "label": "지하 1층 버튼",
        "file": "intro_scene1_elevator.png",
        "prompt": (
            "Interior of an empty office building elevator, late at night. "
            + CHARACTER +
            " He stands alone, seen from a three-quarter REAR angle — the camera is behind "
            "and to one side of him, so we mostly see his back and the edge of his cheek. "
            "GAZE: he is looking down at the button panel in front of him. "
            "He does NOT turn toward the camera and his eyes are never visible to the lens. "
            "His index finger has just pressed the B1 button — the button glows faint amber. "
            "Brushed steel walls with a dull reflection of him. "
            "A small floor indicator above the door reads a descending number. "
            "The mood is ordinary and slightly worn out — nothing strange has happened yet. "
            + LOOK
        ),
    },
    "scene2": {
        "label": "문이 열린다",
        "file": "intro_scene2_dooropen.png",
        "prompt": (
            "Same elevator interior, same man, moments later. "
            "The elevator doors have just begun to part — open only a narrow gap. "
            "An intense unidentifiable light floods in through the gap, "
            "blowing out completely to pure white so that NOTHING outside is visible. "
            "Absolutely no scenery, no room, no landscape beyond the doors — only blinding white light. "
            "The camera is inside the elevator, well behind him and off to one side, "
            "so he is seen from behind in three-quarter rear, small against the doors. "
            "GAZE: he is facing the opening doors, looking straight into the light. "
            "His back is to the camera; his face is barely or not at all visible. "
            "He does NOT turn around. He has not moved yet — only gone still. "
            "The light from the gap is the only bright thing in frame; the elevator "
            "interior stays flat and dim. "
            + CHARACTER + " " + LOOK
        ),
    },
}

# 씬 2는 씬 1을 정체성·색감 앵커로 참조한다
ANCHOR_INSTRUCTION = (
    "IDENTITY AND GRADE ANCHOR:\n"
    "The LAST provided image shows the SAME MAN in the SAME elevator moments earlier. "
    "Match his face exactly — same bone structure, same jawline, same hairstyle, "
    "same shirt and bag, same elevator interior, same color grade and film grain.\n"
    "Use the reference ONLY for identity, wardrobe, set and color. "
    "IGNORE its camera angle and lighting — this shot has its own framing and its own "
    "blown-out light source from the doorway.\n\n"
)


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    keys = [k for k in SCENES if not only or only in k]
    if not keys:
        print(f"[Error] '{only}' 매칭 없음. 가능: {list(SCENES)}")
        sys.exit(1)
    # 씬 1이 앵커이므로 항상 먼저
    keys.sort()

    try:
        from google import genai
        from google.genai import types
        from PIL import Image
    except ImportError as e:
        print(f"[Error] pip install google-genai pillow ({e})")
        sys.exit(1)

    project_id = subprocess.check_output(
        ["gcloud", "config", "get-value", "project"], text=True).strip()
    print(f"GCP 프로젝트: {project_id}")
    OUT.mkdir(parents=True, exist_ok=True)

    clients = [(r, genai.Client(vertexai=True, project=project_id, location=r))
               for r in REGIONS]

    anchor_path = OUT / SCENES["scene1"]["file"]

    for i, key in enumerate(keys):
        s = SCENES[key]
        prompt = s["prompt"]
        parts = []

        if ACTOR.exists():
            parts.append(Image.open(str(ACTOR)))     # 배우 정체성
        if key != "scene1" and anchor_path.exists():
            parts.append(Image.open(str(anchor_path)))
            prompt = ANCHOR_INSTRUCTION + prompt

        parts.append(prompt)

        for attempt, (region, client) in enumerate(clients):
            print(f"[{i+1}/{len(keys)}] {s['label']} [{region}] ", end="", flush=True)
            try:
                # 16:9 로 뽑아야 Veo 에 그대로 넣을 때 구도가 잘리지 않는다.
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
                print(f"실패: {type(e).__name__}: {str(e)[:110]}")
            time.sleep(1)
        else:
            print(f"[Error] {key} — 모든 리전 실패")

    print(f"\n출력: {OUT}")


if __name__ == "__main__":
    main()
