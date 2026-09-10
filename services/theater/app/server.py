#!/usr/bin/env python3
"""
슥 · 한 줄 극장 — 로컬 서버 (라운드 + 투표)

  폰 /write  ──POST /api/submit──▶  라운드 후보 풀
                                        │ 접수 마감
                                        ▼
                                   후보 N개 추출 → 동시 생성 (Veo)
                                        │
                                        ▼
  폰 /write  ──POST /api/vote────▶   투표
                                        │ 마감
                                        ▼
                                   당선작이 정사(canon)로 편입
                                        │
  대형화면 /stage ──GET /api/round──▶  상영

라운드 단계:
    submit(접수) → generate(생성) → vote(투표) → reveal(발표) → 다음 라운드

실행:
    python3 server.py                 # 드라이런 (Veo 호출 없음, 무료)
    python3 server.py --live          # 실제 생성 (과금)
    python3 server.py --live --max 12 # 최대 12건 생성 후 자동 드라이런 전환

    폰 입력  http://<호스트>:8778/write
    상영     http://<호스트>:8778/stage
"""

import argparse
import json
import os
import random
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # services/theater
ACTORS_DIR = Path.home() / "Desktop" / "SSG" / "09_Actors"
SCENES_DIR = ROOT / "static" / "scenes"          # 전시 전용 도입부 이미지 (이미지에 동봉)
if ACTORS_DIR.exists():               # 로컬 개발에서만 존재
    sys.path.insert(0, str(ACTORS_DIR))

import storage

# 체인 프레임은 파생물이라 휘발성 경로에 둔다. 없으면 원본 클립에서 다시 뽑는다.
CHAIN_DIR = Path(os.environ.get("SSG_TMP", "/tmp/ssg")) / "chain"

STORY_PATH = ROOT / "config" / "story.json"


SCENARIOS_DIR = ROOT / "config" / "scenarios"


def load_story():
    """story.json(공통) + scenarios/<id>.json(각 이야기)를 합쳐 돌려준다.

    이야기와 연출 프롬프트를 코드 밖에서 관리하려고 파일을 나눴다.
    프롬프트는 worlds/<id>.json 에 있고 restage/generate_clip 이 읽는다.
    """
    story = json.loads(STORY_PATH.read_text(encoding="utf-8"))
    out = []
    for sid in story.get("scenarios", []):
        f = SCENARIOS_DIR / f"{sid}.json"
        if not f.exists():
            print(f"  ! 시나리오 파일 없음: {f.name}", flush=True)
            continue
        out.append(json.loads(f.read_text(encoding="utf-8")))
    story["scenarios"] = out
    return story


