# 슥 (SSG)

웹소설을 웹드라마로 만드는 서비스.

```
docs/                  기획 · 리서치 · 기능 명세
services/
  theater/             슥 · 한 줄 극장 — 졸업전시 부스 설치물 (배포 중)
archive/               지난 작업 (작가 스튜디오 데모 · 소설 · 진행 기록)
```

## services/theater — 슥 · 한 줄 극장

관람객이 폰으로 **한 문장**을 보내면 그 문장이 영상 장면이 되고,
장면들이 이어져 하나의 웹드라마가 된다. 세 이야기가 동시에 굴러간다.

```bash
cd services/theater
python3 app/server.py                    # 드라이런 (생성 호출 없음, 무료)
python3 app/server.py --live --budget 15 # 실제 생성
```

자세한 설계와 배포는 [services/theater/README.md](services/theater/README.md).

## docs

| | |
|---|---|
| [프로젝트 기획안](docs/프로젝트%20기획안.md) | 서비스 기획 |
| [전시 기획안](docs/전시%20기획안.md) | 부스 설계 |
| [사업계획서](docs/사업계획서.md) | |
| `docs/features/` | Reader · Writer 기능 명세 |
| [작가 인터뷰](docs/research/작가%20인터뷰.md) | **1차 자료** — 서비스 방향을 결정한 인터뷰 |
| [잠재 사용자 리서치](docs/research/잠재%20사용자%20리서치.md) | 작가·독자 양쪽 정리 + 최대 리스크 |
| [시장 조사](docs/research/시장%20조사.md) | 웹소설 1.35조 · 숏폼 드라마 17→38조 |
| `docs/research/` | 그 밖 — 유저 반응 · 유사 서비스 · 표지 영향 · 제작 파이프라인 |

## archive

| | |
|---|---|
| `archive/studio-demo/` | 작가 스튜디오 데모 — 원고 → 캐스팅 → 영상화 프로토타입. `index.html` 을 열면 실행된다 |
| `archive/novel/` `archive/drama/` | 자체 IP 「왕이었는데 아이돌로 환생했다」 |
| `archive/progress/` | 진행 기록 |

---

`_local/` 은 대용량 로컬 작업물(트레일러 소스·배우 클립 등)로 저장소에 올리지 않는다.
