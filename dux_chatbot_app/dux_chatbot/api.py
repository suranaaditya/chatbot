import json
import re
import time
from datetime import date

import frappe
import requests


# =============================================================================
# CONFIG — ollama_url is read from site_config.json (NOT hardcoded).
# Set on the server with: bench --site <site> set-config ollama_url "http://..."
# =============================================================================
def _ollama_url() -> str:
    return frappe.conf.get("ollama_url") or "http://127.0.0.1:11434/api/generate"


# =============================================================================
# CONFIG ACCESSORS — `chatbot_registry` is the SOLE per-doctype config source.
# The four per-doctype config layers were consolidated into ONE `chatbot_registry`
# object keyed by DocType (migration 20c40a5; the flat legacy keys it replaced —
# chatbot_doctypes / _vocabulary / _field_aliases / _status_aliases — were then
# DELETED). These accessors read the registry ONLY: if it is absent they return
# empty (no doctypes / no aliases) — the correct LOUD failure, NOT a silent revert
# to stale config.
# `chatbot_company_aliases` is GLOBAL (not per-doctype), was never in the registry,
# and is retained — read top-level via _cfg_company_aliases().
#
# Registry shape:
#   {"<DocType>": {"vocab": ["<term>", ...],
#                  "field_aliases": {"<alias>": "<field>"},
#                  "status_aliases": {"<term>": {"field": "<f>", "values": [...]}}},
#    ...}
# =============================================================================
def _cfg_registry() -> dict:
    return frappe.conf.get("chatbot_registry") or {}


def _cfg_doctypes() -> list:
    """Allow-list = registry keys (insertion order preserved, so the prompt's
    DocType block order stays stable). Empty if the registry is absent."""
    return list(_cfg_registry().keys())


def _cfg_vocabulary() -> dict:
    """FLAT {term: doctype} — the shape _call_llm consumes — inverted from the
    registry's per-doctype {dt: [terms]}. Non-empty iff the registry has vocab
    terms (_call_llm keys prompt_variant off vocab presence)."""
    out = {}
    for dt, entry in _cfg_registry().items():
        for term in ((entry or {}).get("vocab") or []):
            out[term] = dt
    return out


def _cfg_field_aliases(doctype: str) -> dict:
    """Per-doctype {alias: field} from the registry."""
    return (_cfg_registry().get(doctype) or {}).get("field_aliases", {})


def _cfg_status_aliases(doctype: str) -> dict:
    """Per-doctype {term: {field, values}} from the registry."""
    return (_cfg_registry().get(doctype) or {}).get("status_aliases", {})


def _cfg_company_aliases() -> dict:
    """GLOBAL colloquial->Company map — always top-level, never in the registry."""
    return frappe.conf.get("chatbot_company_aliases") or {}


# =============================================================================
# CONVERSATION MEMORY (p1-10) — last successful read per user, in Redis.
# Stateless-LLM design preserved: chat history is NOT put in the prompt; only
# the previous query's doctype + filters are, and only when something is cached.
# =============================================================================
LAST_QUERY_TTL_SEC = 4 * 60  # 4-minute sliding TTL (was 8*60; shortened p15-7)


def _last_query_key() -> str:
    """Cache key for the last successful read/refine. Scoped per-USER, and
    per-TAB when a browser tab id is present (p15-7): handle_message stashes the
    frontend sessionStorage UUID in frappe.flags.dux_tab_id (request-scoped), so
    two tabs of one login get separate refinement memories. A falsy/absent tab id
    falls back to the user-only key (eval, scripts, console) — deterministic, and
    keeps _get_last_query/_set_last_query arg-less so the eval override holds."""
    base = f"dux_chatbot:last_query:{frappe.session.user}"
    tab = getattr(frappe.flags, "dux_tab_id", None)
    return f"{base}:{tab}" if tab else base


def _get_last_query():
    """Return the cached last-query dict, or None. Sliding TTL: reading does
    NOT extend the timer; only a write (via _set_last_query) resets it."""
    try:
        return frappe.cache().get_value(_last_query_key())
    except Exception:
        return None


def _set_last_query(doctype, filters, fields) -> None:
    """Cache the just-completed read/refine. Resets the 8-min sliding TTL.
    Caching failures must NEVER break the user flow (same contract as
    _log_turn) — the user still gets their answer; the next turn just won't
    have refinement context."""
    try:
        frappe.cache().set_value(
            _last_query_key(),
            {
                "doctype": doctype,
                "filters": filters,
                "fields": fields,
                "ts": frappe.utils.now_datetime().isoformat(),
            },
            expires_in_sec=LAST_QUERY_TTL_SEC,
        )
    except Exception:
        pass


