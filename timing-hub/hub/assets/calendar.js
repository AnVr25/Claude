/* SakhStart — календарь соревнований для сайта fla65.ru (Tilda, блок T123).
   Подключение:
     <div id="sakhstart-calendar" data-year="2026"></div>
     <script src="https://reg.fla65.ru/r/assets/calendar.js" defer></script>
   Данные: <origin скрипта>/r/api/calendar?year=YYYY (docs/public-api.md).
   Без библиотек, ES2017. Всё рисуется в Shadow DOM — стили Tilda не мешают и не страдают.
   Любой текст из данных экранируется, ссылки — только http(s). */
(function () {
  'use strict';
  const me = document.currentScript ||
    [].slice.call(document.getElementsByTagName('script')).filter(s => /\/calendar\.js(\?|#|$)/.test(s.src)).pop();
  let ORIGIN = 'https://reg.fla65.ru';
  try { if (me && me.src) ORIGIN = new URL(me.src, location.href).origin; } catch (e) { /* остаётся reg.fla65.ru */ }

  const MON = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
  const GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  const LV = {
    russia: ['Россия', 'всероссийские'], dfo: ['ДФО', 'окружные'], interregion: ['Межрегион', 'межрегиональные'],
    region: ['Область', 'областные'], mass: ['Забег', 'массовые']
  };
  const FL = [['next', 'Впереди'], ['past', 'Прошедшие'], ['all', 'Весь год']];
  const ARR = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="square"/></svg>';
  const DOC = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2.8h8l4.2 4.2v14.2H6zM14 2.8V7h4.2M9 12h6M9 16h6" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
  const DOT = '<i class="dot" aria-hidden="true"></i>';

  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const safe = u => {
    if (!u || typeof u !== 'string') return '';
    try { const x = new URL(u, ORIGIN); return /^https?:$/.test(x.protocol) ? x.href : ''; } catch (e) { return ''; }
  };
  const NEWTAB = ' target="_blank" rel="noopener"';
  const SRNEW = '<span class="sr"> (откроется в новой вкладке)</span>';
  const link = (u, inner, cls, same) => {
    u = safe(u);
    return u ? `<a class="${cls}" href="${esc(u)}"${same ? '' : NEWTAB}>${inner}${same ? '' : SRNEW}</a>` : '';
  };
  const day = s => { const p = String(s || '').split('-').map(Number); return p.length === 3 && p[0] ? new Date(p[0], p[1] - 1, p[2]) : null; };
  const plural = (n, a, b, c) => { const m = n % 10, h = n % 100; return m === 1 && h !== 11 ? a : m >= 2 && m <= 4 && (h < 12 || h > 14) ? b : c; };
  const size = b => !b ? '' : b < 1048576 ? Math.max(1, Math.round(b / 1024)) + ' КБ' : (b / 1048576).toFixed(1).replace('.', ',') + ' МБ';

  // Даты: {big:'5–6', small:'января', text:'5–6 января'} / {big:'28', small:'февраля — 3 марта', text:'28 февраля — 3 марта'}
  function when(e) {
    const a = e._d, b = e._e;
    if (!a) return { big: '—', small: '', text: '' };
    const d1 = a.getDate(), m1 = GEN[a.getMonth()];
    if (!b || +b === +a) return { big: '' + d1, small: m1, text: d1 + ' ' + m1 };
    if (b.getMonth() === a.getMonth() && b.getFullYear() === a.getFullYear())
      return { big: d1 + '–' + b.getDate(), small: m1, text: d1 + '–' + b.getDate() + ' ' + m1 };
    const tail = b.getDate() + ' ' + GEN[b.getMonth()];
    return { big: '' + d1, small: m1 + ' — ' + tail, text: d1 + ' ' + m1 + ' — ' + tail };
  }
  function deadline(s) {
    const m = /^(\d{4})-(\d\d)-(\d\d)(?:[T ](\d\d):(\d\d))?/.exec(s || '');
    return m ? 'до ' + (+m[3]) + ' ' + GEN[+m[2] - 1] + (m[4] ? ', ' + m[4] + ':' + m[5] : '') : '';
  }

  const CSS = `
:host{all:initial;display:block;--red:#E71E25;--red-d:#C4141B;--navy:#0B1D37;--navy2:#2C4166;--ink:#1B2B45;--mut:#55627A;--line:#DCE0E8;--bg2:#F2F4F7;--or:#F3481D;--ok:#17905A;
 font:17px/1.55 "PT Sans",system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:var(--ink);-webkit-text-size-adjust:100%;text-align:left}
*{box-sizing:border-box}
a{color:inherit;text-decoration:none}
button{font:inherit;color:inherit;cursor:pointer}
a:focus-visible,button:focus-visible{outline:3px solid #E71E2566;outline-offset:2px}
.H,.tag,.fl button,.btn,.a a,.next a,.next button,.mh h3,.t,.d{font-family:Oswald,"Arial Narrow",Arial,sans-serif}
.sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
.ic{width:18px;height:18px;flex:0 0 auto}
.next{display:flex;align-items:center;justify-content:space-between;gap:16px 32px;flex-wrap:wrap;background:var(--navy);color:#C9D1E0;padding:24px 30px;border-left:6px solid var(--red);margin:0 0 28px}
.next p{margin:0;font-size:17px;line-height:1.45;max-width:780px}
.next .k{display:flex;align-items:center;gap:8px;margin:0 0 4px;font:400 14px/1.3 Oswald,Arial,sans-serif;letter-spacing:2px;text-transform:uppercase;color:#FFB3B5}
.next b{color:#fff}
.next a,.next button{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;font-size:16px;letter-spacing:1px;text-transform:uppercase;color:#fff;background:none;border:0;border-bottom:2px solid var(--red);padding:0 0 2px}
.next a:hover,.next button:hover{color:#FFB3B5}
.next a:focus-visible,.next button:focus-visible{outline-color:#fff}
.tools{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:18px 28px;margin:0 0 40px}
.lg{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0;padding:0}
.lg>span{font:14px Oswald,Arial,sans-serif;letter-spacing:1.5px;text-transform:uppercase;color:var(--mut);margin-right:4px}
.clr{margin-left:8px}
.chip{display:inline-flex;align-items:center;background:none;border:0;padding:4px;font-size:15px;color:var(--mut);transition:background .15s,opacity .15s}
.chip:hover{background:var(--bg2)}
.chip[aria-pressed=true]{background:var(--bg2);box-shadow:inset 0 0 0 2px var(--navy);color:var(--navy)}
.lg.on .chip[aria-pressed=false]{opacity:.55}
.lg.on .chip[aria-pressed=false]:hover{opacity:1}
.clr{background:none;border:0;border-bottom:1px solid rgba(231,30,37,.45);padding:0;font-size:15px;color:var(--red)}
.tag{display:inline-block;font-size:12px;line-height:1.2;letter-spacing:1.5px;text-transform:uppercase;padding:4px 8px;background:var(--red);color:#fff;border:1px solid var(--red);white-space:nowrap}
.tag.dfo{background:var(--navy);border-color:var(--navy)}
.tag.interregion{background:var(--navy2);border-color:var(--navy2)}
.tag.region{background:var(--bg2);color:var(--navy);border-color:var(--line)}
.tag.mass{background:#fff;color:var(--red)}
.tag.ad{background:#fff;color:var(--navy);border-color:var(--navy)}
.fl{display:inline-flex;border:2px solid var(--navy)}
.fl button{appearance:none;background:#fff;border:0;border-left:2px solid var(--navy);padding:10px 16px;font-size:15px;line-height:1.3;letter-spacing:1px;text-transform:uppercase;color:var(--navy);white-space:nowrap}
.fl button:first-child{border-left:0}
.fl button:hover{background:var(--bg2)}
.fl button[aria-pressed=true]{background:var(--navy);color:#fff}
.fl small{font:13px "PT Sans",Arial,sans-serif;letter-spacing:0;opacity:.75;margin-left:5px}
.m{margin:0 0 40px}
.m:last-child{margin:0}
.mh{margin:0 0 14px;padding:0 0 10px;border-bottom:3px solid var(--navy)}
.mh h3{font-weight:700;font-size:28px;line-height:1.1;text-transform:uppercase;color:var(--navy);margin:0}
.list{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.ev{display:grid;grid-template-columns:140px minmax(0,1fr) auto;gap:0 28px;align-items:center;background:#fff;border:1px solid var(--line);border-left:6px solid var(--red);padding:20px 26px 20px 22px}
.ev.l-dfo{border-left-color:var(--navy)}
.ev.l-interregion{border-left-color:var(--navy2)}
.ev.l-region{border-left-color:#9AA6BD}
.ev.l-mass{border-left-color:#F08A8E}
.ev.is-run{border-color:var(--red);border-left-color:var(--red);box-shadow:0 0 0 1px var(--red);background:#FFF9F9}
.d b{display:block;font-weight:700;font-size:34px;line-height:1;color:var(--navy);white-space:nowrap}
.d span{display:block;margin-top:6px;font-size:14px;letter-spacing:1px;text-transform:uppercase;color:var(--red)}
.tags{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin:0 0 8px}
.st{font-size:14px;color:var(--mut)}
.is-next .st{color:var(--red);font-weight:700}
.st.run{display:inline-flex;align-items:center;gap:7px;background:var(--red);color:#fff;font-weight:700;padding:2px 9px 2px 8px}
.t{font-weight:600;font-size:22px;line-height:1.2;text-transform:uppercase;color:var(--navy);margin:0 0 4px}
.pl{margin:0;font-size:15px;color:var(--mut)}
.x{margin:6px 0 0;font-size:16px}
.acts{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 0}
.btn{display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:7px 14px;background:#fff;border:2px solid var(--line);font-weight:500;font-size:14px;line-height:1.2;letter-spacing:1px;text-transform:uppercase;color:var(--navy);transition:background .15s,border-color .15s}
.btn:hover,.btn.res{border-color:var(--navy)}
.btn.res:hover{background:var(--navy);color:#fff}
.btn.pri{background:var(--red);border-color:var(--red);color:#fff}
.btn.pri:hover{background:var(--red-d);border-color:var(--red-d)}
.btn small{font:13px "PT Sans",Arial,sans-serif;letter-spacing:0;text-transform:none;opacity:.9}
.btn .on{display:inline-flex;align-items:center;gap:5px;font:700 12px "PT Sans",Arial,sans-serif;letter-spacing:0;text-transform:none;color:var(--red)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:currentColor;animation:pl 1.4s ease-out infinite}
@keyframes pl{0%{box-shadow:0 0 0 0 currentColor}70%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}
.files{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:6px 22px;font-size:15px}
.files a{display:inline-flex;align-items:center;gap:6px}
.files a .ic{color:var(--red)}
.files a span{border-bottom:1px solid rgba(231,30,37,.35)}
.files a:hover span{color:var(--red)}
.files em{font:13px Oswald,Arial,sans-serif;font-style:normal;letter-spacing:1px;text-transform:uppercase;color:var(--mut);white-space:nowrap}
.a{display:flex;flex-direction:column;align-items:flex-end;gap:10px}
.a a{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;font-size:15px;letter-spacing:1px;text-transform:uppercase;color:var(--red)}
.a a:hover{color:var(--red-d)}
.empty,.err{background:var(--bg2);border-left:6px solid var(--red);padding:28px 30px}
.empty p,.err p{margin:0 0 14px}
.err b{display:block;font-size:22px;text-transform:uppercase;color:var(--navy);margin:0 0 6px}
.sk{display:grid;gap:12px}
.sk i{display:block;height:118px;background:linear-gradient(90deg,#EEF1F5 25%,#F7F8FA 50%,#EEF1F5 75%) 0 0/300% 100%;animation:sh 1.3s linear infinite}
.sk i:first-child{height:96px;background-image:linear-gradient(90deg,#DFE4EB 25%,#E9EDF2 50%,#DFE4EB 75%)}
.sk i:nth-child(2){height:44px;width:60%}
@keyframes sh{to{background-position:-150% 0}}
@media (max-width:1100px){
 .ev{grid-template-columns:120px minmax(0,1fr);gap:12px 24px}
 .a{grid-column:2;align-items:flex-start;flex-direction:row;flex-wrap:wrap;gap:8px 20px}
}
@media (max-width:700px){
 :host{font-size:16px}
 .next{padding:20px 18px}
 .tools{flex-direction:column;align-items:stretch;margin-bottom:28px}
 .fl{display:flex}
 .fl button{flex:1 1 0;padding:10px 4px;font-size:14px;letter-spacing:.5px}
 .fl small{margin-left:3px}
 .mh h3{font-size:24px}
 .ev{grid-template-columns:minmax(0,1fr);gap:10px;padding:18px 16px 18px 14px}
 .a{grid-column:auto}
 .d{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 10px}
 .d b{font-size:26px}
 .d span{margin:0}
 .t{font-size:20px}
 .btn{flex:1 1 auto;justify-content:center}
 .empty,.err{padding:22px 18px}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}`;

  function fontsOnce() {
    // @font-face должен быть на уровне документа, чтобы шрифт был доступен внутри shadow root.
    // На fla65.ru Oswald/PT Sans уже подключены Tilda/Google Fonts — тогда ничего не добавляем.
    try {
      if (document.getElementById('sakhstart-brand-css')) return;
      let has = false;
      if (document.fonts && document.fonts.forEach) document.fonts.forEach(f => { if (/oswald/i.test(f.family)) has = true; });
      if (has) return;
      const l = document.createElement('link');
      l.id = 'sakhstart-brand-css'; l.rel = 'stylesheet'; l.href = ORIGIN + '/r/assets/brand.css';
      document.head.appendChild(l);
    } catch (e) { /* без фирменных шрифтов тоже читается */ }
  }

  function Cal(host) {
    this.host = host;
    this.year = parseInt(host.getAttribute('data-year'), 10) || new Date().getFullYear();
    this.api = (safe(host.getAttribute('data-origin')) || ORIGIN + '/').replace(/\/$/, '') + '/r/api/calendar?year=' + this.year;
    this.root = host.shadowRoot || host.attachShadow({ mode: 'open' });
    const h = (location.hash || '').slice(1);
    this.s = { f: h === 'past' || h === 'all' ? h : null, lv: null, ad: false };
    this.raw = '';
    this.root.addEventListener('click', ev => this.click(ev));
    this.load();
  }
  Cal.prototype.shell = function (body, busy) {
    this.root.innerHTML = `<style>${CSS}</style><div class="w" aria-busy="${busy ? 'true' : 'false'}">${body}</div>`;
  };
  Cal.prototype.load = function (quiet) {
    if (!quiet) this.shell('<div class="sk" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div><p class="sr" role="status">Загружаем календарь соревнований…</p>', true);
    return fetch(this.api, { credentials: 'omit', cache: 'no-cache' })
      .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
      .then(t => {
        if (quiet && t === this.raw) return;
        const d = JSON.parse(t);
        if (!d || !Array.isArray(d.events)) throw new Error('нет events');
        this.raw = t;
        this.data(d.events);
        quiet ? this.update() : this.render();
      })
      .catch(err => { if (!quiet) this.fail(err); });
  };
  Cal.prototype.data = function (list) {
    const now = new Date(); now.setHours(0, 0, 0, 0);
    this.ev = list.filter(e => e && e.name && day(e.date)).map(e => {
      const o = Object.assign({}, e);
      o._d = day(e.date); o._e = day(e.date_end) || o._d;
      o._lv = LV[e.level] ? e.level : 'region';
      o._st = e.status === 'running' ? 'run' : e.status === 'finished' || o._e < now ? 'past' : 'next';
      return o;
    }).sort((a, b) => a._d - b._d || a._e - b._e);
    clearInterval(this.timer);
    if (this.ev.some(e => e._st === 'run')) this.timer = setInterval(() => { if (!document.hidden) this.load(true); }, 120000);
  };
  Cal.prototype.fail = function () {
    this.shell(`<div class="err" role="alert"><b>Календарь не загрузился</b><p>Сервер SakhStart сейчас не отвечает. Обновите страницу через минуту или откройте старты и регистрацию на reg.fla65.ru.</p>` +
      `<div class="acts"><button type="button" class="btn" data-retry>Повторить</button>${link(ORIGIN + '/r/', 'Открыть SakhStart' + ARR, 'btn pri')}</div></div>`);
  };
  Cal.prototype.match = function (e, f) {
    const s = this.s;
    if (s.lv && e._lv !== s.lv) return false;
    if (s.ad && !e.adaptive) return false;
    return f === 'all' || (f === 'past' ? e._st === 'past' : e._st !== 'past');
  };
  Cal.prototype.render = function () {
    const lvs = Object.keys(LV).filter(k => this.ev.some(e => e._lv === k));
    const chips = lvs.map(k => `<button type="button" class="chip" data-lv="${k}" aria-pressed="false" title="Только ${LV[k][1]}"><span class="tag ${k}">${LV[k][0]}</span></button>`).join('') +
      (this.ev.some(e => e.adaptive) ? '<button type="button" class="chip" data-ad aria-pressed="false" title="Только адаптивный спорт"><span class="tag ad">Адаптивный спорт</span></button>' : '');
    const fl = FL.map(([k, t]) => `<button type="button" data-f="${k}" aria-pressed="false">${t}<small></small></button>`).join('');
    if (!this.s.f) this.s.f = this.ev.some(e => e._st !== 'past') ? 'next' : 'all';
    this.shell(`<div class="nx"></div><div class="tools"><div class="lg" role="group" aria-label="Уровень соревнований"><span aria-hidden="true">Уровень</span>${chips}<button type="button" class="clr" data-clr hidden>Все уровни</button></div>` +
      `<div class="fl" role="group" aria-label="Какие старты показать">${fl}</div></div><p class="sr" role="status" aria-live="polite"></p><div class="out"></div>`);
    this.update();
  };
  Cal.prototype.update = function () {
    const R = this.root, s = this.s;
    R.querySelectorAll('[data-f]').forEach(b => {
      const k = b.getAttribute('data-f');
      b.setAttribute('aria-pressed', k === s.f ? 'true' : 'false');
      b.querySelector('small').textContent = this.ev.filter(e => this.match(e, k)).length;
    });
    R.querySelectorAll('[data-lv]').forEach(b => b.setAttribute('aria-pressed', b.getAttribute('data-lv') === s.lv ? 'true' : 'false'));
    const ad = R.querySelector('[data-ad]'); if (ad) ad.setAttribute('aria-pressed', s.ad ? 'true' : 'false');
    const lg = R.querySelector('.lg'); if (lg) lg.classList.toggle('on', !!(s.lv || s.ad));
    const clr = R.querySelector('[data-clr]'); if (clr) clr.hidden = !(s.lv || s.ad);
    R.querySelector('.nx').innerHTML = this.nextBox();
    const shown = this.ev.filter(e => this.match(e, s.f));
    const groups = [];
    shown.forEach(e => {
      const key = e._d.getFullYear() * 12 + e._d.getMonth(), g = groups[groups.length - 1];
      if (g && g.key === key) g.items.push(e); else groups.push({ key, items: [e] });
    });
    R.querySelector('.out').innerHTML = groups.length ? groups.map(g => {
      const d = g.items[0]._d, y = d.getFullYear() !== this.year ? ' ' + d.getFullYear() : '';
      return `<div class="m"><div class="mh"><h3>${MON[d.getMonth()]}${y}</h3></div><ul class="list">${g.items.map(e => this.card(e)).join('')}</ul></div>`;
    }).join('') : `<div class="empty"><p>${s.f === 'next' ? 'Впереди стартов с такими условиями нет.' : 'Стартов с такими условиями нет.'}</p><button type="button" class="btn" data-reset>Показать весь год</button></div>`;
    R.querySelector('[role=status]').textContent = 'Показано ' + shown.length + ' ' + plural(shown.length, 'старт', 'старта', 'стартов');
  };
  Cal.prototype.nextBox = function () {
    const run = this.ev.find(e => e._st === 'run'), e = run || this.ev.find(x => x._st === 'next');
    if (!e) return '';
    const w = when(e), city = e.city || e.place;
    let act = '';
    if (run && e.results) act = link(e.results, 'Результаты онлайн' + ARR, '');
    else if (run && e.page) act = link(e.page, 'Страница события' + ARR, '', true);
    else if (!(this.s.f === 'next' && !this.s.lv && !this.s.ad)) act = `<button type="button" data-go>Все предстоящие${ARR}</button>`;
    else if (e.reg && e.reg.open) act = link(e.reg.url || e.page, 'Регистрация' + ARR, '');
    return `<div class="next"><p><span class="k">${run ? DOT + 'Идёт сейчас' : 'Ближайший старт'}</span><b>${esc(w.text)} — ${esc(e.name)}</b>${city ? '. ' + esc(city) : ''}</p>${act}</div>`;
  };
  Cal.prototype.card = function (e) {
    const w = when(e), st = e._st, ours = e.ours !== false;
    const stt = st === 'run' ? `<span class="st run">${DOT}Идёт сейчас</span>` : `<span class="st">${st === 'past' ? 'Прошло' : 'Впереди'}</span>`;
    const pl = [e.place, e.city].filter(Boolean).map(esc).join(' · ');
    const acts = [], side = [];
    if (e.reg && e.reg.open) {
      const dl = deadline(e.reg.deadline);
      acts.push(link(e.reg.url || e.page, 'Регистрация' + (dl ? `<small>${esc(dl)}</small>` : ''), 'btn pri'));
    }
    const res = link(e.results, 'Результаты' + (e.results_live ? `<span class="on">${DOT}онлайн</span>` : ''), 'btn res');
    if (st === 'past') acts.push(res);
    acts.push(link(e.start_list, 'Стартовый протокол', 'btn'));
    if (st !== 'past') acts.push(res);
    acts.push(link(e.live, 'Трансляция' + (st === 'run' ? `<span class="on">${DOT}эфир</span>` : ''), 'btn'));
    acts.push(link(e.photo, 'Фото', 'btn'));
    (Array.isArray(e.links) ? e.links : []).forEach(l => {
      if (!l || !l.url) return;
      if (ours) acts.push(link(l.url, esc(l.title || 'Ссылка'), 'btn'));
      else side.push(link(l.url, esc(l.title || 'Подробнее') + ARR, ''));
    });
    if (e.page) side.unshift(link(e.page, 'Страница события' + ARR, '', true));
    const files = (Array.isArray(e.files) ? e.files : []).filter(f => f && safe(f.url)).map(f => {
      const ext = String(f.ext || '').replace(/[^a-z0-9]/gi, '').slice(0, 6);
      let t = String(f.title || 'Документ');
      if (ext && t.toLowerCase().endsWith('.' + ext.toLowerCase())) t = t.slice(0, -ext.length - 1);
      const meta = [ext.toUpperCase(), size(f.size)].filter(Boolean).join(' · ');
      return `<li>${link(f.url, DOC + `<span>${esc(t)}</span>` + (meta ? `<em>${esc(meta)}</em>` : ''), '')}</li>`;
    });
    const a = acts.filter(Boolean);
    return `<li class="ev l-${e._lv} is-${st}"><div class="d"><b>${esc(w.big)}</b><span>${esc(w.small)}</span></div><div class="b">` +
      `<div class="tags"><span class="tag ${e._lv}">${LV[e._lv][0]}</span>${e.adaptive ? '<span class="tag ad">Адаптивный спорт</span>' : ''}${stt}</div>` +
      `<h4 class="t">${esc(e.name)}</h4>${pl ? `<p class="pl">${pl}</p>` : ''}${e.note ? `<p class="x">${esc(e.note)}</p>` : ''}` +
      (a.length ? `<div class="acts">${a.join('')}</div>` : '') + (files.length ? `<ul class="files" aria-label="Документы">${files.join('')}</ul>` : '') +
      `</div>${side.filter(Boolean).length ? `<div class="a">${side.join('')}</div>` : ''}</li>`;
  };
  Cal.prototype.click = function (ev) {
    const t = ev.target.closest && ev.target.closest('button');
    if (!t) return;
    const s = this.s;
    if (t.hasAttribute('data-retry')) return void this.load();
    if (t.hasAttribute('data-f')) s.f = t.getAttribute('data-f');
    else if (t.hasAttribute('data-lv')) { const k = t.getAttribute('data-lv'); s.lv = s.lv === k ? null : k; }
    else if (t.hasAttribute('data-ad')) s.ad = !s.ad;
    else if (t.hasAttribute('data-clr')) { s.lv = null; s.ad = false; }
    else if (t.hasAttribute('data-reset')) { s.lv = null; s.ad = false; s.f = 'all'; }
    else if (t.hasAttribute('data-go')) { s.lv = null; s.ad = false; s.f = 'next'; }
    else return;
    this.update();
    if (t.hasAttribute('data-clr') || t.hasAttribute('data-reset') || t.hasAttribute('data-go')) {
      const b = this.root.querySelector('[data-f][aria-pressed=true]'); if (b) b.focus();
    }
  };

  function boot() {
    fontsOnce();
    document.querySelectorAll('#sakhstart-calendar,[data-sakhstart-calendar]').forEach(el => {
      if (!el.__sakhstart && el.attachShadow) el.__sakhstart = new Cal(el);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
