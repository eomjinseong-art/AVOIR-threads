# 출근룩 200 스레드 자동포스팅 (구글시트 연동판)

매일 3회(오전 8시 / 오후 1시 / 밤 10시, KST) 구글시트에서 다음 미발행 글을 읽어와
스레드(Threads)에 자동 발행하는 GitHub Actions 봇. 콘텐츠 수정은 시트에서 바로 하면 됨 — 재배포 불필요.

## 시트 컬럼 규격 (1행 = 헤더, 이 이름 그대로 써야 함)

| A: 번호 | B: 본문(원본 줄바꿈) | C: 복붙용 전체 텍스트 | D: 상태 | E: 발행일시 |
|---|---|---|---|---|
| 1 | 옷은 많은데... | 1.\n\n옷은 많은데... | 미발행 | (자동 기록) |

- 실제로 발행되는 건 **C열**(복붙용 전체 텍스트)
- **D열이 "미발행"인 첫 행**을 위에서부터 찾아 발행 → 순서 바꾸거나 행 추가/삭제해도 안전
- 발행 성공 시 D열 → "발행완료", E열 → 발행 시각 자동 기록
- E열이 없으면 시각 기록은 건너뛰고 D열만 갱신됨 (없어도 동작엔 문제 없음)

## ⚠️ 시작 전 필수 선행 작업

### 1. 스레드 계정 → 프로페셔널 전환 + 토큰 재발급
(이전과 동일) 스레드 앱에서 프로페셔널 계정 전환 → Meta 앱에서 Threads User ID와
`threads_content_publish` 권한 포함된 장기 액세스 토큰(60일) 재발급.

### 2. 구글 서비스 계정 생성 (구글시트 접근용)
1. [Google Cloud Console](https://console.cloud.google.com) → 새 프로젝트 생성(또는 기존 프로젝트 사용)
2. **API 및 서비스 → 라이브러리** → "Google Sheets API" 검색 → 사용 설정
3. **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → 서비스 계정**
4. 서비스 계정 생성 후 **키(Keys) 탭 → 키 추가 → JSON** → 다운로드 (예: `service-account.json`)
5. JSON 파일 안의 `client_email` 값(예: `xxx@xxx.iam.gserviceaccount.com`) 확인

### 3. 시트를 서비스 계정과 공유
- 구글시트 우측 상단 **공유** 버튼 → 위에서 확인한 `client_email` 주소를 **편집자**로 추가
  (이 단계를 빼먹으면 "403 Permission denied" 에러가 남)

### 4. GitHub Secrets 등록
| Secret 이름 | 값 | 구하는 법 |
|---|---|---|
| `THREADS_ACCESS_TOKEN` | 장기 액세스 토큰 | 1번 단계 |
| `THREADS_USER_ID` | Threads User ID | 1번 단계 |
| `GOOGLE_SHEET_ID` | 시트 ID | 시트 URL `.../d/{여기}/edit` 부분 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 서비스 계정 JSON을 base64로 인코딩한 문자열 | 아래 명령어 |

터미널(맥/리눅스)에서:
```bash
base64 -i service-account.json | tr -d '\n'
```
Windows(PowerShell)에서:
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("service-account.json"))
```
출력된 긴 문자열을 그대로 `GOOGLE_SERVICE_ACCOUNT_JSON` Secret 값으로 등록.

## 폴더 구조

```
scripts/post_to_threads.py   발행 스크립트 (구글시트 읽기/쓰기 + Threads API 호출)
scripts/requirements.txt     의존성 (gspread, google-auth)
.github/workflows/post-threads.yml   스케줄러 (크론 3개, 상태는 시트에 직접 기록)
```

json 상태 파일이 없어졌으므로 워크플로에서 git commit/push 권한도 더 이상 필요 없음.

## 테스트 방법
Actions 탭 → **Threads 자동 발행 → Run workflow** 수동 실행 →
1번 행(상태=미발행)이 정상 발행되고 시트 D열이 "발행완료"로 바뀌는지 확인.

## 주의할 점
- 시트에서 D열을 손으로 "발행완료"→"미발행"으로 되돌리면 그 글이 재발행됨 (재발행 원할 때 활용 가능)
- 60일마다 Threads 토큰 갱신 필요 (동일)
- 서비스 계정 JSON은 절대 코드에 커밋하지 말 것 — 반드시 Secrets로만 관리