# =============================================================================
# SYSTEM PROMPTS (p1-10 / p1-11)
# Two prompts, gated by cache presence. Built from shared pieces so the
# doctype/filters shape is byte-identical across both; the ONLY differences are
# (a) refine_read in the intent enum and (b) the CONTEXT block appended to the
# refinement variant. The today's-date preamble is prepended at call time.
# SYSTEM_BASE has NO notion of refine_read (decision #31).
# =============================================================================
_PROMPT_HEAD = (
    "You are an ERPNext intent classifier. Reply with ONLY valid JSON, "
    "no prose, no markdown. Schema: "
)
_SCHEMA_BODY = (
    ',"doctype":"Purchase Order","filters":{"supplier":"Acme Corp"}}'
    "\n"
    "doctype is any ERPNext DocType name in English "
    "(e.g. Purchase Order, Sales Invoice, Item, Supplier). "
    "filters is an object of field/value pairs, or {} if none.\n"
    "- For status, you may use either an exact status value from the options "
    'listed under the DocType, OR a common term like "pending", "open", '
    '"unpaid", "paid", "completed". Both are understood; prefer the user\'s '
    "own word if they used one of these common terms.\n"
    "- For amount/number comparisons (more than, less than, above, below), put "
    "the operator INSIDE the value as a string on a real field, e.g. "
    '{"grand_total":">50000"} or {"grand_total":"<25000"}. NEVER put the '
    'operator in the field name (not "grand_total[<]", not "amount_less_than").\n'
    "- If the message is gibberish, off-topic, or you cannot identify a "
    'target DocType with confidence, return intent="unknown" with '
    "doctype=null and empty filters. Do NOT echo schema placeholder "
    "strings as values."
)
SYSTEM_BASE = _PROMPT_HEAD + '{"intent":"read"|"write"|"unknown"' + _SCHEMA_BODY
SYSTEM_WITH_REFINEMENT = (
    _PROMPT_HEAD + '{"intent":"read"|"refine_read"|"write"|"unknown"' + _SCHEMA_BODY
)
# Appended (formatted) to SYSTEM_WITH_REFINEMENT at call time. Kept separate so
# .format() only ever touches {doctype}/{filters} here — never the literal JSON
# braces in _SCHEMA_BODY above.
REFINEMENT_CONTEXT = (
    "\n\n"
    "CONTEXT — previous query in this session:\n"
    "  doctype: {doctype}\n"
    "  filters: {filters}\n"
    "Decide between a NEW query and a refinement by whether the message NAMES "
    "WHAT TO FETCH:\n"
    "- If it names a record type (purchase order/po, purchase invoice, item, "
    "supplier, ...) OR an entity as the thing requested (e.g. \"pos of supplier "
    "X\", \"show X's invoices\", \"all the draft po\"), it is a NEW query: "
    'return intent="read" (or "write"/"unknown") and do NOT reuse the previous '
    "filters.\n"
    "- Return intent=\"refine_read\" ONLY when the message adds a constraint to "
    "the previous results WITHOUT naming what to fetch: a bare number/comparator "
    "(\"less than 25000\", \"above 50000\") or a narrowing like \"from X only\" "
    "/ \"only X\" / \"only the pending ones\". Put ONLY the new/changed filters "
    "in the filters field; do not repeat the old filters.\n"
    "Examples (a previous query exists in every case):\n"
    '  "need all the po of jain engineering" -> read (names po; new query)\n'
    '  "can i get all the draft po" -> read (names po; new query)\n'
    '  "less than 25000" -> refine_read (constraint only; names nothing)\n'
    '  "from company dux only" -> refine_read (constraint only; names nothing)'
)


# =============================================================================
# META INJECTION (task B) — generalize reads beyond Purchase Order via meta.
# get_meta_for_doctype is purpose-parameterized so Phase 3's slot-filler can
# reuse it (write_slots is a stub). Relies on Frappe's built-in (Redis) meta
# cache — no custom cache layer.
# =============================================================================
def get_meta_for_doctype(doctype, purpose):
    """Return a purpose-scoped view of a DocType's meta.

    Purposes:
      - "read_filter": {"fields": [{fieldname, fieldtype, label}, ...],
        "selects": {fieldname: [options]}} — fields the LLM may filter on
        (Frappe-flagged AND filter-typed); small Selects (<=12 options) carry
        their options so the LLM can emit exact valid values (retires STATUS_MAP).
      - "read_display": [fieldname, ...] — result columns, `name` first, capped.
      - "write_slots": STUB for Phase 3.
    """
    meta = frappe.get_meta(doctype)

    if purpose == "read_filter":
        type_keep = {
            "Data", "Link", "Select", "Date", "Datetime",
            "Currency", "Int", "Float", "Check",
        }
        fields = []
        selects = {}
        for f in meta.fields:
            flagged = (
                getattr(f, "in_list_view", 0)
                or getattr(f, "in_standard_filter", 0)
                or getattr(f, "search_index", 0)
                or getattr(f, "reqd", 0)
            )
            if not (flagged and f.fieldtype in type_keep):
                continue
            fields.append({
                "fieldname": f.fieldname,
                "fieldtype": f.fieldtype,
                "label": f.label or f.fieldname,
            })
            if f.fieldtype == "Select" and f.options:
                opts = [o.strip() for o in f.options.split("\n") if o.strip()]
                if 0 < len(opts) <= 12:
                    selects[f.fieldname] = opts
        return {"fields": fields, "selects": selects}

    if purpose == "read_display":
        # Chat-optimal columns, fully meta-driven (no per-doctype hardcoding):
        # name + title (deduped vs its Link shadow) + primary Link fields +
        # one Currency/amount column + in_list_view fill, capped at 6.
        cols = ["name"]  # always first — deep-link target (8058de8)
        title = getattr(meta, "title_field", None)

        # Title field, but skip if it's the *_name shadow of a Link we'll add
        # anyway (e.g. PO's title_field supplier_name shadows the supplier Link).
        # Prefer the Link (filterable, canonical) over its _name shadow.
        link_fieldnames = {
            f.fieldname for f in meta.fields
            if f.fieldtype == "Link"
            and (getattr(f, "in_standard_filter", 0) or getattr(f, "in_list_view", 0))
        }
        title_is_link_shadow = (
            title and any(title == lf + "_name" or title == lf for lf in link_fieldnames)
        )
        if title and not title_is_link_shadow and title not in cols:
            cols.append(title)

        # Primary Link fields — the "who/what" of the record
        for f in meta.fields:
            if len(cols) >= 5:  # leave room for an amount column below
                break
            if f.fieldtype == "Link" and f.fieldname in link_fieldnames \
               and f.fieldname not in cols:
                cols.append(f.fieldname)

        # Ensure one amount/currency column if the doctype has one (chat-useful)
        if len(cols) < 6:
            for f in meta.fields:
                if f.fieldtype == "Currency" and getattr(f, "in_list_view", 0) \
                   and f.fieldname not in cols:
                    cols.append(f.fieldname)
                    break

        # Fill any remaining slots from in_list_view
        for f in meta.fields:
            if len(cols) >= 6:
                break
            if getattr(f, "in_list_view", 0) and f.fieldname not in cols:
                cols.append(f.fieldname)

        return cols[:6]

    if purpose == "write_slots":
        raise NotImplementedError("write_slots — Phase 3")

    raise ValueError(f"Unknown purpose: {purpose}")


