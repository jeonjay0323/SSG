# 슥 · 한 줄 극장 — Cloud Run 이미지
#
# ffmpeg 는 apt 로 깔지 않고 imageio-ffmpeg 가 동봉한 바이너리를 쓴다.
# (체인 프레임 추출용. 이미지가 가벼워지고 빌드도 빨라진다.)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SSG_TMP=/tmp/ssg \
    SSG_CLIPS_DIR=/tmp/ssg/clips

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드
COPY server.py storage.py frames.py restage.py fix_face.py story.json ./
# 이야기와 연출 프롬프트 (코드 밖에서 관리)
COPY scenarios/ ./scenarios/
COPY worlds/ ./worlds/
COPY write.html stage.html ./
# 도입부 스틸·인물 레퍼런스 (정적 자산)
COPY scenes/ ./scenes/
# 영상 생성 모듈 — 로컬에서는 09_Actors 에 있지만 컨테이너에선 같은 경로에 둔다
COPY generate_clip.py ./

CMD ["python", "server.py"]
