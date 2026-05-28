# DUX AI Chatbot — LLM Inference Server

**Status:** ✅ Provisioned & verified · Phase 0 LLM round-trip proven end-to-end (Frappe dev box → this box)
**Last updated:** 2026-05-28
**Purpose:** Dedicated, locked-down LLM inference server running Ollama + Gemma 4 E4B. It powers the natural-language → structured-intent layer of an **ERPNext chatbot**. This box is **LLM-only** — no application code, ERP, or web frontend runs here.

---

## 1. Quick Reference

| Item | Value |
|------|-------|
| Server (public IP) | `<llm-box-ip>` |
| SSH access | `ssh root@<llm-box-ip>` (key-based, passwordless) |
| OS | Ubuntu 24.04.4 LTS (kernel 6.8.0-111-generic) |
| CPU | 8 cores — AMD EPYC 9354P (**CPU-only, no GPU**) |
| RAM | 31 GB (32094 MB) |
| Disk | 387 GB total · ~15 GB used after setup · **~372 GB free** |
| Inference engine | Ollama **0.24.0** |
| Model | `gemma4:e4b` (9.6 GB, Q4_K_M, 8.0B params, 131072 context) |
| Ollama bind | `0.0.0.0:11434` (all interfaces; access gated by the UFW source-IP rule below) |
| API endpoint | `http://<llm-box-ip>:11434` — reachable **only from the dev box `<dev-box-ip>`** |
| Firewall | UFW active — inbound `22/tcp` (SSH, anywhere) + `11434/tcp` **only from `<dev-box-ip>`**; default **deny** |
| Consumer | Frappe dev box `frappe@<dev-box-ip>` · app `dux_chatbot` · site `<dev-site>` |
| Performance | ~21–22 tokens/sec (CPU) |

---

## 2. Architecture Context

This server is **one piece** of the larger DUX ERPNext chatbot. It does exactly one job: turn a natural-language request into structured intent JSON.

```
User message
   │
   ▼
[ Frappe dev box (<dev-box-ip>) ]   ── builds prompt, injects today's date
   │
   ▼
[ THIS SERVER: Ollama + Gemma 4 E4B ]  ── returns intent JSON  (read/write, doctype, filters/fields)
   │
   ▼
[ Backend app ]  ── normalizes to real ERPNext fields, then calls frappe.get_list / frappe.new_doc IN-PROCESS (per-user perms)
   │
   ▼
[ ERPNext / Frappe ]  ── runs the query / creates the document
   │
   ▼
[ Backend app ]  ── formats result into a friendly reply
   │
   ▼
User
```

**Key principle:** The LLM never talks to ERPNext and never touches live data or the system clock. It only produces a *best-guess structured interpretation*. The backend is the translator + validator.

---

## 3. Security Posture

**Access model (updated 2026-05-28):** Ollama is reachable **directly** by the Frappe dev box over port 11434, restricted by a **UFW source-IP rule** to that one host. This replaced the earlier SSH-tunnel plan (which was blocked by host-key verification between the two servers).

- **UFW firewall: active.** Default `deny incoming` / `allow outgoing`.
- Inbound rules:
  - `22/tcp (OpenSSH)` — from anywhere (IPv4 + IPv6).
  - `11434/tcp` — **ALLOW IN only from `<dev-box-ip>`** (the dev box). Every other source is dropped by default-deny.
- Ollama binds to `0.0.0.0:11434` (all interfaces), but the firewall ensures **only the dev box** can actually reach it.

> ⚠️ **Ollama has no authentication of its own.** The *only* control protecting the model is the UFW source-IP rule, so treat the dev box's network identity as the trust boundary. Do **not** add broader rules to 11434; if more consumers are ever needed, add explicit per-IP `ufw allow from <ip>` rules instead of widening the port.

### Ollama bind configuration
Configured via systemd override at `/etc/systemd/system/ollama.service.d/override.conf`:
```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```
Verified listening socket: `*:11434`. Apply changes with `systemctl daemon-reload && systemctl restart ollama`.