def _build_meta_context(refinement_doctype=None):
    """Build the 'Available DocTypes' block injected into the system prompt.

    Returns (context_string, build_ms). Permission-gated: drops DocTypes the
    session user can't read. On a refinement turn (refinement_doctype set) the
    cached doctype gets its full read_filter view; others are names-only (lean).
    On a fresh turn, every candidate gets the light view (name + Select options).

    NEVER raises — same swallow-all contract as _log_turn / _set_last_query. A
    bad whitelist entry degrades to no-meta (pre-task-B behavior), not a broken
    turn.
    """
    t0 = time.perf_counter()
    try:
        whitelist = _cfg_doctypes()
        candidates = [
            dt for dt in whitelist
            if frappe.has_permission(dt, "read", user=frappe.session.user)
        ]
        if not candidates:
            return ("", int((time.perf_counter() - t0) * 1000))

        lines = ["", "Available DocTypes:"]
        for dt in candidates:
            if dt == refinement_doctype:
                view = get_meta_for_doctype(dt, "read_filter")
                field_summary = ", ".join(f["fieldname"] for f in view["fields"][:15])
                lines.append(f"- {dt} (fields: {field_summary})")
                for fname, opts in view["selects"].items():
                    lines.append(f"  {fname} options: {', '.join(opts)}")
            elif refinement_doctype is not None:
                lines.append(f"- {dt}")
            else:
                view = get_meta_for_doctype(dt, "read_filter")
                lines.append(f"- {dt}")
                for fname, opts in view["selects"].items():
                    lines.append(f"  {fname} options: {', '.join(opts)}")
        context = "\n".join(lines)
    except Exception:
        try:
            frappe.log_error(frappe.get_traceback(), "Chatbot meta build failed")
        except Exception:
            pass
        context = ""
    return (context, int((time.perf_counter() - t0) * 1000))


# =============================================================================
# LLM CALL — verified production recipe (think:false MANDATORY)
# =============================================================================
def _call_llm(message: str, meta_context: str = "") -> dict:
    """Call Gemma and return a diagnostics dict for logging:

        {
            "parsed":     <parsed intent dict>,
            "raw":        <raw response string BEFORE json.loads>,
            "variant":    "base"|"with_vocab"|"with_refinement"|"with_vocab_and_refinement",
            "latency_ms": <int wall-time of the HTTP call>,
        }

    Never raises: LLM-unreachable and JSON-parse failures are surfaced inside
    ``parsed`` as {"intent": "unknown", ...} so the caller classifies the
    outcome from the return value rather than from exceptions.

    System prompt assembly order (task B): schema/rules -> meta context ->
    vocab hints -> refinement CONTEXT (appended last, by recency).
    """
    today = f"Today is {date.today().isoformat()}. "

    # p1-10: gate the prompt on cached last-query presence. Read once here for
    # prompt selection; the refine dispatch in handle_message re-reads to merge
    # (that second read is what surfaces the rare expiry race it falls through).
    last_q = _get_last_query()
    refinement_context = bool(last_q)

    # [schema + rules] — refine_read enum only when a cache is present.
    system = today + (SYSTEM_WITH_REFINEMENT if refinement_context else SYSTEM_BASE)
    base_variant = "with_refinement" if refinement_context else "base"

    # [meta context] — candidate DocTypes block (task B), after schema/rules.
    if meta_context:
        system += meta_context

    # [vocab hints] (p1-9) — applied on top of the chosen base prompt.
    vocab = _cfg_vocabulary()
    if vocab:
        hints = "\n".join(f'- "{k}" means "{v}"' for k, v in vocab.items())
        system += f"\n\nVocabulary hints for this client:\n{hints}"
        variant = "with_vocab_and_refinement" if refinement_context else "with_vocab"
    else:
        variant = base_variant

    # [refinement CONTEXT] — appended LAST so the active query reads as most recent.
    if refinement_context:
        system += REFINEMENT_CONTEXT.format(
            doctype=last_q["doctype"],
            filters=json.dumps(last_q.get("filters") or {}),
        )

    payload = {
        "model": "gemma4:e4b",
        "prompt": f'{system}\n\nUser said: "{message}"',
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": "5m",
        "options": {"num_predict": 150, "temperature": 0},
    }

    latency_ms = 0
    try:
        t0 = time.perf_counter()
        resp = requests.post(_ollama_url(), json=payload, timeout=30)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        resp.raise_for_status()
        raw = resp.json().get("response", "{}")
    except requests.RequestException as e:
        frappe.log_error(f"Ollama request failed: {e}", "dux_chatbot.api")
        return {
            "parsed": {"intent": "unknown", "error": "llm_unreachable"},
            "raw": "",
            "variant": variant,
            "latency_ms": latency_ms,
        }

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"intent": "unknown", "raw": raw}

    return {
        "parsed": parsed,
        "raw": raw,
        "variant": variant,
        "latency_ms": latency_ms,
    }


