"""
Quick multi-user auth/session isolation QA.

Run (with backend server running on :8001):
  .\\.venv\\Scripts\\python.exe auth_isolation_qa.py
"""
from __future__ import annotations

import json
import requests

BASE = "http://127.0.0.1:8001"


def req(method: str, path: str, **kwargs):
    r = requests.request(method, f"{BASE}{path}", timeout=30, **kwargs)
    return r.status_code, r.json()


def main():
    out: dict = {}

    # 1) Sign in users with casing/whitespace variants.
    _, a = req("POST", "/api/auth/signin", json={"user_id": " Alice  ", "budget": 20})
    _, b = req("POST", "/api/auth/signin", json={"user_id": "bob", "budget": 55})
    out["signin_alice"] = {"ok": a.get("ok"), "user_id": a.get("user_id")}
    out["signin_bob"] = {"ok": b.get("ok"), "user_id": b.get("user_id")}
    tok_a = a.get("session_token")
    tok_b = b.get("session_token")

    # 2) Update profiles independently.
    _, pa = req("PATCH", "/api/user/profile", json={"session_token": tok_a, "dietary": "vegan"})
    _, pb = req("PATCH", "/api/user/profile", json={"session_token": tok_b, "dietary": "none"})
    out["profile_alice"] = pa
    out["profile_bob"] = pb

    # 3) Mark different visited places.
    _, va = req(
        "POST",
        "/api/user/visited",
        json={"session_token": tok_a, "city": "San Francisco", "place_name": "Ferry Building"},
    )
    _, vb = req(
        "POST",
        "/api/user/visited",
        json={"session_token": tok_b, "city": "San Francisco", "place_name": "Alamo Square"},
    )
    out["visited_alice"] = va
    out["visited_bob"] = vb

    # 4) /auth/me should resolve identity from token.
    _, ma = req("GET", "/api/auth/me", params={"session_token": tok_a})
    _, mb = req("GET", "/api/auth/me", params={"session_token": tok_b})
    out["me_alice"] = ma
    out["me_bob"] = mb

    # 5) Logout alice; token should become invalid.
    _, lo = req("POST", "/api/auth/logout", json={"session_token": tok_a})
    _, ma2 = req("GET", "/api/auth/me", params={"session_token": tok_a})
    out["logout_alice"] = lo
    out["me_alice_after_logout"] = ma2

    # 6) Bob token should still be valid.
    _, mb2 = req("GET", "/api/auth/me", params={"session_token": tok_b})
    out["me_bob_after_alice_logout"] = mb2

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
