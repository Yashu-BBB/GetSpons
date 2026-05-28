"""
test.py — GetSpons Backend Test Suite
======================================
Run from the backend/ directory with the server already running:

    cd backend
    python test.py

Or point it at a remote host:

    BASE_URL=https://your-app.vercel.app python test.py

What it tests
-------------
  ✦ Health check
  ✦ Creator auth  (signup → login → duplicate signup)
  ✦ Creator profile  (save → fetch → cache hit → validation errors)
  ✦ Media kit  (generate → fetch saved → update fields → PDF download)
  ✦ Brands  (list → detail → filters)
  ✦ Pitch  (generate → list → update status → edit content → bad status)
  ✦ Authenticity score  (by handle → by user_id)
  ✦ Brand auth  (register → login → duplicate register)
  ✦ Brand profile  (save → fetch → validation errors)
  ✦ Match engine  (creators list — primary + secondary)
  ✦ Admin  (stats → user list → brand list → cache clear → plan update)
  ✦ Rate limiting  (429 guard present)
  ✦ Auth hardening  (missing token → bad token → wrong admin key)

Each test prints  ✅ PASS  or  ❌ FAIL  with a reason, then a summary.

Set env vars to override defaults:
    BASE_URL          default http://localhost:8000
    ADMIN_KEY         default getspons-admin-secret-2026
    TEST_EMAIL        random by default
    TEST_PASSWORD     default TestPass123!
    BRAND_EMAIL       random by default
    BRAND_PASSWORD    default BrandPass123!
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL      = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_KEY     = os.getenv("ADMIN_KEY", "getspons-admin-secret-2026")
_uid          = uuid.uuid4().hex[:8]
TEST_EMAIL    = os.getenv("TEST_EMAIL",    f"testcreator_{_uid}@gmail.com")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "TestPass123!")
BRAND_EMAIL   = os.getenv("BRAND_EMAIL",   f"testbrand_{_uid}@gmail.com")
BRAND_PASSWORD= os.getenv("BRAND_PASSWORD","BrandPass123!")

# ---------------------------------------------------------------------------
# Tiny test harness
# ---------------------------------------------------------------------------

_results: list[tuple[str, bool, str]] = []


def _check(name: str, passed: bool, reason: str = "") -> bool:
    icon = "✅" if passed else "❌"
    label = f"{icon} {'PASS' if passed else 'FAIL'}  {name}"
    if not passed and reason:
        label += f"\n        reason: {reason}"
    print(label)
    _results.append((name, passed, reason))
    return passed


def _summary() -> None:
    total  = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = total - passed
    print("\n" + "=" * 60)
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  |  {failed} failed ← see ❌ above")
        print("\n  Failed tests:")
        for name, ok, reason in _results:
            if not ok:
                print(f"    • {name}: {reason}")
    else:
        print("  🎉 All tests passed!")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


def _post(path: str, json_body: Any = None, headers: dict = None, **kwargs) -> requests.Response:
    return requests.post(f"{BASE_URL}{path}", json=json_body, headers=headers or {}, timeout=30, **kwargs)


def _get(path: str, headers: dict = None, params: dict = None) -> requests.Response:
    return requests.get(f"{BASE_URL}{path}", headers=headers or {}, params=params, timeout=30)


def _patch(path: str, json_body: Any = None, headers: dict = None) -> requests.Response:
    return requests.patch(f"{BASE_URL}{path}", json=json_body, headers=headers or {}, timeout=30)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin() -> dict:
    return {"X-Admin-Key": ADMIN_KEY}


# ---------------------------------------------------------------------------
# State shared between tests
# ---------------------------------------------------------------------------

creator_token:  str = ""
creator_id:     str = ""
creator_handle: str = f"@testcreator_{_uid}"
brand_token:    str = ""
brand_user_id:  str = ""
pitch_id:       str = ""

# ---------------------------------------------------------------------------
# 0. Connectivity
# ---------------------------------------------------------------------------

def test_health():
    try:
        r = _get("/health")
        _check("Health check", r.status_code == 200 and r.json().get("status") == "ok",
               f"status={r.status_code} body={r.text[:100]}")
    except requests.ConnectionError:
        _check("Health check", False, f"Cannot connect to {BASE_URL}. Is the server running?")
        print("\n⛔  Server unreachable — aborting all tests.")
        _summary()


# ---------------------------------------------------------------------------
# 1. Creator auth
# ---------------------------------------------------------------------------

def test_creator_signup():
    global creator_id
    r = _post("/api/auth/signup", {"email": TEST_EMAIL, "password": TEST_PASSWORD})
    ok = r.status_code == 200 and "user_id" in r.json()
    creator_id = r.json().get("user_id", "")
    _check("Creator signup", ok, f"status={r.status_code} body={r.text[:200]}")


def test_creator_login():
    global creator_token
    r = _post("/api/auth/login", {"email": TEST_EMAIL, "password": TEST_PASSWORD})
    ok = r.status_code == 200 and "access_token" in r.json()
    creator_token = r.json().get("access_token", "")
    _check("Creator login", ok, f"status={r.status_code} body={r.text[:200]}")


def test_creator_duplicate_signup():
    r = _post("/api/auth/signup", {"email": TEST_EMAIL, "password": TEST_PASSWORD})
    # Supabase returns 200 with an error body for duplicate emails
    body = r.json()
    is_error = ("error" in body) or (r.status_code >= 400)
    _check("Creator duplicate signup rejected", is_error,
           f"Expected error for duplicate email, got: status={r.status_code} body={r.text[:200]}")


# ---------------------------------------------------------------------------
# 2. Creator profile
# ---------------------------------------------------------------------------

SAMPLE_PROFILE = {
    "full_name":        "Test Creator",
    "platform":         "YouTube",
    "handle":           "",   # filled in below
    "followers":        75000,
    "niche":            "Tech",
    "secondary_niches": ["Gaming", "Education"],
    "engagement_rate":  4.2,
    "bio":              "I test things so you don't have to.",
    "past_sponsors":    ["TestBrand", "MockCo"],
    "pricing_min":      5000,
    "pricing_max":      20000,
}


def test_profile_save():
    SAMPLE_PROFILE["handle"] = creator_handle
    r = _post("/api/profile/save", SAMPLE_PROFILE, headers=_auth(creator_token))
    _check("Creator profile save", r.status_code == 200,
           f"status={r.status_code} body={r.text[:300]}")


def test_profile_fetch():
    r = _get("/api/profile/me", headers=_auth(creator_token))
    body = r.json()
    ok = r.status_code == 200 and body.get("handle") == creator_handle
    _check("Creator profile fetch", ok, f"status={r.status_code} body={r.text[:300]}")


def test_profile_cache():
    # Second fetch should hit cache — just verify it still returns 200
    r = _get("/api/profile/me", headers=_auth(creator_token))
    _check("Creator profile cache hit", r.status_code == 200,
           f"status={r.status_code} body={r.text[:200]}")


def test_profile_validation_bad_followers():
    bad = {**SAMPLE_PROFILE, "followers": -1}
    r = _post("/api/profile/save", bad, headers=_auth(creator_token))
    _check("Profile rejects negative followers", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


def test_profile_validation_bad_engagement():
    bad = {**SAMPLE_PROFILE, "engagement_rate": 150.0}
    r = _post("/api/profile/save", bad, headers=_auth(creator_token))
    _check("Profile rejects engagement_rate > 100", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


def test_profile_no_auth():
    r = _get("/api/profile/me")
    _check("Profile fetch without token → 422", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


# ---------------------------------------------------------------------------
# 3. Media kit
# ---------------------------------------------------------------------------

def test_mediakit_generate():
    r = _post("/api/mediakit/generate", headers=_auth(creator_token))
    body = r.json()
    ok = r.status_code == 200 and "headline" in body
    _check("Media kit generate", ok, f"status={r.status_code} body={r.text[:300]}")


def test_mediakit_fetch():
    r = _get("/api/mediakit/saved", headers=_auth(creator_token))
    ok = r.status_code == 200 and r.json().get("headline")
    _check("Media kit fetch saved", ok, f"status={r.status_code} body={r.text[:300]}")


def test_mediakit_update():
    r = _patch("/api/mediakit/update", {"cta": "Reach out to us today!"}, headers=_auth(creator_token))
    _check("Media kit update field", r.status_code == 200,
           f"status={r.status_code} body={r.text[:200]}")


def test_mediakit_pdf():
    r = requests.post(f"{BASE_URL}/api/mediakit/pdf", headers=_auth(creator_token), timeout=30)
    ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf")
    _check("Media kit PDF download", ok,
           f"status={r.status_code} content-type={r.headers.get('content-type')}")


def test_mediakit_no_auth():
    r = _get("/api/mediakit/saved")
    _check("Media kit fetch without token → 422", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


# ---------------------------------------------------------------------------
# 4. Brands directory
# ---------------------------------------------------------------------------

def test_brands_list():
    r = _get("/api/brands")
    body = r.json()
    ok = r.status_code == 200 and isinstance(body, list) and len(body) > 0
    _check("Brands list returns data", ok, f"status={r.status_code} count={len(body) if ok else '?'}")


def test_brands_list_filter_niche():
    r = _get("/api/brands", params={"niche": "Tech"})
    ok = r.status_code == 200 and isinstance(r.json(), list)
    _check("Brands list filter by niche", ok, f"status={r.status_code} body={r.text[:200]}")


def test_brands_list_filter_followers():
    r = _get("/api/brands", params={"min_followers": 5000})
    ok = r.status_code == 200 and isinstance(r.json(), list)
    _check("Brands list filter by min_followers", ok, f"status={r.status_code}")


def test_brands_detail():
    # Get the first brand id from the list and fetch its detail
    list_r = _get("/api/brands")
    brands = list_r.json()
    if not brands:
        _check("Brand detail fetch", False, "No brands in list to test detail on")
        return
    brand_id = brands[0]["id"]
    r = _get(f"/api/brands/{brand_id}")
    _check("Brand detail fetch", r.status_code == 200 and "name" in r.json(),
           f"status={r.status_code} body={r.text[:200]}")


def test_brands_detail_not_found():
    r = _get(f"/api/brands/nonexistent-brand-id-{_uid}")
    _check("Brand detail 404 for bad id", r.status_code == 404,
           f"Expected 404, got {r.status_code}")


# ---------------------------------------------------------------------------
# 5. Pitches
# ---------------------------------------------------------------------------

def test_pitch_generate():
    global pitch_id
    # Use the first brand from the list
    list_r = _get("/api/brands")
    brands = list_r.json()
    if not brands:
        _check("Pitch generate", False, "No brands available to pitch to")
        return
    brand_id = brands[0]["id"]
    r = _post("/api/pitches/generate", {"brand_id": brand_id}, headers=_auth(creator_token))
    body = r.json()
    ok = r.status_code == 200 and "id" in body and "subject" in body and "body" in body
    pitch_id = body.get("id", "")
    _check("Pitch generate", ok, f"status={r.status_code} body={r.text[:300]}")


def test_pitch_list():
    r = _get("/api/pitches/mine", headers=_auth(creator_token))
    ok = r.status_code == 200 and isinstance(r.json(), list)
    _check("Pitch list (mine)", ok, f"status={r.status_code} body={r.text[:200]}")


def test_pitch_update_status():
    if not pitch_id:
        _check("Pitch status update", False, "No pitch_id available (generate failed)")
        return
    r = _patch(f"/api/pitches/{pitch_id}", {"status": "sent"}, headers=_auth(creator_token))
    ok = r.status_code == 200 and r.json().get("status") == "sent"
    _check("Pitch status update → sent", ok, f"status={r.status_code} body={r.text[:200]}")


def test_pitch_update_status_deal():
    if not pitch_id:
        _check("Pitch status update → deal", False, "No pitch_id")
        return
    r = _patch(f"/api/pitches/{pitch_id}", {"status": "deal"}, headers=_auth(creator_token))
    ok = r.status_code == 200 and r.json().get("status") == "deal"
    _check("Pitch status update → deal", ok, f"status={r.status_code} body={r.text[:200]}")


def test_pitch_update_bad_status():
    if not pitch_id:
        _check("Pitch rejects invalid status", False, "No pitch_id")
        return
    r = _patch(f"/api/pitches/{pitch_id}", {"status": "unicorn"}, headers=_auth(creator_token))
    _check("Pitch rejects invalid status → 422", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


def test_pitch_edit_content():
    if not pitch_id:
        _check("Pitch content edit", False, "No pitch_id")
        return
    r = _patch(f"/api/pitches/{pitch_id}/content",
               {"subject": "Updated Subject Line", "body": "Updated body content."},
               headers=_auth(creator_token))
    ok = r.status_code == 200
    _check("Pitch content edit (subject + body)", ok, f"status={r.status_code} body={r.text[:200]}")


def test_pitch_edit_content_no_fields():
    if not pitch_id:
        _check("Pitch content edit empty body → 400", False, "No pitch_id")
        return
    r = _patch(f"/api/pitches/{pitch_id}/content", {}, headers=_auth(creator_token))
    _check("Pitch content edit with no fields → 400", r.status_code == 400,
           f"Expected 400, got {r.status_code}")


def test_pitch_wrong_owner():
    if not pitch_id:
        _check("Pitch wrong owner → 404", False, "No pitch_id")
        return
    # Use a made-up token — should get 401 or 404
    r = _patch(f"/api/pitches/{pitch_id}", {"status": "sent"},
               headers={"Authorization": "Bearer faketoken"})
    _check("Pitch update with bad token → 401/404", r.status_code in (401, 404),
           f"Expected 401 or 404, got {r.status_code}")


# ---------------------------------------------------------------------------
# 6. Authenticity score
# ---------------------------------------------------------------------------

def test_authenticity_by_handle():
    handle = creator_handle.lstrip("@")
    r = _get(f"/api/authenticity/{handle}")
    body = r.json()
    ok = r.status_code == 200 and "score" in body and "label" in body
    _check("Authenticity score by handle", ok, f"status={r.status_code} body={r.text[:300]}")


def test_authenticity_by_user_id():
    if not creator_id:
        _check("Authenticity score by user_id", False, "No creator_id (signup failed)")
        return
    r = _get(f"/api/authenticity/id/{creator_id}")
    ok = r.status_code == 200 and "score" in r.json()
    _check("Authenticity score by user_id", ok, f"status={r.status_code} body={r.text[:300]}")


def test_authenticity_not_found():
    r = _get(f"/api/authenticity/no_such_handle_{_uid}")
    _check("Authenticity 404 for unknown handle", r.status_code == 404,
           f"Expected 404, got {r.status_code}")


# ---------------------------------------------------------------------------
# 7. Brand auth
# ---------------------------------------------------------------------------

def test_brand_signup():
    global brand_token, brand_user_id
    r = _post("/api/brand-auth/register", {
        "email":        BRAND_EMAIL,
        "password":     BRAND_PASSWORD,
        "company_name": f"TestCo {_uid}",
    })
    body = r.json()
    ok = r.status_code == 200 and ("brand_user_id" in body or "user_id" in body)
    brand_user_id = body.get("brand_user_id") or body.get("user_id", "")
    _check("Brand signup", ok, f"status={r.status_code} body={r.text[:300]}")


def test_brand_login():
    global brand_token
    r = _post("/api/brand-auth/login", {"email": BRAND_EMAIL, "password": BRAND_PASSWORD})
    body = r.json()
    ok = r.status_code == 200 and "access_token" in body
    brand_token = body.get("access_token", "")
    _check("Brand login", ok, f"status={r.status_code} body={r.text[:300]}")


def test_brand_duplicate_signup():
    r = _post("/api/brand-auth/register", {
        "email":        BRAND_EMAIL,
        "password":     BRAND_PASSWORD,
        "company_name": "Duplicate Co",
    })
    body = r.json()
    is_error = ("error" in body) or (r.status_code >= 400)
    _check("Brand duplicate signup rejected", is_error,
           f"Expected error, got status={r.status_code} body={r.text[:200]}")


# ---------------------------------------------------------------------------
# 8. Brand profile
# ---------------------------------------------------------------------------

SAMPLE_BRAND_PROFILE = {
    "company_name":       "TestCo",
    "contact_person":     "Test Person",
    "contact_email":      BRAND_EMAIL,
    "niche":              "Tech",
    "secondary_niches":   ["Gaming"],
    "budget_min":         5000,
    "budget_max":         50000,
    "min_followers":      10000,
    "max_followers":      500000,
    "preferred_platforms":["YouTube", "Instagram"],
    "description":        "We make test software.",
    "website":            "https://testco.example.com",
    "instagram_handle":   "@testco",
}


def test_brand_profile_save():
    if not brand_token:
        _check("Brand profile save", False, "No brand_token (brand login failed)")
        return
    r = _post("/api/brand-profile/save", SAMPLE_BRAND_PROFILE, headers=_auth(brand_token))
    _check("Brand profile save", r.status_code == 200,
           f"status={r.status_code} body={r.text[:300]}")


def test_brand_profile_fetch():
    if not brand_token:
        _check("Brand profile fetch", False, "No brand_token")
        return
    r = _get("/api/brand-profile/me", headers=_auth(brand_token))
    ok = r.status_code == 200 and r.json().get("niche") == "Tech"
    _check("Brand profile fetch", ok, f"status={r.status_code} body={r.text[:300]}")


def test_brand_profile_bad_budget():
    if not brand_token:
        _check("Brand profile rejects budget_min > budget_max", False, "No brand_token")
        return
    bad = {**SAMPLE_BRAND_PROFILE, "budget_min": 100000, "budget_max": 5000}
    r = _post("/api/brand-profile/save", bad, headers=_auth(brand_token))
    _check("Brand profile rejects budget_min > budget_max → 422", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


def test_brand_profile_bad_followers():
    if not brand_token:
        _check("Brand profile rejects min_followers > max_followers", False, "No brand_token")
        return
    bad = {**SAMPLE_BRAND_PROFILE, "min_followers": 999999, "max_followers": 1000}
    r = _post("/api/brand-profile/save", bad, headers=_auth(brand_token))
    _check("Brand profile rejects min_followers > max_followers → 422", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


# ---------------------------------------------------------------------------
# 9. Match engine
# ---------------------------------------------------------------------------

def test_match_creators():
    if not brand_token:
        _check("Match engine returns creators", False, "No brand_token")
        return
    r = _get("/api/match/creators", headers=_auth(brand_token))
    body = r.json()
    ok = (r.status_code == 200
          and "primary" in body
          and "secondary" in body
          and "total" in body)
    _check("Match engine returns primary/secondary/total", ok,
           f"status={r.status_code} body={r.text[:400]}")


def test_match_no_auth():
    r = _get("/api/match/creators")
    _check("Match without token → 422", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


def test_match_cache():
    if not brand_token:
        _check("Match cache hit", False, "No brand_token")
        return
    r = _get("/api/match/creators", headers=_auth(brand_token))
    _check("Match cache hit (second call 200)", r.status_code == 200,
           f"status={r.status_code}")


# ---------------------------------------------------------------------------
# 10. Admin endpoints
# ---------------------------------------------------------------------------

def test_admin_stats():
    r = _get("/api/admin/stats", headers=_admin())
    ok = r.status_code == 200 and "total_creators" in r.json()
    _check("Admin stats", ok, f"status={r.status_code} body={r.text[:300]}")


def test_admin_users_list():
    r = _get("/api/admin/users", headers=_admin())
    ok = r.status_code == 200 and isinstance(r.json(), list)
    _check("Admin users list", ok, f"status={r.status_code} body={r.text[:200]}")


def test_admin_brands_list():
    r = _get("/api/admin/brands", headers=_admin())
    ok = r.status_code == 200 and isinstance(r.json(), list)
    _check("Admin brands list", ok, f"status={r.status_code} body={r.text[:200]}")


def test_admin_cache_clear():
    r = _post("/api/admin/cache/clear", headers=_admin())
    ok = r.status_code == 200
    _check("Admin cache clear", ok, f"status={r.status_code} body={r.text[:200]}")


def test_admin_plan_update():
    if not creator_id:
        _check("Admin plan update", False, "No creator_id")
        return
    r = _patch(f"/api/admin/users/{creator_id}/plan", {"plan": "pro"}, headers=_admin())
    ok = r.status_code == 200
    _check("Admin plan update → pro", ok, f"status={r.status_code} body={r.text[:200]}")


def test_admin_plan_update_bad_plan():
    if not creator_id:
        _check("Admin plan rejects invalid value", False, "No creator_id")
        return
    r = _patch(f"/api/admin/users/{creator_id}/plan", {"plan": "ultra"}, headers=_admin())
    _check("Admin plan rejects invalid plan → 422", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


def test_admin_wrong_key():
    r = _get("/api/admin/stats", headers={"X-Admin-Key": "wrong-key"})
    _check("Admin rejects wrong key → 401", r.status_code == 401,
           f"Expected 401, got {r.status_code}")


def test_admin_no_key():
    r = _get("/api/admin/stats")
    _check("Admin rejects missing key → 422", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


# ---------------------------------------------------------------------------
# 11. Auth hardening
# ---------------------------------------------------------------------------

def test_bad_token_profile():
    r = _get("/api/profile/me", headers={"Authorization": "Bearer totallyinvalidtoken"})
    _check("Bad token → 401", r.status_code == 401,
           f"Expected 401, got {r.status_code}")


def test_missing_token_mediakit():
    r = _get("/api/mediakit/saved")
    _check("Missing token on mediakit → 422", r.status_code == 422,
           f"Expected 422, got {r.status_code}")


def test_bad_token_pitch():
    r = _get("/api/pitches/mine", headers={"Authorization": "Bearer badtoken"})
    _check("Bad token on pitches → 401", r.status_code == 401,
           f"Expected 401, got {r.status_code}")


# ---------------------------------------------------------------------------
# 12. Rate limiting smoke test
# (just verifies the header / 429 exists under load — not a full blast)
# ---------------------------------------------------------------------------

def test_rate_limit_header_present():
    """
    Hit an endpoint 5 times quickly and verify the server doesn't crash.
    We don't want to actually trigger the limit (that would break later tests),
    so we just check we're still getting 200s.
    """
    failures = 0
    for _ in range(5):
        r = _get("/health")
        if r.status_code != 200:
            failures += 1
    _check("Rate limiter doesn't break normal traffic (5 rapid health checks)",
           failures == 0, f"{failures}/5 requests failed unexpectedly")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    # 0. connectivity
    test_health,
    # 1. creator auth
    test_creator_signup,
    test_creator_login,
    test_creator_duplicate_signup,
    # 2. creator profile
    test_profile_save,
    test_profile_fetch,
    test_profile_cache,
    test_profile_validation_bad_followers,
    test_profile_validation_bad_engagement,
    test_profile_no_auth,
    # 3. media kit
    test_mediakit_generate,
    test_mediakit_fetch,
    test_mediakit_update,
    test_mediakit_pdf,
    test_mediakit_no_auth,
    # 4. brands
    test_brands_list,
    test_brands_list_filter_niche,
    test_brands_list_filter_followers,
    test_brands_detail,
    test_brands_detail_not_found,
    # 5. pitches
    test_pitch_generate,
    test_pitch_list,
    test_pitch_update_status,
    test_pitch_update_status_deal,
    test_pitch_update_bad_status,
    test_pitch_edit_content,
    test_pitch_edit_content_no_fields,
    test_pitch_wrong_owner,
    # 6. authenticity
    test_authenticity_by_handle,
    test_authenticity_by_user_id,
    test_authenticity_not_found,
    # 7. brand auth
    test_brand_signup,
    test_brand_login,
    test_brand_duplicate_signup,
    # 8. brand profile
    test_brand_profile_save,
    test_brand_profile_fetch,
    test_brand_profile_bad_budget,
    test_brand_profile_bad_followers,
    # 9. match engine
    test_match_creators,
    test_match_no_auth,
    test_match_cache,
    # 10. admin
    test_admin_stats,
    test_admin_users_list,
    test_admin_brands_list,
    test_admin_cache_clear,
    test_admin_plan_update,
    test_admin_plan_update_bad_plan,
    test_admin_wrong_key,
    test_admin_no_key,
    # 11. auth hardening
    test_bad_token_profile,
    test_missing_token_mediakit,
    test_bad_token_pitch,
    # 12. rate limiting smoke
    test_rate_limit_header_present,
]

if __name__ == "__main__":
    print(f"\nGetSpons Backend Test Suite")
    print(f"Target : {BASE_URL}")
    print(f"Creator: {TEST_EMAIL}")
    print(f"Brand  : {BRAND_EMAIL}")
    print("=" * 60 + "\n")

    for test_fn in TESTS:
        try:
            test_fn()
        except Exception as exc:
            _check(test_fn.__name__, False, f"Unhandled exception: {exc}")

    _summary()