# =============================================================================
# NORMALIZATION LAYER — translates Gemma's loose JSON to real ERPNext schema.
# STATUS_MAP and DISPLAY_FIELDS are RETIRED (task B): Select values are now
# canonicalized against the doctype's real meta options, and display columns
# come from get_meta_for_doctype(..., "read_display").
#
# p1-14 additions:
#  (1) field pre-validation against meta BEFORE get_list — an unknown filter
#      field becomes query_error (honest 'rephrase' nudge) instead of Frappe's
#      misleading PermissionError (this Frappe version raises PermissionError
#      for unknown filter fields, even as Administrator);
#  (2) comparator operators (>, <, >=, <=, !=) translated to Frappe filter
#      syntax, with numeric coercion for Currency/Int/Float fields;
#  (3) loose case-insensitive `like` matching for Link-field values (cheap
#      entity-resolution proxy; full version is Phase 2);
#  (4) FIELD_MAP demoted to a FALLBACK behind the per-site chatbot_field_aliases
#      config (parallel to chatbot_status_aliases).
# =============================================================================
FIELD_MAP = {
    # Legacy hardcoded field-name aliases — now a FALLBACK behind the per-site
    # `chatbot_field_aliases` config (p1-14 part 4). creation_date ->
    # transaction_date is a genuine DOMAIN alias, NOT derivable from meta: the
    # LLM's "creation_date" means the PO's business date (transaction_date), not
    # the row's DB `creation` timestamp. Kept so PO date queries don't regress
    # if the config key is unset.
    "Purchase Order": {"creation_date": "transaction_date"},
}

COMPARATORS = {">", "<", ">=", "<=", "!="}

# Leading-operator STRING form Gemma actually emits for above/below queries,
# e.g. ">50000", ">= 1000" (it rarely emits the structured [op,val]/{op:val}
# shapes). Longest operators first so >=/<= win over >/<. g1 = op, g2 = operand.
_STR_COMPARATOR_RE = re.compile(r"^\s*(>=|<=|!=|>|<)\s*(.+)$")

# Real DB columns that aren't always present in meta.fields — whitelisted so
# field validation (p1-14 part 1) doesn't reject a legitimate filter on them.
_STD_FIELDS = {
    "name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
    "parent", "parenttype", "parentfield",
}


class _FilterError(Exception):
    """Raised by _normalize_filters when the LLM's filter cannot be built into a
    valid query — an unknown field name (validated against meta) or an operand
    that won't coerce for a numeric field. _handle_read maps it to a
    `query_error` response so the user gets a precise 'rephrase' nudge, instead
    of the query reaching get_list and surfacing as a misleading PermissionError."""

    pass


def _coerce_numeric(operand, fieldtype, fieldname):
    """Coerce a comparator operand to a number on numeric fields so `>`/`<`
    compare numerically, not lexically (">" "50000" as a string compare
    misbehaves). Strips thousands-separator commas first ("50,000" -> 50000).
    Non-numeric fields (Date, Data, Link, ...) pass the operand through
    unchanged — Frappe/MariaDB handles e.g. date-string comparison. A
    non-numeric operand on a numeric field is a query_error."""
    if fieldtype not in ("Currency", "Float", "Percent", "Int"):
        return operand
    cleaned = operand.replace(",", "").strip() if isinstance(operand, str) else operand
    try:
        return int(float(cleaned)) if fieldtype == "Int" else float(cleaned)
    except (TypeError, ValueError):
        raise _FilterError(
            f"I couldn't read '{operand}' as a number for '{fieldname}'. Try a numeric value."
        )


def _like_escape(value: str) -> str:
    """Escape LIKE wildcards (%, _) and the escape char itself so a Link value
    is matched literally apart from our own surrounding %...% (MariaDB LIKE uses
    backslash as the default escape char). Plain names have nothing to escape."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# A "plausible" field name is a clean identifier that does NOT bake a comparator
# into the name. The field-validation message branches on this (p15-1): a
# plausible-but-wrong field (e.g. total_amount, nonexistent_field) keeps the
# precise p1-15 message (it helps the user spot the right field); a mangled
# token — brackets/operators (grand_total[<], amount[<]) or a baked comparator
# word-suffix (amount_less_than) — gets a generic rephrase hint instead of
# echoing nonsense back at the user.
_PLAUSIBLE_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_BAKED_SUFFIX_RE = re.compile(r"_(less|greater|more|fewer)_than$", re.IGNORECASE)


def _is_plausible_field(name) -> bool:
    name = str(name)
    return bool(_PLAUSIBLE_FIELD_RE.match(name)) and not _BAKED_SUFFIX_RE.search(name)


def resolve_company(value):
    """Resolve an LLM-emitted name to a canonical Company name, or None (p15-1c).

    Deterministic, EXACT + ALIAS only — NOT loose substring (with 66 companies a
    substring rule would false-positive a supplier value onto a company). Order:
      1. case-insensitive EXACT match of `value` against the Company master
         (Company names are unique, so this yields at most one);
      2. else case-insensitive lookup of `value` in the per-site
         `chatbot_company_aliases` map, returning its canonical ONLY if that
         canonical itself exists in the Company master (so a typo'd alias canonical
         falls through to None -> supplier, never a filter on a dead company);
      3. else None.
    Never raises: a Company-read failure -> None -> existing supplier handling.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip().lower()
    try:
        by_lower = {n.lower(): n for n in frappe.get_all("Company", pluck="name")}
    except Exception:
        return None
    if v in by_lower:                       # (1) ci-exact against the master
        return by_lower[v]
    aliases = _cfg_company_aliases()   # (2) validated alias
    for k, canon in aliases.items():
        if isinstance(k, str) and k.lower() == v and isinstance(canon, str):
            return by_lower.get(canon.lower())  # master casing, or None if alias canonical is dead
    return None