# ─────────────────────────────────────────────────────────────
# 라운드 상태
# ─────────────────────────────────────────────────────────────
class Track:
    """이야기 하나. 시나리오마다 하나씩, 서로 독립적으로 돈다."""

    def __init__(self, scenario, cfg):
        self.lock = threading.RLock()
        self.cfg = cfg
        self.sid = scenario["id"]
        self.scenario = scenario

        self.round_n = 0
        self.phase = "idle"       # idle → collect → generate → [vote] → reveal
        self.deadline = None
        self.pool = []
        self.candidates = []
        self.votes = {}
        self.winner = None
        self.contested = False
        self.canon = []
        self.cycle = 0        # 완결·초기화 때마다 증가 (체인 프레임 캐시 분리용)
        self.start_round()

    # ── 단계 ──
    def _set(self, phase, seconds=None):
        self.phase = phase
        self.deadline = None if seconds is None else time.monotonic() + seconds

    def start_round(self):
        with self.lock:
            self.round_n += 1
            self.pool, self.candidates, self.votes = [], [], {}
            self.winner, self.contested = None, False
            for d in (PRESTAGE, BEATS):
                for k in [k for k in d if k.startswith(self.sid + ":")]:
                    d.pop(k, None)
            self._set("idle")

    def remaining(self):
        if self.deadline is None:
            return None
        return max(0, round(self.deadline - time.monotonic()))

    def done(self, max_scenes):
        return len(self.canon) >= max_scenes

    # ── 접수 ──
    @staticmethod
    def clean_nick(nick):
        """닉네임도 큰 화면에 뜨므로 문장과 같은 기준으로 거른다."""
        n = (nick or "").strip()[:12]
        if not n:
            return ""
        ok, _ = screen_text(n)
        return n if ok else ""

    def submit(self, text, voter, nick=""):
        text = (text or "").strip()
        with self.lock:
            if self.phase not in ("idle", "collect"):
                return False, "지금은 이 이야기의 접수 시간이 아닙니다"
            if not text:
                return False, "문장을 입력해주세요"
            if len(text) > self.cfg.get("maxChars", 40):
                return False, f"{self.cfg.get('maxChars', 40)}자 이내로 써주세요"
            if any(p["voter"] == voter for p in self.pool):
                return False, "이번 라운드엔 이미 참여하셨습니다"
            ok, why = screen_text(text)
            if not ok:
                print(f"  ✗ [{self.sid}] 차단({why}): {text[:24]}", flush=True)
                return False, "다시 써주시겠어요? 이야기에 어울리는 한 문장이면 좋겠습니다"

            opened = self.phase == "idle"
            if opened:
                self._set("collect", self.cfg["collectSeconds"])
            sub = {"id": f"{self.sid}:{uuid.uuid4().hex[:8]}", "text": text,
                   "voter": voter, "nick": self.clean_nick(nick)}
            self.pool.append(sub)
            n = len(self.pool)
        print(f"  + [{self.sid}] 접수 {n}건: {text[:24]}", flush=True)
        return True, sub

    # ── 투표 ──
    def vote(self, cand_id, voter):
        with self.lock:
            if self.phase != "vote":
                return False, "지금은 투표 시간이 아닙니다"
            if not any(c["id"] == cand_id for c in self.candidates):
                return False, "없는 후보입니다"
            first = voter not in self.votes
            self.votes[voter] = cand_id
            tally = {}
            for cid in self.votes.values():
                tally[cid] = tally.get(cid, 0) + 1
            for c in self.candidates:
                c["votes"] = tally.get(c["id"], 0)
            return True, ("투표 완료" if first else "투표를 변경했습니다")

    def reset(self):
        with self.lock:
            self.canon = []
            self.round_n = 0
            self.cycle += 1
        self.start_round()

    def snapshot(self):
        with self.lock:
            return {
                "id": self.sid,
                "title": self.scenario["title"],
                "lead": self.scenario.get("lead", ""),
                "poster": self.scenario.get("poster"),
                "round": self.round_n,
                "phase": self.phase,
                "remaining": self.remaining(),
                "poolCount": len(self.pool),
                "pool": [{"text": p["text"], "nick": p.get("nick", "")}
                         for p in self.pool][-4:],
                "candidates": [
                    {k: c.get(k) for k in ("id", "text", "nick", "video", "still",
                                            "status", "progress", "votes")}
                    for c in self.candidates
                ],
                "winner": self.winner,
                "contested": self.contested,
                "canon": self.canon,
                "totalVotes": len(self.votes),
            }


class Engine:
    """트랙 3개를 함께 돌린다. 예산·생성 카운터는 전체가 공유한다."""

    def __init__(self, story, cfg, live, max_gen, budget_usd=None):
        self.lock = threading.RLock()
        self.cfg = cfg
        self.story = story
        self.live = live
        self.max_gen = max_gen
        self.budget_usd = budget_usd

        self.spent_usd = 0.0
        self.generated = 0
        self.tracks = {sc["id"]: Track(sc, cfg) for sc in story["scenarios"]}
        print("  트랙: " + " · ".join(t.scenario["title"] for t in self.tracks.values()),
              flush=True)

    def track(self, sid):
        return self.tracks.get(sid)

    def can_generate(self):
        if not self.live:
            return False
        if self.generated >= self.max_gen:
            return False
        if self.budget_usd is not None and self.spent_usd >= self.budget_usd:
            return False
        return True

    def snapshot(self):
        # 락 순서 역전 방지: 트랙 스냅샷을 먼저 뜨고(각자 tr.lock),
        # 그 다음에 공유 카운터만 eng.lock 으로 읽는다.
        # eng.lock 을 쥔 채 tr.lock 을 잡으면 드라이버와 데드락이 난다.
        tracks = [t.snapshot() for t in list(self.tracks.values())]
        with self.lock:
            spent, gen = round(self.spent_usd, 2), self.generated
            live = self.can_generate()
        return {
            "tracks": tracks,
            "spentUsd": spent,
            "generated": gen,
            "live": live,
            "budgetUsd": self.budget_usd,
            "maxScenes": self.story.get("maxScenes", 6),
        }


def asset_refs():
    """인물 ASSET 레퍼런스. 환경이 바뀌어도 얼굴을 고정하는 용도."""
    if not REFS_DIR.exists():
        return []
    return sorted(str(p) for p in REFS_DIR.glob("*.png"))


