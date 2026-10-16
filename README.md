# AVOIR Threads 자동 발행

@avoireditor 스레드 계정에 **하루 2번(오전 출근길 · 저녁 퇴근 후, KST)** 글을 자동으로 올리는 GitHub Actions 봇.

## 동작
| 항목 | 내용 |
|---|---|
| 발행 시간 | 오전 슬롯 07:47~(KST), 저녁 슬롯 20:47~(KST). 크론 지연에 대비해 슬롯마다 여러 번 깨우고 **슬롯당 1개만** 올림 |
| 글 순서 | ① `content/queue.json` 위에서부터 → ② 큐가 비면 기존 구글시트 `출근룩_200_스레드용`의 '미발행' 행 |
| 기록 | `content/state.json` (글 ID, 발행 시각, 링크). 워크플로가 자동 커밋 → 저장소가 '비활성'으로 꺼지는 것도 방지 |
| 실패 알림 | 라벨 `autopost-alert` GitHub 이슈 **1개만** 생성(이미 열려 있으면 조용히 넘어감). 정상 발행되면 자동으로 닫힘 |
| 토큰 죽음 | `/me` 확인 실패 시 아무것도 올리지 않고 이슈만 남김 → 토큰 교체 후 다음 슬롯에 자동 재개 |
| 토큰 연장 | `Threads 토큰 점검·연장` 워크플로가 매주 월요일 토큰을 60일 연장하고 시크릿을 갱신 (`GH_PAT` 필요) |
| 큐 부족 | 남은 글이 10개 이하가 되면 이슈로 알림 |

## 글 추가/수정
`content/queue.json` 에 항목을 추가하면 끝. 이미 나간 글은 `state.json`에 ID로 기록되므로 순서를 바꾸거나 중간에 끼워 넣어도 됨(ID만 겹치지 않게).
```json
{"id": "A070", "category": "출근룩", "text": "본문 (500자 이내)", "link": "https://www.avoir24.com/44"}
```
- `link` 는 선택. 넣으면 링크 미리보기 카드가 붙는다. 링크 글은 6~10개 중 1개 정도로.
- 스타일: 상황 한 줄 훅 → 짧은 디테일 2~4줄 → `A 👈 / 👉 B` 투표 또는 번호 질문으로 댓글 유도.

## 시크릿
| 이름 | 용도 |
|---|---|
| `THREADS_ACCESS_TOKEN` | **필수.** @avoireditor 계정 Threads 장기 액세스 토큰(60일, `threads_basic`, `threads_content_publish`) |
| `GH_PAT` | 선택(권장). 토큰 자동 연장 후 시크릿을 다시 써 넣는 용도. Fine-grained PAT, 이 저장소만, **Secrets: Read and write** |
| `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID` | 선택. 큐가 비었을 때 기존 구글시트 폴백 |
| `THREADS_USER_ID` | 더 이상 사용 안 함 (토큰으로 `/me` 조회) |

## 토큰 재발급 (만료됐을 때)
1. https://developers.facebook.com/apps → 사용 중인 Threads 앱 → **Use cases → Access the Threads API → Settings/Roles** 에서 @avoireditor 가 Threads 테스터로 등록돼 있는지 확인
2. **Graph API Explorer**(https://developers.facebook.com/tools/explorer) 우측 상단을 `threads.net` 으로 바꾸고 앱 선택 → **Generate Threads Access Token** → @avoireditor 로 로그인·허용 (단기 토큰, 1시간)
3. 장기 토큰으로 교환 (앱 시크릿 필요):
   `https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=<앱시크릿>&access_token=<단기토큰>`
   → 응답의 `access_token` (60일)
4. 저장소 **Settings → Secrets and variables → Actions → `THREADS_ACCESS_TOKEN` → Update** 에 붙여넣기
5. Actions → **Threads 자동 발행 → Run workflow (mode = check)** 로 확인. 이후 예약 시간에 자동 재개

## 수동 실행
- `mode=check`: 토큰만 확인(발행 안 함)
- `mode=post`: 슬롯과 상관없이 다음 글 1개 바로 발행 (`dry_run` 켜면 미리보기만)
