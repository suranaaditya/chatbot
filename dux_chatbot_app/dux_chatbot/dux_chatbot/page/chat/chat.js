frappe.pages['chat'].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper, title: 'Dux', single_column: true,
  });

  // Hide Frappe's default page head for an immersive surface
  $(wrapper).find('.page-head').hide();
  $(wrapper).find('.page-body').css({ 'margin-top': 0, 'padding': 0 });

  // App-served brand art (copied into dux_chatbot/public/images -> /assets/...).
  const MASCOT     = '/assets/dux_chatbot/images/dux-mascot.png';   // 3D mascot
  const MARK_LIGHT = '/assets/dux_chatbot/images/dux-mark-v2.png';  // dark monogram (light theme)
  const MARK_DARK  = '/assets/dux_chatbot/images/dux-mark-white.png';// light monogram (dark theme)

  // --- DUX per-tab id: scopes the refinement cache to THIS tab (p15-7) ---------
  // sessionStorage = per-tab, survives reload, cleared on tab close. Do NOT move
  // to localStorage (shared across tabs) or regenerate per page-load (breaks
  // reload continuity). Self-contained — keep this block intact through any UI
  // revamp; submit() passes duxTabId() to handle_message as tab_id.
  function duxTabId() {
    let id = sessionStorage.getItem('dux_tab_id');
    if (!id) {
      id = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : String(Date.now()) + Math.random().toString(16).slice(2);
      sessionStorage.setItem('dux_tab_id', id);
    }
    return id;
  }
  // "New search" mints a FRESH per-tab id so the next handle_message starts a new
  // refinement context (new cache key) — reuses duxTabId's exact key + generator,
  // leaving its sessionStorage persistence (reload continuity) otherwise intact.
  function duxNewTabId() {
    const id = (window.crypto && crypto.randomUUID)
      ? crypto.randomUUID()
      : String(Date.now()) + Math.random().toString(16).slice(2);
    sessionStorage.setItem('dux_tab_id', id);
    return id;
  }

  // ---- inline icon set (ported from the design's icons.jsx, thin-stroke) ------
  function ic(p) {
    return '<svg class="dux-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
      + ' stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + p + '</svg>';
  }
  const IC = {
    filter:   ic('<path d="M3 5h18l-7 8v6l-4-2v-4z"/>'),
    clock:    ic('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    truck:    ic('<path d="M3 7h11v8H3z"/><path d="M14 9h4l3 3v3h-7"/><circle cx="7" cy="17" r="1.6"/><circle cx="17" cy="17" r="1.6"/>'),
    building: ic('<path d="M5 21V5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v16"/><path d="M15 9h3a1 1 0 0 1 1 1v11"/><path d="M9 8h2M9 12h2M9 16h2"/><path d="M3 21h18"/>'),
    rupee:    ic('<path d="M7 5h10M7 9h10M16 5c0 4-3.5 5-6.5 5L16 19"/><path d="M7 9h3"/>'),
    calendar: ic('<rect x="3.5" y="5" width="17" height="16" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'),
    box:      ic('<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>'),
    search:   ic('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
    sparkle:  ic('<path d="M12 3l1.6 4.8L18 9.4l-4.4 1.6L12 16l-1.6-5L6 9.4l4.4-1.6z"/><path d="M19 14l.7 2.1L22 17l-2.3.9L19 20l-.7-2.1L16 17l2.3-.9z"/>'),
    send:     ic('<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>'),
    plus:     ic('<path d="M12 5v14"/><path d="M5 12h14"/>'),
    moon:     ic('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'),
    sun:      ic('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/>'),
    chevron:  ic('<path d="m15 18-6-6 6-6"/>'),
    layers:   ic('<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>'),
    refresh:  ic('<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 4v4h-4"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 20v-4h4"/>'),
  };

  const style = `
  <style>
  @import url('https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

  /* ===== DUX "precision instrument" surface — scoped to .dux-root ===== */
  .dux-root{
    /* structural tokens (shared across themes) */
    --ui:'Geist','Geist Variable',system-ui,-apple-system,'Segoe UI',sans-serif;
    --mono:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;
    --r-sm:8px;--r-md:12px;--r-lg:16px;--r-xl:22px;
    --grad:linear-gradient(90deg,var(--iris) 0%,#4F9FD8 55%,var(--cyan) 100%);
    --glow:1;
    --spring:cubic-bezier(.22,1,.36,1);--ease:cubic-bezier(.4,0,.2,1);

    /* LIGHT THEME (default) — embeds in ERPNext v16 light Desk */
    --canvas:#F3F4F7;--surface-1:#FFFFFF;--surface-2:#FFFFFF;--surface-3:#F0F1F5;
    --card-bg:#FFFFFF;--hairline:#E7E9EE;--hairline-2:#DCDFE6;
    --iris:#5C4DE6;--iris-soft:#6D5EF6;--iris-deep:#4A3CD0;
    --cyan:#0E9C8B;--cyan-soft:#0CB4A0;
    --fg-1:#1A2030;--fg-2:#586273;--fg-3:#8A93A3;--fg-4:#AAB2BF;
    --ok:#15916A;--ok-bg:rgba(21,145,106,.10);
    --pending:#B0741A;--pending-bg:rgba(176,116,26,.11);
    --err:#C8475E;--err-bg:rgba(200,71,94,.09);
    --hdr-bg:rgba(255,255,255,.82);--th-bg:#FAFAFC;--meta-bg:#FAFAFC;
    --row-hover:rgba(92,77,230,.045);--avatar-bg:#F4F4FC;
    --user-bg:linear-gradient(180deg,rgba(92,77,230,.12),rgba(92,77,230,.08));
    --user-border:rgba(92,77,230,.28);--user-fg:#2C2566;
    --shadow-card:0 6px 26px rgba(22,28,46,.07);--shadow-pop:0 10px 34px rgba(22,28,46,.10);
    --inset-hi:inset 0 1px 0 rgba(255,255,255,.6);--scrollthumb:#D4D8E0;
    --ambient:radial-gradient(120% 64% at 50% -16%,rgba(92,77,230,.06),transparent 60%),
              radial-gradient(80% 50% at 88% 6%,rgba(14,156,139,.045),transparent 55%);
    --pill-bg:#F5F6F9;

    position:fixed;inset:0;z-index:99999;
    font-family:var(--ui);background:var(--canvas);color:var(--fg-1);
    display:flex;flex-direction:column;overflow:hidden;
    -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
  }
  /* DARK THEME (toggle) — focused instrument surface */
  .dux-root[data-dux-theme="dark"]{
    --canvas:#0A0D13;--surface-1:#11151E;--surface-2:#181D29;--surface-3:#1E2433;
    --card-bg:linear-gradient(180deg,#181D29,#161A25);--hairline:#232938;--hairline-2:#2C3344;
    --iris:#6D5EF6;--iris-soft:#8A7DF8;--iris-deep:#5B4DE0;
    --cyan:#2DD4BF;--cyan-soft:#5CE6D5;
    --fg-1:#E8EAF1;--fg-2:#9AA3B7;--fg-3:#5E6678;--fg-4:#424A5C;
    --ok:#34D39A;--ok-bg:rgba(52,211,154,.10);
    --pending:#E0A85C;--pending-bg:rgba(224,168,92,.11);
    --err:#E8738A;--err-bg:rgba(232,115,138,.10);
    --hdr-bg:rgba(17,21,30,.80);--th-bg:#141926;--meta-bg:rgba(255,255,255,.008);
    --row-hover:rgba(109,94,246,.06);--avatar-bg:rgba(255,255,255,.035);
    --user-bg:linear-gradient(180deg,rgba(109,94,246,.20),rgba(109,94,246,.13));
    --user-border:rgba(124,110,248,.34);--user-fg:#F1F0FF;
    --shadow-card:0 18px 50px rgba(0,0,0,.42);--shadow-pop:0 14px 40px rgba(0,0,0,.40);
    --inset-hi:inset 0 1px 0 rgba(255,255,255,.045);--scrollthumb:#2C3344;
    --ambient:radial-gradient(120% 70% at 50% -12%,rgba(109,94,246,.16),transparent 60%),
              radial-gradient(90% 60% at 88% 8%,rgba(45,212,191,.07),transparent 55%);
    --pill-bg:var(--surface-3);
  }
  .dux-root *{box-sizing:border-box;}
  .dux-root a{color:inherit;text-decoration:none;}
  .dux-root button{font-family:inherit;}
  .dux-root .dux-ic{width:1em;height:1em;display:block;}
  .dux-mono{font-family:var(--mono);font-variant-numeric:tabular-nums;}

  /* ambient depth */
  .dux-ambient{position:absolute;inset:0;pointer-events:none;z-index:0;background:var(--ambient);
    transition:background .4s var(--ease);}

  /* monogram mark (dual PNG, theme-swapped) */
  .dux-mark{position:relative;display:inline-block;}
  .dux-mark img{width:100%;height:100%;object-fit:contain;display:block;}
  .dux-mark .dux-m-dark{display:none;}
  .dux-root[data-dux-theme="dark"] .dux-mark .dux-m-light{display:none;}
  .dux-root[data-dux-theme="dark"] .dux-mark .dux-m-dark{display:block;}

  /* ===== Header ===== */
  .dux-hdr{position:relative;z-index:5;display:flex;align-items:center;justify-content:space-between;
    padding:14px 22px;flex:0 0 auto;background:var(--hdr-bg);
    -webkit-backdrop-filter:blur(16px) saturate(130%);backdrop-filter:blur(16px) saturate(130%);
    border-bottom:1px solid var(--hairline);}
  .dux-hdr-brand{display:flex;align-items:center;gap:12px;}
  .dux-brand-mark{width:32px;height:32px;flex:0 0 auto;border-radius:9px;overflow:hidden;
    display:grid;place-items:center;background:radial-gradient(circle at 50% 38%,var(--avatar-bg),transparent 78%);}
  .dux-brand-mark img{width:100%;height:100%;object-fit:cover;object-position:50% 38%;transform:scale(1.28);
    -webkit-mask-image:radial-gradient(circle at 50% 44%,#000 60%,transparent 76%);
            mask-image:radial-gradient(circle at 50% 44%,#000 60%,transparent 76%);}
  .dux-brand-divider{width:1px;height:24px;background:var(--hairline-2);}
  .dux-brand-text{display:flex;align-items:baseline;gap:7px;}
  .dux-brand-text b{font-size:16px;font-weight:600;letter-spacing:-.02em;color:var(--fg-1);}
  .dux-brand-text small{font-size:12px;color:var(--fg-3);font-weight:450;}
  .dux-hdr-right{display:flex;align-items:center;gap:9px;}

  .dux-iconbtn{width:34px;height:34px;flex:0 0 auto;border-radius:10px;cursor:pointer;
    display:grid;place-items:center;background:var(--surface-1);border:1px solid var(--hairline-2);
    color:var(--fg-2);transition:all .22s var(--spring);}
  .dux-iconbtn .dux-ic{width:16px;height:16px;}
  .dux-iconbtn:hover{color:var(--iris);border-color:var(--iris);transform:translateY(-1px);}
  .dux-btn-new{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;font-weight:500;
    color:var(--fg-1);padding:8px 14px;border-radius:999px;cursor:pointer;
    background:var(--surface-1);border:1px solid var(--hairline-2);transition:all .25s var(--spring);}
  .dux-btn-new .dux-ic{width:14px;height:14px;}
  .dux-btn-new:hover{background:var(--surface-3);border-color:var(--iris);color:var(--iris);transform:translateY(-1px);}

  /* ===== Stream ===== */
  .dux-stream{position:relative;z-index:2;flex:1 1 auto;overflow-y:auto;scroll-behavior:smooth;}
  .dux-stream::-webkit-scrollbar{width:10px;}
  .dux-stream::-webkit-scrollbar-thumb{background:var(--scrollthumb);border-radius:999px;border:3px solid var(--canvas);}
  .dux-inner{max-width:1160px;margin:0 auto;padding:30px 28px 26px;display:flex;flex-direction:column;gap:24px;}
  .dux-turn{animation:duxSettle .5s var(--spring) both;}
  @keyframes duxSettle{from{opacity:0;transform:translateY(12px);}to{opacity:1;transform:none;}}

  /* user message */
  .dux-msg-user{display:flex;flex-direction:column;align-items:flex-end;gap:5px;}
  .dux-bubble-user{max-width:640px;background:var(--user-bg);border:1px solid var(--user-border);
    color:var(--user-fg);padding:12px 16px;border-radius:16px 16px 5px 16px;
    font-size:14.5px;line-height:1.55;box-shadow:var(--inset-hi);white-space:pre-wrap;}

  /* timestamp (mono) */
  .dux-ts{font-family:var(--mono);font-size:10.5px;color:var(--fg-4);letter-spacing:.02em;
    transition:color .3s var(--ease);user-select:none;}
  .dux-turn:hover .dux-ts{color:var(--fg-2);}
  .dux-msg-user .dux-ts{padding-right:3px;}

  /* assistant message */
  .dux-msg-ai{display:flex;gap:13px;align-items:flex-start;}
  .dux-avatar{position:relative;flex:0 0 auto;width:34px;height:34px;border-radius:10px;margin-top:1px;
    display:grid;place-items:center;background:var(--avatar-bg);border:1px solid var(--hairline-2);
    box-shadow:var(--inset-hi);overflow:hidden;}
  .dux-avatar .dux-mark{width:21px;height:15px;}
  .dux-avatar::after{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;
    background:var(--grad);opacity:calc(.45*var(--glow));
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
    -webkit-mask-composite:xor;mask-composite:exclude;}
  .dux-ai-body{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:10px;}
  .dux-ai-text{font-size:14.5px;line-height:1.6;color:var(--fg-1);max-width:66ch;}
  .dux-ai-text b{font-weight:600;}
  .dux-accent-n{color:var(--cyan);font-family:var(--mono);font-variant-numeric:tabular-nums;font-weight:600;}
  .dux-err-text{color:var(--err);}

  /* ===== Result card ===== */
  .dux-result-card{background:var(--card-bg);border:1px solid var(--hairline);border-radius:var(--r-lg);
    box-shadow:var(--shadow-card),var(--inset-hi);overflow:hidden;}

  /* filter pills */
  .dux-pills-bar{padding:14px 16px 13px;border-bottom:1px solid var(--hairline);position:relative;}
  .dux-pills-bar::before{content:"";position:absolute;left:0;right:0;top:0;height:2px;
    background:var(--grad);opacity:calc(.6*var(--glow));}
  .dux-pills-label{display:flex;align-items:center;gap:7px;font-size:11px;letter-spacing:.08em;
    text-transform:uppercase;color:var(--fg-3);margin-bottom:11px;font-weight:600;}
  .dux-pills-label .dux-ic{width:13px;height:13px;opacity:.8;}
  .dux-pills{display:flex;flex-wrap:wrap;gap:8px;}
  .dux-pill{display:inline-flex;align-items:center;gap:7px;padding:6px 11px 6px 9px;border-radius:9px;
    font-size:12.5px;background:var(--pill-bg);border:1px solid var(--hairline-2);color:var(--fg-1);
    animation:duxPillIn .5s var(--spring) both;}
  .dux-pi{width:22px;height:22px;border-radius:6px;display:grid;place-items:center;flex:0 0 auto;}
  .dux-pi .dux-ic{width:13px;height:13px;}
  .dux-pk{color:var(--fg-3);}
  .dux-pv{font-weight:500;}
  .dux-pv.num{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--cyan);}
  @keyframes duxPillIn{from{opacity:0;transform:translateY(6px) scale(.96);}to{opacity:1;transform:none;}}
  .dux-pi.t-iris{background:rgba(109,94,246,.14);color:var(--iris);}
  .dux-pi.t-cyan{background:rgba(45,212,191,.14);color:var(--cyan);}
  .dux-pi.t-pending{background:var(--pending-bg);color:var(--pending);}
  .dux-pi.t-ok{background:var(--ok-bg);color:var(--ok);}
  .dux-pi.t-mut{background:var(--surface-3);color:var(--fg-2);}

  /* meta row */
  .dux-result-meta{display:flex;align-items:center;justify-content:space-between;padding:11px 16px;
    border-bottom:1px solid var(--hairline);background:var(--meta-bg);}
  .dux-count{font-size:12.5px;color:var(--fg-2);}
  .dux-count b{color:var(--fg-1);font-family:var(--mono);font-weight:600;}
  .dux-sum{font-size:12.5px;color:var(--fg-3);}
  .dux-sum b{color:var(--cyan);font-family:var(--mono);font-weight:600;}

  /* data table */
  .dux-tbl-scroll{overflow-x:auto;}
  .dux-tbl{width:100%;border-collapse:collapse;font-size:13px;table-layout:auto;}
  .dux-tbl thead th{text-align:left;font-weight:600;font-size:10.5px;letter-spacing:.07em;
    text-transform:uppercase;color:var(--fg-3);padding:11px 16px;border-bottom:1px solid var(--hairline);
    white-space:nowrap;background:var(--th-bg);}
  .dux-tbl thead th.num,.dux-tbl tbody td.num{text-align:right;}
  .dux-tbl tbody td{padding:12px 16px;border-bottom:1px solid var(--hairline);color:var(--fg-1);
    white-space:normal;vertical-align:middle;overflow-wrap:anywhere;}
  .dux-tbl tbody tr{transition:background .18s var(--ease);}
  .dux-tbl tbody tr:last-child td{border-bottom:none;}
  .dux-tbl tbody tr:hover{background:var(--row-hover);}
  .dux-cell-id{font-family:var(--mono);color:var(--cyan);font-weight:600;cursor:pointer;white-space:nowrap;}
  .dux-root a.dux-cell-id:hover{color:var(--cyan-soft);text-decoration:underline;}
  .dux-cell-num{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--fg-1);font-weight:500;white-space:nowrap;}
  .dux-cell-num .rs{color:var(--fg-3);margin-right:1px;}
  .dux-cell-date{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--fg-2);font-size:12.5px;white-space:nowrap;}
  .dux-cell-sup{color:var(--fg-1);}
  .dux-cell-co{color:var(--fg-2);}
  .dux-empty-rows{padding:30px 18px;text-align:center;color:var(--fg-2);font-size:14px;}

  /* status tag */
  .dux-tag{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;padding:3px 9px;border-radius:999px;font-weight:500;white-space:nowrap;}
  .dux-tag .d{width:5px;height:5px;border-radius:50%;}
  .dux-tag.pending{color:var(--pending);background:var(--pending-bg);}.dux-tag.pending .d{background:var(--pending);}
  .dux-tag.approved{color:var(--ok);background:var(--ok-bg);}.dux-tag.approved .d{background:var(--ok);}
  .dux-tag.draft{color:var(--fg-2);background:var(--surface-3);}.dux-tag.draft .d{background:var(--fg-3);}

  /* ===== Thinking (mascot variant) ===== */
  .dux-thinking{display:flex;gap:13px;align-items:flex-start;}
  .dux-think-card{flex:1 1 auto;padding:15px 17px;border-radius:var(--r-md);background:var(--surface-2);
    border:1px solid var(--hairline);position:relative;overflow:hidden;box-shadow:var(--shadow-card);}
  .dux-think-bar{position:absolute;top:0;left:0;right:0;height:2px;background:var(--grad);opacity:calc(.85*var(--glow));}
  .dux-think-bar::after{content:"";position:absolute;inset:0;
    background:linear-gradient(90deg,transparent,rgba(255,255,255,.7),transparent);
    transform:translateX(-100%);animation:duxSweep 1.5s var(--ease) infinite;}
  @keyframes duxSweep{to{transform:translateX(100%);}}
  .dux-think-mascot{display:flex;align-items:center;gap:13px;}
  .dux-tm-img{position:relative;width:44px;height:44px;flex:0 0 auto;display:grid;place-items:center;}
  .dux-tm-img img{width:40px;height:40px;object-fit:contain;animation:duxBob 2.4s var(--ease) infinite;
    filter:drop-shadow(0 3px 8px rgba(0,0,0,.22));
    -webkit-mask-image:radial-gradient(circle at 50% 46%,#000 60%,transparent 76%);
            mask-image:radial-gradient(circle at 50% 46%,#000 60%,transparent 76%);}
  .dux-tm-img::before{content:"";position:absolute;inset:-6px;border-radius:50%;
    background:radial-gradient(circle,rgba(109,94,246,.28),transparent 70%);animation:duxPulseG 2s var(--ease) infinite;}
  @keyframes duxBob{0%,100%{transform:translateY(0);}50%{transform:translateY(-3px);}}
  @keyframes duxPulseG{0%,100%{opacity:.5;transform:scale(.92);}50%{opacity:1;transform:scale(1.06);}}
  .dux-think-head{font-size:13.5px;color:var(--fg-1);font-weight:500;}
  .dux-shim{background:linear-gradient(90deg,var(--fg-3) 30%,var(--fg-1) 50%,var(--fg-3) 70%);
    background-size:200% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;
    animation:duxShim 2.2s linear infinite;}
  @keyframes duxShim{to{background-position:-200% 0;}}
  .dux-think-sub{font-size:12px;color:var(--fg-3);margin-top:5px;}

  /* ===== Empty state ===== */
  .dux-empty{flex:1 1 auto;display:grid;place-items:center;position:relative;z-index:2;padding:40px;}
  .dux-empty-inner{max-width:560px;text-align:center;display:flex;flex-direction:column;align-items:center;}
  .dux-empty-mascot{position:relative;width:128px;height:128px;display:grid;place-items:center;margin-bottom:24px;}
  .dux-empty-mascot img{width:116px;height:116px;object-fit:contain;
    filter:drop-shadow(0 12px 28px rgba(20,28,46,.22));animation:duxFloaty 5s var(--ease) infinite;
    -webkit-mask-image:radial-gradient(circle at 50% 46%,#000 62%,transparent 78%);
            mask-image:radial-gradient(circle at 50% 46%,#000 62%,transparent 78%);}
  .dux-empty-mascot::before{content:"";position:absolute;width:200px;height:200px;border-radius:50%;
    background:radial-gradient(circle,rgba(109,94,246,calc(.18*var(--glow))),rgba(45,212,191,calc(.05*var(--glow))) 45%,transparent 68%);}
  @keyframes duxFloaty{0%,100%{transform:translateY(0) rotate(-1deg);}50%{transform:translateY(-8px) rotate(1deg);}}
  .dux-empty h1{font-size:26px;font-weight:600;letter-spacing:-.025em;margin:0 0 10px;color:var(--fg-1);}
  .dux-empty h1 em{font-style:normal;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;}
  .dux-empty p{font-size:14.5px;line-height:1.6;color:var(--fg-2);margin:0 0 24px;max-width:440px;}
  .dux-examples{display:flex;flex-direction:column;gap:9px;width:100%;max-width:420px;}
  .dux-ex-label{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--fg-3);margin-bottom:2px;font-weight:600;}
  .dux-ex{display:flex;align-items:center;gap:11px;text-align:left;padding:12px 14px;border-radius:11px;cursor:pointer;
    background:var(--surface-2);border:1px solid var(--hairline);color:var(--fg-1);font-size:13.5px;font-family:var(--ui);
    transition:all .25s var(--spring);box-shadow:var(--inset-hi);}
  .dux-ex:hover{border-color:var(--iris);transform:translateX(3px);}
  .dux-ex .dux-ic{width:15px;height:15px;color:var(--fg-3);flex:0 0 auto;}
  .dux-ex:hover .dux-ic{color:var(--iris);}
  .dux-ex-q{flex:1 1 auto;}
  .dux-ex-k{color:var(--fg-3);font-family:var(--mono);font-size:10px;opacity:0;transition:opacity .2s;}
  .dux-ex:hover .dux-ex-k{opacity:1;}

  /* ===== Composer ===== */
  .dux-composer-zone{position:relative;z-index:5;flex:0 0 auto;padding:0 24px 22px;}
  .dux-composer-zone::before{content:"";position:absolute;left:0;right:0;top:-42px;height:42px;
    background:linear-gradient(180deg,transparent,var(--canvas));pointer-events:none;}
  .dux-composer-inner{max-width:1160px;margin:0 auto;}

  /* live filter-context strip (current refinement cache, above the composer) */
  .dux-ctx-strip{display:flex;align-items:center;gap:10px;margin-bottom:10px;padding:7px 8px 7px 13px;
    border-radius:12px;background:var(--surface-1);border:1px solid var(--hairline);
    box-shadow:var(--inset-hi);animation:duxSettle .4s var(--spring) both;}
  .dux-ctx-lead{display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--fg-3);white-space:nowrap;}
  .dux-ctx-lead .dux-ic{width:13px;height:13px;color:var(--iris);}
  .dux-ctx-lead b{color:var(--fg-1);font-family:var(--mono);}
  .dux-ctx-chips{display:flex;gap:6px;flex-wrap:wrap;flex:1 1 auto;min-width:0;}
  .dux-ctx-chip{font-size:11px;padding:3px 8px;border-radius:7px;background:rgba(109,94,246,.10);
    border:1px solid rgba(109,94,246,.22);color:var(--fg-1);white-space:nowrap;}
  .dux-ctx-chip .num{font-family:var(--mono);color:var(--cyan);}
  .dux-ctx-strip .dux-btn-new{flex:0 0 auto;}
  @media (max-width:720px){ .dux-ctx-lead small,.dux-ctx-strip .dux-btn-new span{white-space:nowrap;} }

  .dux-composer{position:relative;display:flex;align-items:flex-end;gap:10px;padding:11px 11px 11px 16px;
    border-radius:var(--r-xl);background:var(--surface-1);border:1px solid var(--hairline-2);
    box-shadow:var(--shadow-pop),var(--inset-hi);transition:border-color .3s var(--ease);}
  .dux-composer::after{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1px;pointer-events:none;
    background:var(--grad);opacity:0;transition:opacity .35s var(--ease);
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
    -webkit-mask-composite:xor;mask-composite:exclude;}
  .dux-composer.focus{border-color:transparent;}
  .dux-composer.focus::after{opacity:calc(.9*var(--glow));}
  .dux-composer.shimmer::before{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;overflow:hidden;
    background:linear-gradient(115deg,transparent 30%,rgba(109,94,246,.06) 50%,transparent 70%);
    background-size:250% 100%;animation:duxCompShim 5s linear infinite;}
  @keyframes duxCompShim{to{background-position:-250% 0;}}
  .dux-lead-glyph{flex:0 0 auto;width:22px;height:22px;margin-bottom:6px;display:grid;place-items:center;}
  .dux-lead-glyph .dux-ic{width:18px;height:18px;color:var(--iris);}
  .dux-input{flex:1 1 auto;resize:none;border:none;outline:none;background:transparent;color:var(--fg-1);
    font-family:var(--ui);font-size:14.5px;line-height:1.5;padding:6px 0;max-height:140px;min-height:24px;box-shadow:none;}
  .dux-input::placeholder{color:var(--fg-3);}
  .dux-input:focus{outline:none;box-shadow:none;}
  .dux-send{width:40px;height:40px;border-radius:13px;flex:0 0 auto;cursor:pointer;display:grid;place-items:center;
    border:none;position:relative;background:linear-gradient(150deg,var(--iris),var(--iris-deep));
    box-shadow:0 6px 18px rgba(109,94,246,calc(.40*var(--glow))),inset 0 1px 0 rgba(255,255,255,.22);
    transition:all .2s var(--spring);}
  .dux-send .dux-ic{width:18px;height:18px;color:#fff;}
  .dux-send:hover{transform:translateY(-2px);box-shadow:0 10px 26px rgba(109,94,246,calc(.52*var(--glow))),inset 0 1px 0 rgba(255,255,255,.28);}
  .dux-send:active{transform:translateY(0) scale(.96);}
  .dux-send:disabled{opacity:.4;cursor:not-allowed;background:var(--surface-3);box-shadow:none;}
  .dux-send:disabled .dux-ic{color:var(--fg-3);}
  .dux-composer-hint{display:flex;align-items:center;justify-content:space-between;margin-top:9px;padding:0 4px;}
  .dux-kbd{font-size:10.5px;color:var(--fg-4);display:flex;align-items:center;gap:6px;}
  .dux-kbd kbd{font-family:var(--mono);font-size:10px;background:var(--surface-2);border:1px solid var(--hairline-2);
    border-radius:5px;padding:1px 5px;color:var(--fg-2);}
  .dux-powered{font-size:10.5px;color:var(--fg-4);display:flex;align-items:center;gap:6px;}
  .dux-gdot{width:5px;height:5px;border-radius:50%;background:var(--grad);}

  @media (prefers-reduced-motion:reduce){
    .dux-empty-mascot img,.dux-tm-img img,.dux-ambient,.dux-shim,.dux-composer.shimmer::before,.dux-think-bar::after{animation:none;}
  }
  @media (max-width:720px){
    .dux-bubble-user{max-width:88%;}
    .dux-inner{padding:22px 14px;}
    .dux-composer-zone{padding:0 14px 16px;}
    .dux-brand-text small{display:none;}
  }
  </style>`;

  const html = `
  <div class="dux-root">
    <div class="dux-ambient"></div>
    <header class="dux-hdr">
      <div class="dux-hdr-brand">
        <button class="dux-iconbtn" id="dux-home" title="Back to Desk">${IC.chevron}</button>
        <span class="dux-brand-mark"><img src="${MASCOT}" alt="DUX"/></span>
        <span class="dux-brand-divider"></span>
        <div class="dux-brand-text"><b>DUX</b><small>Assistant</small></div>
      </div>
      <div class="dux-hdr-right">
        <button class="dux-iconbtn" id="dux-theme" title="Toggle light / dark">${IC.moon}</button>
        <button class="dux-btn-new" id="dux-new">${IC.plus} New search</button>
      </div>
    </header>

    <div class="dux-stream" id="dux-stream"><div class="dux-inner" id="dux-inner"></div></div>

    <div class="dux-composer-zone"><div class="dux-composer-inner">
      <div id="dux-ctx"></div>
      <div class="dux-composer shimmer" id="dux-composer">
        <span class="dux-lead-glyph">${IC.sparkle}</span>
        <textarea class="dux-input" id="dux-input" rows="1"
          placeholder="Ask about purchase orders, suppliers, amounts…"></textarea>
        <button class="dux-send" id="dux-send" title="Send" aria-label="Send">${IC.send}</button>
      </div>
      <div class="dux-composer-hint">
        <span class="dux-kbd"><kbd>↵</kbd> to send <span style="opacity:.5">·</span> <kbd>⇧↵</kbd> new line</span>
        <span class="dux-powered"><span class="dux-gdot"></span> DUX reads only your authorised records</span>
      </div>
    </div></div>
  </div>`;

  // remove any stale surface from a previous load
  document.querySelectorAll('.dux-root').forEach(el => el.remove());

  $(page.body).html(style + html);

  // Frappe's content container is transform-clipped, which traps position:fixed
  // inside it (leaving the navbar gap + sidebar showing). Move the surface onto
  // <body> so it covers the full viewport.
  const duxRoot = $(page.body).find('.dux-root').get(0);
  document.body.appendChild(duxRoot);

  // it now lives on <body>; show it only while on the chat route
  if (frappe.router && frappe.router.on) {
    frappe.router.on('change', () => {
      const r = frappe.get_route();
      duxRoot.style.display = (r && r[0] === 'chat') ? 'flex' : 'none';
    });
  }

  // theme: default light; persisted (a display pref — safe to share across tabs)
  const savedTheme = (function () { try { return localStorage.getItem('dux_theme'); } catch (e) { return null; } })();
  function applyTheme(mode) {
    duxRoot.dataset.duxTheme = mode;
    const btn = document.getElementById('dux-theme');
    if (btn) { btn.innerHTML = (mode === 'dark') ? IC.sun : IC.moon; btn.title = (mode === 'dark') ? 'Switch to light' : 'Switch to dark'; }
    try { localStorage.setItem('dux_theme', mode); } catch (e) {}
  }
  applyTheme(savedTheme === 'dark' ? 'dark' : 'light');

  const stream   = document.getElementById('dux-stream');
  const inner    = document.getElementById('dux-inner');
  const input    = document.getElementById('dux-input');
  const send     = document.getElementById('dux-send');
  const composer = document.getElementById('dux-composer');
  const ctxMount = document.getElementById('dux-ctx');
  let emptyEl = null;

  // Live refinement-context state. Mirrors api.py's per-tab last_query cache:
  // LAST_QUERY_TTL_SEC = 4*60 (sliding) — the backend (re)writes it ONLY on a
  // count>0 read/refine, and reading does NOT extend it. Keep CTX_TTL_MS in sync
  // with that server constant. On expiry the strip clears, so the user always
  // sees exactly which filters are (and are no longer) carried into the next turn.
  const CTX_TTL_MS = 4 * 60 * 1000;
  const PH_DEFAULT = 'Ask about purchase orders, suppliers, amounts…';
  const PH_REFINE  = 'Refine within these filters, or start a new search…';
  let contextChips = [];
  let contextTimer = null;

  const esc = s => (s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const scroll = () => { requestAnimationFrame(() => { stream.scrollTop = stream.scrollHeight; }); };
  function autosize() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 140) + 'px'; }
  input.addEventListener('input', autosize);

  function nowTime() {
    try { return new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }); }
    catch (e) { const d = new Date(); return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2); }
  }
  function prettyField(f) { return String(f).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()); }
  function titleCase(s) { return String(s).replace(/\b\w/g, c => c.toUpperCase()); }
  function inr(n) { const x = Number(n); if (isNaN(x)) return String(n); try { return x.toLocaleString('en-IN'); } catch (e) { return String(n); } }
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fmtDate(v) {
    if (v === null || v === undefined || v === '') return '—';
    const m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return String(v);
    return parseInt(m[3], 10).toString().padStart(2, '0') + ' ' + MONTHS[parseInt(m[2], 10) - 1] + ' ' + m[1];
  }
  function fmtCell(v) { if (v === null || v === undefined || v === '') return '—'; if (typeof v === 'number') return inr(v); return String(v); }

  // =========================================================================
  // FILTER PILLS — map normalized_filters_json (the list-of-lists that ACTUALLY
  // queried ERPNext) into human {klabel, value, icon, tint} chips. Read-only.
  // GATE 1 contract: EVERY filter yields a chip (generic fallback if unmapped) —
  // transparency is the point, so a filter must never be silently hidden.
  // =========================================================================
  const OP_SYM = { '<': '<', '>': '>', '>=': '≥', '<=': '≤', '!=': '≠', '=': '=' };
  const COMPARATORS = ['<', '>', '>=', '<=', '!='];

  function fieldKind(field) {
    const f = String(field || '').toLowerCase();
    if (f === 'status' || f === 'workflow_state' || f === 'docstatus') return 'status';
    if (f === 'supplier' || f === 'supplier_name') return 'supplier';
    if (f === 'customer' || f === 'customer_name') return 'customer';
    if (f === 'company') return 'company';
    if (/grand_total|net_total|rounded_total|total_amount|base_.*total|^total$|amount|paid|outstanding|rate|price/.test(f)) return 'amount';
    if (/date|posting|transaction|schedule|due|delivery/.test(f)) return 'date';
    if (/item|product/.test(f)) return 'item';
    return 'generic';
  }
  const KIND_META = {
    status:   { klabel: 'Status',   ic: IC.clock,    tint: 't-pending' },
    supplier: { klabel: 'Supplier', ic: IC.truck,    tint: 't-iris' },
    customer: { klabel: 'Customer', ic: IC.truck,    tint: 't-iris' },
    company:  { klabel: 'Company',  ic: IC.building, tint: 't-mut' },
    amount:   { klabel: 'Amount',   ic: IC.rupee,    tint: 't-cyan' },
    date:     { klabel: 'Date',     ic: IC.calendar, tint: 't-mut' },
    item:     { klabel: 'Item',     ic: IC.box,      tint: 't-iris' },
    generic:  { klabel: '',         ic: IC.filter,   tint: 't-mut' },
  };
  function statusTint(v) {
    const s = String(v || '').toLowerCase();
    if (/draft/.test(s)) return 't-mut';
    if (/paid|approved|completed|closed|fulfilled|delivered|received and billed|active/.test(s)) return 't-ok';
    return 't-pending';
  }
  // Strip the loose-Link wildcards (%val%) + unescape _like_escape's \% \_ \\.
  function stripLike(v) {
    let s = String(v);
    if (s.charAt(0) === '%') s = s.slice(1);
    if (s.charAt(s.length - 1) === '%') s = s.slice(0, -1);
    return s.replace(/\\([%_\\])/g, '$1');
  }
  // Recover the colloquial status word ("pending") the LLM emitted, so a status
  // set renders "Status: Pending" not "Status: To Receive and Bill +2 more".
  function colloquialStatus(field, rawFilters, valuesLower) {
    try {
      const keys = Object.keys(rawFilters || {});
      for (let i = 0; i < keys.length; i++) {
        const k = keys[i];
        if (k.toLowerCase() === String(field).toLowerCase() || k.toLowerCase() === 'status') {
          const rv = rawFilters[k];
          if (typeof rv === 'string' && valuesLower.indexOf(rv.toLowerCase()) === -1) return rv;
        }
      }
    } catch (e) {}
    return null;
  }

  function filtersToChips(normalized, rawIntent) {
    const chips = [];
    const rawFilters = (rawIntent && rawIntent.filters) || {};
    (normalized || []).forEach(function (cond) {
      // ultra-defensive: a malformed condition still produces a (generic) chip
      if (!Array.isArray(cond) || cond.length < 2) {
        chips.push({ klabel: 'Filter', value: typeof cond === 'string' ? cond : JSON.stringify(cond), ic: IC.filter, tint: 't-mut', isNum: false });
        return;
      }
      const field = cond[0], op = cond[1], value = cond.length >= 3 ? cond[2] : '';
      const kind = fieldKind(field);
      const meta = KIND_META[kind] || KIND_META.generic;
      let klabel = meta.klabel || prettyField(field);
      let ic = meta.ic, tint = meta.tint, isNum = false, valueLabel;

      if (op === 'in') {
        const arr = Array.isArray(value) ? value : [value];
        if (kind === 'status') {
          const collo = colloquialStatus(field, rawFilters, arr.map(x => String(x).toLowerCase()));
          valueLabel = collo ? titleCase(collo)
            : (arr.length === 1 ? String(arr[0]) : String(arr[0]) + ' +' + (arr.length - 1) + ' more');
          tint = statusTint(collo || arr[0]);
        } else {
          valueLabel = arr.length === 1 ? String(arr[0]) : String(arr[0]) + ' +' + (arr.length - 1) + ' more';
        }
      } else if (op === 'like') {
        valueLabel = titleCase(stripLike(value));
        if (kind === 'generic') ic = IC.search;
      } else if (op === 'between' && Array.isArray(value)) {
        if (kind === 'amount') { valueLabel = '₹' + inr(value[0]) + ' – ₹' + inr(value[1]); isNum = true; }
        else { valueLabel = String(value[0]) + ' – ' + String(value[1]); }
      } else if (COMPARATORS.indexOf(op) !== -1) {
        if (kind === 'amount') { valueLabel = OP_SYM[op] + ' ₹' + inr(value); ic = IC.rupee; tint = 't-cyan'; }
        else { valueLabel = OP_SYM[op] + ' ' + String(value); }
        isNum = true;
      } else { // '=' and any other operator
        if (kind === 'status') { valueLabel = titleCase(value); tint = statusTint(value); }
        else if (kind === 'amount') { valueLabel = '₹' + inr(value); isNum = true; }
        else { valueLabel = String(value); }
      }
      chips.push({ klabel: klabel, value: valueLabel, ic: ic, tint: tint, isNum: isNum });
    });
    return chips;
  }

  function pillsBarHTML(chips) {
    if (!chips.length) return '';
    const pills = chips.map(function (c, i) {
      return '<span class="dux-pill" style="animation-delay:' + (i * 60) + 'ms">'
        + '<span class="dux-pi ' + c.tint + '">' + c.ic + '</span>'
        + (c.klabel ? '<span class="dux-pk">' + esc(c.klabel) + ':</span>' : '')
        + '<span class="dux-pv' + (c.isNum ? ' num' : '') + '">' + esc(c.value) + '</span>'
        + '</span>';
    }).join('');
    return '<div class="dux-pills-bar"><div class="dux-pills-label">' + IC.filter
      + ' Showing results for</div><div class="dux-pills">' + pills + '</div></div>';
  }

  // =========================================================================
  // RENDER — turns
  // =========================================================================
  const EXAMPLES = [
    { q: 'Show my pending purchase orders', ic: IC.clock },
    { q: 'Purchase orders from Bhandari under 50000', ic: IC.truck },
    { q: 'Show purchase orders above 50000', ic: IC.rupee },
  ];
  function renderEmpty() {
    const ex = EXAMPLES.map(function (e) {
      return '<button class="dux-ex" data-q="' + esc(e.q) + '">' + e.ic
        + '<span class="dux-ex-q">' + esc(e.q) + '</span><span class="dux-ex-k">↵</span></button>';
    }).join('');
    inner.insertAdjacentHTML('beforeend',
      '<div class="dux-empty" id="dux-empty"><div class="dux-empty-inner">'
      + '<div class="dux-empty-mascot"><img src="' + MASCOT + '" alt="DUX"/></div>'
      + '<h1>Ask DUX about your <em>operations</em></h1>'
      + '<p>Type a plain-English question and DUX pulls the exact records from your ERP — '
      + 'with the filters that produced them shown for full transparency.</p>'
      + '<div class="dux-examples"><div class="dux-ex-label">Try asking</div>' + ex + '</div>'
      + '</div></div>');
    emptyEl = document.getElementById('dux-empty');
  }
  function removeEmpty() { if (emptyEl) { emptyEl.remove(); emptyEl = null; } }

  function avatarHTML() {
    return '<div class="dux-avatar"><span class="dux-mark">'
      + '<img class="dux-m-light" src="' + MARK_LIGHT + '" alt="DUX"/>'
      + '<img class="dux-m-dark" src="' + MARK_DARK + '" alt=""/></span></div>';
  }

  function addUser(text) {
    removeEmpty();
    inner.insertAdjacentHTML('beforeend',
      '<div class="dux-turn dux-msg-user"><div class="dux-bubble-user">' + esc(text) + '</div>'
      + '<div class="dux-ts">' + nowTime() + '</div></div>');
    scroll();
  }

  // assistant turn: avatar + (text line) + optional card + timestamp
  function addAssistantTurn(textHTML, extraHTML) {
    removeEmpty();
    inner.insertAdjacentHTML('beforeend',
      '<div class="dux-turn dux-msg-ai">' + avatarHTML() + '<div class="dux-ai-body">'
      + '<div class="dux-ai-text">' + textHTML + '</div>'
      + (extraHTML || '')
      + '<div class="dux-ts">DUX · ' + nowTime() + '</div></div></div>');
    scroll();
  }

  function addThinking() {
    removeEmpty();
    const id = 'dux-think-' + Date.now();
    inner.insertAdjacentHTML('beforeend',
      '<div class="dux-turn dux-thinking" id="' + id + '"><div class="dux-think-card">'
      + '<div class="dux-think-bar"></div><div class="dux-think-mascot">'
      + '<div class="dux-tm-img"><img src="' + MASCOT + '" alt=""/></div>'
      + '<div><div class="dux-think-head"><span class="dux-shim">Reading your operations data…</span></div>'
      + '<div class="dux-think-sub">Parsing intent · matching filters · querying records</div></div>'
      + '</div></div></div>');
    scroll();
    return id;
  }

  function addBot(response) {
    // Defensive: old raw-intent debug shape (ping_llm) — render as text.
    if (response && !response.type && response.intent) {
      return addAssistantTurn('Here&rsquo;s what I understood: <span class="dux-mono">'
        + esc(JSON.stringify(response)) + '</span>', '');
    }
    const type = response && response.type;
    if (type === 'records') return addBotRecords(response);
    if (type === 'unsupported') return addAssistantTurn(esc(response.message || 'Not supported yet.'), '');
    if (type === 'error') return addAssistantTurn('<span class="dux-err-text">' + esc(response.message || 'Something went wrong.') + '</span>', '');
    return addAssistantTurn('<span class="dux-err-text">Unexpected response from DUX.</span>', '');
  }

  function amountField(fields) {
    for (let i = 0; i < (fields || []).length; i++) if (fieldKind(fields[i]) === 'amount') return fields[i];
    return null;
  }
  function computeSum(fields, records) {
    const af = amountField(fields);
    if (!af) return null;
    let s = 0, any = false;
    (records || []).forEach(function (r) {
      const v = r[af];
      if (typeof v === 'number') { s += v; any = true; }
      else if (v !== null && v !== undefined && v !== '' && !isNaN(parseFloat(v))) { s += parseFloat(v); any = true; }
    });
    return any ? { field: af, sum: s } : null;
  }

  function cellHTML(field, val, linkBase, row) {
    if (field === 'name') {
      const name = row.name;
      if (linkBase && name) {
        return '<td><a href="' + esc(linkBase) + '/' + encodeURIComponent(name) + '" class="dux-cell-id"'
          + ' target="_blank" rel="noopener">' + esc(String(name)) + '</a></td>';
      }
      return '<td class="dux-cell-id">' + esc(fmtCell(val)) + '</td>';
    }
    const k = fieldKind(field);
    if (field === 'status' || field === 'workflow_state') {
      return '<td>' + (val === null || val === undefined || val === '' ? '—' : statusTag(val)) + '</td>';
    }
    if (k === 'amount') {
      if (val === null || val === undefined || val === '') return '<td class="num dux-cell-num">—</td>';
      return '<td class="num dux-cell-num"><span class="rs">₹</span>' + esc(inr(val)) + '</td>';
    }
    if (k === 'date') return '<td class="dux-cell-date">' + esc(fmtDate(val)) + '</td>';
    if (k === 'supplier' || k === 'customer') return '<td class="dux-cell-sup">' + esc(fmtCell(val)) + '</td>';
    if (k === 'company') return '<td class="dux-cell-co">' + esc(fmtCell(val)) + '</td>';
    return '<td>' + esc(fmtCell(val)) + '</td>';
  }
  function statusTag(v) {
    return '<span class="dux-tag ' + statusTagClass(v) + '"><span class="d"></span>' + esc(String(v)) + '</span>';
  }
  function statusTagClass(v) {
    const s = String(v || '').toLowerCase();
    if (/draft/.test(s)) return 'draft';
    if (/paid|approved|completed|closed|fulfilled|delivered|received and billed|active/.test(s)) return 'approved';
    if (/cancel|return|hold|rejected/.test(s)) return 'draft';
    return 'pending';
  }
  function tableHTML(fields, records, linkBase) {
    const head = fields.map(function (f) {
      return '<th' + (fieldKind(f) === 'amount' ? ' class="num"' : '') + '>' + esc(prettyField(f)) + '</th>';
    }).join('');
    const rows = records.map(function (r) {
      const cells = fields.map(function (f) { return cellHTML(f, r[f], linkBase, r); }).join('');
      return '<tr>' + cells + '</tr>';
    }).join('');
    return '<div class="dux-tbl-scroll"><table class="dux-tbl"><thead><tr>' + head
      + '</tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  function addBotRecords(payload) {
    const dt = payload.doctype || '—';
    const fields = payload.fields || ['name'];
    const records = payload.records || [];
    const count = payload.count || 0;
    const linkBase = payload.link_base || '';
    const normalized = payload.normalized_filters || [];
    const chips = filtersToChips(normalized, payload.intent || null);
    const sumInfo = computeSum(fields, records);

    // assistant text line
    let text;
    if (count === 0) {
      text = 'No <b>' + esc(dt) + '</b> records matched those filters. You can relax a filter or start a new search.';
    } else {
      text = 'Found <span class="dux-accent-n">' + count + '</span> ' + esc(dt) + ' '
        + (count === 1 ? 'record' : 'records')
        + (sumInfo ? ', worth <span class="dux-accent-n">₹' + inr(sumInfo.sum) + '</span> in total' : '')
        + (chips.length ? '. The filters that produced this are shown below.' : '.');
    }

    const card = '<div class="dux-result-card">'
      + pillsBarHTML(chips)
      + '<div class="dux-result-meta"><span class="dux-count"><b>' + count + '</b> '
        + (count === 1 ? 'record' : 'records') + ' found</span>'
        + (sumInfo ? '<span class="dux-sum">Total&nbsp;&nbsp;<b>₹' + inr(sumInfo.sum) + '</b></span>' : '')
      + '</div>'
      + (count > 0
          ? tableHTML(fields, records, linkBase)
          : '<div class="dux-empty-rows">No matching records. Try widening the filters or start a new search.</div>')
      + '</div>';

    addAssistantTurn(text, card);
  }

  // =========================================================================
  // LIVE FILTER CONTEXT — a persistent strip above the composer showing the
  // refinement filters CURRENTLY cached on the backend (per-tab, 4-min sliding
  // TTL). Mirrors the server: only a count>0 records turn (re)writes the cache,
  // so only that updates the strip + resets the timer; on expiry the strip
  // clears, so the user always knows what is (and isn't) still in the filter.
  // =========================================================================
  function renderContextStrip() {
    if (!ctxMount) return;
    if (!contextChips.length) { ctxMount.innerHTML = ''; return; }
    const chips = contextChips.map(function (c) {
      return '<span class="dux-ctx-chip">' + esc(c.klabel || 'Filter') + ': '
        + '<span' + (c.isNum ? ' class="num"' : '') + '>' + esc(c.value) + '</span></span>';
    }).join('');
    ctxMount.innerHTML =
      '<div class="dux-ctx-strip">'
      + '<span class="dux-ctx-lead">' + IC.layers + ' Filter context <b>' + contextChips.length + '</b></span>'
      + '<div class="dux-ctx-chips">' + chips + '</div>'
      + '<button class="dux-btn-new" id="dux-ctx-new" title="Clear filter context">' + IC.refresh + ' New search</button>'
      + '</div>';
    const b = document.getElementById('dux-ctx-new');
    b && b.addEventListener('click', newSearch);
  }
  // sessionStorage mirror (per-tab, like duxTabId) so the strip survives a page
  // reload while the backend cache is still live, honouring the remaining TTL.
  function persistContext(expiresAt) {
    try {
      if (contextChips.length) {
        const slim = contextChips.map(function (c) { return { klabel: c.klabel, value: c.value, isNum: c.isNum }; });
        sessionStorage.setItem('dux_ctx', JSON.stringify({ chips: slim, expiresAt: expiresAt }));
      } else { sessionStorage.removeItem('dux_ctx'); }
    } catch (e) {}
  }
  function expireContext() {
    contextChips = []; contextTimer = null;
    renderContextStrip(); input.placeholder = PH_DEFAULT;
    try { sessionStorage.removeItem('dux_ctx'); } catch (e) {}
  }
  // Refresh the live context from a non-empty records turn (mirrors the server
  // write). Resets the 4-min sliding timer; on expiry the strip + placeholder clear.
  function setContext(normalized, rawIntent) {
    contextChips = filtersToChips(normalized || [], rawIntent || null);
    renderContextStrip();
    input.placeholder = contextChips.length ? PH_REFINE : PH_DEFAULT;
    if (contextTimer) { clearTimeout(contextTimer); contextTimer = null; }
    if (contextChips.length) {
      contextTimer = setTimeout(expireContext, CTX_TTL_MS);
      persistContext(Date.now() + CTX_TTL_MS);
    } else {
      try { sessionStorage.removeItem('dux_ctx'); } catch (e) {}
    }
  }
  function clearContext() {
    contextChips = [];
    if (contextTimer) { clearTimeout(contextTimer); contextTimer = null; }
    renderContextStrip();
    input.placeholder = PH_DEFAULT;
    try { sessionStorage.removeItem('dux_ctx'); } catch (e) {}
  }
  // Restore a still-valid context after a reload (backend cache + per-tab id both
  // survive reload, so the strip should too — for the remaining TTL only).
  function restoreContext() {
    let raw = null;
    try { raw = sessionStorage.getItem('dux_ctx'); } catch (e) { return; }
    if (!raw) return;
    let data = null;
    try { data = JSON.parse(raw); } catch (e) { data = null; }
    if (!data || !Array.isArray(data.chips) || !data.chips.length || !data.expiresAt) { return clearContext(); }
    const remaining = data.expiresAt - Date.now();
    if (remaining <= 0) { return clearContext(); }
    contextChips = data.chips;
    renderContextStrip();
    input.placeholder = PH_REFINE;
    if (contextTimer) clearTimeout(contextTimer);
    contextTimer = setTimeout(expireContext, remaining);
  }

  // =========================================================================
  // SUBMIT / actions
  // =========================================================================
  function submit() {
    const text = input.value.trim();
    if (!text) return;
    addUser(text);
    input.value = ''; autosize(); send.disabled = true;
    const tid = addThinking();
    frappe.call({
      method: 'dux_chatbot.api.handle_message',
      args: { message: text, tab_id: duxTabId() },
      callback: function (r) {
        const el = document.getElementById(tid); if (el) el.remove();
        const resp = r && r.message;
        if (resp) {
          addBot(resp);
          // Mirror the backend cache write: ONLY a non-empty records turn
          // (re)writes last_query, so only that refreshes the live context +
          // resets its 4-min timer. Empty / unsupported / error leave it as-is.
          if (resp.type === 'records' && (resp.count || 0) > 0) {
            setContext(resp.normalized_filters, resp.intent);
          }
        } else {
          addAssistantTurn('<span class="dux-err-text">No response from DUX.</span>', '');
        }
        send.disabled = false; input.focus();
      },
      error: function () {
        const el = document.getElementById(tid); if (el) el.remove();
        addAssistantTurn('<span class="dux-err-text">Could not reach DUX. Check the LLM box connection.</span>', '');
        send.disabled = false;
      }
    });
  }

  // "New search": fresh per-tab refinement context + clear the visible conversation
  function newSearch() {
    duxNewTabId();
    clearContext();
    inner.innerHTML = '';
    renderEmpty();
    input.value = ''; autosize(); send.disabled = false;
    input.focus();
  }

  // =========================================================================
  // BINDINGS
  // =========================================================================
  send.addEventListener('click', submit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  });
  input.addEventListener('focus', () => composer.classList.add('focus'));
  input.addEventListener('blur', () => composer.classList.remove('focus'));

  // example chips (delegated; they live inside the empty state)
  inner.addEventListener('click', e => {
    const ex = e.target.closest && e.target.closest('.dux-ex');
    if (ex) { input.value = ex.getAttribute('data-q') || ''; autosize(); submit(); }
  });

  const homeBtn = document.getElementById('dux-home');
  homeBtn && homeBtn.addEventListener('click', () => { window.location.href = '/app'; });
  const themeBtn = document.getElementById('dux-theme');
  themeBtn && themeBtn.addEventListener('click', () => {
    applyTheme(duxRoot.dataset.duxTheme === 'dark' ? 'light' : 'dark');
  });
  const newBtn = document.getElementById('dux-new');
  newBtn && newBtn.addEventListener('click', newSearch);

  renderEmpty();
  restoreContext();
  setTimeout(() => input.focus(), 200);
};
