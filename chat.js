frappe.pages['chat'].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper, title: 'Dux', single_column: true,
  });

  // Hide Frappe's default page head for an immersive surface
  $(wrapper).find('.page-head').hide();
  $(wrapper).find('.page-body').css({ 'margin-top': 0, 'padding': 0 });

  const MASCOT = '/assets/dux_chatbot/images/dux-mascot.png';

  const style = `
  <style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  .dux-root{--bg:#161514;--bg2:#1c1a18;--surface:#232120;--surface2:#2a2725;
    --line:rgba(255,255,255,.07);--accent:#FF6B1A;--accent-deep:#F26722;
    --cream:#F5F0E6;--dim:#9a938b;--dimmer:#6f6862;
    position:fixed;inset:0;z-index:99999;
    font-family:'Inter',sans-serif;background:
      radial-gradient(120% 80% at 50% 0%,#211e1b 0%,var(--bg) 55%);
    color:var(--cream);display:flex;flex-direction:column;overflow:hidden;}
  .dux-root *{box-sizing:border-box;}
  /* drifting ambient glow */
  .dux-aura{position:absolute;inset:0;pointer-events:none;opacity:.5;
    background:radial-gradient(40% 30% at 70% 20%,rgba(255,107,26,.10),transparent 70%),
               radial-gradient(35% 30% at 20% 80%,rgba(255,107,26,.06),transparent 70%);
    animation:auraDrift 18s ease-in-out infinite alternate;}
  @keyframes auraDrift{from{transform:translateY(0)}to{transform:translateY(-16px)}}

  /* back-to-Desk button (navbar is covered in full-screen mode) */
  .dux-home{position:absolute;top:16px;left:18px;z-index:3;width:38px;height:38px;
    border-radius:11px;border:1px solid var(--line);background:var(--surface);color:var(--cream);
    cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .18s ease;}
  .dux-home:hover{border-color:var(--accent);color:var(--accent);background:var(--surface2);}

  .dux-stream{flex:1;overflow-y:auto;padding:32px 0 12px;position:relative;z-index:1;}
  .dux-inner{max-width:760px;margin:0 auto;padding:0 24px;}
  .dux-stream::-webkit-scrollbar{width:8px;}
  .dux-stream::-webkit-scrollbar-thumb{background:#322e2b;border-radius:8px;}

  /* empty / hero state */
  .dux-hero{display:flex;flex-direction:column;align-items:center;justify-content:center;
    text-align:center;min-height:62vh;gap:6px;}
  .dux-hero-img{width:190px;height:150px;object-fit:contain;
    -webkit-mask-image:radial-gradient(circle at 50% 45%,#000 58%,transparent 74%);
            mask-image:radial-gradient(circle at 50% 45%,#000 58%,transparent 74%);
    filter:drop-shadow(0 18px 40px rgba(255,107,26,.18));
    animation:bob 4.5s ease-in-out infinite;}
  @keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-12px)}}
  .dux-hello{font-size:30px;font-weight:700;letter-spacing:-.02em;margin-top:10px;}
  .dux-hello span{color:var(--accent);}
  .dux-sub{color:var(--dim);font-size:14.5px;max-width:380px;line-height:1.5;}
  .dux-chips{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-top:22px;}
  .dux-chip{background:var(--surface);border:1px solid var(--line);color:var(--cream);
    padding:10px 16px;border-radius:999px;font-size:13px;cursor:pointer;
    transition:all .18s ease;font-family:inherit;}
  .dux-chip:hover{border-color:var(--accent);background:var(--surface2);transform:translateY(-2px);}

  /* messages */
  .dux-msg{display:flex;gap:12px;margin:18px 0;animation:rise .4s cubic-bezier(.2,.7,.3,1);}
  @keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
  .dux-msg.user{flex-direction:row-reverse;}
  .dux-ava{width:40px;height:40px;border-radius:50%;flex:0 0 40px;overflow:hidden;
    background:radial-gradient(circle at 50% 42%,#2a2725,#141312);border:1px solid var(--line);}
  .dux-ava img{width:100%;height:100%;object-fit:cover;object-position:37% 45%;transform:scale(1.32);
    -webkit-mask-image:radial-gradient(circle at 50% 47%,#000 62%,transparent 78%);
            mask-image:radial-gradient(circle at 50% 47%,#000 62%,transparent 78%);}
  .dux-bubble{max-width:78%;padding:13px 16px;border-radius:16px;font-size:14.5px;
    line-height:1.55;}
  .dux-msg.bot .dux-bubble{background:var(--surface);border:1px solid var(--line);
    border-top-left-radius:5px;color:var(--cream);}
  .dux-msg.user .dux-bubble{background:linear-gradient(135deg,var(--accent),var(--accent-deep));
    color:#fff;border-top-right-radius:5px;font-weight:500;}

  /* intent result card (shown for now, since ping_llm returns JSON) */
  .dux-card{margin-top:10px;background:var(--bg2);border:1px solid var(--line);
    border-radius:12px;overflow:hidden;font-size:12.5px;}
  .dux-card-h{display:flex;gap:8px;align-items:center;padding:9px 13px;
    border-bottom:1px solid var(--line);background:rgba(255,107,26,.05);}
  .dux-badge{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
    padding:3px 8px;border-radius:5px;background:var(--accent);color:#1a1817;}
  .dux-card-h b{font-size:13px;color:var(--cream);}
  .dux-card pre{margin:0;padding:12px 13px;color:var(--dim);white-space:pre-wrap;
    font-family:'SF Mono',ui-monospace,monospace;font-size:11.5px;line-height:1.6;}

  /* thinking */
  .dux-think{display:flex;gap:12px;margin:18px 0;align-items:center;}
  .dux-think .dux-ava img{animation:none;}
  .dux-dots{display:flex;gap:5px;padding:14px 16px;background:var(--surface);
    border:1px solid var(--line);border-radius:16px;border-top-left-radius:5px;}
  .dux-dots span{width:7px;height:7px;border-radius:50%;background:var(--accent);
    opacity:.5;animation:blink 1.3s infinite;}
  .dux-dots span:nth-child(2){animation-delay:.18s;}
  .dux-dots span:nth-child(3){animation-delay:.36s;}
  @keyframes blink{0%,60%,100%{opacity:.35;transform:translateY(0)}30%{opacity:1;transform:translateY(-3px)}}

  /* composer */
  .dux-composer{padding:14px 24px 22px;position:relative;z-index:1;}
  .dux-composer-in{max-width:760px;margin:0 auto;display:flex;gap:10px;align-items:flex-end;
    background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:8px 8px 8px 18px;
    transition:border-color .2s ease;}
  .dux-composer-in:focus-within{border-color:var(--accent);}
  .dux-input{flex:1;background:transparent;border:none;outline:none;resize:none;color:var(--cream);
    font-family:inherit;font-size:14.5px;line-height:1.5;max-height:140px;padding:7px 0;}
  .dux-input::placeholder{color:var(--dimmer);}
  .dux-send{width:40px;height:40px;border-radius:13px;border:none;cursor:pointer;flex:0 0 40px;
    background:linear-gradient(135deg,var(--accent),var(--accent-deep));color:#fff;
    display:flex;align-items:center;justify-content:center;transition:transform .12s ease,opacity .2s;}
  .dux-send:hover{transform:scale(1.06);}
  .dux-send:active{transform:scale(.92);}
  .dux-send:disabled{opacity:.4;cursor:not-allowed;transform:none;}
  .dux-foot{text-align:center;color:var(--dimmer);font-size:11px;margin-top:10px;}
  @media (prefers-reduced-motion:reduce){.dux-hero-img,.dux-aura{animation:none;}}
  </style>`;

  const html = `
  <div class="dux-root">
    <div class="dux-aura"></div>
    <button class="dux-home" id="dux-home" title="Back to Desk">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
        <path d="M3 11L12 3l9 8M5 9.5V20h14V9.5" stroke="currentColor"
          stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <div class="dux-stream" id="dux-stream"><div class="dux-inner" id="dux-inner">
      <div class="dux-hero" id="dux-hero">
        <img class="dux-hero-img" src="${MASCOT}" alt="Dux"/>
        <div class="dux-hello">Hi, I'm <span>Dux</span></div>
        <div class="dux-sub">Your ERP companion. Ask me about your purchase orders,
          stock, or to draft a material request — in plain English or Hinglish.</div>
        <div class="dux-chips">
          <button class="dux-chip">Show my pending purchase orders</button>
          <button class="dux-chip">Stock of item X</button>
          <button class="dux-chip">Create a material request</button>
        </div>
      </div>
    </div></div>
    <div class="dux-composer"><div>
      <div class="dux-composer-in">
        <textarea class="dux-input" id="dux-input" rows="1"
          placeholder="Message Dux…"></textarea>
        <button class="dux-send" id="dux-send" title="Send">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M4 12L20 4L13 20L11 13L4 12Z" fill="currentColor"
              stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
        </button>
      </div>
      <div class="dux-foot">Dux can make mistakes — review drafts before submitting.</div>
    </div></div>
  </div>`;

  // remove any stale surface from a previous load
  document.querySelectorAll('.dux-root').forEach(el => el.remove());

  $(page.body).html(style + html);

  // Frappe's content container is transform-clipped, which traps position:fixed
  // inside it (leaving the navbar gap + sidebar showing). Move the surface onto
  // <body> so it covers the full viewport below the navbar.
  const duxRoot = $(page.body).find('.dux-root').get(0);
  document.body.appendChild(duxRoot);

  // it now lives on <body>; show it only while on the chat route
  if (frappe.router && frappe.router.on) {
    frappe.router.on('change', () => {
      const r = frappe.get_route();
      duxRoot.style.display = (r && r[0] === 'chat') ? 'flex' : 'none';
    });
  }

  const stream = document.getElementById('dux-stream');
  const inner  = document.getElementById('dux-inner');
  const input  = document.getElementById('dux-input');
  const send   = document.getElementById('dux-send');
  const hero   = document.getElementById('dux-hero');

  const esc = s => (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  const scroll = () => { stream.scrollTop = stream.scrollHeight; };

  function autosize(){ input.style.height='auto'; input.style.height=Math.min(input.scrollHeight,140)+'px'; }
  input.addEventListener('input', autosize);

  function addUser(text){
    if(hero) hero.remove();
    inner.insertAdjacentHTML('beforeend',
      `<div class="dux-msg user"><div class="dux-bubble">${esc(text)}</div></div>`);
    scroll();
  }
  function addThinking(){
    const id='think-'+Date.now();
    inner.insertAdjacentHTML('beforeend',
      `<div class="dux-think" id="${id}">
        <div class="dux-ava"><img src="${MASCOT}"/></div>
        <div class="dux-dots"><span></span><span></span><span></span></div></div>`);
    scroll(); return id;
  }
  function addBot(intent){
    // ping_llm returns parsed intent JSON for now — render it as a styled card.
    const dt = intent && intent.doctype ? intent.doctype : '—';
    const it = intent && intent.intent ? intent.intent : 'unknown';
    const pretty = JSON.stringify(intent, null, 2);
    inner.insertAdjacentHTML('beforeend',
      `<div class="dux-msg bot">
        <div class="dux-ava"><img src="${MASCOT}"/></div>
        <div>
          <div class="dux-bubble">Here's what I understood — wiring this to live ERP data is the next step.</div>
          <div class="dux-card">
            <div class="dux-card-h"><span class="dux-badge">${esc(it)}</span><b>${esc(dt)}</b></div>
            <pre>${esc(pretty)}</pre>
          </div>
        </div></div>`);
    scroll();
  }
  function addError(msg){
    inner.insertAdjacentHTML('beforeend',
      `<div class="dux-msg bot"><div class="dux-ava"><img src="${MASCOT}"/></div>
        <div class="dux-bubble">⚠️ ${esc(msg)}</div></div>`);
    scroll();
  }

  function submit(){
    const text = input.value.trim();
    if(!text) return;
    addUser(text);
    input.value=''; autosize(); send.disabled=true;
    const tid = addThinking();
    frappe.call({
      method:'dux_chatbot.api.ping_llm',
      args:{ message:text },
      callback:function(r){
        const el=document.getElementById(tid); if(el) el.remove();
        if(r && r.message){ addBot(r.message); } else { addError('No response from Dux.'); }
        send.disabled=false; input.focus();
      },
      error:function(){
        const el=document.getElementById(tid); if(el) el.remove();
        addError('Could not reach Dux. Check the LLM box connection.');
        send.disabled=false;
      }
    });
  }

  send.addEventListener('click', submit);
  input.addEventListener('keydown', e=>{
    if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); submit(); }
  });
  inner.addEventListener('click', e=>{
    if(e.target.classList.contains('dux-chip')){ input.value=e.target.textContent; submit(); }
  });
  const home = document.getElementById('dux-home');
  home && home.addEventListener('click', () => { window.location.href = '/app'; });
  setTimeout(()=>input.focus(), 200);
};
