#!/usr/bin/env python3
"""DUX chatbot eval harness (p1-6) — a re-runnable regression ruler.

NOT part of the app request path. Standalone script: it monkeypatches the
chatbot's logging/refinement seams so it can run the REAL handle_message
classify+normalize path without writing Chatbot Log rows and without
cross-case refinement contamination, then asserts on the captured result.

Run on the dev server (the documented standalone-frappe pattern):
    rsync this file up, then:
    cd ~/frappe-bench && ./env/bin/python /tmp/run_eval.py
Site/path default to dev; override with DUX_EVAL_SITE / DUX_EVAL_SITES_PATH.

Scoring is split into:
  * REAL pass-rate   — level-2 (intent+doctype+normalized-filters) and
    level-3 (non-empty smoke) assertions. Deterministic, data-independent
    for level-2; level-3 asserts non-empty against known-stable dev data.
  * KNOWN-LIMITATIONS holding — expected-behavior cases (field-baked
    comparator -> query_error, write -> unsupported, etc.) so a documented
    gap is TRACKED, not counted as a regression. If the field-baked case
    ever returns success, it's flagged RESOLVED (not failed) — the signal
    that the parked prompt-level comparator fix has landed.

Every `expected` reflects behavior observed in real logs and/or re-verified
live during STEP 0 — not a hoped-for answer key.
"""

import os
import sys
import json
import time

SITE = os.environ.get("DUX_EVAL_SITE", "erp.jewonline.in")
SITES_PATH = os.environ.get("DUX_EVAL_SITES_PATH", "/home/frappe/frappe-bench/sites")
_BENCH = os.path.dirname(SITES_PATH.rstrip("/"))
# Frappe apps are usually editable-installed, but add the app dir defensively
# so `import dux_chatbot.api` resolves under a raw env-python invocation.
sys.path.insert(0, os.path.join(_BENCH, "apps", "dux_chatbot"))


# =============================================================================
# EVAL CASES — 18 distinct queries (13 level-2, 1 level-3-only, 4 known).
# kind: "level2" asserts intent+doctype+filters (+optional nonempty smoke);
#       "level3" asserts intent+doctype+nonempty only (filter shape varies);
#       "known"  asserts outcome (documented behavior/limitation).
# =============================================================================
PENDING_PO = ["To Receive and Bill", "To Bill", "To Receive"]  # PO "pending" alias set

