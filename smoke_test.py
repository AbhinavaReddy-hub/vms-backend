"""End-to-end smoke test for the VMS backend.

Runs the whole system and prints pass/fail for each step:
  auth -> permissions -> invite -> visitor registration -> approval
  -> kiosk check-in -> cafeteria step-out/step-in -> checkout
  -> walk-in -> blocklist -> roles -> audit -> security boundaries

Usage (with the API running on port 8000):
    python smoke_test.py
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "http://localhost:8000"
API = BASE + "/api/v1"

passed = 0
failed = 0


def call(method, url, body=None, token=None, device=None, expect=200):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if device:
        headers["X-Device-Token"] = device
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
            try:
                return r.status, json.loads(text)
            except json.JSONDecodeError:
                return r.status, text
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except urllib.error.URLError:
        print("\n  Cannot reach the API. Is it running on port 8000?")
        sys.exit(1)


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  [PASS] %s %s" % (label, detail))
    else:
        failed += 1
        print("  [FAIL] %s %s" % (label, detail))


def section(name):
    print("\n=== %s ===" % name)


def iso(hours=1):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------- health
section("Health")
s, d = call("GET", BASE + "/health")
check("API is up", s == 200)
print("       database=%s  face_service=%s" % (d.get("database"), d.get("face_service")))
face_up = d.get("face_service") == "up"

# ---------------------------------------------------------------- auth
section("Auth")
s, d = call("POST", API + "/auth/login",
            {"email": "abhinav@company.com", "password": "Admin@12345"})
check("admin login", s == 200 and "access_token" in d)
admin = d.get("access_token", "")

s, d = call("POST", API + "/auth/login",
            {"email": "abhinav@company.com", "password": "wrong"})
check("wrong password rejected", s == 401)
check("generic error message", d.get("detail") == "Invalid email or password")

s, d = call("POST", API + "/auth/login",
            {"email": "suresh@company.com", "password": "Host@12345"})
host = d.get("access_token", "")
check("host login", s == 200)

s, d = call("GET", API + "/auth/me", token=admin)
check("admin has full permissions", len(d.get("permissions", [])) > 40,
      "(%d permissions)" % len(d.get("permissions", [])))

s, d = call("GET", API + "/auth/me", token=host)
check("host has limited permissions", len(d.get("permissions", [])) < 5,
      "(%d permissions)" % len(d.get("permissions", [])))

# ---------------------------------------------------------------- permissions
section("Permission enforcement")
s, _ = call("GET", API + "/admins")
check("no token -> 401", s == 401)

s, _ = call("GET", API + "/admins", token=host)
check("host on admin route -> 403", s == 403)

s, _ = call("GET", API + "/admins", token=admin)
check("admin on admin route -> 200", s == 200)

# ---------------------------------------------------------------- invite
section("Invite creation")
s, inv = call("POST", API + "/invites", {
    "visitor_type_id": 1, "full_name": "Smoke Test Visitor",
    "email": "smoke@example.com", "arrival_at": iso(2),
    "purpose": "Automated test", "primary_host_id": 3,
    "private_notes": "STAFF ONLY", "public_notes": "Bring ID",
    "auto_approve": False, "send_invite_email": False}, token=admin)
check("invite created", s == 201, "(id=%s)" % inv.get("id"))
invite_id = inv.get("id")
token_str = inv.get("registration_link", "").split("/register/")[-1]

s, grp = call("POST", API + "/invites/bulk", {
    "group_name": "Smoke Group", "visitor_type_id": 2, "default_host_id": 4,
    "send_invite_emails": False,
    "rows": [
        {"arrival_at": iso(3), "full_name": "Group A", "email": "ga@example.com"},
        {"arrival_at": iso(3), "full_name": "Group B", "email": "gb@example.com"},
        {"arrival_at": iso(3), "full_name": "Dup", "email": "ga@example.com"},
        {"arrival_at": iso(3), "full_name": "BadHost", "host_id": 99999}]}, token=admin)
check("group invite created 2 of 4", grp.get("created") == 2)
check("bad rows failed individually", len(grp.get("failed", [])) == 2)
links = {i["registration_link"] for i in grp.get("invites", [])}
check("each person got a SEPARATE token", len(links) == 2)

# ---------------------------------------------------------------- registration
section("Visitor self-registration (no login)")
s, pub = call("GET", API + "/public/invite/" + token_str)
check("visitor can open link", s == 200)
check("private notes NOT leaked", "private_notes" not in pub)
check("public notes ARE shown", pub.get("public_notes") == "Bring ID")

s, otp = call("POST", API + "/public/invite/" + token_str + "/otp/send",
              {"phone": "+919990001111"})
check("OTP sent", s == 200)
code = otp.get("dev_code", "")

s, _ = call("POST", API + "/public/invite/" + token_str + "/otp/verify",
            {"phone": "+919990001111", "code": "000000"})
check("wrong OTP rejected", s == 400)

s, _ = call("POST", API + "/public/invite/" + token_str + "/otp/verify",
            {"phone": "+919990001111", "code": code})
check("correct OTP accepted", s == 200)

s, _ = call("POST", API + "/public/invite/" + token_str + "/face",
            {"image_b64": "fake"})
check("face blocked before consent", s == 400)

s, _ = call("POST", API + "/public/invite/" + token_str + "/consent", {"accepted": True})
check("consent recorded", s == 200)

s, sub = call("POST", API + "/public/invite/" + token_str + "/submit", {"company": "Acme"})
check("registration submitted", s == 200, "(status=%s)" % sub.get("status"))

# ---------------------------------------------------------------- approval
section("Approval")
s, appr = call("GET", API + "/approvals?status=pending", token=host)
check("host sees their queue", s == 200 and appr.get("total", 0) > 0)
approval_id = appr["items"][0]["id"] if appr.get("items") else None

if approval_id:
    s, d = call("POST", API + "/approvals/%d/approve" % approval_id, {}, token=host)
    check("host approved", s == 200 and d.get("status") == "approved")

# ---------------------------------------------------------------- kiosk
section("Kiosk pairing")
s, pair = call("POST", API + "/kiosk/pair", {"pairing_code": "123456",
                                             "app_version": "1.0.0"})
if s == 200:
    device = pair.get("device_token", "")
    check("device paired", True)
    s2, _ = call("POST", API + "/kiosk/pair", {"pairing_code": "123456"})
    check("pairing code cannot be reused", s2 == 400)
else:
    device = ""
    print("  [SKIP] device already paired in a previous run")

if device:
    s, _ = call("GET", API + "/admins", device=device)
    check("device token on admin route -> 401", s == 401)
    s, _ = call("GET", API + "/kiosk/config", token=admin)
    check("admin token on kiosk route -> 401", s == 401)

    section("Movement flow: entry -> cafeteria -> back -> exit")
    s, ident = call("POST", API + "/kiosk/identify", {"qr_token": token_str}, device=device)
    check("identify by QR", s == 200 and ident.get("found"))
    visitor_id = ident.get("visitor_id")
    check("suggests check_in", ident.get("suggested_action") == "check_in")

    s, ci = call("POST", API + "/kiosk/checkin",
                 {"invite_token": token_str, "method": "qr"}, device=device)
    check("checked in", s == 200, "(badge=%s)" % ci.get("badge_number"))
    visit_id = ci.get("visit_id")

    s, so = call("POST", API + "/kiosk/step-out",
                 {"visitor_id": visitor_id, "method": "face", "match_score": 0.81},
                 device=device)
    check("stepped out (cafeteria)", s == 200 and so.get("presence") == "stepped_out")

    s, ident2 = call("POST", API + "/kiosk/identify", {"qr_token": token_str}, device=device)
    check("kiosk knows they are out", ident2.get("suggested_action") == "step_in")

    s, si = call("POST", API + "/kiosk/step-in",
                 {"visitor_id": visitor_id, "method": "face", "match_score": 0.79},
                 device=device)
    check("stepped back in", s == 200)

    s, _ = call("POST", API + "/kiosk/step-in", {"visitor_id": visitor_id}, device=device)
    check("double step-in rejected", s == 400)

    s, co = call("POST", API + "/kiosk/checkout",
                 {"visitor_id": visitor_id, "method": "face"}, device=device)
    check("checked out", s == 200)

    if visit_id:
        s, v = call("GET", API + "/visits/%d" % visit_id, token=admin)
        types = [m["type"] for m in v.get("movements", [])]
        check("ONE visit holds all 4 movements",
              types == ["entry", "step_out", "step_in", "exit"], str(types))
        check("visit is closed", v.get("status") == "closed")

    section("Walk-in")
    s, o = call("POST", API + "/kiosk/walkin/otp/send", {"phone": "+919990002222"},
                device=device)
    wcode = o.get("dev_code", "")
    s, _ = call("POST", API + "/kiosk/walkin/otp/verify",
                {"phone": "+919990002222", "code": wcode}, device=device)
    check("walk-in phone verified", s == 200)

    s, wi = call("POST", API + "/kiosk/walkin/submit", {
        "full_name": "Walk In Person", "phone": "+919990002222",
        "purpose": "Unscheduled meeting", "host_id": 3,
        "visitor_type_id": 1, "consent_given": True}, device=device)
    check("walk-in submitted", s == 200)
    waid = wi.get("approval_id")

    if waid:
        s, st = call("GET", API + "/kiosk/walkin/%d/status" % waid, device=device)
        check("waiting screen shows pending", st.get("status") == "pending")
        s, _ = call("POST", API + "/approvals/%d/approve" % waid, {}, token=host)
        s, st2 = call("GET", API + "/kiosk/walkin/%d/status" % waid, device=device)
        check("waiting screen updates to approved", st2.get("status") == "approved")

# ---------------------------------------------------------------- blocklist
section("Blocklist")
s, _ = call("POST", API + "/blocklist", {
    "full_name": "Smoke Blocked", "email": "blocked@example.com",
    "reason": "Test entry"}, token=admin)
check("blocklist entry added", s == 201)

s, chk = call("POST", API + "/blocklist/check",
              {"email": "blocked@example.com"}, token=admin)
check("blocklist match detected", chk.get("match") is True)

s, chk2 = call("POST", API + "/blocklist/check",
               {"email": "nobody@example.com"}, token=admin)
check("clean person not flagged", chk2.get("match") is False)

# ---------------------------------------------------------------- roles
section("Roles & permissions")
s, perms = call("GET", API + "/permissions", token=admin)
check("permission catalog loads", s == 200, "(%d permissions)" % perms.get("total", 0))

s, role = call("POST", API + "/roles", {
    "name": "Smoke Role %s" % datetime.now().strftime("%H%M%S"),
    "description": "created by smoke test",
    "permissions": ["visitors.entries.view_all", "approvals.decide_invites"]}, token=admin)
check("custom role created", s == 201)

s, _ = call("POST", API + "/roles", {"name": "Bad", "permissions": ["not.a.real.key"]},
            token=admin)
check("unknown permission key rejected", s == 400)

s, _ = call("DELETE", API + "/roles/1", token=admin)
check("system role cannot be deleted", s == 400)

# ---------------------------------------------------------------- dashboard
section("Dashboard & reporting")
s, summ = call("GET", API + "/dashboard/summary", token=admin)
check("dashboard summary", s == 200 and "capacity" in summ)

s, _ = call("GET", API + "/dashboard/evacuation-list", token=admin)
check("evacuation list", s == 200)

s, _ = call("GET", API + "/analytics/overview?days=30", token=admin)
check("analytics overview", s == 200)

s, audit = call("GET", API + "/audit-log", token=admin)
check("audit log has entries", s == 200 and audit.get("total", 0) > 0,
      "(%d entries)" % audit.get("total", 0))

s, _ = call("DELETE", API + "/audit-log/1", token=admin)
check("audit log has no delete route", s == 404)

# ---------------------------------------------------------------- settings
section("Settings")
s, _ = call("PATCH", API + "/settings", {"face.match_threshold": 0.72}, token=admin)
check("face threshold changed", s == 200)

s, _ = call("PATCH", API + "/settings", {"face.not_a_setting": 1}, token=admin)
check("unknown setting rejected", s == 400)

s, jobs = call("POST", API + "/jobs/run", {}, token=admin)
check("maintenance jobs ran", s == 200 and "ran_at" in jobs)

# ---------------------------------------------------------------- result
print("\n" + "=" * 50)
print("  PASSED: %d    FAILED: %d" % (passed, failed))
if not face_up:
    print("  (face service was not running - face endpoints not exercised)")
print("=" * 50)
sys.exit(1 if failed else 0)
