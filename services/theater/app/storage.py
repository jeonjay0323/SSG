#!/usr/bin/env python3
"""
저장소 추상화 — 로컬 파일 / GCS 양쪽 지원

Cloud Run 의 파일시스템은 휘발성이라 생성된 클립과 canon 스냅샷을 담을 수 없다.
환경변수 SSG_BUCKET 이 있으면 GCS 를, 없으면 로컬 디렉터리를 쓴다.
덕분에 개발은 로컬 그대로, 배포는 코드 변경 없이 GCS 로 간다.

레이아웃:
    clips/<name>.mp4    생성된 영상
    canon.json          확정된 이야기 스냅샷
"""

import io
import os
from pathlib import Path

BUCKET = os.environ.get("SSG_BUCKET")            # 예: project-xxx-ssg
LOCAL_STATE = Path(__file__).resolve().parent.parent   # services/theater
# 버킷이 없을 때 클립을 둘 곳. generate_clip.py 의 CLIPS_DIR 과 같은 자리를
# 가리켜야 한다 — 예전에는 홈 디렉터리의 절대경로가 박혀 있어서, 폴더 이름이
# 바뀐 뒤로 쓰는 곳과 읽는 곳이 어긋나 로컬 재생이 404 였다.
LOCAL_CLIPS = Path(os.environ.get("SSG_LOCAL_CLIPS", str(LOCAL_STATE / "clips")))

_client = None


def _bucket():
    global _client
    if _client is None:
        from google.cloud import storage
        _client = storage.Client()
    return _client.bucket(BUCKET)


def using_gcs():
    return bool(BUCKET)


# ── 클립 ──
def put_clip(name, data):
    if BUCKET:
        blob = _bucket().blob(f"clips/{name}")
        blob.upload_from_string(data, content_type="video/mp4")
    else:
        LOCAL_CLIPS.mkdir(parents=True, exist_ok=True)
        (LOCAL_CLIPS / name).write_bytes(data)


def clip_size(name):
    """없으면 None."""
    if BUCKET:
        b = _bucket().blob(f"clips/{name}")
        if not b.exists():
            return None
        b.reload()
        return b.size
    p = LOCAL_CLIPS / name
    return p.stat().st_size if p.exists() else None


def read_clip(name, start=None, end=None):
    """[start, end] 바이트 구간. 둘 다 None 이면 전체.

    Range 요청마다 전체를 내려받지 않도록 GCS 부분 다운로드를 쓴다.
    """
    if BUCKET:
        b = _bucket().blob(f"clips/{name}")
        return b.download_as_bytes(start=start, end=end)
    p = LOCAL_CLIPS / name
    if start is None:
        return p.read_bytes()
    with p.open("rb") as f:
        f.seek(start)
        return f.read(end - start + 1)


def clip_to_tempfile(name, dest):
    """체인 프레임 추출용 — ffmpeg 는 로컬 경로가 필요하다."""
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if BUCKET:
        dest.write_bytes(read_clip(name))
    else:
        src = LOCAL_CLIPS / name
        if src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
    return dest


# ── 상태 스냅샷 ──
def put_state(text):
    if BUCKET:
        _bucket().blob("canon.json").upload_from_string(
            text, content_type="application/json; charset=utf-8")
    else:
        tmp = LOCAL_STATE / "canon.tmp"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(LOCAL_STATE / "canon.json")


def get_state():
    if BUCKET:
        b = _bucket().blob("canon.json")
        return b.download_as_text(encoding="utf-8") if b.exists() else None
    p = LOCAL_STATE / "canon.json"
    return p.read_text(encoding="utf-8") if p.exists() else None


def clear_state():
    if BUCKET:
        b = _bucket().blob("canon.json")
        if b.exists():
            b.delete()
    else:
        (LOCAL_STATE / "canon.json").unlink(missing_ok=True)