def chain_start_frame(tr):
    """씬 N 의 시작 프레임 = 직전 확정 씬 영상의 마지막 프레임.

    이게 없으면 모든 관람객 씬이 도입부 씬 2 에서 다시 시작해서,
    이야기는 나아가는데 그림은 매번 리셋된다.
    """
    # startFrame 은 "/scenes/..." 형태의 URL. 하위 폴더(chain/)가 있으므로
    # 파일명만 떼면 안 되고 /scenes/ 접두사만 벗겨야 한다.
    rel = tr.scenario["generation"]["startFrame"].removeprefix("/scenes/")
    default = SCENES_DIR / rel
    with tr.lock:
        prev = tr.canon[-1] if tr.canon else None
    if not prev or not prev.get("video"):
        return default

    name = Path(prev["video"]).name
    # 사이클을 파일명에 넣는다. 완결 후 씬 번호가 1 로 돌아가므로
    # 이게 없으면 새 이야기가 옛 이야기의 프레임에서 이어진다.
    out = CHAIN_DIR / f"{tr.sid}c{tr.cycle}_after{prev['n']}.png"
    if out.exists():
        return out
    try:
        from frames import last_good_frame
        src = storage.clip_to_tempfile(name, CHAIN_DIR / name)
        path, ts = last_good_frame(src, out)
        print(f"  체인 프레임: {src.name} @ {ts:.1f}s → {out.name}", flush=True)
        return path
    except Exception as e:
        print(f"  ! 체이닝 실패 ({type(e).__name__}) — 기본 시작 프레임 사용", flush=True)
        return default


# 제출 id → 미리 세워둔 시작 프레임(Future)
PRESTAGE = {}
PRESTAGE_POOL = ThreadPoolExecutor(max_workers=4)


def wants_new_angle(gen, scene_idx):
    """이번 씬에서 카메라 앵글을 바꿀지.

    얼굴 교정과는 별개다 — 교정은 매 씬 하고, 앵글만 주기적으로 바꾼다.
    (둘을 묶어두면 앵글을 유지하는 씬에 레퍼런스가 아예 안 들어간다.)
    restageEvery: 0 = 앵글 항상 고정, 1 = 매 씬 새 앵글, 2 = 한 씬 걸러.
    """
    # 첫 관람객 씬은 항상 새 앵글이다. 도입부가 던진 질문("문 밖에 있던 것은")에
    # 답해야 하는데, 구도를 그대로 유지하면 도입부와 거의 같은 그림이 나온다.
    if scene_idx == 0:
        return True
    every = gen.get("restageEvery", 1)
    if not every:
        return False
    return scene_idx % every == (every - 1)


# 해석된 장면 묘사 — 리스테이징과 Veo 가 같은 문구를 쓰도록 보관한다
BEATS = {}


def interpret_beat(tr, text, world):
    """관람객 문장 → 촬영 가능한 묘사. 실패하면 원문."""
    try:
        from beat import interpret
        with tr.lock:
            prev = tr.canon[-1]["text"] if tr.canon else None
        return interpret(text, world, prev)
    except Exception as e:
        print(f"  ! 문장 해석 실패 ({type(e).__name__}) — 원문 사용", flush=True)
        return text


def prestage(eng, tr, sub_id, text):
    """제출 즉시 다음 컷 프레임을 미리 세운다 (접수 창과 병행).

    후보는 접수 마감 때 뽑히지만, 대개 제출 수가 후보 수 이하라
    거의 모든 제출이 그대로 후보가 된다. 미리 만들어두면 헛일이 드물다.
    """
    with tr.lock:
        idx = len(tr.canon)
    gen = tr.scenario["generation"]
    world_id = tr.scenario.get("world")

    def work():
        # 얼굴 교정은 매 씬 필수. 앵글만 주기적으로 바꾼다.
        from restage import restage, shot_for, hold_shot, load_world
        w = load_world(world_id) if world_id else None
        shot = shot_for(idx, w) if wants_new_angle(gen, idx) else hold_shot(w)
        beat = interpret_beat(tr, text, w)
        base = chain_start_frame(tr)
        out = CHAIN_DIR / f"staged_{sub_id.replace(':', '_')}.png"
        restage(base, out, shot, beat=beat, world=w,
                aspect=gen.get("aspect", "16:9"))
        BEATS[sub_id] = beat
        return out, shot

    PRESTAGE[sub_id] = PRESTAGE_POOL.submit(work)


