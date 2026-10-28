#!/usr/bin/env python3
"""DealRadar parsiuntėjas (GitHub). Tik parsiunčia, ką liepia serveris – jokių filtrų ar kainų.

  python fetch.py ssh -i KEY deal@HOST

Paleidžia nurodytą komandą (SSH į serverį) ir per jos stdin/stdout keičiasi JSON eilutėmis:
serveris siunčia {"op": "get", "url": ...}, čia parsiunčiama ir grąžinamas žalias atsakymas.
Leidžiami tik Vinted adresai. Log'e – tik kiekiai.
"""
import json
import re
import subprocess
import sys
from urllib.parse import urlsplit

ALLOWED_HOST = re.compile(r"^(?:[a-z0-9-]+\.)?vinted\.(?:[a-z]{2,3}|co\.uk)$")
MAX_TEXT = 4_000_000


def new_session():
    from curl_cffi import requests
    return requests.Session(impersonate="chrome")


def cookies(session):
    """Slapukų kopija serveriui. Tas pats vardas keliuose domenuose (__cf_bm) – ne klaida."""
    jar = getattr(session.cookies, "jar", None)
    if jar is not None:
        return {c.name: c.value for c in jar}
    return dict(session.cookies)


def fetch(session, msg):
    url = msg.get("url") or ""
    parts = urlsplit(url)
    if parts.scheme != "https" or not ALLOWED_HOST.match(parts.hostname or ""):
        return {"id": msg.get("id"), "error": "adresas neleidžiamas"}
    try:
        r = session.get(url, params=msg.get("params") or None, headers=msg.get("headers") or None,
                        timeout=min(float(msg.get("timeout") or 20), 60))
        return {"id": msg.get("id"), "status": r.status_code, "url": str(r.url),
                "headers": {k: v for k, v in r.headers.items()},
                "cookies": cookies(session),
                "text": (r.text or "")[:MAX_TEXT]}
    except Exception as e:
        return {"id": msg.get("id"), "error": f"{type(e).__name__}: {str(e)[:200]}"}


def serve(inp, out, session_factory=new_session, run_id=""):
    """Pagrindinis ciklas. Grąžina (užklausų, klaidų skaičius, serverio 'done' žinutė)."""
    def send(obj):
        out.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
        out.flush()

    send({"hello": 1, "run": run_id})
    sessions, got, errors = {}, 0, 0              # sid -> sesija (ES: kiekvienai šaliai sava)
    for line in inp:
        msg = json.loads(line)
        op = msg.get("op")
        if op == "session":
            sessions[msg.get("sid")] = session_factory()
        elif op == "get":
            sid = msg.get("sid")
            if sid not in sessions:
                sessions[sid] = session_factory()
            reply = fetch(sessions[sid], msg)
            got += 1
            errors += 1 if "error" in reply else 0
            send(reply)
        elif op == "done":
            return got, errors, msg
    return got, errors, None


def main(argv):
    if not argv:
        print("naudojimas: fetch.py <komanda į serverį...>")
        return 2
    import os
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                            encoding="utf-8", bufsize=1)
    try:
        got, errors, done = serve(proc.stdout, proc.stdin, run_id=os.environ.get("GITHUB_RUN_ID", ""))
    except (BrokenPipeError, ValueError) as e:
        got, errors, done = 0, 1, None
        print(f"ryšio klaida: {type(e).__name__}")
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.wait(timeout=60)
    print(f"gauta {got}, išsiųsta serveriui {got - errors}" + (f", klaidų {errors}" if errors else ""))
    if done is None:
        print("serveris nebaigė (ryšys nutrūko)")
        return 1
    if done.get("error"):
        print(f"serveris: {done['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