The UFW rule that gates it:
```bash
ufw allow from <dev-box-ip> to any port 11434 proto tcp
```

### Installed system packages
`ufw`, `curl`, `htop`, `ca-certificates`, `jq` (plus standard Ubuntu 24.04 base).

---

## 4. Network Interfaces

| Interface | Address | Notes |
|-----------|---------|-------|
| `lo` | 127.0.0.1/8, ::1 | loopback — Ollama binds here |
| `eth0` | **<llm-box-ip>/24** | public IP; default gateway <gateway-ip> |
| `eth0` (IPv6) | <llm-box-ipv6> | public IPv6 |

**No private interface** (no 10.x.x.x / 192.168.x.x) — only loopback + the single public `eth0`.

---

## 5. How to Access

### A. Interactive terminal chat (simplest — no tunnel needed)
```bash
ssh -t root@<llm-box-ip> 'ollama run gemma4:e4b --verbose'
```
- `-t` allocates a terminal so the `>>>` prompt works.
- `--verbose` prints timing stats (tokens/sec) after each reply.
- Inside the REPL: `/bye` to quit, `/clear` to reset context, `/?` for help, `/set nothink` to disable reasoning mode.

### B. Direct API access from the dev box (current production path)
The Frappe dev box (`<dev-box-ip>`) reaches Ollama directly over the firewall-restricted port — **no tunnel**:
```bash
# run on the dev box (frappe@<dev-box-ip>):
curl -s http://<llm-box-ip>:11434/api/tags                    # list models
curl -s http://<llm-box-ip>:11434/api/generate -d '{...}'     # inference (see §7)
```
This is the path the `dux_chatbot` Frappe app uses (see §13).

### C. SSH tunnel from your laptop (optional, ad-hoc testing only)
Your laptop is **not** in the firewall allow-list, so to poke at the API from your own machine, tunnel through SSH:
```bash
ssh -N -L 11434:127.0.0.1:11434 root@<llm-box-ip>
```
Silent pipe (`-N` = no shell — don't type into it; **`Ctrl+C` to close**). Maps your laptop's `localhost:11434` → the server's Ollama. Then `http://localhost:11434` works locally (browser shows `Ollama is running` — it's an API, not a web UI).

---

## 6. Model Details

`gemma4:e4b` — pulled via `ollama pull gemma4:e4b`.

| Property | Value |
|----------|-------|
| ID | `c6eb396dbd59` |
| On-disk size | 9.6 GB |
| Architecture | gemma4 |
| Parameters | 8.0B |
| Context length | 131072 |
| Quantization | Q4_K_M |
| Requires | Ollama ≥ 0.20.0 (we run 0.24.0) |
| Capabilities | completion, vision, audio, tools, thinking |

---

## 7. Production Request Recipe

Use this request shape from the backend for the intent-classifier workload:

```json
{
  "model": "gemma4:e4b",
  "prompt": "<today's date> + <user message> + <schema instructions>",
  "stream": false,
  "think": false,
  "format": "json",
  "keep_alive": "5m",
  "options": { "num_predict": 150, "temperature": 0 }
}
```