def _normalize_filters(doctype: str, raw: dict) -> list:
    """Gemma's loose dict -> frappe.get_list's list-of-lists filter format.

    Field-aware status semantic layer: a colloquial status term emitted on the
    status field is looked up in the per-doctype chatbot_status_aliases config,
    which maps it to {target field, value set} and becomes an `in` filter. The
    config's "field" lets a term target workflow_state on workflow-enabled sites
    vs status otherwise (decided per-client; workflow path built but verified
    for status only). Exact status values fall through to a case-insensitive
    option match (single `=`), so power-user exact-status queries still work
    (soften-not-flip). Eventual home is a Desk-editable "Chatbot DocType Config"
    DocType (parked).

    p1-14 per-filter pipeline: resolve the field name (chatbot_field_aliases
    config -> legacy FIELD_MAP -> as-is) -> validate the resolved field against
    the doctype meta (unknown -> _FilterError -> query_error) -> build the
    filter: status alias (`in`), comparator (`>`/`<`/`>=`/`<=`/`!=` with numeric
    coercion), loose Link match (`like %val%`), Select canonicalization (`=`),
    between, or plain `=`.
    """
    try:
        meta = frappe.get_meta(doctype)
        field_types = {f.fieldname: f.fieldtype for f in meta.fields}
        valid_fields = set(field_types) | _STD_FIELDS
    except Exception:
        # Meta unavailable (unexpected — doctype is validated upstream in
        # _handle_read). Degrade to pre-p1-14 behavior: skip validation rather
        # than false-reject every filter.
        field_types = {}
        valid_fields = None

    try:
        selects = get_meta_for_doctype(doctype, "read_filter")["selects"]
    except Exception:
        selects = {}

    aliases = _cfg_status_aliases(doctype)
    field_aliases = _cfg_field_aliases(doctype)

    out = []
    for key, val in (raw or {}).items():
        # [field-name resolution] config field-alias -> legacy FIELD_MAP -> as-is.
        real_field = field_aliases.get(key) or FIELD_MAP.get(doctype, {}).get(key, key)

        # [part 1: validate the RESOLVED field BEFORE building/querying anything].
        # Catching wrong fields here keeps Frappe's PermissionError (raised for
        # unknown filter fields) meaning ONLY a genuine access denial.
        if valid_fields is not None and real_field not in valid_fields:
            if _is_plausible_field(key):
                # Real-word wrong field (e.g. total_amount) — the precise p1-15
                # message helps the user spot/correct it. Byte-identical to before.
                raise _FilterError(
                    f"I don't recognize the field '{key}' on {doctype}. Could you rephrase?"
                )
            # Field-baked / mangled token (grand_total[<], amount[<],
            # amount_less_than) — never echo it; give an actionable example (p15-1).
            raise _FilterError(
                "I couldn't parse that filter. Try rephrasing — "
                'for example, "POs above 50000" or "POs less than 25000".'
            )
        fieldtype = field_types.get(real_field)

        if isinstance(val, str):
            # (1) field-aware status alias -> `in` filter on the configured
            #     field. Gated to a status-field emission; a malformed config
            #     entry skips safely (never raises) and falls through below.
            alias_entry = aliases.get(val.lower()) if real_field == "status" else None
            if (isinstance(alias_entry, dict) and alias_entry.get("field")
                    and isinstance(alias_entry.get("values"), list) and alias_entry["values"]):
                out.append([alias_entry["field"], "in", alias_entry["values"]])
                continue
            # (2) part 2 string-form comparator: Gemma emits a leading-operator
            #     STRING (">50000", ">= 1000") for above/below queries, not the
            #     structured [op,val] list / {op:val} dict handled below. Parse
            #     it to a real comparator. Numeric fields coerce the operand;
            #     Date/other fields pass it through (so "transaction_date >
            #     2026-01-01" works too). Exact-status and Link values never
            #     start with an operator, so this won't hijack them.
            m = _STR_COMPARATOR_RE.match(val)
            if m:
                out.append([real_field, m.group(1), _coerce_numeric(m.group(2).strip(), fieldtype, real_field)])
                continue
            # (3) part 3: loose, case-insensitive Link match. MariaDB's default
            #     _ci collation makes `like` case-insensitive; `%val%` is
            #     forgiving for partial names ("Bhandari" -> "Bhandari Hardware").
            #     It can match MULTIPLE records (e.g. "Bhandari" -> both Bhandari
            #     Hardware AND Bhandari Printers) — acceptable for v1: the user
            #     sees the list and refines. Top-N disambiguation is Phase 2
            #     entity resolution (ChromaDB).
            if fieldtype == "Link":
                # p15-1c: the model routes company names to `supplier` (it can't
                # entity-type, and ignores the "company" keyword — STEP-0 probe).
                # Deterministically rescue a value that resolves to exactly one
                # Company (ci-exact or via chatbot_company_aliases) and is NOT also
                # a real Supplier -> filter on `company`. Real suppliers / ambiguous
                # names keep the loose-Link wildcard unchanged.
                if real_field == "supplier":
                    canonical = resolve_company(val)
                    if canonical and not frappe.db.exists("Supplier", val):
                        out.append(["company", "=", canonical])
                        continue
                out.append([real_field, "like", f"%{_like_escape(val)}%"])
                continue
            # (4) case-insensitive Select-option match, then (5) raw -> `=`.
            real_val = val
            for opt in selects.get(real_field, []):
                if opt.lower() == val.lower():
                    real_val = opt  # canonical casing from meta
                    break
            out.append([real_field, "=", real_val])
        # part 2: comparator as a 2-element [op, value] list, e.g. [">", 50000].
        elif isinstance(val, list) and len(val) == 2 and val[0] in COMPARATORS:
            out.append([real_field, val[0], _coerce_numeric(val[1], fieldtype, real_field)])
        # part 2: comparator as a single-key {op: value} dict, e.g. {">": 50000}.
        elif isinstance(val, dict) and len(val) == 1 and next(iter(val)) in COMPARATORS:
            op, operand = next(iter(val.items()))
            out.append([real_field, op, _coerce_numeric(operand, fieldtype, real_field)])
        # between: {"value": [lo, hi]}.
        elif isinstance(val, dict) and "value" in val and isinstance(val["value"], list):
            out.append([real_field, "between", val["value"]])
        else:
            out.append([real_field, "=", val])
    return out


