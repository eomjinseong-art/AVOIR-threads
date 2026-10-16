# 활성화된 워크플로

아래 두 워크플로는 `.github/workflows/` 에 올라가 동작합니다.
이 폴더의 YAML 복사본은 중복을 피하기 위해 제거했습니다. 로직은 옮길 때 바꾸지 않았습니다.

- `.github/workflows/post-threads.yml`
  (하루 2슬롯 크론, 이슈 알림 권한, 발행 기록 커밋, 수동 check/post 모드)
- `.github/workflows/refresh-token.yml`
  (매주 토큰 점검·60일 자동 연장)