EVAL_CASES = [
    # ---- status semantic layer ----
    {"id": "status_alias_pending", "query": "show my pending purchase orders", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["status", "in", PENDING_PO]], "nonempty": True},
    {"id": "exact_status", "query": "show purchase orders that are to receive and bill", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["status", "=", "To Receive and Bill"]]},

    # ---- no-filter reads ----
    {"id": "no_filter_po", "query": "show purchase orders", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order", "filters": []},
    {"id": "items_no_filter", "query": "show me my items", "kind": "level2",
     "intent": "read", "doctype": "Item", "filters": [], "nonempty": True},

    # ---- comparators (string-form -> parsed + coerced; above/more-than emit
    #      total_amount -> alias -> grand_total) ----
    {"id": "comparator_above", "query": "show purchase orders above 50000", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["grand_total", ">", 50000.0]], "nonempty": True},
    {"id": "comparator_below", "query": "show purchase orders below 25000", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["grand_total", "<", 25000.0]]},
    {"id": "comparator_more_than", "query": "show purchase order more than 25000", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["grand_total", ">", 25000.0]]},
    # Imperative "less than" — the phrasing-determinism counterpart to the
    # known_limit_field_baked_comparator case below. Measured n=10: this prefix
    # reliably value-strings (-> grand_total<25000, success), while the
    # conversational "can you show me po less than..." reliably field-bakes.
    # The pair pins the phrasing boundary; if either side flips, the eval flags it.
    {"id": "comparator_less_than", "query": "show purchase orders less than 25000", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["grand_total", "<", 25000.0]]},

    # ---- loose Link matching ----
    {"id": "loose_link_supplier", "query": "show purchase orders from Bhandari", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["supplier", "like", "%Bhandari%"]]},
    {"id": "loose_link_supplier2", "query": "show me po for supplier abhijeet", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["supplier", "like", "%abhijeet%"]]},
    # NOTE: a company-field loose-Link case was DROPPED here (p1-6 calibration).
    # Measured n=10: "po of company jain engineering" routes to the SUPPLIER
    # field 10/10 (0/10 company) — the model can't reliably filter-by-company;
    # it dumps the value into supplier. A deterministic company assertion would
    # be mis-calibrated, and a supplier result is redundant with loose_link_*.
    # Tracked instead as the parked "unreliable company-field routing" gap.

    # ---- company routing rescue (p15-1c) — the base model dumps company names
    #      into `supplier`; resolve_company reroutes exact/aliased company values to
    #      `company` (= exact), while real suppliers stay on supplier (like). The
    #      Jain case proves the "jain engineering" alias entry, not just Dux. ----
    {"id": "company_exact", "query": "po of company Dux Digitech", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["company", "=", "Dux Digitech"]], "nonempty": True},
    {"id": "company_alias", "query": "po of company dux", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["company", "=", "Dux Digitech"]], "nonempty": True},
    {"id": "company_alias_jain", "query": "po of company Jain Engineering", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["company", "=", "Jain Engineering Works (India) Private Limited"]], "nonempty": True},
    {"id": "supplier_regression", "query": "po of Bhandari", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["supplier", "like", "%Bhandari%"]]},
    {"id": "keyword_conflict_regression", "query": "po of company Bhandari", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["supplier", "like", "%Bhandari%"]]},

    # ---- multi-filter (status alias + loose Link in one fresh turn) ----
    {"id": "multi_filter", "query": "show pending purchase orders from Bhandari Hardware", "kind": "level2",
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["status", "in", PENDING_PO], ["supplier", "like", "%Bhandari Hardware%"]]},

    # ---- Purchase Invoice "unpaid" — NOW an alias (was exact option-match before the
    #      status-alias fill this batch). The fill is the intended gap-close, so this
    #      existing case deliberately flips ["status","=","Unpaid"] -> the alias set,
    #      mirroring Sales Invoice. [Unpaid,Overdue] is a superset of the previously
    #      non-empty Unpaid, so the smoke still holds. ----
    {"id": "pi_unpaid_alias", "query": "show unpaid purchase invoices", "kind": "level2",
     "intent": "read", "doctype": "Purchase Invoice",
     "filters": [["status", "in", ["Unpaid", "Overdue"]]], "nonempty": True},
    # ---- Sales Invoice alias status (doctype named to avoid the invoice ambiguity gap) ----
    {"id": "si_alias_status", "query": "show unpaid sales invoices", "kind": "level2",
     "intent": "read", "doctype": "Sales Invoice",
     "filters": [["status", "in", ["Unpaid", "Overdue"]]]},

    # ---- Purchase Receipt — FIRST new-doctype registration into chatbot_registry.
    #      THE reported bug: "purchase receipt" used to route to Purchase Invoice; now
    #      registered, it routes to Purchase Receipt AND passes the _handle_read whitelist
    #      gate (the two things that were missing). 11 records -> non-empty smoke. ----
    {"id": "pr_routing", "query": "show me purchase receipts", "kind": "level2",
     "intent": "read", "doctype": "Purchase Receipt",
     "filters": [], "nonempty": True},
    # PR status alias "pending" -> [To Bill, Partly Billed]. Assert the FILTER SHAPE
    # regardless of count (records may not be in those states -> no non-empty smoke).
    {"id": "pr_pending", "query": "pending purchase receipts", "kind": "level2",
     "intent": "read", "doctype": "Purchase Receipt",
     "filters": [["status", "in", ["To Bill", "Partly Billed"]]]},

    # ---- Purchase Invoice status-alias fill (the gap closed this batch) ----
    # "pending" -> [Unpaid, Overdue]: this filter could NOT have been produced before the
    # fill (PInv had empty status_aliases) — proves the gap is closed.
    {"id": "pi_pending", "query": "pending purchase invoices", "kind": "level2",
     "intent": "read", "doctype": "Purchase Invoice",
     "filters": [["status", "in", ["Unpaid", "Overdue"]]]},
    # "paid" -> [Paid] via the new alias (a status=Paid filter present, as the prompt wants).
    {"id": "pi_paid", "query": "paid purchase invoices", "kind": "level2",
     "intent": "read", "doctype": "Purchase Invoice",
     "filters": [["status", "in", ["Paid"]]]},

    # ---- level-3 only: value-specific item lookup (field varies item_name/item_code).
    #      Phrasing AVOIDS the word "stock" — that's now a Bin vocab term, so "stock of
    #      <item>" intentionally routes to Bin (the stock feature). This case tests the
    #      Item-master value lookup, so it names the item plainly. ----
    {"id": "item_specific", "query": "show me item 100mm DI", "kind": "level3",
     "intent": "read", "doctype": "Item", "nonempty": True},

    # ---- STOCK QUERYING (piece 1) — Bin aggregate. Test item Petrol: 5 warehouses,
    #      total actual_qty = 10546. THE routing test: "stock/quantity/how many" must hit
    #      doctype=Bin (was "Item" -> the Item card before). If routing is flaky across the
    #      phrasings below, Option A's vocab steer is insufficient -> escalate to Option B
    #      (dedicated intent). resp_type/stock_total assert the AGGREGATE itself is right. ----
    {"id": "stock_routing", "query": "what is the stock of Petrol", "kind": "level2",
     "intent": "read", "doctype": "Bin", "resp_type": "stock", "stock_total": 10546, "nonempty": True},
    {"id": "stock_howmany", "query": "how many Petrol do we have", "kind": "level2",
     "intent": "read", "doctype": "Bin", "resp_type": "stock", "stock_total": 10546},
    {"id": "stock_warehouse_breakdown", "query": "stock of Petrol", "kind": "level2",
     "intent": "read", "doctype": "Bin", "resp_type": "stock", "stock_warehouses": 5},
    # routing robustness — distinct phrasings must ALL hit Bin (the A-viability signal):
    {"id": "stock_phrasing_instock", "query": "how much Petrol do we have in stock", "kind": "level2",
     "intent": "read", "doctype": "Bin", "resp_type": "stock"},
    {"id": "stock_phrasing_level", "query": "stock level of Petrol", "kind": "level2",
     "intent": "read", "doctype": "Bin", "resp_type": "stock"},

    # ---- refine-vs-fresh classification steer (p15-6) — seeded cases warm the
    #      cache so the REFINEMENT prompt fires (variant-sanity in _checks_for
    #      proves the seed took). A message that NAMES WHAT TO FETCH must classify
    #      `read` (line 794: read bypasses the cache => stack dropped, by code). ----
    {"id": "refine_fresh_win_incident",  # WIN: the CBL-00151 incident — must flip to read
     "query": "need all the po of jain engineering", "kind": "level2",
     "seed": {"doctype": "Purchase Order",
              "filters": {"company": "jain engineering", "grand_total": "<50000",
                          "supplier": "abhijeet", "status": "Draft"}},
     "intent": "read", "doctype": "Purchase Order",
     "carried_absent": ["abhijeet", "grand_total", "Draft"]},
    {"id": "refine_fresh_win_draft_po",  # WIN: names po -> read; resets to just Draft
     "query": "can i get all the draft po", "kind": "level2",
     "seed": {"doctype": "Purchase Order",
              "filters": {"company": "jain engineering", "grand_total": "<50000",
                          "supplier": "abhijeet"}},
     "intent": "read", "doctype": "Purchase Order",
     "filters": [["status", "=", "Draft"]]},
    {"id": "refine_constraint_only_tripwire",  # NON-NEGOTIABLE (clause 1): must STAY refine + merge
     "query": "less than 25000", "kind": "level2",
     "seed": {"doctype": "Purchase Order", "filters": {"status": "pending"}},
     "intent": "refine_read",
     "filters": [["status", "in", ["To Receive and Bill", "To Bill", "To Receive"]],
                 ["grand_total", "<", 25000.0]]},
    {"id": "refine_from_only_tripwire",  # soft boundary (clause 2): "from X only" stays refine
     "query": "from company dux only", "kind": "level2",
     "seed": {"doctype": "Purchase Order", "filters": {"status": "pending"}},
     "intent": "refine_read"},

    # ---- known behavior / limitations ----
    # Field-baked comparator limitation — phrasing-DETERMINISTIC (measured n=10):
    # the conversational "can you show me po..." prefix makes Gemma hallucinate a
    # bad field (amount_uom / amount_less_than / total_amount[<] — the specific
    # field drifts, the query_error outcome is stable 10/10), whereas the
    # imperative "show purchase orders less than..." value-strings cleanly (see
    # comparator_less_than above). Acceptable outcomes: query_error (HOLD, gap
    # present) OR success (RESOLVED? — flagged, not failed). Fails ONLY on
    # permission_denied / handler_error / wrong-result. Tighten expect_outcome to
    # ["success"] once the parked prompt-level comparator canonicalization lands.
    {"id": "known_limit_field_baked_comparator", "query": "can you show me po less than 25000",
     "kind": "known", "expect_outcome": ["query_error"], "resolved_if": "success"},
    {"id": "unsupported_write", "query": "Create a material request",
     "kind": "known", "expect_outcome": ["unsupported"]},
    {"id": "doctype_not_served", "query": "show me journal entries",
     "kind": "known", "expect_outcome": ["unknown", "unsupported"]},
    {"id": "gibberish", "query": "asdf asdf 123",
     "kind": "known", "expect_outcome": ["unknown"]},
]