# =============================================================================
# READ HANDLER — runs IN-PROCESS as frappe.session.user.
# This is what enforces per-user permissions automatically — no API tokens.
# =============================================================================
def _handle_read(intent: dict) -> dict:
    doctype = intent.get("doctype")

    if not doctype or not frappe.db.exists("DocType", doctype):
        return {
            "type": "error",
            "intent": intent,
            "message": f"I don't recognize the record type: {doctype or '(none)'}.",
            "error_kind": "unknown_doctype",  # caller maps to outcome=unknown
        }

    # Chatbot scope = curated whitelist (site_config.chatbot_doctypes). User
    # permission is enforced separately by frappe.get_list running as the
    # session user below — this gate is "not wired up for the bot", not "no perm".
    whitelist = _cfg_doctypes()
    if doctype not in whitelist:
        return {
            "type": "unsupported",
            "intent": intent,
            "message": (
                f"I understood that you want to read {doctype}, but it's not one "
                "of the record types I'm set up for yet. More coming soon."
            ),
        }

    try:
        filters = _normalize_filters(doctype, intent.get("filters", {}))
    except _FilterError as e:
        # p1-14 part 1: wrong field / unparseable operand caught BEFORE get_list
        # — honest query_error (user should rephrase), distinct from the
        # PermissionError / generic except blocks around get_list below.
        return {
            "type": "error",
            "intent": intent,
            "message": str(e),
            "error_kind": "query_error",  # caller maps to outcome=query_error
        }
    fields = get_meta_for_doctype(doctype, "read_display")

    try:
        records = frappe.get_list(
            doctype,
            filters=filters,
            fields=fields,
            limit_page_length=20,
            order_by="modified desc",
        )
    except frappe.PermissionError:
        return {
            "type": "error",
            "intent": intent,
            "message": "You don't have permission to view those records.",
            "error_kind": "permission_denied",  # caller maps to outcome=permission_denied
        }
    except Exception:
        # Bad field name, malformed filter, bad operator, etc. — NOT a
        # permissions problem. The user should rephrase, not contact their
        # admin. Capture the full traceback in the Error Log so ops can see
        # the real cause while the user sees only the friendly message.
        frappe.log_error(frappe.get_traceback(), "Chatbot read query_error")
        return {
            "type": "error",
            "intent": intent,
            "message": "I couldn't run that query — I may have misunderstood a field or value. Try rephrasing.",
            "error_kind": "query_error",  # caller maps to outcome=query_error
        }

    link_base = f"/app/{doctype.lower().replace(' ', '-')}"

    return {
        "type": "records",
        "intent": intent,
        "doctype": doctype,
        "fields": fields,
        "records": records,
        "count": len(records),
        "link_base": link_base,
        # The post-normalization filter list that ACTUALLY queried ERPNext above.
        # Surfaced to the UI (read-only) so it can render transparent "filter
        # pills" showing which filters produced this result. Visual-layer only —
        # identical to what _log_turn records as normalized_filters_json. This is
        # the lone backend touch for the UI revamp; classification / normalization
        # / refinement logic is untouched.
        "normalized_filters": filters,
    }


