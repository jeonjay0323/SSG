# SSG · 작가 스튜디오 데모

웹소설 원고를 웹드라마로 만드는 **슥(SSG)** 작가 사이드 인터랙티브 프로토타입입니다. Figma 디자인을 단일 HTML 파일로 구현했습니다.

## 실행

별도 빌드 없이 `index.html`을 브라우저로 열면 됩니다.

```bash
open index.html
```

## 화면 흐름

1. **원고 작성 (write)** — 제목·부제목·본문 작성. 본문에 등장인물(보라)·감정(회색)·장소(초록) 밑줄 실시간 강조, 하단 "원고 읽는 중" 분석 바에 인물/장소 추가 알림. "원고 불러오기"는 파일 열기.
2. **로딩 (분석)** — 원고를 읽으며 인물 이름 카드가 타이핑 → 플립되어 얼굴 공개.
3. **출연진 확인 (casting)** — 추출된 배우 카드(키워드 칩·프롬프트·보이스).
4. **페이지 전환 로딩 (loading-new)** — 슥 로고가 세로축으로 회전하는 전환 로딩.
5. **영상화 (video)** — 좌측 씬 패널(드롭다운·원고싱크·장소인물·프롬프트·생성하기) + 큰 프리뷰 + 세로 썸네일 7씬. 생성 중 disabled 처리.
6. **미리보기 (preview)** — 완성 영상 팝업.

## 인터랙션

- 브라우저 **뒤로/앞으로 가기**로 화면 이동 (history 기반)
- **새로고침** 시 현재 화면 유지 (sessionStorage)
- video에서 **← →** 방향키로 씬 전환, **ESC**로 미리보기 닫기

## 스택

- 단일 `index.html` (Vanilla JS + CSS)
- 폰트: Pretendard, Paperlogy
- 디자인 토큰: primary `#a100ff`, accent(green) `#00a43e`, surface `#fafafa` 등

🤖 Generated with [Claude Code](https://claude.com/claude-code)
