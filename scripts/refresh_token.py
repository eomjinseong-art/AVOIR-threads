"""
Threads 장기 토큰 자동 연장 (매주 실행).

- Threads 장기 토큰(60일)은 만료 전이면 refresh_access_token 으로 다시 60일 연장된다.
  (발급 후 24시간이 지나야 하고, 이미 만료된 토큰은 연장 불가)
- 새 토큰을 저장소 시크릿 THREADS_ACCESS_TOKEN 에 다시 써 넣으려면 시크릿 쓰기 권한이 있는
  PAT 가 필요하다 → 시크릿 GH_PAT (fine-grained, 이 저장소만, Secrets: Read and write).
- GH_PAT 가 없으면 연장은 건너뛰고 토큰 상태만 확인한다(죽었으면 이슈 1개).
토큰 값은 절대 출력하지 않는다.
"""
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import post_to_threads as p  # noqa: E402

KST = timezone(timedelta(hours=9))
INFO = Path(__file__).resolve().parent.parent / "content" / "token.json"


def main():
    token = (os.environ.get("THREADS_ACCESS_TOKEN") or "").strip()
    pat = (os.environ.get("GH_PAT") or "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    uid, username, err = p.threads_me(token) if token else (None, None, "시크릿 비어 있음")
    if not uid:
        print(f"::warning::토큰 확인 실패: {p.scrub(err, token)}")
        new = p.alert("token", "Threads 토큰이 만료됐거나 유효하지 않습니다 — 자동 발행 일시 정지",
                      f"Threads API 응답: `{p.scrub(err, token)}`\n\n만료된 토큰은 연장할 수 없습니다. "
                      "새 장기 토큰을 발급해 `THREADS_ACCESS_TOKEN` 시크릿을 교체해 주세요 (README 참고).")
        sys.exit(1 if new else 0)
    print(f"[토큰] 정상 (@{username})")

    if not pat:
        print("::notice::GH_PAT 시크릿이 없어 자동 연장을 건너뜁니다. 토큰은 발급 후 60일에 만료되니 그 전에 교체하거나 GH_PAT 를 등록하세요.")
        return

    q = urllib.parse.urlencode({"grant_type": "th_refresh_token", "access_token": token})
    code, res = p._request(f"https://graph.threads.net/refresh_access_token?{q}")
    new_token = res.get("access_token") if isinstance(res, dict) else None
    if not new_token:
        print(f"::warning::연장 실패 HTTP {code}: {p.scrub(res, token)}")
        new = p.alert("refresh", "Threads 토큰 자동 연장 실패",
                      f"refresh_access_token 응답: `{p.scrub(res, token)}`\n\n토큰은 아직 유효합니다. "
                      "발급 24시간 이내라면 다음 주에 다시 시도됩니다.")
        sys.exit(1 if new else 0)
    print(f"::add-mask::{new_token}")

    r = subprocess.run(["gh", "secret", "set", "THREADS_ACCESS_TOKEN", "--repo", repo],
                       input=new_token, text=True, capture_output=True,
                       env={**os.environ, "GH_TOKEN": pat})
    if r.returncode != 0:
        msg = p.scrub(p.scrub(r.stderr, new_token), pat)
        print(f"::error::시크릿 저장 실패: {msg}")
        new = p.alert("refresh", "새 Threads 토큰을 시크릿에 저장하지 못했습니다",
                      f"`gh secret set` 오류: `{msg}`\n\nGH_PAT 권한(이 저장소, Secrets: Read and write)을 확인해 주세요.")
        sys.exit(1 if new else 0)

    expires = datetime.now(KST) + timedelta(seconds=int(res.get("expires_in", 0) or 0))
    INFO.write_text(json.dumps({"refreshed_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
                                "expires_at": expires.strftime("%Y-%m-%d")}, indent=1) + "\n")
    print(f"[연장] 완료, 새 만료일 {expires:%Y-%m-%d} KST")
    p.close_alerts(["refresh"], "✅ 토큰 자동 연장 성공. 알림을 닫습니다.")


if __name__ == "__main__":
    main()