# =============================================================================
# STOCK HANDLER (stock-querying piece 1) — doctype "Bin" needs an AGGREGATE answer
# (total actual_qty + per-warehouse breakdown), NOT a document row-list. This is an
# ADDITIVE branch alongside _handle_read; the document read path is unchanged.
# =============================================================================
def _handle_stock(intent: dict) -> dict:
    """Stock-on-hand answer for the Bin doctype: current actual_qty per item per
    warehouse, AGGREGATED into a per-item total + per-warehouse breakdown — the
    shape "what is the stock of X" wants (a number, not a row list). actual_qty
    ONLY (projected/reserved omitted — users found them confusing).

    PERMISSION model is identical to _handle_read: the get_list runs IN-PROCESS as
    frappe.session.user, so a role-less user hits the SAME permission_denied path
    (Bin read is role-gated to Stock/Sales/Purchase User+Manager). No bypass, no
    get_latest_stock_qty (which would skip per-user perms). Item resolution reuses
    _normalize_filters' loose-Link output (Bin.item_code is a Link to Item, so
    "100mm DI" -> ["item_code","like","%100mm DI%"]); a loose match can hit MULTIPLE
    items ("stock of pipe") -> each is returned with its own total (user refines).
    """
    if "Bin" not in _cfg_doctypes():
        return {"type": "unsupported", "intent": intent,
                "message": "Stock lookups aren't set up yet."}
    try:
        filters = _normalize_filters("Bin", intent.get("filters", {}))
    except _FilterError as e:
        return {"type": "error", "intent": intent, "message": str(e),
                "error_kind": "query_error"}
    try:
        rows = frappe.get_list(
            "Bin",
            filters=filters,
            fields=["item_code", "warehouse", "actual_qty", "stock_uom"],
            limit_page_length=0,  # aggregate needs ALL warehouse rows (Bin is small)
            order_by="item_code asc, actual_qty desc",
        )
    except frappe.PermissionError:
        return {"type": "error", "intent": intent,
                "message": "You don't have permission to view stock levels.",
                "error_kind": "permission_denied"}
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Chatbot stock query_error")
        return {"type": "error", "intent": intent,
                "message": "I couldn't look up that stock — try naming the item differently.",
                "error_kind": "query_error"}

    # aggregate actual_qty by item_code (first-seen order preserved)
    agg, order = {}, []
    for r in rows:
        ic = r.get("item_code")
        if ic not in agg:
            agg[ic] = {"item_code": ic, "stock_uom": r.get("stock_uom"),
                       "total_qty": 0.0, "per_warehouse": []}
            order.append(ic)
        agg[ic]["total_qty"] += (r.get("actual_qty") or 0)
        agg[ic]["per_warehouse"].append({"warehouse": r.get("warehouse"),
                                         "actual_qty": r.get("actual_qty") or 0})
    items = [agg[ic] for ic in order]
    return {
        "type": "stock",
        "intent": intent,
        "doctype": "Bin",
        "items": items,
        "count": len(items),
        "normalized_filters": filters,  # the item filter, for the read-only pills
    }


# =============================================================================
# LOGGING — persist every turn to the Chatbot Log DocType.
# Logging MUST NOT break the user flow: _log_turn swallows ALL errors.
#
# TODO(retention): Chatbot Log rows accumulate unbounded. A retention/cleanup
#   strategy (e.g. default_log_clearing_doctypes in hooks.py, or a scheduled
#   task) should prune old rows. Out of scope for this session — flagged for
#   a future one.
# =============================================================================
def _log_turn(record: dict) -> None:
    """Persist a Chatbot Log row. NEVER raises — logging must not break the
    user flow. Failures get a frappe.log_error and are otherwise swallowed."""
    try:
        doc = frappe.new_doc("Chatbot Log")
        doc.update(record)
        doc.insert(ignore_permissions=True)
        frappe.db.commit()  # commit the log even if the parent request rolls back
    except Exception:
        try:
            frappe.log_error(frappe.get_traceback(), "Chatbot Log insert failed")
        except Exception:
            pass  # truly cannot help further; do not propagate


# =============================================================================
# PUBLIC ENTRY POINTS
# =============================================================================
@frappe.whitelist()
def ping_llm(message: str) -> dict:
    """Debug endpoint — returns raw parsed intent JSON. Kept for diagnostics."""
    return _call_llm(message)["parsed"]


@frappe.whitelist()
def chatbot_registry_status() -> dict:
    """Read-only completeness view (System Manager only): per registered DocType,
    which config layers are populated + the live record count. The standing,
    one-call version of the manual config audit ("what's configured vs not").
    Reads through the same accessors, so it reflects the ACTIVE source (registry
    when present, else the legacy keys)."""
    frappe.only_for("System Manager")
    vocab = _cfg_vocabulary()
    out = {}
    for dt in _cfg_doctypes():
        try:
            count = frappe.db.count(dt)
        except Exception:
            count = None
        out[dt] = {
            "vocab": bool([t for t, d in vocab.items() if d == dt]),
            "field_aliases": bool(_cfg_field_aliases(dt)),
            "status_aliases": bool(_cfg_status_aliases(dt)),
            "records": count,
        }
    return out


