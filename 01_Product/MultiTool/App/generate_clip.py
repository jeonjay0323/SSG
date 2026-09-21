#!/usr/bin/env python3
"""
씬 이미지 → 영상 클립 생성기 (Veo 3.1 · image-to-video)

기존 파이프라인의 마지막 칸을 채운다:
    원고 → 스크립트 → [씬 이미지: generate_sageuk.py] → [영상: 이 스크립트] → 합성

핵심 전제:
    씬 이미지를 '시작 프레임'으로 넣으면, 이미 구축한 앵커 기반 캐릭터 일관성이
    영상까지 그대로 이어진다. 텍스트만으로 생성하면 얼굴이 다시 흔들린다.

사용법:
    python generate_clip.py sageuk_v6_unified/act1_scene2_kneeling_drinking_rain.png
    python generate_clip.py <이미지> --tier fast --seconds 6 --motion slow_push
    python generate_clip.py <이미지> --preflight      # 비용만 계산하고 종료 (무료)
    python generate_clip.py <이미지> --yes            # 확인 없이 바로 생성
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 01_Product/MultiTool
CLIPS_DIR = Path(os.environ.get("SSG_CLIPS_DIR", str(ROOT / "Clips")))

# 리전 로테이션 — 기존 스크립트와 동일한 전략(할당량 분산)
REGIONS = ["us-central1", "us-east4", "us-west1", "us-west4"]

# ─────────────────────────────────────────────────────────────
# 티어 — 탐색은 lite, 확정된 프롬프트만 standard.
# 단가는 720p 기준 참고값이며 공식 가격 페이지와 대조할 것.
# ─────────────────────────────────────────────────────────────
TIERS = {
    "lite":     {"model": "veo-3.1-lite-generate-001", "usd_per_sec": 0.05, "note": "탐색용"},
    "fast":     {"model": "veo-3.1-fast-generate-001", "usd_per_sec": 0.10, "note": "중간 검증"},
    "standard": {"model": "veo-3.1-generate-001",      "usd_per_sec": 0.40, "note": "최종본"},
}

# 카메라 무빙 프리셋.
# 씬 이미지가 이미 구도를 확정했으므로, 프롬프트는 '무엇을 그릴지'가 아니라
# '어떻게 움직일지'만 지시한다. 내용을 다시 묘사하면 얼굴이 재생성되며 흔들린다.
MOTION_PRESETS = {
    "slow_push": (
        "Very slow, subtle camera push-in toward the subject. "
        "The subject stays still — only micro-movements: slow blink, faint breath, "
        "slight shift of the eyes. Rain continues to fall steadily. "
        "Cloth and hair move only as much as the wind and rain would move them."
    ),
    "hold": (
        "Locked-off static camera. No camera movement at all. "
        "Only ambient motion: falling rain, drifting mist, the subject's slow blink and breathing. "
        "The composition stays exactly as framed."
    ),
    "drift_left": (
        "Extremely slow lateral camera drift to the left, a few centimeters over the whole shot. "
        "The subject remains still except for breathing and a single slow blink. "
        "Rain falls continuously."
    ),
    "rack_focus": (
        "Camera stays locked. Focus slowly racks from the foreground to the subject's eyes. "
        "The subject does not move except for breathing and a slow blink."
    ),

    # ── 〈지하 1층〉 도입부 전용 ──
    "subtle_hold": (
        "Locked-off static camera, no camera movement. "
        "Only the smallest signs of life: a slow blink, shallow breathing, "
        "a faint shift of weight. Ambient light flickers almost imperceptibly. "
        "Nothing dramatic happens. The shot simply breathes."
    ),
    "door_widen": (
        "Locked-off camera. The elevator doors part a little further, and the blade of light "
        "between them slowly widens across the frame. "
        "CRITICAL: the space beyond the doors stays completely blown out to pure white — "
        "absolutely nothing outside ever becomes visible. No room, no scenery, no figures, "
        "no shapes emerging from the light. Only white. "
        "The man slowly turns his head toward the light and goes still. "
        "He does not step forward. The shot ends before anything is revealed."
    ),

    # 관람객 씬 전용 — 문 밖이 '드러나야' 한다. door_widen 과 정반대 목적이므로 혼동 금지.
    # 카메라는 고정. 움직일수록 인물이 흔들린다.
    "reveal_beyond": (
        "Locked-off camera — the frame does not move, no push-in, no pan, no zoom. "
        "The blown-out white light beyond the open doors resolves into a clear view of "
        "what lies outside. The man stays exactly where he is inside the elevator, "
        "seen from the same angle as the first frame; he only turns his head and reacts. "
        "He does not walk out. "
        "What is revealed beyond the doors is given in the STORY BEAT and must be "
        "clearly and unmistakably visible."
    ),
    "staged": (
        "The camera holds the composition of the first frame — no re-framing, no cut. "
        "Only a very slight, slow drift or breath of movement, as a locked-off cinema "
        "camera would have. Motion comes from the world and from the man's small "
        "gestures: a slow blink, breathing, a turn of the head, cloth settling. "
        "He never looks into the lens."
    ),
    "continue_beyond": (
        "Locked-off camera — the frame does not move. "
        "The scene continues from exactly where the first frame left off, in the same place. "
        "The man stays in shot, same position and scale. "
        "What changes is only what the STORY BEAT describes."
    ),
}

# 관람객 씬용 — 인물은 절대 불변, 바뀌어도 되는 건 '문 밖 세계'뿐.
# (IDENTITY_LOCK 은 '아무것도 바꾸지 말라'는 지시라 관람객 씬에 쓰면 문장이 무시되고,
#  반대로 너무 느슨하게 풀면 인물까지 흔들린다. 그래서 둘을 명시적으로 갈라 적는다.)
CHARACTER_LOCK = (
    "WHAT MUST NOT CHANGE — the man himself:\n"
    "His face, bone structure, short narrow chin and slim V-line jaw, eyes, nose, hairstyle. "
    "His white dress shirt with sleeves rolled to the forearm, dark trousers, "
    "and worn brown leather laptop bag. He is the SAME PERSON in every shot — "
    "if his face differs from the reference images, the output is WRONG. "
    "Also keep the desaturated cool grey-blue Misaeng grade, the flat fluorescent light, "
    "the low contrast and fine 35mm grain, "
    "and keep him at the same position and scale in frame as the first frame.\n\n"
    "WHAT MAY CHANGE — only the world beyond him:\n"
    "The environment visible past the elevator doors changes to match the story beat. "
    "Nothing else changes.\n\n"
    "No text, no captions, no watermarks, no on-screen graphics."
)

# Veo 는 negative_prompt 를 따로 받는다. 프롬프트 본문에 "하지 마"를 적는 것보다
# 이쪽이 잘 듣는다 — 특히 카메라 응시와 화면 텍스트.
NEGATIVE = (
    "looking at the camera, looking into the lens, direct eye contact with the lens, "
    "staring into camera, glancing at camera, addressing the camera, "
    "smiling at the camera, posing for the camera, portrait pose, headshot, "
    "breaking the fourth wall, "
    "text, subtitles, captions, watermark, logo, on-screen graphics, UI overlay, "
    "teal and orange grade, warm golden light, rim light, lens flare, glamour lighting, "
    "centred symmetrical hero shot, studio lighting, plastic retouched skin, "
    "deformed face, distorted features, extra limbs, warping, morphing"
)

# 감독 레이어 — 관람객 문장에는 없는 연출 지시. 모든 관람객 씬에 붙는다.
DIRECTOR = (
    "DIRECTION — shoot this in the visual language of the Korean drama Misaeng. "
    "Observational and unglamorous; the camera is a witness in the room, not a "
    "storyteller showing off.\n"
    "THE FOURTH WALL IS NEVER BROKEN: the man does not know he is being filmed. "
    "He never looks into the lens, never acknowledges or performs for the camera. "
    "Even when his face is toward camera, his eyes stay angled off-frame.\n"
    "Keep him off-centre, partially framed by doorways, glass, pillars or foreground "
    "objects. Backs of heads, shoulders and profiles are normal.\n"
    "Performance is interior and suppressed — stillness, a held breath, eyes moving "
    "before the body. No theatrical reactions, no hands to the face.\n"
    "Flat overhead fluorescent light, faintly green and unflattering. Desaturated cool "
    "grey-blue, low contrast, milky blacks. NO teal-and-orange grade, no warm amber, "
    "no rim light, no lens flare. A quiet handheld feel, longer lens, shallow focus.\n"
    "No text, captions, watermarks or on-screen graphics at any point."
)

ASSET_NOTE = (
    "The additional reference images provided are ASSET references of this exact man "
    "(studio shots on a plain backdrop). Use them ONLY to lock his face, build and wardrobe. "
    "IGNORE their plain gray background and studio lighting entirely — "
    "the shot's location and lighting come from the first frame and the story beat."
)

# 어느 프리셋을 쓰든 항상 붙는 블록 — 정체성 유지가 최우선.
IDENTITY_LOCK = (
    "CRITICAL — IDENTITY LOCK: The provided image is the exact first frame. "
    "Preserve the subject's face, bone structure, hairstyle, costume, lighting and color grade "
    "EXACTLY as in the image. Do not restyle, do not beautify, do not age the face, "
    "do not change the framing or lens. This is a continuation of that frame, not a reinterpretation. "
    "No text, no captions, no watermarks, no on-screen graphics."
)


def build_prompt(motion_key, extra=None, beat=None, has_refs=False, world=None, line=None):
    """beat = 관람객이 쓴 문장. 주어지면 프롬프트 맨 앞에 최우선 지시로 놓는다.

    뒤에 붙이면 카메라 지시와 정체성 고정에 묻혀 무시된다 —
    실제로 그래서 문장과 무관한 영상이 나왔다.
    """
    parts = []
    if beat:
        parts.append(
            "STORY BEAT — THIS IS THE MOST IMPORTANT INSTRUCTION. "
            "The shot exists to show this and nothing else:\n"
            f"{beat}\n"
            "Render this as things and actions that a camera can see. "
            "NEVER render it as written words — no captions, no subtitles, no signage, "
            "no readable text, no letters or characters anywhere in the frame. "
            "If the rest of these notes conflict with the story beat, the story beat wins."
        )
    if line:
        # 대사는 '들리는 것'이다. 글자로 찍히면 한글이 깨져 나온다.
        parts.append(
            "SPOKEN DIALOGUE — the character says this line out loud, in Korean:\n"
            f'"{line}"\n'
            "Audio: a single Korean line delivered in the character's own voice, "
            "matched to the lip movement. No narrator, no translation, no other speech. "
            "The words are HEARD ONLY — they never appear as text, captions or subtitles "
            "anywhere in the frame."
        )
    parts.append(MOTION_PRESETS[motion_key])
    if beat:
        parts.append((world or {}).get("director") or DIRECTOR)
    parts.append(CHARACTER_LOCK if beat else IDENTITY_LOCK)
    if has_refs:
        parts.append(ASSET_NOTE)
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


def gcloud_project():
    """프로젝트 ID. 컨테이너에는 gcloud CLI 가 없으므로 단계적으로 찾는다."""
    for key in ("GOOGLE_CLOUD_PROJECT", "GCP_PROJECT", "SSG_PROJECT"):
        v = os.environ.get(key)
        if v:
            return v
    try:
        import google.auth
        _, project = google.auth.default()
        if project:
            return project
    except Exception:
        pass
    return subprocess.check_output(
        ["gcloud", "config", "get-value", "project"], text=True
    ).strip()


def generate_clip(img_path, tier="lite", seconds=8, motion="slow_push",
                  extra=None, beat=None, refs=None, world=None, aspect="16:9",
                  resolution="720p", audio=False, gcs=None, out_stem=None, on_progress=None,
                  line=None):
    """씬 이미지 → 영상 클립 1편. 성공 시 (출력경로, 메타dict) 반환.

    server.py 등 다른 프로세스에서 재사용하기 위해 CLI와 분리했다.
    on_progress(str) 로 진행 상황을 콜백한다.
    """
    from google import genai
    from google.genai import types

    def say(msg):
        if on_progress:
            on_progress(msg)

    img_path = Path(img_path)
    if not img_path.exists():
        raise FileNotFoundError(img_path)

    t = TIERS[tier]
    est = t["usd_per_sec"] * seconds
    project_id = gcloud_project()
    refs = [Path(r) for r in (refs or []) if Path(r).exists()]
    # reference_images(ASSET) 제약 — 전부 실측으로 확인한 것:
    #   · lite/fast          → 400 "not supported by this model"  (standard 전용)
    #   · 4초                → "supported durations are [8]"       (8초 전용)
    #   · 시작 프레임과 병용 → "Image and reference images cannot be both set."
    # 즉 image-to-video(체이닝)와 reference-to-video 는 배타적 모드다.
    # 이야기의 장소 연속성이 인물 고정보다 중요하므로 체이닝을 우선하고 refs 를 버린다.
    if refs:
        reason = None
        if tier != "standard" or seconds != 8:
            reason = f"standard+8초 전용 (현재 {tier}+{seconds}초)"
        else:
            reason = "시작 프레임과 병용 불가 — 체이닝 우선"
        say(f"레퍼런스 미사용: {reason}")
        refs = []
    prompt = build_prompt(motion, extra, beat, has_refs=bool(refs), world=world, line=line)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    cfg_kwargs = dict(
        aspect_ratio=aspect,
        number_of_videos=1,
        duration_seconds=seconds,
        resolution=resolution,
        person_generation="allow_adult",
        generate_audio=bool(audio or line),
        negative_prompt=(world or {}).get("negative") or NEGATIVE,
    )
    if gcs:
        cfg_kwargs["output_gcs_uri"] = gcs
    if refs:
        # ASSET = 인물/사물 정체성 고정. STYLE 은 화풍용이라 여기선 쓰지 않는다.
        cfg_kwargs["reference_images"] = [
            types.VideoGenerationReferenceImage(
                image=types.Image.from_file(location=str(r)),
                reference_type=types.VideoGenerationReferenceType.ASSET,
            ) for r in refs
        ]

    stem = out_stem or f"{img_path.stem}__{tier}_{motion}_{seconds}s"
    last_err = None
    unavailable = []

    for region in REGIONS:
      for attempt in range(3):
        try:
            say(f"{region} 요청" + (f" (재시도 {attempt})" if attempt else ""))
            client = genai.Client(vertexai=True, project=project_id, location=region)
            op = client.models.generate_videos(
                model=t["model"],
                prompt=prompt,
                image=types.Image.from_file(location=str(img_path)),
                config=types.GenerateVideosConfig(**cfg_kwargs),
            )

            # 폴링 간격이 길면 완성 후에도 그만큼 놀게 된다.
            # 대기 시간이 곧 이탈이라 촘촘하게 본다.
            waited = 0
            while not op.done:
                time.sleep(3)
                waited += 3
                op = client.operations.get(op)
                say(f"생성 중 {waited}초")
                if waited > 600:
                    raise TimeoutError("10분 초과")

            if getattr(op, "error", None):
                e = op.error
                # code 8 = 서비스 과부하. 잠깐 쉬고 같은 리전에서 다시.
                if isinstance(e, dict) and e.get("code") == 8 and attempt < 2:
                    say("과부하 — 재시도 대기")
                    time.sleep(15)
                    continue
                raise RuntimeError(e)
            videos = op.response.generated_videos
            if not videos:
                # 드물게 성공 응답인데 비어서 온다. 대개 일시적이라 재시도한다.
                if attempt < 2:
                    say("빈 결과 — 재시도")
                    time.sleep(5)
                    continue
                raise RuntimeError("결과가 비어 있음 (안전 필터 차단 가능성)")

            out = CLIPS_DIR / f"{stem}.mp4"
            v = videos[0].video
            if getattr(v, "video_bytes", None):
                out.write_bytes(v.video_bytes)
                where = str(out)
            else:
                where = getattr(v, "uri", "(uri 없음)")

            meta = {
                "source_image": str(img_path), "model": t["model"], "tier": tier,
                "seconds": seconds, "resolution": resolution, "aspect": aspect,
                "motion": motion, "audio": audio, "region": region,
                "refs": [r.name for r in refs],
                "prompt": prompt, "estimated_usd": round(est, 3), "output": where,
            }
            (CLIPS_DIR / f"{stem}.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            say("완료")
            return where, meta

        except Exception as e:
            msg = str(e)
            if "was not found or your project does not have access" in msg:
                say(f"{region}: 이 리전에 모델 없음 — 건너뜀")
                unavailable.append(region)
            else:
                say(f"{region} 실패: {type(e).__name__}")
                last_err = e          # 의미 있는 에러만 보존
            break

    if last_err is None and unavailable:
        raise RuntimeError(
            f"'{t['model']}' 을(를) 쓸 수 있는 리전이 없습니다 "
            f"(미지원: {', '.join(unavailable)})")
    raise RuntimeError(f"모든 리전 실패: {last_err}")


def main():
    ap = argparse.ArgumentParser(description="씬 이미지 → Veo 3.1 영상 클립")
    ap.add_argument("image", help="시작 프레임으로 쓸 씬 이미지 경로")
    ap.add_argument("--tier", choices=TIERS, default="lite")
    ap.add_argument("--seconds", type=int, default=8, help="클립 길이(초)")
    ap.add_argument("--motion", choices=MOTION_PRESETS, default="slow_push")
    ap.add_argument("--extra", default=None, help="프롬프트에 추가할 연출 지시")
    ap.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    ap.add_argument("--resolution", default="720p", choices=["720p", "1080p"])
    ap.add_argument("--audio", action="store_true", help="Veo 네이티브 오디오 생성")
    ap.add_argument("--gcs", default=None, help="결과 저장 GCS URI (필요한 경우)")
    ap.add_argument("--preflight", action="store_true", help="비용만 계산하고 종료")
    ap.add_argument("--yes", action="store_true", help="확인 프롬프트 건너뛰기")
    args = ap.parse_args()

    img_path = Path(args.image)
    if not img_path.is_absolute():
        img_path = ROOT / img_path
    if not img_path.exists():
        print(f"[Error] 이미지 없음: {img_path}")
        sys.exit(1)

    tier = TIERS[args.tier]
    est = tier["usd_per_sec"] * args.seconds

    print("─" * 58)
    print(f"  시작 프레임 : {img_path.name}")
    print(f"  티어        : {args.tier} ({tier['note']}) — {tier['model']}")
    print(f"  길이/해상도 : {args.seconds}초 · {args.resolution} · {args.aspect}")
    print(f"  카메라      : {args.motion}")
    print(f"  오디오      : {'생성' if args.audio else '없음'}")
    print(f"  예상 비용   : 약 ${est:.2f}  ({tier['usd_per_sec']}/초 × {args.seconds}초)")
    print("─" * 58)

    if args.preflight:
        print("preflight 모드 — 생성하지 않고 종료합니다.")
        return

    if not args.yes:
        ans = input(f"생성할까요? 약 ${est:.2f} 청구됩니다. [y/N] ").strip().lower()
        if ans != "y":
            print("취소됨.")
            return

    try:
        where, meta = generate_clip(
            img_path, tier=args.tier, seconds=args.seconds, motion=args.motion,
            extra=args.extra, aspect=args.aspect, resolution=args.resolution,
            audio=args.audio, gcs=args.gcs,
            on_progress=lambda m: print(f"  · {m}", flush=True),
        )
    except Exception as e:
        print(f"\n[Error] {e}")
        sys.exit(1)

    print(f"\n✓ 완료 → {where}")
    print(f"  파라미터 → {CLIPS_DIR / (Path(where).stem + '.json')}")


if __name__ == "__main__":
    main()