def staged_start_frame(eng, tr, cand, prog):
    """다음 컷의 시작 프레임을 새로 세운다.

    직전 프레임을 그대로 쓰면 얼굴이 밀리고 앵글이 늘 같다.
    이미지 모델로 한 번 거치면서 얼굴을 레퍼런스로 되돌리고
    샷 타입을 바꿔 '편집된 컷'처럼 만든다.
    실패하면 원본 체인 프레임으로 조용히 폴백한다.
    """
    fut = PRESTAGE.pop(cand["id"], None)
    if fut is not None:
        try:
            prog("컷 세우는 중")
            out, shot = fut.result(timeout=90)
            return out, shot
        except Exception as e:
            print(f"  ! 선행 리스테이징 실패 ({type(e).__name__})", flush=True)

    base = chain_start_frame(tr)
    with tr.lock:
        idx = len(tr.canon)
    try:
        from restage import restage, shot_for, hold_shot, load_world
        sc = tr.scenario
        gen = sc["generation"]
        w = load_world(sc["world"]) if sc.get("world") else None
        shot = shot_for(idx, w) if wants_new_angle(gen, idx) else hold_shot(w)
        out = CHAIN_DIR / f"staged_{cand['id'].replace(':', '_')}.png"
        prog(f"컷 세우는 중 · {shot['label']}")
        beat = BEATS.get(cand["id"]) or interpret_beat(tr, cand["text"], w)
        BEATS[cand["id"]] = beat
        restage(base, out, shot, beat=beat, world=w,
                aspect=gen.get("aspect", "16:9"))
        return out, shot
    except Exception as e:
        print(f"  ! 리스테이징 실패 ({type(e).__name__}) — 원본 프레임 사용", flush=True)
        return base, None


def make_candidate_video(eng, tr, cand):
    gen = tr.scenario["generation"]
    do_live = eng.can_generate()

    def prog(m):
        with tr.lock:
            cand["progress"] = m

    start, shot = (staged_start_frame(eng, tr, cand, prog)
                   if do_live else (chain_start_frame(tr), None))

    if not do_live:
        prog("드라이런")
        time.sleep(2)
        with tr.lock:
            cand["still"] = "/scenes/" + start.relative_to(SCENES_DIR).as_posix()
            cand["progress"] = "드라이런"
            cand["status"] = "ready"        # 마지막
        return

    # 리스테이징된 첫 프레임을 즉시 화면에 내보낸다. 생성이 끝날 때까지의
    # 빈 시간이 "내 문장의 첫 프레임을 보는 시간"이 된다.
    try:
        if start and Path(start).parent == CHAIN_DIR:
            with tr.lock:
                cand["still"] = "/staged/" + Path(start).name
    except Exception:
        pass

    try:
        from generate_clip import generate_clip
        prog("생성 중")
        where, meta = generate_clip(
            start,
            tier=gen.get("tier", "lite"),
            seconds=gen.get("seconds", 4),
            aspect=gen.get("aspect", "16:9"),
            # 리스테이징으로 프레이밍이 이미 정해졌으면 카메라를 붙잡아 둔다.
            # 아니면 첫 관람객 씬만 '문 밖이 드러나는' 샷.
            motion=("staged" if shot else
                    ("reveal_beyond" if not tr.canon else "continue_beyond")),
            # 관람객 문장은 최우선 지시(beat)로 프롬프트 맨 앞에 놓인다.
            # extra 로 뒤에 붙이면 카메라·정체성 지시에 묻혀 무시된다.
            beat=BEATS.get(cand["id"]) or cand["text"],
            world=(__import__("restage").load_world(tr.scenario["world"])
                   if tr.scenario.get("world") else None),
            out_stem=f"{tr.sid}_{tr.round_n}_{cand['id'].split(':')[-1]}",
            on_progress=prog,
        )
        # 화이트아웃 등으로 끝부분이 못 쓰는 프레임이면 잘라낸다. 안 그러면 클립은
        # 끝까지 재생되는데 다음 씬은 그 앞 상태에서 시작해 되감기처럼 보인다.
        # (파일 작업이므로 어떤 락도 잡지 않는다)
        try:
            from frames import last_good_frame, duration, trim
            src = Path(where)
            safe = cand["id"].replace(":", "_")
            _, good_ts = last_good_frame(src, CHAIN_DIR / f"probe_{safe}.png")
            if good_ts < duration(src) - 0.4:
                trimmed = CHAIN_DIR / f"cut_{safe}.mp4"
                trim(src, trimmed, good_ts + 0.05)
                where = str(trimmed)
                prog(f"끝 정리 ({good_ts:.1f}초)")
        except Exception as e:
            print(f"  ! 트림 건너뜀 ({type(e).__name__})", flush=True)

        name = Path(where).name
        if storage.using_gcs() and Path(where).exists():
            storage.put_clip(name, Path(where).read_bytes())

        with eng.lock:                      # 공유 카운터
            eng.spent_usd += meta["estimated_usd"]
            eng.generated += 1
        with tr.lock:
            cand["video"] = "/clips/" + name
            cand["shot"] = shot["label"] if shot else None
            cand["progress"] = "완료"
            cand["status"] = "ready"        # 반드시 마지막 — 드라이버가 이걸 보고 확정한다
    except Exception as e:
        print(f"  ✗ 생성 실패 {cand['id']}: {str(e)[:150]}", flush=True)
        with tr.lock:
            cand["status"] = "ready"          # 실패해도 투표는 진행 — 정지화면으로
            cand["still"] = "/scenes/" + start.relative_to(SCENES_DIR).as_posix()
            cand["progress"] = "생성 실패 · 정지화면"