@frappe.whitelist()
def handle_message(message: str, tab_id: str = None) -> dict:
    """The real chat entry point. Returns a typed response the UI can render.

    Every turn is logged exactly once (success or failure) via the finally
    block. ``outcome`` is derived from return values — the inner helpers
    (_call_llm, _handle_read) swallow their own errors and never raise — with
    a defensive ``except`` for genuinely unexpected exceptions. The ``raise``
    re-propagates so the user still gets their normal error response; we only
    record the turn before letting it bubble up.
    """
    # p15-7: stash the frontend per-tab id (sessionStorage UUID) request-scoped so
    # _last_query_key() scopes the refinement cache to THIS tab. Guarded on a
    # truthy tab_id — an empty/None value falls through to the user-only key
    # (matching the eval/script path), never an empty ":"-suffixed key fragment.
    if tab_id:
        frappe.flags.dux_tab_id = tab_id
    record = {
        "timestamp": frappe.utils.now_datetime(),
        "session_user": frappe.session.user,
        "session_id": frappe.session.sid,
        "user_message": message,
        "prompt_variant": "base",    # overwritten once we know the real variant
        "meta_build_ms": 0,          # set from _build_meta_context below
        "result_count": 0,           # 0 for empty / errors unless set on success
        "outcome": "handler_error",  # overwritten on every known path below
    }
    try:
        # task B: build the candidate-DocType meta block before the LLM call.
        # Lean on refinement turns (only the cached doctype gets full meta).
        # meta_build_ms is set here so it logs even if the turn later errors.
        last_q = _get_last_query()
        refinement_doctype = last_q["doctype"] if last_q else None
        meta_context, meta_build_ms = _build_meta_context(refinement_doctype)
        record["meta_build_ms"] = meta_build_ms

        llm = _call_llm(message, meta_context=meta_context)
        intent = llm["parsed"]
        record["prompt_variant"] = llm["variant"]
        record["llm_latency_ms"] = llm["latency_ms"]
        record["llm_raw_response"] = llm["raw"]
        record["parsed_intent"] = intent.get("intent")
        record["parsed_doctype"] = intent.get("doctype")
        record["parsed_filters_json"] = json.dumps(intent.get("filters") or {}, default=str)

        intent_type = intent.get("intent")

        # --- LLM-level failures surface as intent == "unknown" ---------------
        if intent_type == "unknown":
            if intent.get("error") == "llm_unreachable":
                record["outcome"] = "llm_error"
                record["error_message"] = "LLM unreachable"
            elif "raw" in intent:
                record["outcome"] = "parse_error"
                record["error_message"] = "LLM returned non-JSON"
            else:
                record["outcome"] = "unknown"
            return {
                "type": "error",
                "intent": intent,
                "message": "I didn't quite catch that — could you rephrase?",
            }

        # --- read / refine_read ----------------------------------------------
        # refine_read merges the LLM's new filters onto the cached last query
        # (new wins on conflict) and always reuses the cached doctype. If the
        # cache expired between the LLM call and here (rare race), fall through
        # to a fresh read with whatever the LLM gave us — never crash.
        if intent_type in ("read", "refine_read"):
            if intent_type == "refine_read":
                last_q = _get_last_query()
                if last_q:
                    merged_filters = {
                        **(last_q.get("filters") or {}),
                        **(intent.get("filters") or {}),
                    }
                    effective_intent = {
                        **intent,
                        "doctype": last_q["doctype"],  # always the cached doctype
                        "filters": merged_filters,
                    }
                else:
                    # Race fall-through: cache expired between the LLM call and
                    # dispatch. Treat as a fresh read. No special cache gating
                    # is needed here — caching below is purely count>0, so an
                    # empty result on this turn won't cache (same as a fresh read).
                    effective_intent = intent
            else:
                effective_intent = intent

            doctype = effective_intent.get("doctype")
            # Bin = stock-on-hand: an AGGREGATE answer (total + per-warehouse), not a
            # document row-list. Intercept BEFORE the generic read so it never falls
            # through to the row-renderer (or the Item card — the bug we're fixing).
            response = (_handle_stock(effective_intent) if doctype == "Bin"
                        else _handle_read(effective_intent))
            rtype = response.get("type")
            if rtype == "records":
                eff_filters = effective_intent.get("filters", {})
                normalized = _normalize_filters(doctype, eff_filters)
                record["normalized_filters_json"] = json.dumps(normalized, default=str)
                # executed_call is Long Text (p1-13) — no length cap, so the
                # full query string (including long multi-filter ones) is logged.
                record["executed_call"] = f"frappe.get_list({doctype}, filters={normalized})"
                record["result_count"] = response.get("count", 0)
                record["outcome"] = "success" if response.get("count", 0) > 0 else "empty"
                # Cache for future refinement ONLY on a non-empty result —
                # identical condition for fresh reads and refinements. An empty
                # or wrong refine must NOT poison the cache for later turns.
                if response.get("count", 0) > 0:
                    _set_last_query(
                        doctype=doctype,
                        filters=eff_filters,
                        fields=response.get("fields", []),
                    )
            elif rtype == "stock":
                # Bin aggregate: log like a read (so the turn is auditable), but do
                # NOT cache for refinement in Piece 1 (stock refinement is a follow-up).
                norm = response.get("normalized_filters") or []
                record["normalized_filters_json"] = json.dumps(norm, default=str)
                record["executed_call"] = f"frappe.get_list(Bin, filters={norm}) [stock aggregate]"
                record["result_count"] = response.get("count", 0)
                record["outcome"] = "success" if response.get("count", 0) > 0 else "empty"
            elif rtype == "unsupported":
                record["outcome"] = "unsupported"
            else:  # type == "error": unknown doctype, permission, or query error
                msg = response.get("message") or ""
                # Drive the outcome off the explicit error_kind flag set by
                # _handle_read (p1-15) — every error return now carries one, so
                # no fragile message text-matching is needed.
                kind = response.get("error_kind")
                if kind == "permission_denied":
                    record["outcome"] = "permission_denied"
                elif kind == "query_error":
                    record["outcome"] = "query_error"
                elif kind == "unknown_doctype":
                    record["outcome"] = "unknown"
                else:
                    record["outcome"] = "handler_error"
                record["error_message"] = msg
            return response

        # --- write (not yet supported) ---------------------------------------
        # NOTE: cache is intentionally NOT cleared on write/unknown (locked
        # design) — users often refer back across a non-read interruption.
        if intent_type == "write":
            record["outcome"] = "unsupported"
            return {
                "type": "unsupported",
                "intent": intent,
                "message": "Drafting documents is coming soon — for now I can read data.",
            }

        # --- anything else ---------------------------------------------------
        record["outcome"] = "unknown"
        return {
            "type": "error",
            "intent": intent,
            "message": "I'm not sure how to handle that yet.",
        }
    except Exception:
        record["outcome"] = "handler_error"
        record["error_message"] = frappe.get_traceback()
        raise
    finally:
        _log_turn(record)