# =============================================================================
# COMPARISON RULES — order-insensitive conditions, case-insensitive strings,
# numeric equality. Designed so a case never fails on cosmetic differences
# (filter order, LLM casing, 50000 vs 50000.0), only on real shape changes.
# =============================================================================
def _values_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        # `in`-value lists compared order-insensitively (membership is what matters)
        ka = sorted(x.lower() if isinstance(x, str) else x for x in a)
        kb = sorted(x.lower() if isinstance(x, str) else x for x in b)
        return ka == kb
    return a == b


def _condition_equal(c1, c2):
    if not (isinstance(c1, list) and isinstance(c2, list) and len(c1) == len(c2) == 3):
        return c1 == c2
    return c1[0] == c2[0] and c1[1] == c2[1] and _values_equal(c1[2], c2[2])


def _filters_equal(actual, expected):
    """Order-insensitive set-style compare of [field, op, value] conditions."""
    if actual is None:
        return False
    if len(actual) != len(expected):
        return False
    remaining = list(actual)
    for ec in expected:
        hit = next((i for i, ac in enumerate(remaining) if _condition_equal(ac, ec)), None)
        if hit is None:
            return False
        remaining.pop(hit)
    return not remaining


# =============================================================================
# HARNESS
# =============================================================================
_captured = {}
_seed = None  # per-case last_query seed for warm-cache (refinement) cases; None = cold/fresh


