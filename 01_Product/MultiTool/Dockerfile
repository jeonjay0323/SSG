# 슥 · 멀티툴 — Cloud Run 이미지
#
# 빌드 컨텍스트는 01_Product/MultiTool/ 다.
#   gcloud run deploy ssg-theater --source 01_Product/MultiTool ...
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

# 디렉터리 단위로 통째로 복사한다.
# 예전에는 파일을 하나씩 나열하다 restage.py / scenarios / worlds 를 빠뜨려
# 리스테이징이 조용히 건너뛰어지거나 컨테이너가 크래시 루프를 돌았다.
COPY App/       ./App/
COPY Config/    ./Config/
COPY Templates/ ./Templates/
COPY Static/    ./Static/

CMD ["python", "App/server.py"]