# ─────────────────────────────────────────────────────────────
# 입력 필터
#
# 전시는 무인 운영이고, 관람객 문장은 대형 화면에 그대로 자막으로 뜬다.
# Veo 자체 안전 필터는 '영상 생성'만 막을 뿐 문장 노출은 못 막는다.
# 접수 시점에 걸러야 화면에 아예 안 뜬다.
# ─────────────────────────────────────────────────────────────
BLOCKLIST = [
    # 욕설·비속어
    "씨발", "시발", "ㅅㅂ", "병신", "ㅂㅅ", "지랄", "좆", "존나", "새끼", "개새",
    "미친놈", "미친년", "닥쳐", "꺼져", "엿먹",
    # 성적 표현
    "섹스", "야동", "자위", "성기", "강간", "성폭행",
    # 혐오·차별
    "한남", "김치녀", "된장녀", "틀딱", "급식충", "맘충", "장애인새끼",
    # 폭력
    "죽여", "죽인다", "자살", "테러", "폭탄",
]


# 호환 자모(ㅅ, ㅣ) → 조합용 자모. 이걸 거쳐야 NFC 로 '시'가 된다.
# "ㅅ ㅣ 발" 같은 분리 입력이 그냥은 안 걸리기 때문에 필요하다.
_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"


def _normalize(text):
    import re
    import unicodedata
    t = unicodedata.normalize("NFKC", text).lower()
    # 글자 사이에 낀 공백·기호·숫자 제거 (ㅅ.ㅣ.발, 시-발 등)
    t = re.sub(r"[\s\W_0-9]+", "", t, flags=re.UNICODE)
    # 분리된 자모를 음절로 합친다.
    # NFKC 가 호환 자모(ㅅ U+3145)를 조합용 자모(U+1109)로 이미 바꿔놓으므로
    # 두 표현을 모두 인덱스로 변환해야 한다.
    def cho_idx(c):
        o = ord(c)
        if 0x1100 <= o <= 0x1112:
            return o - 0x1100
        return _CHO.index(c) if c in _CHO else None

    def jung_idx(c):
        o = ord(c)
        if 0x1161 <= o <= 0x1175:
            return o - 0x1161
        return _JUNG.index(c) if c in _JUNG else None

    out, i = [], 0
    while i < len(t):
        a = cho_idx(t[i])
        b = jung_idx(t[i + 1]) if i + 1 < len(t) else None
        if a is not None and b is not None:
            out.append(chr(0xAC00 + (a * 21 + b) * 28))
            i += 2
        else:
            out.append(t[i])
            i += 1
    return "".join(out)


def screen_text(text):
    """(통과여부, 사유). 애매하면 통과시킨다 — 과잉 차단이 더 나쁘다."""
    t = _normalize(text)
    for w in BLOCKLIST:
        if w in t:
            return False, "표현"
    # 같은 글자 6회 이상 반복 (ㅋㅋㅋㅋㅋㅋ, ㅁㅁㅁㅁㅁㅁ 등 도배)
    run = 1
    for a, b in zip(t, t[1:]):
        run = run + 1 if a == b else 1
        if run >= 6:
            return False, "반복"
    # 링크·연락처 — 정규화하면 구두점이 사라지므로 원문으로 본다
    raw = text.lower()
    if any(k in raw for k in ("http://", "https://", "www.", ".com", ".net", ".kr", "@")):
        return False, "링크"
    return True, None




