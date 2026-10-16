# 적용 대기 중인 워크플로

이 두 파일은 `.github/workflows/` 로 옮겨야 동작합니다.
(자동화 도구의 GitHub 토큰에 `workflow` 권한이 없어 직접 넣지 못했습니다.)

- `post-threads.yml` → `.github/workflows/post-threads.yml` 을 **덮어쓰기**
  (하루 2슬롯 크론, 이슈 알림 권한, 발행 기록 커밋, 수동 check/post 모드)
- `refresh-token.yml` → `.github/workflows/refresh-token.yml` 로 **새로 추가**
  (매주 토큰 점검·60일 자동 연장)

가장 쉬운 방법: GitHub 웹에서 이 파일을 열어 내용 복사 → `.github/workflows/` 의 파일 편집/생성 화면에 붙여넣고 커밋.

옮기기 전에도 `scripts/post_to_threads.py` 는 기존 워크플로에서 그대로 돌아갑니다
(스레드 계정의 최근 글을 보고 중복·슬롯을 판단하므로 하루 2개만 올림). 다만 이슈 알림과 기록 커밋은 새 워크플로가 있어야 동작합니다.