def _setup_frappe():
    import frappe
    frappe.init(site=SITE, sites_path=SITES_PATH)
    frappe.connect()
    frappe.set_user("Administrator")
    return frappe


def _patch(api):
    """Monkeypatch the logging + refinement seams: capture instead of logging,
    and force every case to be a fresh first-turn classification (no refine)."""
    def capture(record):
        _captured.clear()
        _captured.update(record)
    api._log_turn = capture
    api._get_last_query = lambda: _seed          # None -> cold (fresh); dict -> warm (refinement prompt + merge)
    api._set_last_query = lambda *a, **k: None


def _invoke(api, query):
    """Run the real handle_message; return the captured record (populated even
    if handle_message re-raises, since _log_turn runs in its finally). The
    handle_message RETURN value (the response dict) is attached as rec['_response']
    so response-shape checks (e.g. the stock aggregate) can assert on it."""
    _captured.clear()
    resp = None
    try:
        resp = api.handle_message(query)
    except Exception as e:  # defensive: handler_error path re-raises post-capture
        _captured.setdefault("_exception", repr(e))
    rec = dict(_captured)
    rec["_response"] = resp
    return rec


def _checks_for(case, rec):
    """Return (list of (name, ok), info-string) for a real (level2/level3) case.
    Checks are conditional on the case's keys, so a refinement case can assert
    intent alone (TRIP-WIRE-2) or carried-absent (WIN-1) without pinning exact
    filters. The variant check is a SEED-SANITY guard: a seeded case MUST run the
    refinement prompt — if a seed silently fails to warm, variant stays with_vocab
    and the case fails, instead of a false green on the cold prompt."""
    intent = rec.get("parsed_intent")
    doctype = rec.get("parsed_doctype")
    count = rec.get("result_count", 0) or 0
    nfj = rec.get("normalized_filters_json")
    actual = json.loads(nfj) if nfj else None
    variant = rec.get("prompt_variant")

    checks = [("intent", intent == case["intent"])]
    if "doctype" in case:
        checks.append(("doctype", doctype == case["doctype"]))
    if "filters" in case:
        checks.append(("filters", _filters_equal(actual, case["filters"])))
    if case.get("carried_absent"):
        checks.append(("carried-absent",
                       not any(s in (nfj or "") for s in case["carried_absent"])))
    if case.get("nonempty"):
        checks.append(("nonempty", count > 0))
    # response-shape checks (stock-querying piece 1) — read the attached response.
    resp = rec.get("_response") or {}
    if "resp_type" in case:
        checks.append(("resp_type", resp.get("type") == case["resp_type"]))
    if "stock_total" in case:
        its = resp.get("items") or []
        tot = its[0].get("total_qty") if its else None
        checks.append(("stock_total",
                       tot is not None and abs(float(tot) - float(case["stock_total"])) < 0.5))
    if "stock_warehouses" in case:
        its = resp.get("items") or []
        pw = its[0].get("per_warehouse") if its else []
        checks.append(("stock_warehouses",
                       bool(its) and len(pw) == case["stock_warehouses"]
                       and abs(sum(x.get("actual_qty") or 0 for x in pw)
                               - float(its[0].get("total_qty") or 0)) < 0.5))
    exp_variant = "with_vocab_and_refinement" if case.get("seed") else "with_vocab"
    checks.append(("variant", variant == exp_variant))
    info = (f"intent={intent} dt={doctype} variant={variant} "
            f"outcome={rec.get('outcome')} count={count} filters={actual}")
    if resp.get("type") == "stock":
        info += " stock=" + str([(i.get("item_code"), i.get("total_qty"), len(i.get("per_warehouse") or []))
                                 for i in (resp.get("items") or [])])
    return checks, info