def save_snapshot(eng):
    """확정된 이야기를 디스크에 남긴다.

    전시 중 서버가 한 번 죽으면 그날 쌓인 이야기가 통째로 사라진다.
    라운드가 확정될 때마다 저장하고, 기동 시 읽어와 이어간다.
    임시 파일에 쓰고 교체 — 쓰는 도중 죽어도 기존 스냅샷이 살아남는다.
    """
    tracks = {}
    for sid, t in list(eng.tracks.items()):
        with t.lock:
            tracks[sid] = {"round": t.round_n, "canon": list(t.canon)}
    with eng.lock:
        data = {"tracks": tracks,
                "spentUsd": round(eng.spent_usd, 4),
                "generated": eng.generated}
    try:
        storage.put_state(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"  ! 스냅샷 저장 실패: {type(e).__name__}", flush=True)


def load_snapshot(eng):
    try:
        raw = storage.get_state()
        if not raw:
            return
        d = json.loads(raw)
    except Exception as e:
        print(f"  ! 스냅샷 읽기 실패: {type(e).__name__} — 새로 시작", flush=True)
        return
    with eng.lock:
        eng.spent_usd = d.get("spentUsd", 0.0)
        eng.generated = d.get("generated", 0)
        for sid, td in (d.get("tracks") or {}).items():
            t = eng.tracks.get(sid)
            if t:
                t.canon = td.get("canon", [])
                t.round_n = max(t.round_n, td.get("round", 1))
    n = sum(len(t.canon) for t in eng.tracks.values())
    if n:
        print(f"  ↻ 스냅샷 복구: 씬 {n}개 · "
              f"생성 {eng.generated}건 · ${eng.spent_usd:.2f}", flush=True)


def _commit_winner(eng, tr):
    """당선작을 그 트랙의 정사(canon)에 편입. 호출자가 tr.lock 을 잡고 있어야 한다."""
    w = next((c for c in tr.candidates if c["id"] == tr.winner), None)
    if not w:
        return
    tr.canon.append({
        "n": len(tr.scenario["scenes"]) + len(tr.canon) + 1,
        "text": w["text"], "nick": w.get("nick", ""),
        "video": w["video"], "still": w["still"],
        "votes": w["votes"], "contested": tr.contested,
        "shot": w.get("shot"),
    })


def advance(eng, tr, story, pool):
    """트랙 하나의 단계를 한 틱만큼 진행시킨다."""
    # 생성 완료 감지는 데드라인과 무관하게 매 틱 확인한다.
    committed = False
    with tr.lock:
        if tr.phase == "generate" and tr.candidates and \
           all(c["status"] == "ready" for c in tr.candidates):
            if len(tr.candidates) > 1:
                tr.contested = True
                tr._set("vote", tr.cfg["voteSeconds"])
                print(f"  [{tr.sid}] 생성 완료 — 후보 {len(tr.candidates)}개, 투표", flush=True)
            else:
                tr.winner = tr.candidates[0]["id"]
                tr._set("reveal", tr.cfg.get("revealSeconds", 10))
                _commit_winner(eng, tr)
                committed = True
                print(f"  [{tr.sid}] 생성 완료 — 단독, 투표 없이 확정", flush=True)
            phase, left = tr.phase, tr.remaining()
            done_here = True
        else:
            phase, left = tr.phase, tr.remaining()
            done_here = False

    # 락 밖에서 저장한다. 안에서 하면 eng.lock 과 순서가 엇갈려 데드락이 난다.
    if committed:
        save_snapshot(eng)
    if done_here:
        return

    if left is None or left > 0:
        return

    if phase == "collect":
        with tr.lock:
            k = min(tr.cfg["candidates"], len(tr.pool))
            picked = random.sample(tr.pool, k)
            tr.candidates = [{
                "id": p["id"], "text": p["text"], "nick": p.get("nick", ""),
                "video": None, "still": None,
                "status": "generating", "progress": "대기", "votes": 0,
            } for p in picked]
            tr._set("generate", 600)
            dropped = len(tr.pool) - k
        print(f"  [{tr.sid}] 접수 마감 — {k}개"
              + (f" ({dropped}건 미채택)" if dropped else "")
              + ("  · 투표 예정" if k > 1 else "  · 단독"), flush=True)
        for c in tr.candidates:
            pool.submit(make_candidate_video, eng, tr, c)

    elif phase == "generate":
        with tr.lock:
            for c in tr.candidates:
                if c["status"] != "ready":
                    c["status"] = "ready"
                    c["still"] = tr.scenario["generation"]["startFrame"]
                    c["progress"] = "시간 초과 · 정지화면"
            tr._set("vote", tr.cfg["voteSeconds"])
        print(f"  [{tr.sid}] 생성 시간 초과 — 투표로 진행", flush=True)

    elif phase == "vote":
        with tr.lock:
            best = max(tr.candidates, key=lambda c: c["votes"])
            tr.winner = best["id"]
            tr._set("reveal", tr.cfg.get("revealSeconds", 10))
            _commit_winner(eng, tr)
        save_snapshot(eng)              # 락 밖에서
        print(f"  [{tr.sid}] 투표 마감 — {best['text'][:22]} ({best['votes']}표)", flush=True)

    elif phase == "reveal":
        if tr.done(story.get("maxScenes", 6)):
            # 완결된 이야기를 잠시 그대로 둔다. 바로 지우면 완성된 한 편을
            # 아무도 보지 못한 채 사라진다.
            with tr.lock:
                tr._set("finale", tr.cfg.get("finaleSeconds", 25))
            print(f"  [{tr.sid}] ■ 〈{tr.scenario['title']}〉 완결 — "
                  f"{tr.cfg.get('finaleSeconds', 25)}초 상영 후 새 이야기", flush=True)
        else:
            tr.start_round()

    elif phase == "finale":
        tr.reset()
        save_snapshot(eng)
        print(f"  [{tr.sid}] 새 이야기 시작", flush=True)


