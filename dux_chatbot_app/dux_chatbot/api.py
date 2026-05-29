import json
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
# LLM CALL — verified production recipe (think:false MANDATORY)
# =============================================================================
def _call_llm(message: str) -> dict:
    """Call Gemma and return a diagnostics dict for logging:

        {
            "parsed":     <parsed intent dict>,
            "raw":        <raw response string BEFORE json.loads>,
            "variant":    "base" | "with_vocab",
            "latency_ms": <int wall-time of the HTTP call>,
        }

    Never raises: LLM-unreachable and JSON-parse failures are surfaced inside
    ``parsed`` as {"intent": "unknown", ...} so the caller classifies the
    outcome from the return value rather than from exceptions.
    """
    system = (
        f"Today is {date.today().isoformat()}. "
        "You are an ERPNext intent classifier. Reply with ONLY valid JSON, "
        "no prose, no markdown. Schema: "
        '{"intent":"read"|"write","doctype":"<DocType>",'
        '"filters":{...} or "fields":{...}}'
    )

    vocab = frappe.conf.get("chatbot_vocabulary") or {}
    variant = "with_vocab" if vocab else "base"
    if vocab:
        hints = "\n".join(f'- "{k}" means "{v}"' for k, v in vocab.items())
        system += f"\n\nVocabulary hints for this client:\n{hints}"

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
# Per-DocType maps; start small, extend as we add DocTypes.
# =============================================================================
FIELD_MAP = {
    "Purchase Order": {"creation_date": "transaction_date"},
}
STATUS_MAP = {
    "Purchase Order": {
        "Pending": "To Receive and Bill",
        "pending": "To Receive and Bill",
        "Open": "To Receive and Bill",
    },
}
DISPLAY_FIELDS = {
    "Purchase Order": [
        "name", "supplier", "transaction_date", "grand_total", "status",
    ],
}


def _normalize_filters(doctype: str, raw: dict) -> list:
    """Gemma's loose dict -> frappe.get_list's list-of-lists filter format."""
    out = []
    for key, val in (raw or {}).items():
        real_field = FIELD_MAP.get(doctype, {}).get(key, key)
        if isinstance(val, str):
            real_val = STATUS_MAP.get(doctype, {}).get(val, val)
            out.append([real_field, "=", real_val])
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
        }

    # v1 scope: only Purchase Order is wired up. Other DocTypes acknowledged
    # but not executed — keeps blast radius small while we iterate.
    if doctype not in DISPLAY_FIELDS:
        return {
            "type": "unsupported",
            "intent": intent,
            "message": (
                f"I understood that you want to read {doctype}, but I'm only "
                "wired for Purchase Orders right now. More coming soon."
            ),
        }

    filters = _normalize_filters(doctype, intent.get("filters", {}))
    fields = DISPLAY_FIELDS[doctype]

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
        }
    except Exception as e:
        frappe.log_error(f"get_list failed for {doctype}: {e}", "dux_chatbot.api")
        return {
            "type": "error",
            "intent": intent,
            "message": "Something went wrong reading those records.",
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
def handle_message(message: str) -> dict:
    """The real chat entry point. Returns a typed response the UI can render.

    Every turn is logged exactly once (success or failure) via the finally
    block. ``outcome`` is derived from return values — the inner helpers
    (_call_llm, _handle_read) swallow their own errors and never raise — with
    a defensive ``except`` for genuinely unexpected exceptions. The ``raise``
    re-propagates so the user still gets their normal error response; we only
    record the turn before letting it bubble up.
    """
    record = {
        "timestamp": frappe.utils.now_datetime(),
        "session_user": frappe.session.user,
        "session_id": frappe.session.sid,
        "user_message": message,
        "prompt_variant": "base",    # overwritten once we know the real variant
        "result_count": 0,           # 0 for empty / errors unless set on success
        "outcome": "handler_error",  # overwritten on every known path below
    }
    try:
        llm = _call_llm(message)
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

        # --- read ------------------------------------------------------------
        if intent_type == "read":
            response = _handle_read(intent)
            rtype = response.get("type")
            if rtype == "records":
                doctype = intent.get("doctype")
                normalized = _normalize_filters(doctype, intent.get("filters", {}))
                record["normalized_filters_json"] = json.dumps(normalized, default=str)
                record["executed_call"] = f"frappe.get_list({doctype}, filters={normalized})"
                record["result_count"] = response.get("count", 0)
                record["outcome"] = "success" if response.get("count", 0) > 0 else "empty"
            elif rtype == "unsupported":
                record["outcome"] = "unsupported"
            else:  # type == "error": unknown doctype, permission, or get_list failure
                msg = response.get("message") or ""
                low = msg.lower()
                if "permission" in low:
                    record["outcome"] = "permission_denied"
                elif "recognize" in low:
                    record["outcome"] = "unknown"
                else:
                    record["outcome"] = "handler_error"
                record["error_message"] = msg
            return response

        # --- write (not yet supported) ---------------------------------------
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
