#!/usr/bin/env python3
"""
문장 해석 — 참여자의 한 줄을 '찍을 수 있는 장면'으로 바꾼다.

참여자 문장을 그대로 영상 프롬프트에 넣으면 두 가지가 깨진다.

  ① 글자가 화면에 찍힌다
     "안녕" 처럼 시각적으로 그릴 게 없는 입력이 오면, 모델은 그 단어를
     자막이나 간판으로 그려 넣는다. 프롬프트에 한국어 문장이 인용부호로
     들어가 있으면 특히 그렇다.

  ② 세계 밖으로 나간다
     판타지 숲에서 "지하철이 왔다" 같은 입력이 그대로 렌더된다.

그래서 Veo 에 넘기기 전에 문장을 한 번 해석한다.
  · 세계 안에서 말이 되게 접지(grounding)하고
  · 카메라로 찍을 수 있는 영어 묘사로 바꾸고
  · 글자를 그리지 못하게 못박는다

실패하면 원문을 그대로 쓴다 — 서비스가 멈추는 것보다 낫다.
"""

import os
import subprocess

MODEL = "gemini-2.5-flash"
REGIONS = ["us-central1", "us-east4"]

SYSTEM = """You turn a museum visitor's one-line story input into a single shot
description for a film camera.

RULES — all of them matter:

1. NEVER render the sentence as text. The output must never ask for letters,
   captions, subtitles, signage, screens with readable words, handwriting or any
   written language in the image. If the visitor's input is a greeting, a single
   word, a question, gibberish, or otherwise has no visual content, invent a
   small physical action or event in the world that could plausibly follow, and
   describe THAT instead.

2. Stay inside the world. The setting, era and genre are given below. If the
   input contradicts the world, bend it into something that fits: keep the
   visitor's intent (mood, who acts, what changes) but re-express it with things
   that exist in this world.

3. Describe only what a camera can see: a physical subject, an action, a change
   in the space, light. No inner thoughts, no exposition.

   DIALOGUE IS THE ONE EXCEPTION. When the visitor wrote their line inside
   quotation marks, the character SAYS it. Describe the act of speaking —
   who speaks, to whom, how the body and face carry the line. Still never ask
   for the words to appear as written text anywhere in the frame; the words are
   heard, not seen.

4. One or two sentences. Present tense. English. No camera directions
   (no "close-up", no "the camera pans") — framing is decided elsewhere.

5. Keep it small and concrete. One event, not a montage."""


def _project():
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


import re

# 따옴표로 감싼 부분은 '말한 것'으로 본다. 홑·겹·한국식 인용부호를 모두 받는다.
QUOTE = re.compile(r'["\u201c\u201d\u2018\u2019\'\u300c\u300d\u300e\u300f]([^"\u201c\u201d\u2018\u2019\'\u300c\u300d\u300e\u300f]{1,40})'
                   r'["\u201c\u201d\u2018\u2019\'\u300c\u300d\u300e\u300f]')


def spoken(text):
    """따옴표 안의 대사를 돌려준다. 없으면 None."""
    m = QUOTE.search(text or "")
    return m.group(1).strip() if m and m.group(1).strip() else None


def interpret(text, world=None, previous=None):
    """참여자 문장 → 촬영 가능한 영어 장면 묘사. 실패하면 원문을 돌려준다."""
    if not text or not text.strip():
        return text

    w = world or {}
    ctx = [
        f"WORLD: {w.get('label', 'unspecified')}",
        f"SETTING AND TONE: {w.get('toneRef', '')} — {w.get('grade', '')}",
        f"CHARACTER: {w.get('character', '')}",
        f"WARDROBE: {w.get('wardrobe', '')}",
    ]
    if previous:
        ctx.append(f"WHAT JUST HAPPENED: {previous}")
    line = spoken(text)
    if line:
        ctx.append(f'THE CHARACTER SAYS (Korean, spoken aloud): "{line}"')
        ctx.append("Describe the character speaking this line — posture, gaze, "
                   "breath, what the line does to the moment. The words are heard, "
                   "never written in the frame.")
    ctx.append(f'VISITOR INPUT (Korean): "{text}"')
    ctx.append("Write the shot description now.")

    try:
        from google import genai
        from google.genai import types
        pid = _project()
        for region in REGIONS:
            try:
                c = genai.Client(vertexai=True, project=pid, location=region)
                res = c.models.generate_content(
                    model=MODEL,
                    contents="\n".join(ctx),
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM,
                        temperature=0.7,
                        # 사고(thinking)를 끄지 않으면 토큰이 거기서 소진돼
                        # 본문이 잘려 나온다. 짧은 변환이라 사고가 필요 없다.
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                        max_output_tokens=400,
                    ),
                )
                out = (res.text or "").strip()
                if out:
                    return out
            except Exception:
                continue
    except Exception:
        pass
    return text