**Why each setting:**
- `think: false` — disables Gemma's reasoning trace. **Critical.** With thinking on, the model spends its whole token budget reasoning and can return an *empty* answer (see §9). Off = 4× faster.
- `format: "json"` — forces pure, directly-parseable JSON (no ```` ```json ```` markdown fences, no prose). Backend can `json.parse()` the `.response` field directly.
- `temperature: 0` — deterministic; same input → same output (important for a classifier).
- `keep_alive: "5m"` — keeps the model resident in RAM to avoid the ~12.6 s cold-load. Increase to `"30m"` or `-1` (always-on) for bursty traffic.
- `num_predict: 150` — safety cap on output tokens. Responses finish naturally well under this. (`num_predict` = max NEW output tokens; default `-1` = unlimited. Distinct from `num_ctx` = 131072, the total input+output context window.)

**Date handling:** The model has no clock. Inject `Today is YYYY-MM-DD.` into the prompt so it can resolve relative dates ("last month") to absolute ranges — OR have it emit a token like `"period":"last_month"` and resolve it in backend code. (Observed: it interprets "last month" as a rolling 30 days, not the calendar month, unless told otherwise.)

**Stricter output (later):** Instead of `format:"json"`, you can pass a full JSON **schema** to `format` to force exact keys/types once DocType filter shapes are finalized.

### Example call (from the dev box)
```bash
curl -s http://<llm-box-ip>:11434/api/generate -d '{
  "model": "gemma4:e4b",
  "prompt": "Today is 2026-05-28. Convert this ERPNext request to JSON: show purchase orders from last month that are still pending. Use keys: intent (read or write), doctype (English DocType name), filters (object).",
  "stream": false,
  "think": false,
  "format": "json",
  "options": {"num_predict": 150, "temperature": 0}
}'
```

---

## 8. Verified Test Results

All tests run on 2026-05-28. Model resolves correctly in **English, Hindi, and Hinglish**.

### Smoke tests (original validation)
| Test | Input | Output | Speed |
|------|-------|--------|-------|
| Read | "show my pending purchase orders" | `{"intent":"read","doctype":"Purchase Order","filters":{}}` | 15 tok, 21.33 tok/s, 14.56 s (incl. cold load) |
| Write | "create a material request for 10 widgets for IT warehouse" | `{"intent":"write","doctype":"Material Request","fields":{"quantity":"10","item":"widgets","destination":"IT warehouse"}}` | 27 tok, 21.39 tok/s, 2.44 s (warm) |

### Multilingual intent classification (all correct)
| Lang | Input | Output |
|------|-------|--------|
| EN | show me all open sales invoices | `{"intent":"read","doctype":"Sales Invoice","data":{}}` |
| EN | create a new customer named Acme Corp with email acme@example.com | `{"intent":"write","doctype":"Customer","data":{"name":"Acme Corp","email":"acme@example.com"}}` |
| EN | how many purchase orders are pending approval over 5000 rupees | `{"intent":"read","doctype":"Purchase Order","data":{"status":"Pending Approval","min_amount":5000}}` |
| HI | मुझे सभी लंबित खरीद आदेश दिखाओ | `{"intent":"read","doctype":"Purchase Order","data":{}}` |
| HI | आईटी गोदाम के लिए 10 लैपटॉप का सामग्री अनुरोध बनाओ | `{"intent":"write","doctype":"Material Request","data":{"item_name":"Laptop","qty":10,"uom":"unit"}}` |
| HI | इस महीने के सभी बिक्री चालान दिखाओ | `{"intent":"read","doctype":"Sales Invoice","data":{}}` |
| Hinglish | naye supplier add karo naam Sharma Traders | `{"intent":"write","doctype":"Supplier","data":{"name":"Sharma Traders"}}` |

**Performance:** steady ~21–22 tok/s on CPU. First request after idle pays a one-time ~12.6 s model-load cost; warm requests for short JSON land in ~2–6 s.

---

## 9. Key Finding: Disable "Thinking" Mode

Gemma 4 E4B ships with a reasoning ("thinking") mode **on by default** in the bare REPL. For a JSON classifier this is harmful.

Head-to-head, same prompt, `num_predict: 400`:

| | Thinking ON | Thinking OFF |
|---|---|---|
| Reasoning text | 1385 chars | 0 |
| Tokens generated | 400 (hit cap) | 96 |
| Per-token speed | 21.4 tok/s | 22.6 tok/s |
| Wall-clock | 20.1 s | 5.5 s |
| **Actual JSON answer** | **EMPTY** ❌ (budget exhausted by reasoning) | clean JSON ✅ |

**Conclusion:** Always send `"think": false`. Per-token speed is unchanged — thinking simply generates far more tokens, ballooning latency and (when capped) breaking the output entirely.

---

## 10. Backend → ERPNext Translation (design notes)

The handler converts Gemma's intent JSON into **in-process Frappe ORM calls** (`frappe.get_list` / `frappe.new_doc`) — **NOT** the REST API. Because the whitelisted handler runs inside the **logged-in user's own session**, Frappe enforces **per-user permissions automatically** (no API key, no `Authorization` token, no impersonation). This is **architecture decision #9** and the whole reason permissions work correctly per user. The canonical implementation blueprint is **`chat_handler_template.py`**.

### READ → `frappe.get_list(...)`
```python
frappe.get_list(
    "Purchase Order",
    filters={
        "status": "To Receive and Bill",
        "transaction_date": ["between", ["2026-04-01", "2026-04-30"]],
    },
    fields=["name", "supplier", "grand_total", "status"],
    limit_page_length=20,
)  # runs as the current user → only rows they are permitted to see
```

### WRITE → `frappe.new_doc(...).insert()`
```python
doc = frappe.new_doc("Material Request")
doc.material_request_type = "Purchase"
doc.schedule_date = "2026-06-04"
doc.append("items", {"item_code": "LAPTOP-001", "qty": 10, "warehouse": "IT Store - XYZ"})
doc.insert()         # permission-checked as the current user
# doc.submit()       # only after explicit user confirmation (see safety rules)
```

### The handler MUST normalize the LLM's guesses
Gemma produces plausible-but-not-valid fields; the handler maps them to the real schema:

| Gemma emits | ERPNext reality | Fix |
|-------------|-----------------|-----|
| `"status":"Pending"` | `"To Receive and Bill"` | status lookup table |
| `"creation_date"` | `"transaction_date"` | fieldname map |
| `"item_name":"Laptop"` | `"item_code":"LAPTOP-001"` | Item lookup |
| `"destination":"IT warehouse"` | `"warehouse":"IT Store - XYZ"` | Warehouse lookup |
| flat `fields` | nested `items[]` child table | reshape |

### Safety rules for the handler
1. **Confirm before every WRITE.** Creating ERP documents is hard to reverse — the bot should ask "I'll create X — confirm?" and only `.insert()` / `.submit()` on yes. Reads can run immediately.
2. **Lean on Frappe's permission system + validation.** Because calls run in-process as the current user, Frappe already blocks unauthorized reads/writes — but still validate the LLM's output (catch invented fields/items) and ask the user to clarify rather than forwarding bad data.

---

## 11. Operational Constraints (DO / DON'T for this box)

**This server is LLM-only.** To keep it clean and secure:

- ❌ Do **not** widen the 11434 UFW rule beyond `<dev-box-ip>` (the dev box). Add explicit per-IP `ufw allow from <ip>` rules if more consumers are ever needed — never open it to `Anywhere`.
- ❌ Do **not** change `OLLAMA_HOST` away from `0.0.0.0:11434` without re-checking the firewall first (Ollama has no auth — the UFW rule is the only guard).
- ❌ Do **not** install Frappe, ERPNext, Python venvs, FastAPI, Node, or any app/web code here — those belong on the backend/app server.
- ❌ Do **not** pull other models unless explicitly intended (only `gemma4:e4b` is needed).
- ✅ Routine `apt update && apt upgrade` is fine. Avoid rebooting unless an upgrade explicitly requires it.

---

## 12. Common Commands Cheat-Sheet

```bash
# Check service + bind address
ssh root@<llm-box-ip> 'systemctl is-active ollama; ss -tlnp | grep 11434'