def _eval_real(api, case):
    global _seed
    _seed = case.get("seed")  # warm the cache for refinement cases; None = cold
    try:
        rec = _invoke(api, case["query"])
        checks, info = _checks_for(case, rec)
        ok = all(v for _, v in checks)
        flaky = False
        if not ok:  # one retry to separate a hard fail from LLM flakiness
            rec2 = _invoke(api, case["query"])
            checks2, info2 = _checks_for(case, rec2)
            if all(v for _, v in checks2):
                ok, flaky, checks, info = True, True, checks2, info2
            else:
                checks, info = checks2, info2  # report the (stable) failing run
    finally:
        _seed = None  # UNCONDITIONAL reset — a thrown seeded case must not warm the next
    status = "FLAKY" if flaky else ("PASS" if ok else "FAIL")
    return {"case": case, "ok": ok, "status": status, "checks": checks, "info": info}


def _eval_known(api, case):
    rec = _invoke(api, case["query"])
    outcome = rec.get("outcome")
    expected = case["expect_outcome"]
    resolved_if = case.get("resolved_if")
    if outcome in expected:
        status, held = "HOLD", True
    elif resolved_if and outcome == resolved_if:
        status, held = "RESOLVED?", True  # not a regression — limitation may be fixed
    else:
        status, held = "REGRESSION", False
    info = f"outcome={outcome} expected={expected}"
    return {"case": case, "held": held, "status": status, "info": info}


