#!/usr/bin/env python3
"""
load_generator.py (Train Ticket) — closed-loop workload generator over the TT booking flow.

Mirrors the Sock Shop generator's CLI + CSV schema exactly, so run_scenario.sh, audit_alignment,
and the loader consume it unchanged. Only the user model (endpoints + journeys) is Train-Ticket
specific.

CSV columns (identical to Sock Shop): timestamp,user_id,scenario,method,endpoint,status_code,
latency_ms,success,error

TT topology: requests go through the ts-ui-dashboard nginx front door (:8080), which proxies
`/api/v1/<service>/...` to the ts-*-services. Auth is JWT (login returns a bearer token).

*** ENDPOINTS/PAYLOADS ARE THE STANDARD TT API — VALIDATE AGAINST THE LIVE STACK (Phase 0b). ***
The paths below are the well-known Train Ticket endpoints; exact bodies can vary by TT version.
`--probe` runs one login + one search and prints the raw responses so you can confirm/fix the
API quickly on the VM before a real run.

Usage:
    python3 load_generator.py --host http://localhost:8080 --users 200 --duration 120 \
        --think-min 0.2 --think-max 1.0 --profile steady --output out.csv
    python3 load_generator.py --host http://localhost:8080 --probe     # API sanity check
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

# --- TT API (validate on VM) -----------------------------------------------------------------
LOGIN = "/api/v1/users/login"
TRIPS = "/api/v1/travelservice/trips/left"          # high-speed trains
TRIPS2 = "/api/v1/travel2service/trips/left"         # other trains
ORDERS_REFRESH = "/api/v1/orderservice/order/refresh"
PRESERVE = "/api/v1/preserveservice/preserve"
PAY = "/api/v1/inside_pay_service/inside_payment"

# Standard TT test account + routes VALIDATED on the live stack. The seeded trips (G1234-D1345,
# from ts-travel-service InitData) run shanghai -> suzhou -> taiyuan; station names in the DB are
# lowercase, no spaces (shanghai, suzhou, taiyuan - NOT "Shang Hai"). trips/left matches these
# names against the route, so the search terms MUST be the seeded lowercase names.
DEFAULT_USER = "fdse_microservice"
DEFAULT_PASS = "111111"
ROUTES = [("shanghai", "suzhou"), ("shanghai", "taiyuan"), ("suzhou", "taiyuan")]

# trips/left rejects any departureTime that is not strictly after today (TravelServiceImpl.
# afterToday) -> returns []. Query a few days ahead so the booking flow returns real trips.
DEPART_DAYS_AHEAD = 3


def _depart_date():
    return (dt.date.today() + dt.timedelta(days=DEPART_DAYS_AHEAD)).strftime("%Y-%m-%d")

# weighted journey mix per profile (scenario -> weight)
PROFILES = {
    "steady": {"search": 55, "browse_orders": 20, "book_pay": 20, "search2": 5},
    "low": {"search": 60, "browse_orders": 25, "book_pay": 10, "search2": 5},
    "burst": {"search": 45, "browse_orders": 15, "book_pay": 35, "search2": 5},
}

_rows_lock = threading.Lock()
_rows: list = []
_stop = threading.Event()


def _now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _record(uid, scenario, method, endpoint, code, lat_ms, ok, err=""):
    with _rows_lock:
        _rows.append({
            "timestamp": _now_iso(), "user_id": uid, "scenario": scenario, "method": method,
            "endpoint": endpoint, "status_code": code, "latency_ms": round(lat_ms, 2),
            "success": ok, "error": (err or "")[:200],
        })


def _req(sess, uid, scenario, method, host, path, **kw):
    url = host.rstrip("/") + path
    t0 = time.perf_counter()
    try:
        r = sess.request(method, url, timeout=kw.pop("timeout", 30), **kw)
        lat = (time.perf_counter() - t0) * 1000
        ok = 200 <= r.status_code < 400
        _record(uid, scenario, method, path, r.status_code, lat, ok, "" if ok else r.text[:200])
        return r
    except Exception as e:  # noqa: BLE001
        lat = (time.perf_counter() - t0) * 1000
        _record(uid, scenario, method, path, 0, lat, False, str(e))
        return None


def _login(sess, uid, host, user, pw):
    r = _req(sess, uid, "login", "POST", host, LOGIN, json={"username": user, "password": pw})
    if r is not None and r.status_code == 200:
        try:
            tok = (r.json().get("data") or {}).get("token")
            if tok:
                sess.headers["Authorization"] = "Bearer " + tok
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _search(sess, uid, host, scenario, path):
    frm, to = random.choice(ROUTES)
    # field is startPlace (TripInfo.startPlace) - NOT startingPlace; the wrong name deserializes
    # to null and trips/left silently returns [] ("[query][Travel Query Fail][Something null]").
    body = {"startPlace": frm, "endPlace": to, "departureTime": _depart_date()}
    return _req(sess, uid, scenario, "POST", host, path, json=body)


def journey(sess, uid, host, scenario, user, pw):
    if "Authorization" not in sess.headers and not _login(sess, uid, host, user, pw):
        return
    if scenario == "search":
        _search(sess, uid, host, scenario, TRIPS)
    elif scenario == "search2":
        _search(sess, uid, host, scenario, TRIPS2)
    elif scenario == "browse_orders":
        _search(sess, uid, host, scenario, TRIPS)
        _req(sess, uid, scenario, "GET", host, ORDERS_REFRESH)
    elif scenario == "book_pay":
        r = _search(sess, uid, host, scenario, TRIPS)
        trip = None
        try:
            data = (r.json().get("data") if r is not None else None) or []
            if data:
                trip = data[0]
        except Exception:  # noqa: BLE001
            trip = None
        frm, to = random.choice(ROUTES)
        preserve_body = {
            "accountId": "", "contactsId": "", "tripId": (trip or {}).get("tripId", "D1345"),
            "seatType": "2", "date": _depart_date(),
            "from": frm, "to": to, "assurance": "0", "foodType": "0", "consigneeName": "",
        }
        _req(sess, uid, scenario, "POST", host, PRESERVE, json=preserve_body)
        _req(sess, uid, scenario, "POST", host, PAY, json={"orderId": "", "tripId": preserve_body["tripId"]})


def worker(uid, host, duration, think, profile, user, pw):
    sess = requests.Session()
    sess.headers["Content-Type"] = "application/json"
    scenarios = list(PROFILES[profile].keys())
    weights = list(PROFILES[profile].values())
    end = time.time() + duration
    while time.time() < end and not _stop.is_set():
        sc = random.choices(scenarios, weights=weights, k=1)[0]
        try:
            journey(sess, uid, host, sc, user, pw)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(random.uniform(*think))


def probe(host, user, pw):
    s = requests.Session(); s.headers["Content-Type"] = "application/json"
    print("LOGIN", host + LOGIN)
    r = s.post(host.rstrip("/") + LOGIN, json={"username": user, "password": pw}, timeout=30)
    print(" ", r.status_code, r.text[:300])
    if r.status_code == 200:
        tok = (r.json().get("data") or {}).get("token")
        if tok:
            s.headers["Authorization"] = "Bearer " + tok
    print("SEARCH", host + TRIPS)
    r = s.post(host.rstrip("/") + TRIPS,
               json={"startPlace": "shanghai", "endPlace": "suzhou",
                     "departureTime": _depart_date()}, timeout=30)
    print(" ", r.status_code, r.text[:400])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://localhost:8080")
    ap.add_argument("--users", type=int, default=200)
    ap.add_argument("--duration", type=int, default=120)
    ap.add_argument("--think-min", type=float, default=0.2)
    ap.add_argument("--think-max", type=float, default=1.0)
    ap.add_argument("--profile", choices=list(PROFILES), default="steady")
    ap.add_argument("--output", default="load_results.csv")
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--password", default=DEFAULT_PASS)
    ap.add_argument("--probe", action="store_true", help="one login+search, print responses, exit")
    a = ap.parse_args()

    if a.probe:
        probe(a.host, a.user, a.password)
        return

    think = (a.think_min, a.think_max)
    with ThreadPoolExecutor(max_workers=a.users) as ex:
        for uid in range(a.users):
            ex.submit(worker, uid, a.host, a.duration, think, a.profile, a.user, a.password)
    with open(a.output, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["timestamp", "user_id", "scenario", "method",
                                           "endpoint", "status_code", "latency_ms", "success", "error"])
        w.writeheader()
        w.writerows(_rows)
    ok = sum(1 for r in _rows if r["success"])
    print(f"[load] {len(_rows)} requests ({ok} ok, {len(_rows)-ok} fail) -> {a.output}")


if __name__ == "__main__":
    main()