# List installed models
ssh root@<llm-box-ip> 'ollama list'

# Firewall status
ssh root@<llm-box-ip> 'ufw status verbose'

# Interactive chat (with speed stats, thinking can be toggled with /set nothink)
ssh -t root@<llm-box-ip> 'ollama run gemma4:e4b --verbose'

# Connectivity test FROM the dev box (should list gemma4:e4b)
ssh frappe@<dev-box-ip> 'curl -s http://<llm-box-ip>:11434/api/tags'

# Open API tunnel from laptop (Ctrl+C to close) — laptop is NOT in the firewall allow-list
ssh -N -L 11434:127.0.0.1:11434 root@<llm-box-ip>

# Restart Ollama after config change
ssh root@<llm-box-ip> 'systemctl daemon-reload && systemctl restart ollama'
```

---

## 13. Dev-Box Frappe App (Phase 0 scaffold + round-trip)

The consumer side lives on the **shared Frappe dev bench** (`frappe@<dev-box-ip>`, bench `/home/frappe/frappe-bench`, Python 3.14.3, frappe 16.12.0 / erpnext 16.10.0). Only the dev site `<dev-site>` and the `dux_chatbot` app are in scope — **never** the client sites (`client-1`, `client-2`, `client-3`, `client-4`), and **never** `bench restart` / `bench start` (this box runs under supervisor).

**What exists after Phase 0:**
- Custom app `dux_chatbot` (title "DUX Chatbot", publisher "DUX Digitech", MIT) — created with `bench new-app`, pip-installed (editable) into the bench env, registered in `sites/apps.txt`, and installed on `<dev-site>` **only**.
- One whitelisted method: `dux_chatbot.api.ping_llm(message)` in `apps/dux_chatbot/dux_chatbot/api.py`. It builds the verified request recipe (§7), POSTs to `http://<llm-box-ip>:11434/api/generate` (timeout 30 s), and returns the parsed `.response` JSON — or `{"intent":"unknown","raw":<text>}` on `JSONDecodeError`.

