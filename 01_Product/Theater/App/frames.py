#!/usr/bin/env python3
"""
영상 프레임 추출 유틸 — 씬 체이닝용

씬 N 의 시작 프레임 = 씬 N-1 영상의 마지막 프레임.
이게 없으면 모든 관람객 씬이 같은 프레임(씬 2)에서 다시 시작해서,
이야기는 나아가는데 그림은 매번 리셋된다.

brew 없이 imageio-ffmpeg 가 동봉한 바이너리를 쓴다.
"""

import subprocess
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def last_frame(video_path, out_path, back_off=0.15):
    """영상의 마지막 프레임을 PNG 로 뽑는다.

    정확히 끝(0초 전)을 집으면 빈 프레임이 나오는 경우가 있어
    back_off 초만큼 앞을 집는다.
    """
    video_path, out_path = Path(video_path), Path(out_path)
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    dur = duration(video_path)
    ts = max(0.0, dur - back_off)

    subprocess.run(
        [FFMPEG, "-y", "-v", "error",
         "-ss", f"{ts:.3f}", "-i", str(video_path),
         "-frames:v", "1", "-q:v", "2", str(out_path)],
        check=True, capture_output=True,
    )
    if not out_path.exists() or out_path.stat().st_size == 0:
        # 마지막 근처에서 실패하면 끝에서부터 역방향으로 한 프레임
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-sseof", "-0.5", "-i", str(video_path),
             "-update", "1", "-frames:v", "1", str(out_path)],
            check=True, capture_output=True,
        )
    return out_path


def frame_at(video_path, out_path, ts):
    """지정 시각의 프레임 1장."""
    video_path, out_path = Path(video_path), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-ss", f"{ts:.3f}", "-i", str(video_path),
         "-frames:v", "1", "-q:v", "2", str(out_path)],
        check=True, capture_output=True,
    )
    return out_path


def _degenerate(png_path, blown_limit=0.35, dark_limit=0.45):
    """날아갔거나(흰색) 뭉갠(검정) 프레임인지 판정.

    체이닝 시작 프레임이 거의 흰 화면이면 모델에 줄 단서가 없어서
    다음 씬에서 장소·인물이 통째로 흔들린다.
    """
    try:
        from PIL import Image
    except ImportError:
        return False
    px = list(Image.open(png_path).convert("L").resize((160, 90)).getdata())
    n = len(px)
    blown = sum(1 for p in px if p > 248) / n
    dark = sum(1 for p in px if p < 8) / n
    return blown > blown_limit or dark > dark_limit


def last_good_frame(video_path, out_path, steps=12, step=0.5):
    """끝에서부터 거슬러 올라가며 '쓸 만한' 프레임을 고른다.

    마지막 프레임이 화이트아웃된 경우(예: 문이 열리며 빛이 화면을 덮는 샷)
    그대로 쓰면 다음 씬의 단서가 사라지므로, 디테일이 남은 프레임까지 물러난다.
    """
    dur = duration(video_path)
    for i in range(steps):
        ts = max(0.0, dur - 0.15 - i * step)
        frame_at(video_path, out_path, ts)
        if not _degenerate(out_path):
            return out_path, ts
        if ts <= 0:
            break
    return out_path, max(0.0, dur - 0.15)


def trim(video_path, out_path, end_ts):
    """영상을 end_ts 까지 잘라낸다.

    체이닝은 '직전 클립의 마지막 프레임'에서 이어붙는데, 화이트아웃 등으로
    시드를 앞 시점에서 뽑으면 클립은 끝까지 재생되고 다음 씬은 그 앞 상태에서
    시작해 되감기처럼 보인다. 시드 지점에서 클립을 잘라 두 시점을 일치시킨다.
    """
    video_path, out_path = Path(video_path), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", str(video_path),
         "-t", f"{end_ts:.3f}", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-an", str(out_path)],
        check=True, capture_output=True,
    )
    return out_path


def duration(video_path):
    """ffprobe 없이 ffmpeg 로 길이를 얻는다."""
    r = subprocess.run(
        [FFMPEG, "-i", str(video_path)],
        capture_output=True, text=True,
    )
    for line in r.stderr.splitlines():
        if "Duration:" in line:
            hms = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("사용법: python3 frames.py <영상> <출력.png>")
        sys.exit(1)
    p = last_frame(sys.argv[1], sys.argv[2])
    print(f"✓ {p}  (원본 {duration(sys.argv[1]):.2f}초)")
