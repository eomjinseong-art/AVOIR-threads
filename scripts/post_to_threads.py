"""
GitHub Actions에서 실행되는 스레드(Threads) 자동 발행 스크립트 - 구글시트 연동판.

동작 순서:
1. 구글시트를 서비스 계정으로 열어 전체 행을 읽는다.
2. 위에서부터 '상태' 열이 "미발행"(또는 빈칸)인 첫 행을 찾는다.
3. 그 행의 '복붙용 전체 텍스트' 열 내용을 Threads API로 발행한다.
   (컨테이너 생성 -> 발행, 2단계)
4. 성공하면 해당 행의 '상태' 열을 "발행완료"로, '발행일시' 열에 타임스탬프를 기록한다.

필요 환경변수 (GitHub Secrets):
- THREADS_ACCESS_TOKEN         : Threads API 장기 액세스 토큰
- GOOGLE_SERVICE_ACCOUNT_JSON  : 구글 서비스 계정 키 JSON (base64 인코딩된 문자열)
- GOOGLE_SHEET_ID              : 구글시트 URL의 /d/{이 부분}/edit 에 해당하는 ID

계정 ID(THREADS_USER_ID)는 더 이상 Secret으로 관리하지 않는다.
실행할 때마다 access_token으로 /me 를 조회해서 자동으로 얻는다 - 잘못된 ID를
수동으로 잘못 복사해 넣는 실수를 원천적으로 없애기 위함.

시트 컬럼 순서(1행이 헤더)를 아래와 같다고 가정한다:
  A: 번호   B: 본문(원본 줄바꿈)   C: 복붙용 전체 텍스트   D: 상태   E: 발행일시
"""

import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials

GRAPH_BASE = "https://graph.threads.net/v1.0"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

STATUS_DONE = "발행완료"
KST = timezone(timedelta(hours=9))


def get_gspread_client():
    encoded = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    # Secret 붙여넣기 과정에서 섞여 들어갈 수 있는 공백/개행 제거
    encoded = "".join(encoded.split())
    key_dict = json.loads(base64.b64decode(encoded))
    creds = Credentials.from_service_account_info(key_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def http_post(url, params: dict):
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"HTTP {e.code} 오류: {body}")


def create_text_container(user_id: str, access_token: str, text: str) -> str:
    url = f"{GRAPH_BASE}/{user_id}/threads"
    params = {"media_type": "TEXT", "text": text, "access_token": access_token}
    result = http_post(url, params)
    if "id" not in result:
        raise RuntimeError(f"컨테이너 생성 실패: {result}")
    return result["id"]


def publish_container(user_id: str, access_token: str, creation_id: str) -> dict:
    url = f"{GRAPH_BASE}/{user_id}/threads_publish"
    params = {"creation_id": creation_id, "access_token": access_token}
    return http_post(url, params)


def get_threads_user_id(access_token: str) -> tuple:
    """토큰으로 실제 계정 ID/username을 직접 조회. 잘못 복사된 ID를 쓸 위험을 없앤다."""
    url = f"{GRAPH_BASE}/me?fields=id,username&access_token={urllib.parse.quote(access_token)}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"/me 조회 실패 (토큰 문제 가능성 높음) - HTTP {e.code}: {body}")
    if "id" not in result:
        raise RuntimeError(f"/me 응답에 id가 없습니다: {result}")
    return result["id"], result.get("username", "?")


def main():
    access_token = (os.environ.get("THREADS_ACCESS_TOKEN") or "").strip()
    sheet_id = (os.environ.get("GOOGLE_SHEET_ID") or "").strip()

    print(f"[디버그] sheet_id 길이: {len(sheet_id)}")
    print(f"[디버그] access_token 길이: {len(access_token)}")

    if not all([access_token, sheet_id, os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")]):
        print("[오류] 필수 환경변수(THREADS_ACCESS_TOKEN / "
              "GOOGLE_SHEET_ID / GOOGLE_SERVICE_ACCOUNT_JSON) 중 누락된 값이 있습니다.")
        sys.exit(1)

    # THREADS_USER_ID를 Secret으로 받지 않고, 토큰으로 매번 직접 조회 (오타/오복사 방지)
    try:
        user_id, username = get_threads_user_id(access_token)
    except Exception as e:
        print(f"[오류] 계정 ID 조회 실패: {e}")
        sys.exit(1)
    print(f"[디버그] 조회된 계정: username={username}, id 길이={len(user_id)}")

    gc = get_gspread_client()
    sh = gc.open_by_key(sheet_id)
    ws = sh.sheet1  # 첫 번째 시트를 사용. 시트명이 다르면 sh.worksheet("이름")으로 변경

    print(f"[디버그] 시트 헤더: {ws.row_values(1)}")

    records = ws.get_all_records()  # 1행을 헤더로 사용해 dict 리스트로 반환
    print(f"[디버그] 전체 행 수: {len(records)}")

    target_row_index = None  # 실제 시트 행 번호 (헤더 포함, 1-base)
    target_record = None

    for i, row in enumerate(records):
        status = str(row.get("상태", "")).strip()
        if status != STATUS_DONE:
            target_row_index = i + 2  # 헤더(1행) + 0-base 보정
            target_record = row
            break

    if target_record is None:
        print(f"[완료] 발행할 글이 더 없습니다. 전체 {len(records)}개 모두 발행완료 상태입니다.")
        sys.exit(0)

    text = str(target_record.get("복붙용 전체 텍스트", "")).strip()
    post_num = target_record.get("번호", "?")

    if not text:
        print(f"[오류] {post_num}번 행의 '복붙용 전체 텍스트' 열이 비어 있습니다. 시트를 확인하세요.")
        sys.exit(1)

    print(f"[진행] {post_num}번 글 발행 시도 (시트 행 {target_row_index})")
    print(f"--- 본문 미리보기 ---\n{text[:80]}...\n---------------------")

    try:
        creation_id = create_text_container(user_id, access_token, text)
        time.sleep(5)  # Threads API 컨테이너 처리 대기
        result = publish_container(user_id, access_token, creation_id)
        print(f"[성공] {post_num}번 글 발행 완료. 응답: {result}")
    except Exception as e:
        print(f"[실패] {post_num}번 글 발행 중 오류 발생: {e}")
        sys.exit(1)

    # 헤더 순서 기준으로 열 번호 계산
    headers = ws.row_values(1)
    status_col = headers.index("상태") + 1
    ws.update_cell(target_row_index, status_col, STATUS_DONE)

    if "발행일시" in headers:
        ts_col = headers.index("발행일시") + 1
        now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        ws.update_cell(target_row_index, ts_col, now_kst)

    print(f"[시트 갱신] {target_row_index}행 상태 -> {STATUS_DONE}")


if __name__ == "__main__":
    main()