def driver(eng):
    """세 트랙을 동시에 굴린다."""
    story = load_story()
    pool = ThreadPoolExecutor(max_workers=6)
    while True:
        time.sleep(0.4)
        for tr in list(eng.tracks.values()):
            try:
                advance(eng, tr, story, pool)
            except Exception as e:
                print(f"  ! [{tr.sid}] 진행 실패 {type(e).__name__}: {str(e)[:120]}",
                      flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(data)

    def _file(self, path, ctype):
        if not path.exists():
            return self._send(404, {"error": "not found"})
        self._send(200, path.read_bytes(), ctype)

    def _clip(self, name):
        """클립은 로컬/GCS 어느 쪽에 있든 Range(206)로 서빙한다."""
        size = storage.clip_size(name)
        if size is None:
            return self._send(404, {"error": "not found"})
        rng = self.headers.get("Range")
        start, end, status = 0, size - 1, 200
        if rng and rng.startswith("bytes="):
            spec = rng.split("=", 1)[1].split(",")[0].strip()
            a, _, b = spec.partition("-")
            try:
                if a:
                    start = int(a)
                    if b:
                        end = min(int(b), size - 1)
                elif b:
                    start = max(0, size - int(b))
                status = 206
            except ValueError:
                start, end, status = 0, size - 1, 200
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        data = storage.read_clip(name, start, end) if status == 206 \
            else storage.read_clip(name)
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def _media(self, path, ctype):
        """미디어는 Range 요청(206)을 지원해야 한다.
        브라우저는 <video> 로드 시 Range 를 보내는데, 200 으로 전체를 돌려주면
        Chrome 이 readyState 0 에서 멈춘다."""
        if not path.exists():
            return self._send(404, {"error": "not found"})
        size = path.stat().st_size
        rng = self.headers.get("Range")

        start, end = 0, size - 1
        status = 200
        if rng and rng.startswith("bytes="):
            spec = rng.split("=", 1)[1].split(",")[0].strip()
            s, _, e = spec.partition("-")
            try:
                if s:
                    start = int(s)
                    if e:
                        end = min(int(e), size - 1)
                elif e:                      # bytes=-500 (뒤에서 N바이트)
                    start = max(0, size - int(e))
                status = 206
            except ValueError:
                start, end, status = 0, size - 1, 200
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        with path.open("rb") as f:
            f.seek(start)
            data = f.read(end - start + 1)

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        # 생성된 클립은 내용이 바뀌지 않으므로 캐시를 허용한다 (반복 재생 부담 감소)
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/write", "/write.html"):
            return self._file(ROOT / "templates" / "write.html", "text/html; charset=utf-8")
        if p in ("/stage", "/stage.html"):
            return self._file(ROOT / "templates" / "stage.html", "text/html; charset=utf-8")
        if p == "/api/round":
            return self._send(200, ENGINE.snapshot())
        if p == "/api/story":
            return self._send(200, load_story())
        if p.startswith("/staged/"):
            # 리스테이징 결과 — 생성이 끝나기 전에 '첫 프레임'을 먼저 보여준다
            return self._media(CHAIN_DIR / Path(p).name, "image/png")
        if p.startswith("/clips/"):
            return self._clip(Path(p).name)
        if p.startswith("/scenes/"):
            rel = p[len("/scenes/"):]
            target = (SCENES_DIR / rel).resolve()
            if SCENES_DIR.resolve() not in target.parents:   # 경로 탈출 방지
                return self._send(404, {"error": "not found"})
            return self._media(target, "image/png")
        self._send(404, {"error": "not found"})

    def do_HEAD(self):
        # BaseHTTPRequestHandler 는 HEAD 를 501 로 돌려준다.
        # 링크 미리보기·헬스체크가 HEAD 를 쓰므로 GET 과 같게 응답한다.
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"ok": False, "message": "bad json"})

        voter = (body.get("voter") or "").strip()[:64]
        if not voter:
            return self._send(400, {"ok": False, "message": "voter 없음"})

        sid = (body.get("scenarioId") or "").strip()
        tr = ENGINE.track(sid)

        if self.path == "/api/submit":
            if not tr:
                return self._send(200, {"ok": False, "message": "이야기를 골라주세요"})
            ok, res = tr.submit(body.get("text"), voter, body.get("nick"))
            if ok and ENGINE.can_generate():
                # 접수 창이 도는 동안 다음 컷 프레임을 미리 세워둔다.
                prestage(ENGINE, tr, res["id"], res["text"])
            return self._send(200, {"ok": ok,
                                    "message": "접수됐습니다" if ok else res,
                                    "count": len(tr.pool) if ok else None,
                                    "round": tr.round_n})
        if self.path == "/api/reset":
            # scenarioId 를 주면 그 이야기만, 없으면 전부 처음으로
            targets = [tr] if tr else list(ENGINE.tracks.values())
            for t in targets:
                t.reset()
            save_snapshot(ENGINE)
            return self._send(200, {"ok": True,
                                    "message": "처음으로 돌아갑니다",
                                    "reset": [t.sid for t in targets]})
        if self.path == "/api/vote":
            if not tr:
                return self._send(200, {"ok": False, "message": "이야기를 골라주세요"})
            ok, msg = tr.vote(body.get("candidateId"), voter)
            return self._send(200, {"ok": ok, "message": msg})
        self._send(404, {"ok": False, "message": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int,
                default=int(os.environ.get("PORT", 8778)))
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--max", type=int, default=12, help="live 모드 최대 생성 건수")
    ap.add_argument("--budget", type=float, default=None,
                    help="누적 생성비 상한(USD). 도달하면 자동 드라이런")
    ap.add_argument("--fresh", action="store_true", help="스냅샷 무시하고 새로 시작")
    ap.add_argument("--fast", action="store_true", help="라운드를 짧게 (테스트용)")
    args = ap.parse_args()

    # Cloud Run 에서는 CLI 인자 대신 환경변수로 준다
    if os.environ.get("SSG_LIVE", "").lower() in ("1", "true", "yes"):
        args.live = True
    if os.environ.get("SSG_BUDGET"):
        args.budget = float(os.environ["SSG_BUDGET"])
    if os.environ.get("SSG_MAX"):
        args.max = int(os.environ["SSG_MAX"])

    story = load_story()
    cfg = dict(story["round"])
    cfg["maxChars"] = story["handoff"].get("maxChars", 40)
    if args.fast:
        cfg.update(collectSeconds=8, voteSeconds=15, revealSeconds=5)

    CHAIN_DIR.mkdir(parents=True, exist_ok=True)

    global ENGINE
    ENGINE = Engine(story, cfg, args.live, args.max, args.budget)
    if args.fresh:
        storage.clear_state()
    else:
        load_snapshot(ENGINE)
    threading.Thread(target=driver, args=(ENGINE,), daemon=True).start()

    if not story.get("scenarios"):
        print("[Error] 시나리오가 하나도 없습니다 — scenarios/*.json 을 확인하세요")
        sys.exit(1)
    per = 0.05 * story["scenarios"][0]["generation"].get("seconds", 4)
    cap = f" · 예산 ${args.budget:.2f}" if args.budget else ""
    mode = (f"LIVE (최대 {args.max}건 · 건당 약 ${per:.2f}{cap})"
            if args.live else "DRY-RUN (무료)")
    print("─" * 60)
    print(f"  슥 · 한 줄 극장 — {mode}")
    print(f"  라운드: 첫 문장 → 동시 접수 {cfg['collectSeconds']}s → 생성 → "
          f"[2명 이상이면 투표 {cfg['voteSeconds']}s] → 발표")
    print(f"  세 이야기가 각각 독립적으로 돕니다")
    print(f"  폰 입력  http://localhost:{args.port}/write")
    print(f"  상영     http://localhost:{args.port}/stage")
    print("─" * 60, flush=True)

    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
