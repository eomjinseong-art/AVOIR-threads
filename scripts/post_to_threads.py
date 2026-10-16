"""
AVOIR Threads 자동 발행 (GitHub Actions).

발행 순서
1. content/queue.json (저장소 안 콘텐츠 큐)에서 아직 안 나간 첫 글
2. 큐가 비면 구글시트(기존 '출근룩_200_스레드용')의 '미발행' 첫 행 (시크릿이 있을 때만)

안전장치
- 시작하자마자 토큰을 /me 로 확인한다. 토큰이 죽어 있으면 글을 올리지 않는다.
- 문제가 생기면 GitHub 이슈를 하나만 연다(라벨 autopost-alert). 이미 열려 있으면 새로 만들지 않고 조용히 끝낸다 → 스팸 없음.
- 다음 정상 발행 때 열린 알림 이슈를 자동으로 닫는다.
- 슬롯(오전/저녁)마다 한 번만 올린다. GitHub 크론이 몇 번 겹쳐 돌아도 중복 발행이 없다.
- 발행 기록은 content/state.json 에 남기고, 워크플로가 커밋한다(저장소가 '비활성'으로 꺼지는 것도 막아 준다).

환경변수
- THREADS_ACCESS_TOKEN (필수)
- GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID (선택: 시트 폴백)
- GITHUB_TOKEN, GITHUB_REPOSITORY (이슈 알림용, Actions가 넣어 준다)
- MODE: post(기본) | check(토큰만 확인, 발행 안 함)
- FORCE: true 면 슬롯 시간·중복 검사를 건너뛰고 바로 1개 발행 (수동 실행용)
- DRY_RUN: true 면 무엇을 올릴지만 출력
비밀값은 절대 출력하지 않는다.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

GRAPH = "https://graph.threads.net/v1.0"
KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "content" / "queue.json"
STATE = ROOT / "content" / "state.json"
ALERT_LABEL = "autopost-alert"
LOW_QUEUE = 10


def env_flag(name):
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- HTTP
def _request(url, data=None, headers=None, method=None):
    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:300]}


def scrub(obj, token):
    s = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    return s.replace(token, "***") if token else s


# ---------------------------------------------------------------- Threads
def threads_me(token):
    q = urllib.parse.urlencode({"fields": "id,username", "access_token": token})
    code, res = _request(f"{GRAPH}/me?{q}")
    if code == 200 and "id" in res:
        return res["id"], res.get("username", "?"), None
    err = res.get("error", {}) if isinstance(res, dict) else {}
    return None, None, f"HTTP {code} / code {err.get('code')} / {err.get('message', res)}"


def publish_text(user_id, token, text, link=None):
    params = {"media_type": "TEXT", "text": text, "access_token": token}
    if link:
        params["link_attachment"] = link
    code, res = _request(f"{GRAPH}/{user_id}/threads", params)
    if "id" not in res:
        raise RuntimeError(f"컨테이너 생성 실패 HTTP {code}: {scrub(res, token)}")
    cid = res["id"]
    for _ in range(10):  # 처리 완료 대기 (최대 ~30초)
        time.sleep(3)
        q = urllib.parse.urlencode({"fields": "status,error_message", "access_token": token})
        _, st = _request(f"{GRAPH}/{cid}?{q}")
        if st.get("status") in ("FINISHED", None):
            break
        if st.get("status") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"컨테이너 오류: {scrub(st, token)}")
    code, res = _request(f"{GRAPH}/{user_id}/threads_publish",
                         {"creation_id": cid, "access_token": token})
    if "id" not in res:
        raise RuntimeError(f"발행 실패 HTTP {code}: {scrub(res, token)}")
    media_id = res["id"]
    q = urllib.parse.urlencode({"fields": "permalink", "access_token": token})
    _, info = _request(f"{GRAPH}/{media_id}?{q}")
    return media_id, info.get("permalink", "")


def recent_posts(token, limit=100):
    """계정의 최근 글 (id, text, timestamp). 저장소 기록이 없어도 중복·슬롯을 판단할 수 있게."""
    q = urllib.parse.urlencode({"fields": "id,text,timestamp,permalink", "limit": limit, "access_token": token})
    code, res = _request(f"{GRAPH}/me/threads?{q}")
    if code != 200:
        print(f"::warning::최근 글 조회 실패 HTTP {code} (저장소 기록만 사용)")
        return []
    return res.get("data", [])


def norm(text):
    return "".join((text or "").split())


def slot_of_timestamp(ts):
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(KST)
    except (TypeError, ValueError):
        return None
    return current_slot(dt)


# ---------------------------------------------------------------- GitHub 이슈 알림
def gh_api(path, data=None, method=None):
    tok = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not tok or not repo:
        return None, None
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
               "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data is not None else None
    return _request(f"https://api.github.com/repos/{repo}{path}", body, headers, method)


def open_alerts():
    code, res = gh_api(f"/issues?state=open&labels={ALERT_LABEL}&per_page=50")
    return res if code == 200 and isinstance(res, list) else []


def alert(kind, title, body):
    """같은 kind 의 열린 이슈가 있으면 아무것도 안 함. 새로 열었으면 True."""
    for iss in open_alerts():
        if f"[{kind}]" in iss.get("title", ""):
            print(f"[알림] 이미 열린 이슈 #{iss['number']} 가 있어 새 알림은 생략합니다.")
            return False
    run = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    code, res = gh_api("/issues", {"title": f"[{kind}] {title}", "labels": [ALERT_LABEL],
                                   "body": f"{body}\n\n실행 로그: {run}\n\n"
                                           "_자동 생성된 알림입니다. 문제가 해결되면 다음 정상 발행 때 자동으로 닫힙니다._"},
                       "POST")
    if code in (200, 201):
        print(f"[알림] 이슈 #{res.get('number')} 생성")
        return True
    print(f"[알림] 이슈 생성 실패 HTTP {code}")
    return True  # 알림을 못 남겼으니 실행을 실패로 표시해 메일 알림이라도 가게 한다


def close_alerts(kinds, note):
    for iss in open_alerts():
        if any(f"[{k}]" in iss.get("title", "") for k in kinds):
            gh_api(f"/issues/{iss['number']}/comments", {"body": note}, "POST")
            gh_api(f"/issues/{iss['number']}", {"state": "closed"}, "PATCH")
            print(f"[알림] 이슈 #{iss['number']} 닫음")


# ---------------------------------------------------------------- 상태/슬롯
def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"posted": {}, "slots": {}}


def save_state(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def current_slot(now):
    """오전 슬롯 07:00~16:59, 저녁 슬롯 19:00~02:59 (KST). GitHub 크론 지연을 감안해 넓게 잡는다."""
    h = now.hour
    if 7 <= h < 17:
        return f"{now:%Y-%m-%d}-am"
    if h >= 19:
        return f"{now:%Y-%m-%d}-pm"
    if h < 3:
        return f"{(now - timedelta(days=1)):%Y-%m-%d}-pm"
    return None


# ---------------------------------------------------------------- 시트 폴백
def sheet_next():
    sa = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    sid = (os.environ.get("GOOGLE_SHEET_ID") or "").strip()
    if not sa or not sid:
        return None
    import base64
    import gspread
    from google.oauth2.service_account import Credentials
    info = json.loads(base64.b64decode("".join(sa.split())))
    gc = gspread.authorize(Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    ws = gc.open_by_key(sid).sheet1
    for i, row in enumerate(ws.get_all_records()):
        if str(row.get("상태", "")).strip() != "발행완료":
            text = str(row.get("복붙용 전체 텍스트", "")).strip()
            if text:
                return {"id": f"sheet#{row.get('번호', i + 1)}", "text": text,
                        "_sheet": (ws, i + 2)}
    return None


def mark_sheet(item):
    ws, row = item["_sheet"]
    headers = ws.row_values(1)
    ws.update_cell(row, headers.index("상태") + 1, "발행완료")
    if "발행일시" in headers:
        ws.update_cell(row, headers.index("발행일시") + 1, datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"))


# ---------------------------------------------------------------- main
def main():
    mode = (os.environ.get("MODE") or "post").strip().lower()
    force, dry = env_flag("FORCE"), env_flag("DRY_RUN")
    token = (os.environ.get("THREADS_ACCESS_TOKEN") or "").strip()
    now = datetime.now(KST)
    print(f"[시작] {now:%Y-%m-%d %H:%M} KST, mode={mode}, force={force}, dry_run={dry}")

    if not token:
        new = alert("token", "THREADS_ACCESS_TOKEN 시크릿이 비어 있습니다",
                    "Settings → Secrets and variables → Actions 에 `THREADS_ACCESS_TOKEN` 을 등록해 주세요.")
        sys.exit(1 if new else 0)

    user_id, username, err = threads_me(token)
    if not user_id:
        print(f"::warning::Threads 토큰 확인 실패: {scrub(err, token)}")
        if mode == "check" and not os.environ.get("NOTIFY"):
            sys.exit(1)
        new = alert("token", "Threads 토큰이 만료됐거나 유효하지 않습니다 — 자동 발행 일시 정지",
                    f"Threads API `/me` 응답: `{scrub(err, token)}`\n\n"
                    "해결: 새 **장기(60일) Threads 액세스 토큰**을 발급해 저장소 시크릿 "
                    "`THREADS_ACCESS_TOKEN` 값을 교체하세요. 교체 후 다음 예약 시간에 자동으로 재개됩니다 "
                    "(README의 '토큰 재발급' 참고).")
        sys.exit(1 if new else 0)
    print(f"[토큰] 정상 (계정 @{username})")
    if mode == "check":
        return

    state = load_state()
    slot = current_slot(now)
    history = recent_posts(token)
    history_slots = {slot_of_timestamp(h.get("timestamp")) for h in history}
    history_texts = {norm(h.get("text")) for h in history}
    if not force:
        if slot is None:
            print("[건너뜀] 발행 시간대(오전 07–17시 / 저녁 19–03시 KST)가 아닙니다.")
            return
        if slot in state["slots"] or slot in history_slots:
            print(f"[건너뜀] 이번 슬롯({slot})에는 이미 글이 올라가 있습니다.")
            return

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    remaining = [p for p in queue
                 if p["id"] not in state["posted"] and norm(p["text"]) not in history_texts]
    item = remaining[0] if remaining else None
    if item is None:
        try:
            item = sheet_next()
        except Exception as e:  # 시트 문제로 전체가 죽지 않게
            print(f"::warning::시트 폴백 실패: {e}")
    if item is None:
        new = alert("queue", "발행할 글이 없습니다 (큐 소진)",
                    "`content/queue.json` 에 새 글을 추가해 주세요. 형식은 README 참고.")
        sys.exit(1 if new else 0)

    print(f"[진행] {item['id']} 발행 (슬롯 {slot or '수동'})\n---\n{item['text']}\n---")
    if dry:
        print("[DRY_RUN] 실제 발행은 하지 않았습니다.")
        return

    try:
        media_id, permalink = publish_text(user_id, token, item["text"], item.get("link"))
    except Exception as e:
        print(f"::error::{scrub(str(e), token)}")
        new = alert("publish", "Threads 발행 실패", f"글 `{item['id']}` 발행 중 오류:\n\n```\n{scrub(str(e), token)}\n```")
        sys.exit(1 if new else 0)

    print(f"[성공] {item['id']} → {permalink or media_id}")
    if "_sheet" in item:
        try:
            mark_sheet(item)
        except Exception as e:
            print(f"::warning::시트 상태 갱신 실패: {e}")
    stamp = now.strftime("%Y-%m-%d %H:%M")
    state["posted"][item["id"]] = {"at": stamp, "media_id": media_id, "permalink": permalink}
    state["slots"][slot or f"manual-{stamp}"] = item["id"]
    save_state(state)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"permalink={permalink}\n")

    close_alerts(["token", "publish", "queue"], f"✅ {stamp} KST 정상 발행 확인 ({item['id']}). 알림을 닫습니다.")
    left = len(remaining) - (1 if remaining else 0)
    if left <= LOW_QUEUE:
        alert("queue-low", f"콘텐츠 큐가 {left}개 남았습니다",
              f"저장소 큐에 남은 글이 {left}개입니다 (하루 2개 기준 약 {left // 2}일). 새 글을 추가해 주세요.")


if __name__ == "__main__":
    main()
