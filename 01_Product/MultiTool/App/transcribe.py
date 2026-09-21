#!/usr/bin/env python3
"""
자막 — 생성된 클립에서 '실제로 들리는 말'만 받아 적는다.

참여자가 쓴 문장을 그대로 자막으로 올리면 화면과 소리가 어긋난다.
"「도망쳐!」 그가 외쳤다" 에서 들리는 건 "도망쳐!" 뿐이고, 모델이 그 대사를
아예 말하지 않거나 다르게 말하는 경우도 있다. 자막은 들리는 것만 적어야 한다.

그래서 클립이 나온 뒤 오디오만 떼어 Gemini 에게 받아 적게 한다.
말이 없으면 빈 문자열이 돌아오고, 그러면 자막도 뜨지 않는다.

실패하면 빈 문자열 — 자막이 없는 편이 틀린 자막보다 낫다.
"""

import os
import subprocess
import tempfile
from pathlib import Path

MODEL = "gemini-2.5-flash"
REGIONS = ["us-central1", "us-east4"]

SYSTEM = """You transcribe the speech in a short video's audio track.

RULES:
1. Write ONLY words that are actually spoken aloud in the audio. Korean, verbatim.
2. If nobody speaks — music, ambience, footsteps, silence, breathing only —
   answer with exactly: NONE
3. Never invent, translate, summarise or describe. No sound effects, no
   speaker labels, no quotation marks, no punctuation you did not hear.
4. One line. If several lines are spoken, join them with a single space."""


def _audio_of(video_path):
    """클립에서 오디오만 떼어 임시 파일로. 트랙이 없으면 None."""
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = Path(tempfile.gettempdir()) / f"ssg_{Path(video_path).stem}.mp3"
    r = subprocess.run(
        [ff, "-y", "-v", "error", "-i", str(video_path),
         "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(out)],
        capture_output=True,
    )
    if r.returncode != 0 or not out.exists() or out.stat().st_size < 512:
        return None
    return out


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


def heard(video_path):
    """클립에서 들리는 대사를 돌려준다. 말이 없거나 실패하면 빈 문자열."""
    try:
        audio = _audio_of(video_path)
        if not audio:
            return ""
        from google import genai
        from google.genai import types
        pid = _project()
        data = audio.read_bytes()
        for region in REGIONS:
            try:
                c = genai.Client(vertexai=True, project=pid, location=region)
                res = c.models.generate_content(
                    model=MODEL,
                    contents=[types.Part.from_bytes(data=data, mime_type="audio/mpeg"),
                              "Transcribe the spoken words."],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM,
                        temperature=0,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                        max_output_tokens=200,
                    ),
                )
                out = (res.text or "").strip().strip('"').strip()
                if not out or out.upper().startswith("NONE"):
                    return ""
                return out[:60]
            except Exception:
                continue
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        print(f, "->", repr(heard(f)))
