#!/usr/bin/env python3
"""
리스테이징 — 다음 씬의 시작 프레임을 '연출된 컷'으로 다시 세운다.

문제:
    직전 클립의 마지막 프레임을 그대로 Veo 에 넘기면
      · 얼굴이 세대마다 밀린다 (가장 많이 틀어진 프레임을 물려받으므로)
      · 앵글이 늘 같아 편집된 드라마가 아니라 한 컷의 연장처럼 보인다
      · 인물이 계속 카메라를 본다

해법:
    Veo 는 시작 프레임과 ASSET 레퍼런스를 함께 못 받지만
    (Image and reference images cannot be both set),
    이미지 모델은 레퍼런스를 여러 장 받는다.

    그래서 Veo 에 넘기기 전에 이미지 모델로 한 번 거친다:
      ① 배우 레퍼런스로 얼굴을 되돌리고          → 정체성
      ② 장소·의상·색감은 직전 프레임에서 가져오고 → 연속성
      ③ 샷 타입을 바꿔 새 앵글로 다시 세운다      → 컷 전환·다양한 뷰포트

    결과물이 곧 '다음 컷의 첫 프레임'이 된다.

톤 레퍼런스: 드라마 〈미생〉.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 01_Product/theater
REFS_DIR = ROOT / "static" / "scenes" / "refs"
MODEL = "gemini-2.5-flash-image"
REF_LIMIT = 3      # 속도/정확도 균형점 (5장 16.6초 / 3장 11.0초 실측)
REGIONS = ["us-central1", "us-east4", "us-west1", "us-west4"]


# ─────────────────────────────────────────────────────────────
# 샷 문법 — 〈미생〉식. 무언가에 가려지고, 비껴 서고, 작게 잡힌다.
# 씬 순서대로 돌아가며 편집된 드라마처럼 보이게 한다.
# ─────────────────────────────────────────────────────────────
SHOTS = [
    {
        "key": "obstructed_wide",
        "label": "와이드 · 가려짐",
        "desc": ("A wide shot taken from behind an obstruction — a door frame, a pillar or "
                 "a glass partition cuts across the foreground, out of focus. "
                 "He stands small and off-centre in the space beyond it, seen from behind "
                 "or in three-quarter rear. The environment dominates the frame."),
    },
    {
        "key": "profile_glass",
        "label": "측면 · 유리 너머",
        "desc": ("A medium shot of him in profile, shot through glass or a reflective steel "
                 "surface so that faint reflections sit over him. "
                 "He looks straight ahead into the space. He is pushed to one side of the "
                 "frame with empty space in front of him."),
    },
    {
        "key": "over_shoulder",
        "label": "오버숄더",
        "desc": ("An over-the-shoulder shot from close behind him: the back of his head and "
                 "one shoulder fill the near side of the frame, heavily out of focus, "
                 "while what he is looking at sits sharp in the distance. "
                 "His face is not visible at all."),
    },
    {
        "key": "quiet_closeup",
        "label": "클로즈업 · 침묵",
        "desc": ("A close-up of his face at a three-quarter angle, his eyes fixed on something "
                 "off-frame to the side — never the lens. He is holding something in. "
                 "Something out of focus crosses the very front of the frame. "
                 "Shallow depth of field, the background dissolved into soft shapes."),
    },
    {
        "key": "high_small",
        "label": "하이앵글 · 작게",
        "desc": ("A high-angle wide shot looking down at him from above, so that he is small "
                 "and enclosed by the floor and the architecture around him. "
                 "He is turned away from the camera. Cold overhead light."),
    },
    {
        "key": "waist_follow",
        "label": "웨이스트 · 뒤따름",
        "desc": ("A waist-level shot from just behind him, the frame breathing slightly as if "
                 "handheld. His back and one side of his face are visible. "
                 "The space he is facing opens up ahead of him."),
    },
]


# 앵글을 바꾸지 않는 모드. 얼굴 교정만 하고 카메라는 직전 프레임 그대로 둔다.
# 매 씬 앵글이 바뀌면 컷이 계속 튀지만, 얼굴 교정은 매 씬 필요하다.
SHOT_HOLD = {
    "key": "hold",
    "label": "연속 · 동일 구도",
    "hold": True,
    "desc": ("Keep the EXACT same camera setup as the previous still — same angle, "
             "same distance, same framing, same composition, the subject at the same "
             "position and scale in frame. This is the same shot continuing, not a new "
             "one. Do not re-frame, do not move the camera, do not change the lens."),
}


# ── 월드 (연출 프롬프트) ───────────────────────────────
# worlds/<id>.json 에서 읽는다. 코드를 고치지 않고 톤·샷·배우를 바꿀 수 있다.
WORLDS_DIR = ROOT / "config" / "worlds"
_world_cache = {}


def load_world(world_id):
    if world_id in _world_cache:
        return _world_cache[world_id]
    f = WORLDS_DIR / f"{world_id}.json"
    if not f.exists():
        raise FileNotFoundError(f"월드 파일 없음: {f}")
    import json
    w = json.loads(f.read_text(encoding="utf-8"))
    _world_cache[world_id] = w
    return w


def shot_for(index, world=None):
    """씬 순번에 따라 샷을 고른다. 같은 앵글이 연달아 나오지 않게."""
    shots = (world or {}).get("shots") or SHOTS
    return shots[index % len(shots)]


def hold_shot(world=None):
    return (world or {}).get("hold") or SHOT_HOLD


# ─────────────────────────────────────────────────────────────
# 감독 레이어 — 관람객에게는 보이지 않는 연출 지시.
# 관람객은 "무슨 일이 일어나는가"만 쓰고, "어떻게 찍는가"는 전부 여기서 정한다.
# ─────────────────────────────────────────────────────────────
DIRECTOR = (
    "DIRECTION — shoot this in the visual language of the Korean drama Misaeng. "
    "Observational, unglamorous, documentary-adjacent. The camera is a witness that "
    "happens to be in the room, not a storyteller showing off.\n\n"

    "THE FOURTH WALL IS NEVER BROKEN:\n"
    "The man does not know he is being filmed. He never looks into the lens, never "
    "acknowledges the camera, never poses. His eyes are always occupied by something "
    "inside the scene. If his face is toward camera, his gaze is still angled off-frame. "
    "A straight-to-lens portrait look is a failure.\n\n"

    "FRAME THROUGH SOMETHING — this is the signature of the style:\n"
    "Shoot past or through whatever is in the room: a door frame, a glass partition, "
    "blinds, a pillar, a handrail, a gap between surfaces. Let foreground objects sit in "
    "front of him, out of focus, cutting into the frame. He is often partially hidden, "
    "seen between things, or reflected in glass and steel. A clean unobstructed view of "
    "him is the exception, not the rule.\n\n"

    "BLOCKING:\n"
    "Never centre him. Push him off to one side, low in the frame, or small against the "
    "architecture. Give the space more room than the person — the environment presses in "
    "on him. Backs of heads, shoulders and profiles are normal. He may be cut by the edge "
    "of frame.\n\n"

    "LENS:\n"
    "Longer focal length with compressed perspective, shallow depth of field that isolates "
    "him from a busy background. A quiet handheld feel — the frame sits slightly "
    "imperfectly, as if held by a person. No crane moves, no sweeping camera, no dramatic "
    "angles for their own sake.\n\n"

    "LIGHT AND COLOUR — Misaeng palette, NOT Hollywood:\n"
    "Flat overhead fluorescent light, faintly green, ordinary and unflattering. "
    "Desaturated cool grey-blue. Low contrast, milky blacks, no crushed shadows. "
    "NO teal-and-orange grade, no warm amber accents, no rim light, no lens flare, "
    "nothing glossy or advertising-like. Any light source visible is one that actually "
    "exists in that room.\n\n"

    "PERFORMANCE:\n"
    "Interior and suppressed — Korean workplace realism, where people hold everything in. "
    "Stillness, a held breath, eyes moving before the body does. No theatrical gasping, "
    "no wide melodramatic eyes, no hands raised to the face.\n\n"

    "FORBIDDEN: eye contact with camera, posed portrait framing, centred symmetrical hero "
    "shots, teal-and-orange grade, warm golden light, rim light, lens flare, glamour "
    "lighting, plastic retouched skin, text, subtitles, captions, watermarks, logos, "
    "UI overlays.\n"
)

CONTINUITY = (
    "You are given reference photographs of an actor, followed by ONE film still that is "
    "the last frame of the previous shot.\n\n"
    "TASK: produce the FIRST FRAME OF THE NEXT MOMENT in the same scene.\n\n"
    "MUST STAY THE SAME (continuity):\n"
    "· THE ACTOR'S FACE — THIS IS THE SINGLE MOST IMPORTANT REQUIREMENT.\n"
    "  The face must be the man in the reference photographs and no one else: "
    "same bone structure, same slim V-line jaw and short narrow chin, same large dark "
    "eyes and eyelid shape, same straight nose, same full lips, same thick straight brows, "
    "same black hair with a soft fringe over the forehead.\n"
    "  The face in the previous film still HAS DRIFTED and is NOT reliable. "
    "Where the previous still and the references disagree about his face, "
    "THE REFERENCES WIN — repaint the face to match them. "
    "If a viewer would not immediately recognise him as the man in the reference "
    "photographs, the output is WRONG.\n"
    "· His wardrobe: plain white dress shirt with sleeves rolled to the forearm, "
    "dark charcoal trousers, worn brown leather laptop bag.\n"
    "· The location, set dressing and everything in the environment from the previous still.\n"
    "· The desaturated cool grey-blue Misaeng grade, the flat fluorescent light, "
    "the low contrast and the fine 35mm grain.\n\n"
    "· IGNORE the reference photographs' own backgrounds and lighting — "
    "they exist only to identify his face and clothing.\n\n"
)

# 앵글을 바꾸는 경우에만 붙는다
CHANGE_CLAUSE = (
    "MUST CHANGE (this is a new camera setup, not the same frame):\n"
    "· The camera angle, distance and composition, as specified below.\n\n"
    "NEW CAMERA SETUP:\n"
)

# 앵글을 유지하는 경우 — 바꿀 것은 얼굴뿐임을 못박는다
HOLD_CLAUSE = (
    "CAMERA STAYS, THE MOMENT MOVES ON:\n"
    "· Keep the camera exactly where it was — same angle, distance, framing, lens.\n"
    "· Correct the actor's face to match the reference photographs.\n"
    "· BUT the scene has moved forward: what the STORY BEAT describes must now be "
    "visible in this frame. This is the next moment from the same camera position, "
    "not a copy of the previous still.\n\n"
    "CAMERA:\n"
)


def build_continuity(world):
    """월드의 배우·의상·색감을 넣어 연속성 규칙을 만든다."""
    return (
        "You are given reference photographs of an actor, followed by ONE film still that is "
        "the last frame of the previous shot.\n\n"
        "TASK: produce the FIRST FRAME OF THE NEXT MOMENT in the same scene.\n\n"
        "MUST STAY THE SAME (continuity):\n"
        "· THE ACTOR'S FACE — THIS IS THE SINGLE MOST IMPORTANT REQUIREMENT.\n"
        f"  {world['character']}\n"
        "  The face must be the man in the reference photographs and no one else. "
        "The face in the previous film still HAS DRIFTED and is NOT reliable. "
        "Where the previous still and the references disagree about his face, "
        "THE REFERENCES WIN — repaint the face to match them. "
        "If a viewer would not immediately recognise him as the man in the reference "
        "photographs, the output is WRONG.\n"
        f"· His wardrobe: {world['wardrobe']}\n"
        "· The location, set dressing and everything in the environment from the previous still.\n"
        f"· The grade and light: {world['grade']}\n\n"
        "· IGNORE the reference photographs' own backgrounds and lighting — "
        "they exist only to identify his face and clothing.\n\n"
    )


def restage(prev_frame, out_path, shot, beat=None, refs_dir=None, world=None,
            aspect="16:9"):
    """직전 프레임 → 다음 컷의 시작 프레임.

    shot : SHOTS 항목
    beat : 관람객 문장. 새 컷이 무엇을 담아야 하는지 알려준다.
    """
    from google import genai
    from google.genai import types
    from PIL import Image

    prev_frame, out_path = Path(prev_frame), Path(out_path)
    if isinstance(world, str):
        world = load_world(world)
    refs_dir = refs_dir or (ROOT / "static" / world["refsDir"] if world else REFS_DIR)
    # 레퍼런스가 많을수록 느리다. 얼굴 정보가 많은 순으로 3장만.
    order = ["ref_closeup", "ref_quarter", "ref_full", "ref_front", "ref_profile"]
    pool = {p.stem: p for p in Path(refs_dir).glob("*.png")}
    refs = [pool[k] for k in order if k in pool][:REF_LIMIT] or \
        sorted(pool.values())[:REF_LIMIT]
    if not refs:
        raise FileNotFoundError(f"배우 레퍼런스 없음: {refs_dir}")

    clause = HOLD_CLAUSE if shot.get("hold") else CHANGE_CLAUSE
    director = (world or {}).get("director") or DIRECTOR
    continuity = build_continuity(world) if world else CONTINUITY
    prompt = director + "\n" + continuity + clause + shot["desc"]
    if beat:
        prompt += (
            f"\n\nSTORY BEAT — what this frame must show:\n{beat}\n"
            "Compose the frame so this is clearly visible. "
            "Render it as things and actions, never as written words: no captions, "
            "no signage, no readable text, no letters anywhere in the image."
        )

    parts = [Image.open(str(r)) for r in refs] + [Image.open(str(prev_frame)), prompt]

    project_id = _project()
    last = None
    for region in REGIONS:
        try:
            client = genai.Client(vertexai=True, project=project_id, location=region)
            res = client.models.generate_content(
                model=MODEL, contents=parts,
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio=aspect)),
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
    raise RuntimeError(f"리스테이징 실패: {last}")


def _project():
    import os
    for k in ("GOOGLE_CLOUD_PROJECT", "GCP_PROJECT", "SSG_PROJECT"):
        if os.environ.get(k):
            return os.environ[k]
    try:
        import google.auth
        _, p = google.auth.default()
        if p:
            return p
    except Exception:
        pass
    return subprocess.check_output(
        ["gcloud", "config", "get-value", "project"], text=True).strip()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("사용법: python3 restage.py <직전프레임> <출력.png> [샷키] [문장]")
        print("  샷:", ", ".join(s["key"] for s in SHOTS))
        sys.exit(1)
    key = sys.argv[3] if len(sys.argv) > 3 else "profile_glass"
    shot = next((s for s in SHOTS if s["key"] == key), SHOTS[1])
    beat = sys.argv[4] if len(sys.argv) > 4 else None
    print(f"✓ {restage(sys.argv[1], sys.argv[2], shot, beat)}  [{shot['label']}]")
