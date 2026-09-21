#!/usr/bin/env python3
"""프리셋 문장의 1씬 영상을 미리 만들어 둔다.

1씬은 시작 프레임이 시나리오의 seed 로 고정돼 있어 미리 만들 수 있다.
2씬부터는 시작 프레임이 '앞 라운드에서 무엇이 뽑혔는가' 에 달려 있어 불가능하다.

목적은 첫 접촉의 속도다. 프리셋을 고르면 기다림 없이 바로 장면이 나온다.
서버는 canon 이 비어 있고 문장이 프리셋과 정확히 일치할 때만 이 클립을 쓴다.

    python3 Tools/build_presets.py            # 전부
    python3 Tools/build_presets.py isekai     # 한 세계만
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 01_Product/MultiTool
sys.path.insert(0, str(ROOT / "App"))

CONFIG = ROOT / "Config"
SCENES = ROOT / "Static" / "scenes"
STAGED = Path(os.environ.get("SSG_TMP", "/tmp/ssg")) / "presets"
STAGED.mkdir(parents=True, exist_ok=True)


def preset_name(sid, i):
    """서버와 반드시 같은 규칙을 써야 한다."""
    return f"preset_{sid}_{i}.mp4"


def build_one(sc, world, i, text):
    from beat import interpret
    from restage import restage, shot_for
    from generate_clip import generate_clip
    from frames import last_good_frame, duration, trim
    import storage

    sid, gen = sc["id"], sc["generation"]
    name = preset_name(sid, i)
    if storage.clip_size(name) is not None:
        return f"  = {name} 이미 있음"

    base = SCENES / gen["startFrame"].removeprefix("/scenes/")
    beat = interpret(text, world, None)
    shot = shot_for(0, world)          # 첫 참여자 씬은 항상 새 앵글
    staged = STAGED / f"{sid}_{i}.png"
    restage(base, staged, shot, beat=beat, world=world,
            aspect=gen.get("aspect", "16:9"))

    where, _ = generate_clip(
        staged,
        tier=gen.get("tier", "lite"),
        seconds=gen.get("seconds", 4),
        aspect=gen.get("aspect", "16:9"),
        motion="staged",
        beat=beat,
        world=world,
        out_stem=f"preset_{sid}_{i}",
    )

    # 서버와 같은 트리밍. 안 하면 클립 끝과 다음 씬 시작이 어긋난다.
    src = Path(where)
    try:
        _, good = last_good_frame(src, STAGED / f"probe_{sid}_{i}.png")
        if good < duration(src) - 0.4:
            cut = STAGED / f"cut_{sid}_{i}.mp4"
            trim(src, cut, good + 0.05)
            src = cut
    except Exception as e:
        print(f"  ! 트리밍 건너뜀 {sid}/{i} ({type(e).__name__})", flush=True)

    storage.put_clip(name, src.read_bytes())
    return f"  + {name}  ({src.stat().st_size // 1024} KB)  {text}"


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    story = json.loads((CONFIG / "story.json").read_text(encoding="utf-8"))
    jobs = []
    for sid in story["scenarios"]:
        if only and sid != only:
            continue
        sc = json.loads((CONFIG / "scenarios" / f"{sid}.json").read_text(encoding="utf-8"))
        sents = (sc.get("suggest") or {}).get("sentences") or []
        if not sents:
            print(f"  ! {sid}: suggest.sentences 없음")
            continue
        from restage import load_world
        world = load_world(sc["world"]) if sc.get("world") else None
        for i, text in enumerate(sents):
            jobs.append((sc, world, i, text))

    print(f"프리셋 {len(jobs)}편 생성 — 약 ${len(jobs) * 0.2:.1f}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(build_one, *j) for j in jobs]
        for f in futs:
            try:
                print(f.result(), flush=True)
            except Exception as e:
                print(f"  ! 실패 ({type(e).__name__}) {e}", flush=True)


if __name__ == "__main__":
    main()