def main():
    frappe = _setup_frappe()
    import dux_chatbot.api as api
    _patch(api)

    # Warm the model so case 1 isn't a cold-load timing outlier.
    t0 = time.perf_counter()
    _invoke(api, "show purchase orders")
    warm_ms = int((time.perf_counter() - t0) * 1000)

    real, known = [], []
    lat = []
    for case in EVAL_CASES:
        if case["kind"] in ("level2", "level3"):
            r = _eval_real(api, case)
            real.append(r)
        else:
            r = _eval_known(api, case)
            known.append(r)
        ml = _captured.get("llm_latency_ms")
        if isinstance(ml, int):
            lat.append(ml)

    # ---- report ----
    print("=" * 78)
    print(f"DUX CHATBOT EVAL — baseline   site={SITE}")
    print(f"warm-up latency: {warm_ms}ms   |   {len(EVAL_CASES)} cases "
          f"({len(real)} real + {len(known)} known-behavior)")
    if lat:
        print(f"avg LLM latency: {sum(lat) // len(lat)}ms over {len(lat)} calls")
    print("=" * 78)

    print("\nREAL CASES (level-2 / level-3):")
    for r in real:
        c = r["case"]
        marks = " ".join(f"{n}{'✓' if v else '✗'}" for n, v in r["checks"])
        print(f"  [{r['status']:5}] {c['id']:34} {marks}")

    print("\nKNOWN-BEHAVIOR CASES:")
    for r in known:
        c = r["case"]
        print(f"  [{r['status']:10}] {c['id']:34} {r['info']}")

    real_pass = sum(1 for r in real if r["ok"])
    flaky = sum(1 for r in real if r["status"] == "FLAKY")
    smoke_total = sum(1 for c in EVAL_CASES if c.get("nonempty"))
    smoke_pass = sum(1 for r in real if r["case"].get("nonempty")
                     and dict(r["checks"]).get("nonempty"))
    held = sum(1 for r in known if r["held"])
    resolved = sum(1 for r in known if r["status"] == "RESOLVED?")
    regressed = sum(1 for r in known if r["status"] == "REGRESSION")

    print("\n" + "=" * 78)
    print(f"SCORE (real, level-2+level-3):   {real_pass}/{len(real)}"
          + (f"   ({flaky} flaky — passed on retry)" if flaky else ""))
    print(f"  level-3 non-empty smoke held:  {smoke_pass}/{smoke_total}")
    print(f"KNOWN-LIMITATIONS holding:       {held}/{len(known)}"
          f"   ({resolved} resolved?, {regressed} regressed)")
    print("=" * 78)

    fails = [r for r in real if not r["ok"]]
    if fails or regressed:
        print("\nFAILURE / SURPRISE DETAILS:")
        for r in fails:
            failed = [n for n, v in r["checks"] if not v]
            print(f"\n  ✗ {r['case']['id']}  (failed: {', '.join(failed)})")
            print(f"      query:    {r['case']['query']!r}")
            if r["case"]["kind"] == "level2":
                print(f"      expected: filters={r['case']['filters']}")
            print(f"      got:      {r['info']}")
        for r in known:
            if r["status"] == "REGRESSION":
                print(f"\n  ✗ {r['case']['id']}  (known-behavior REGRESSION)")
                print(f"      query:    {r['case']['query']!r}")
                print(f"      got:      {r['info']}")
    if resolved:
        print("\nRESOLVED? (a tracked limitation stopped failing — investigate, don't celebrate blindly):")
        for r in known:
            if r["status"] == "RESOLVED?":
                print(f"  • {r['case']['id']}: {r['info']}")


if __name__ == "__main__":
    main()