> **Gotcha encountered:** `bench new-app` calls `uv` to install the app into the env, but `uv` (at `~/.local/bin/uv`, pipx) is only on the **login-shell** PATH, not the non-interactive SSH PATH. The first scaffold aborted at that step; it was completed manually with `bash -lc '... uv pip install -e ...'` and the app name appended to `sites/apps.txt` (the step `new-app` never reached). Without the `apps.txt` entry, `bench install-app` raises `App ... not in apps.txt`.

**Round-trip proven (2026-05-28):**
```
bench --site <dev-site> execute dux_chatbot.api.ping_llm \
  --kwargs "{'message':'show my pending purchase orders'}"
→ {"intent": "read", "doctype": "Purchase Order", "filters": {"status": "Pending"}}
```
Cold call **15.4 s** (incl. model cold-load + bench bootstrap) → warm call **1.95 s**. (The `bench execute` wall-time includes ~1–2 s Frappe bootstrap; from inside a running gunicorn worker the real latency is lower.)

**Applying code changes on this box (the `--preload` gotcha):** gunicorn runs with `--preload`, so workers won't pick up code edits until the **master** is restarted. Do it **without** `bench restart`:
```bash
bench --site <dev-site> clear-cache
SUP=$(pgrep -x supervisord | head -1)
MASTER=$(ps -ef | awk -v sup="$SUP" '/gunicorn -b 127\.0\.0\.1:8000/ && !/grep/ && $3==sup {print $2}')
kill -TERM "$MASTER"   # supervisor respawns the master in ~2 s
```

---

## 14. Open Items / Next Steps

- [x] **Done (Phase 0):** LLM box reachable from the dev box (UFW source-IP rule) + `dux_chatbot` app scaffolded, installed on `<dev-site>`, and LLM round-trip proven via `ping_llm`.
- [ ] **Phase 1:** chat UI + business logic — wire `ping_llm`'s intent JSON into the **in-process handler** (`frappe.get_list` / `frappe.new_doc`, blueprint `chat_handler_template.py`) (§10). The chat Desk page UI already exists (§13).
- [ ] Build the handler (intent JSON → in-process `frappe.get_list` / `frappe.new_doc`, **not** REST — decision #9, runs as the logged-in user for per-user permissions), with field/status/item/warehouse normalization maps per DocType.
- [ ] Implement the write-confirmation gate before any `.insert()` / `.submit()`.
- [ ] Decide date semantics (rolling 30-day vs calendar month) and bake into the prompt or backend.
- [ ] Consider a JSON **schema** (not just `format:"json"`) once DocType filter shapes are fixed.
- [ ] Tune `keep_alive` to match real traffic patterns.
- [ ] (If sub-second latency at scale is needed) evaluate a GPU host — current ~21 tok/s is CPU-bound but fine for human-chat pace.
