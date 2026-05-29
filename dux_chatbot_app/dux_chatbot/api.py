import json
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
    system = (
        f"Today is {date.today().isoformat()}. "
        "You are an ERPNext intent classifier. Reply with ONLY valid JSON, "
        "no prose, no markdown. Schema: "
        '{"intent":"read"|"write","doctype":"<DocType>",'
        '"filters":{...} or "fields":{...}}'
    )

    vocab = frappe.conf.get("chatbot_vocabulary") or {}
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
    try:
        resp = requests.post(_ollama_url(), json=payload, timeout=30)
        resp.raise_for_status()
        raw = resp.json().get("response", "{}")
    except requests.RequestException as e:
        frappe.log_error(f"Ollama request failed: {e}", "dux_chatbot.api")
        return {"intent": "unknown", "error": "llm_unreachable"}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"intent": "unknown", "raw": raw}


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
# PUBLIC ENTRY POINTS
# =============================================================================
@frappe.whitelist()
def ping_llm(message: str) -> dict:
    """Debug endpoint — returns raw intent JSON. Kept for diagnostics."""
    return _call_llm(message)


@frappe.whitelist()
def handle_message(message: str) -> dict:
    """The real chat entry point. Returns a typed response the UI can render."""
    intent = _call_llm(message)

    if intent.get("intent") == "unknown":
        return {
            "type": "error",
            "intent": intent,
            "message": "I didn't quite catch that — could you rephrase?",
        }

    if intent.get("intent") == "read":
        return _handle_read(intent)

    if intent.get("intent") == "write":
        return {
            "type": "unsupported",
            "intent": intent,
            "message": "Drafting documents is coming soon — for now I can read data.",
        }

    return {
        "type": "error",
        "intent": intent,
        "message": "I'm not sure how to handle that yet.",
    }
