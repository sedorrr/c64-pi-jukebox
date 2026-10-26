/* C64-Jukebox: the page. No build step - plain JavaScript, talks to /api (JSON). */
'use strict';
const $ = id => document.getElementById(id);
const H = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const MASK = '••••';
const store = {
  get(k, d) { try { const v = localStorage.getItem('c64pi.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('c64pi.' + k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
};
function fmt(s) { if (s == null || isNaN(s)) return ''; s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
let toastT;
function toast(t) { const e = $('toast'); e.textContent = t; e.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => e.classList.remove('on'), 3500); }

/* ---------------------------------------------------------------- API */
async function api(path, data, raw) {
  const o = data === undefined ? {} : {method: 'POST', headers: {'X-C64': '1'}, body: raw ? data : JSON.stringify(data)};
  if (data !== undefined && !raw) o.headers['Content-Type'] = 'application/json';
  let r;
  try { r = await fetch('/api/' + path, o); } catch (e) { throw new Error('Keine Verbindung zum Pi'); }
  let j = {};
  try { j = await r.json(); } catch (e) { j = {ok: false, msg: 'Fehler ' + r.status}; }
  if (r.status === 401 && path !== 'login' && path !== 'password') {
    /* a request sent just before a password change still carries the old cookie: only log out if we really are */
    let still = false;
    try { still = (await (await fetch('/api/hello')).json()).login; } catch (e) { /* offline */ }
    if (!still) showLogin();
    throw new Error('Bitte anmelden');
  }
  if (!r.ok || j.ok === false) throw new Error(j.msg || ('Fehler ' + r.status));
  return j;
}
async function waitJob(id, onProgress) {
  for (;;) {
    await new Promise(r => setTimeout(r, 400));
    const j = await api('job?id=' + id);
    if (onProgress) onProgress(j.progress || '', j);
    if (j.done) { if (j.error) throw new Error(j.error); return j.result; }
  }
}
/* progress of a network search: bar in percent, the addresses being checked right now, what was found so far */
function ipRange(list) {
  if (!list || !list.length) return '';
  const a = list[0], b = list[list.length - 1];
  if (a === b) return a;
  const pa = a.split('.'), pb = b.split('.');
  return pa.slice(0, 3).join('.') === pb.slice(0, 3).join('.') ? a + ' … .' + pb[3] : a + ' … ' + b;
}
function scanHtml(j, want) {
  const i = j.info || {}, pct = j.pct || 0;
  const found = (i.found || []).filter(t => !want || want.test(t));
  const now = i.phase === 'names' ? (i.busy && i.busy.length ? 'frage den Namen von ' + H(i.busy[0]) + ' ab' : 'fertig')
    : (i.busy && i.busy.length ? 'prüft gerade ' + H(ipRange(i.busy)) : 'startet …');
  return '<div class=jprog role=progressbar aria-valuenow=' + pct + ' aria-valuemin=0 aria-valuemax=100><div style="width:' + pct + '%"></div></div>' +
    '<div class=hint><b>' + pct + ' %</b> – ' + now + '</div>' +
    (found.length ? '<div class=hint>gefunden: ' + found.map(H).join(', ') + '</div>' : '');
}
function errToast(e) { if (e && e.message !== 'Bitte anmelden') toast(e.message || String(e)); }

/* ---------------------------------------------------------------- login */
function showLogin() { $('app').hidden = true; $('login').hidden = false; setTimeout(() => $('lpw').focus(), 50); }
$('lform').onsubmit = async ev => {
  ev.preventDefault(); $('lmsg').textContent = '';
  try { await api('login', {pw: $('lpw').value}); $('lpw').value = ''; start(); }
  catch (e) { $('lmsg').textContent = e.message; }
};
$('logout').onclick = async () => { await api('logout', {}).catch(() => {}); showLogin(); };

/* ---------------------------------------------------------------- tabs, help */
function tab(t) {
  document.querySelectorAll('#tabs button').forEach(b => b.setAttribute('aria-selected', b.dataset.t === t));
  document.querySelectorAll('main > section').forEach(s => s.classList.toggle('off', s.dataset.tab !== t));
  store.set('tab', t);
  if (t === 'files') filesShow();
  if (t === 'lists') plsLoad();
  if (t === 'dev') devShow();
  if (t === 'show') showShow();
  if (t === 'set') setShow();
  if (t === 'help') helpLoad();
}
document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => tab(b.dataset.t));
let helpDone = false;
async function helpLoad(target) {
  if (!helpDone) {
    const r = await fetch('/hilfe').catch(() => null);
    $('helpbody').innerHTML = r && r.ok ? await r.text() : 'Handbuch nicht erreichbar.';
    helpDone = true;
    $('helpbody').querySelectorAll('a[data-h]').forEach(a => a.onclick = ev => { ev.preventDefault(); helpJump(a.dataset.h); });
  }
  if (target) helpJump(target);
}
function helpJump(h) { const e = document.getElementById('h-' + h); if (e) e.scrollIntoView({behavior: 'smooth', block: 'start'}); }
function help(h) { tab('help'); helpLoad(h); }

/* ---------------------------------------------------------------- state, now playing */
let S = null;
async function poll() {
  if (document.visibilityState === 'hidden') return;
  try { S = await api('state'); } catch (e) { return; }
  nowShow();
  lTick();
}
function badges(i) {
  const b = [];
  if (i.songs > 1) b.push(i.songs + ' Lieder');
  if (i.chips > 1) b.push('<span class="badge st">' + i.chips + ' SIDs</span>');
  if (i.models && i.models.filter(Boolean).length) b.push(i.models.filter(Boolean).join(' + '));
  if (i.sids) b.push('$' + i.sids.join(' $'));
  return b.map(x => x.startsWith('<') ? x : '<span class=badge>' + H(x) + '</span>').join('');
}
function nowShow() {
  const p = S.player, n = p.now;
  $('pwwarn').hidden = !S.pwdefault;
  $('bplay').innerHTML = p.state === 'play' ? '&#10074;&#10074;' : '&#9654;';
  $('bplay').title = p.state === 'play' ? 'Pause' : 'Abspielen';
  if (n) {
    $('nt').textContent = n.title || n.name;
    $('na').textContent = [n.author, n.released && n.released !== n.year ? n.released : ''].filter(Boolean).join(' · ');
    $('nb').innerHTML = badges(n) + (p.state === 'pause' ? '<span class=badge>Pause</span>' : '');
    const stil = (n.stil || []).map(t => '<p>' + H(t) + '</p>').join('');
    if ($('nstil').dataset.h !== stil) { $('nstil').innerHTML = stil; $('nstil').dataset.h = stil; }
    $('nstil').hidden = !stil;
    $('tel').textContent = fmt(p.el);
    $('tlen').textContent = n.secs ? fmt(n.secs) : (S.opts.limit_min ? 'max. ' + fmt(S.opts.limit_min * 60) : '');
    const len = n.secs || S.opts.limit_min * 60;
    $('pbar').style.width = len ? Math.min(100, 100 * p.el / len) + '%' : '0';
    $('songsel').hidden = !(n.songs > 1);
    $('endrow').hidden = !(p.state === 'play' && !n.secs) || !!n.loop || !!n.hvsc;
    $('looprow').hidden = !n.loop;
    $('namerow').hidden = !n.hvsc;
    if (n.hvsc) $('nametxt').textContent = 'In der HVSC als ' + n.hvsc.path.split('/').pop() + ' (' + n.hvsc.path.split('/').slice(1, -1).join('/') + ') mit ' + fmt(n.hvsc.len) + ' – als Länge übernehmen?';
    if (n.loop) $('looptxt').textContent = 'Fängt nach ' + fmt(n.loop) + ' von vorn an – als Länge übernehmen?';
    $('sinfo').textContent = 'Lied ' + n.song + ' von ' + n.songs;
    $('topnow').textContent = (p.state === 'pause' ? '❚❚ ' : '♪ ') + (n.title || n.name) + (n.author ? ' – ' + n.author : '');
  } else {
    $('nt').textContent = p.state === 'load' ? 'Lade …' : 'Nichts läuft';
    $('na').textContent = p.total ? p.total + ' Titel in der Liste' : '';
    $('nstil').hidden = true;
    $('nb').innerHTML = ''; $('tel').textContent = ''; $('tlen').textContent = ''; $('pbar').style.width = '0';
    $('songsel').hidden = true; $('topnow').textContent = ''; $('endrow').hidden = true; $('looprow').hidden = true; $('namerow').hidden = true;
  }
  $('pmsg').textContent = [p.msg, S.sidaddr].filter(Boolean).join(' · ');
  $('oshuf').checked = !!S.opts.shuffle; $('orep').checked = S.opts.repeat !== false;
  const sel = $('ou64'), opts = S.ultimates.map((u, i) => '<option value=' + i + '>' + H(u.label || u.addr || 'Ultimate ' + (i + 1)) + '</option>').join('');
  if (sel.dataset.o !== opts) { sel.innerHTML = opts; sel.dataset.o = opts; }
  sel.value = S.sel; sel.parentElement.hidden = S.ultimates.length < 2;
  if (document.querySelector('section[data-tab=dev]:not(.off)')) stShow();
}
const ctl = (c, x) => api('ctl', Object.assign({c}, x || {})).then(poll).catch(errToast);
$('bplay').onclick = () => ctl(S && S.player.state === 'play' ? 'pause' : 'play');
$('bstop').onclick = () => ctl('stop');
$('bnext').onclick = () => ctl('next');
$('bloopok').onclick = () => { const n = S.player.now; api('ctl', {c: 'looptake'}).then(() => { toast('Länge ' + fmt(n && n.loop) + '* übernommen'); poll(); }).catch(errToast); };
$('bloopno').onclick = () => ctl('loopno');
$('bnameok').onclick = () => { const n = S.player.now; api('ctl', {c: 'nametake'}).then(() => { toast('Länge ' + fmt(n && n.hvsc && n.hvsc.len) + '* übernommen'); poll(); }).catch(errToast); };
$('bnameno').onclick = () => ctl('nameno');
$('bend').onclick = () => api('ctl', {c: 'endhere'}).then(() => { toast('Länge ' + fmt(Math.round(S.player.el)) + '* gemerkt'); poll(); }).catch(errToast);
$('bprev').onclick = () => ctl('prev');
$('sdown').onclick = () => { const n = S.player.now; if (n && n.song > 1) ctl('song', {n: n.song - 1}); };
$('sup').onclick = () => { const n = S.player.now; if (n && n.song < n.songs) ctl('song', {n: n.song + 1}); };
$('oshuf').onchange = () => ctl('shuffle', {on: $('oshuf').checked});
$('orep').onchange = () => api('config', {player: {repeat: $('orep').checked}}).then(poll).catch(errToast);
$('ou64').onchange = () => api('config', {u64_sel: +$('ou64').value}).then(() => { toast('Ultimate gewechselt'); poll(); }).catch(errToast);

/* ---------------------------------------------------------------- the play list window
   A table like the PC program's (Dateiname, Titel, Komponist, Stück, SIDs, Länge, Gespielt, ★), sorted by a click on a
   column header. Only the visible rows exist in the page (the list can hold a whole HVSC); they come from /api/rows
   in blocks. The running tune is marked and kept in the middle of the window. */
const isPhone = () => window.matchMedia('(max-width: 760px)').matches;
const RH = () => isPhone() ? 46 : 34;
const LS = {count: 0, total: 0, lver: -1, over: -1, rows: new Map(), q: '', fav: false, sort: {}, cur: -1, curRow: -1, upnext: -1,
  sel: new Set(), anchor: -1, pending: false, queued: null, userAt: 0, progAt: 0, lastIndex: -2, lastTap: {i: -1, t: 0}};
function lenText(r) {
  if (r.len == null) return '';
  return r.lk === 'default' ? '(' + fmt(r.len) + ')' : fmt(r.len) + (r.lk === 'user' ? '*' : '');
}
function sidText(r) {
  if (!r.chips) return '';
  return r.chips + (r.sids && r.sids.length ? ' ($' + r.sids.join('/$') + ')' : '');
}
/* like the PC jukebox: a tune needing a SID address the Ultimate does not have right now */
function sidWarn(r) {
  if (r.sfit === 'fix') return S && S.opts.sidauto === false
    ? 'Das Ultimate hat diese SID-Adresse gerade nicht („SID-Sockel automatisch umstellen“ ist aus)'
    : 'Das Ultimate hat diese SID-Adresse gerade nicht – für das Stück wird ein SID-Sockel umgestellt';
  if (r.sfit === 'no') return 'Das Ultimate hat diese SID-Adresse nicht, und es gibt keine eindeutige Umstellung – das Stück klingt unvollständig';
  return '';
}
async function lFetch(start, focus) {
  if (LS.pending) { LS.queued = {start, focus: focus || (LS.queued && LS.queued.focus)}; return; }   /* run after this one */
  LS.pending = true;
  try {
    start = Math.max(0, Math.floor(start / 100) * 100);
    const r = await api('rows?start=' + start + '&n=200&q=' + encodeURIComponent(LS.q) + (LS.fav ? '&fav=1' : ''));
    if (r.lver !== LS.lver || r.count !== LS.count) LS.rows.clear();
    if (r.over !== LS.over) { LS.sel.clear(); LS.anchor = -1; }        /* other numbering: an old selection would hit other tunes */
    Object.assign(LS, {count: r.count, total: r.total, lver: r.lver, over: r.over, cur: r.cur, curRow: r.cur_row, upnext: r.upnext, sort: r.sort || {}});
    r.rows.forEach((row, k) => LS.rows.set(r.start + k, row));
    lHead(r);
    $('lspace').style.height = (LS.count * RH()) + 'px';
    if (focus) lFocus(); else lRender();
  } catch (e) { /* the next poll tries again */ }
  LS.pending = false;
  if (LS.queued) { const q = LS.queued; LS.queued = null; lFetch(q.start, q.focus); }
}
function lHead(r) {
  $('lempty').hidden = r.total > 0;
  const parts = [];
  if (r.total) parts.push(r.total.toLocaleString('de-DE') + ' Titel, gesamt ' + fmtLong(r.secs) + (r.est ? ' (' + r.est + ' geschätzt)' : ''));
  if (r.count !== r.total) parts.push(r.count + ' passen');
  if (r.source) parts.push(r.source);
  const sa = S && S.player.stop_after;
  if (sa) parts.push(sa.songs ? 'Stopp nach ' + sa.songs + ' Titel(n)' : 'Stopp in ' + sa.min + ' min');
  $('lhead').textContent = parts.join(' · ');
  document.querySelectorAll('#lhd [data-col]').forEach(el => {
    el.textContent = el.textContent.replace(/ [▲▼]$/, '') + (LS.sort.col === el.dataset.col ? (LS.sort.rev ? ' ▼' : ' ▲') : '');
  });
}
function fmtLong(s) {
  s = Math.round(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return h ? h + ':' + String(m).padStart(2, '0') + ':' + String(x).padStart(2, '0') + ' h' : m + ':' + String(x).padStart(2, '0') + ' min';
}
function lRow(pos, r) {
  if (!r) return '<div class=lrow data-p=' + pos + '><span class=c-no>' + (pos + 1) + '</span><span class=c-name>…</span></div>';
  const cls = 'lrow' + (LS.sel.has(r.i) ? ' sel' : '') + (r.i === LS.cur ? ' cur' : '');
  const song = r.songs > 1 ? (r.song || 1) + '/' + r.songs : '';
  const sw = sidWarn(r);
  const t2 = [r.author, song ? 'Stück ' + song : '', r.chips > 1 || sw ? (sw ? '⚠ ' : '') + r.chips + (r.chips > 1 ? ' SIDs' : ' SID') : ''].filter(Boolean).join(' · ');
  return '<div class="' + cls + '" data-p=' + pos + ' data-i=' + r.i + (LS.q || LS.fav ? '' : ' draggable=true') + '>' +
    '<span class=c-no>' + (r.i + 1) + '</span><span class=c-name title="' + H(r.path) + '">' + H(r.name) + '</span>' +
    '<span class=c-title>' + H(r.title || r.name) + (r.i === LS.upnext && r.i !== LS.cur ? '<span class=nx title="kommt als Nächstes">▸</span>' : '') +
    '<span class=t2>' + H(t2) + '</span></span><span class=c-author>' + H(r.author) + '</span>' +
    '<span class=c-song data-dbl=song>' + song + '</span><span class="c-sids' + (sw ? ' sidw" title="' + H(sw) : '') + '">' + (sw ? '⚠ ' : '') + H(sidText(r)) + '</span>' +
    '<span class="c-len lk-' + (r.lk || 'none') + '" data-dbl=len>' + lenText(r) + '</span><span class=c-plays>' + (r.plays || '') + '</span>' +
    '<span class=c-fav data-fav title="Favorit">' + (r.fav ? '★' : '☆') + '</span>' +
    '<span class=c-more><button data-more aria-label="Mehr zu diesem Titel">⋯</button></span></div>';
}
function lRender() {
  const win = $('lwin'), rh = RH(), hd = $('lhd').offsetHeight;
  const first = Math.max(0, Math.floor(win.scrollTop / rh) - 6);
  const last = Math.min(LS.count, first + Math.ceil(win.clientHeight / rh) + 14);
  let html = '', missing = -1;
  for (let p = first; p < last; p++) {
    const r = LS.rows.get(p);
    if (!r && missing < 0) missing = p;
    html += lRow(p, r);
  }
  $('lrows').style.transform = 'translateY(' + (first * rh) + 'px)';
  $('lrows').innerHTML = html;
  if (missing >= 0) lFetch(Math.max(0, missing - 50));
  void hd;
}
function lFocus(force) {
  const pos = LS.curRow;
  if (pos < 0) { lRender(); return; }
  const win = $('lwin'), rh = RH();
  const want = Math.max(0, pos * rh - win.clientHeight / 2 + rh);
  LS.progAt = Date.now();
  win.scrollTop = want;
  lRender();
  void force;
}
/* the running tune stays in focus: on every change of tune, and when nobody scrolled for 15 s */
function lTick() {
  if (!S || document.querySelector('section[data-tab=play].off')) return;
  const p = S.player;
  if (p.lver !== LS.lver) { lFetch(LS.curRow >= 0 && p.index !== LS.lastIndex ? LS.curRow - 50 : Math.floor($('lwin').scrollTop / RH()) - 50, p.index !== LS.lastIndex); }
  else if (p.index !== LS.lastIndex) { LS.cur = p.index; if (!LS.q && !LS.fav) LS.curRow = p.index; lFetch(Math.max(0, LS.curRow - 50), true); }
  else if (Date.now() - LS.userAt > 15000 && LS.curRow >= 0) {
    const win = $('lwin'), rh = RH(), top = win.scrollTop / rh, vis = win.clientHeight / rh;
    if (LS.curRow < top || LS.curRow > top + vis - 2) lFocus();
  }
  LS.lastIndex = p.index;
}
$('lwin').addEventListener('scroll', () => { if (Date.now() - LS.progAt > 200) LS.userAt = Date.now(); lRender(); }, {passive: true});
['wheel', 'touchstart', 'keydown', 'mousedown'].forEach(ev => $('lwin').addEventListener(ev, () => { LS.userAt = Date.now(); }, {passive: true}));
let lfT;
$('lfilter').oninput = () => { clearTimeout(lfT); lfT = setTimeout(() => { LS.q = $('lfilter').value.trim(); LS.rows.clear(); $('lwin').scrollTop = 0; lFetch(0, true); }, 250); };
$('lfav').onchange = () => { LS.fav = $('lfav').checked; LS.rows.clear(); $('lwin').scrollTop = 0; lFetch(0, true); };
$('lhd').onclick = ev => {
  const c = ev.target.closest('[data-col]');
  if (c) api('ctl', {c: 'sort', col: c.dataset.col}).then(() => { LS.rows.clear(); lFetch(0, true); poll(); }).catch(errToast);
};
const rowOf = el => { const d = el && el.closest('.lrow[data-i]'); return d ? {pos: +d.dataset.p, i: +d.dataset.i, el: d, r: LS.rows.get(+d.dataset.p)} : null; };
/* the item numbers of the whole (filtered) list, in list order - for "select all" and shift ranges */
async function lIds() {
  try {
    const r = await api('rows?ids=1&q=' + encodeURIComponent(LS.q) + (LS.fav ? '&fav=1' : ''));
    if (r.over !== LS.over) { LS.sel.clear(); LS.rows.clear(); lFetch(0); return null; }
    return r.ids;
  } catch (e) { errToast(e); return null; }
}
async function lSelect(x, ev) {
  if (ev && (ev.metaKey || ev.ctrlKey)) { LS.sel.has(x.i) ? LS.sel.delete(x.i) : LS.sel.add(x.i); LS.anchor = x.pos; }
  else if (ev && ev.shiftKey && LS.anchor >= 0) {
    const a = Math.min(LS.anchor, x.pos), b = Math.max(LS.anchor, x.pos);
    let all = true;
    for (let p = a; p <= b; p++) if (!LS.rows.get(p)) { all = false; break; }
    const ids = all ? null : await lIds();
    LS.sel.clear();
    for (let p = a; p <= b; p++) { const r = LS.rows.get(p); if (r) LS.sel.add(r.i); else if (ids && p < ids.length) LS.sel.add(ids[p]); }
  } else { LS.sel.clear(); LS.sel.add(x.i); LS.anchor = x.pos; }
  lRender();
}
const selList = () => [...LS.sel].sort((a, b) => a - b);
$('lrows').addEventListener('click', ev => {
  const x = rowOf(ev.target); if (!x) return;
  if (ev.target.closest('[data-fav]')) { lFav(x.i); return; }
  if (ev.target.closest('[data-more]')) { lRowMenu(x); return; }
  const now = Date.now();
  if (LS.lastTap.i === x.i && now - LS.lastTap.t < 380) {          /* double click / double tap */
    LS.lastTap = {i: -1, t: 0};
    const dbl = ev.target.closest('[data-dbl]');
    if (dbl && dbl.dataset.dbl === 'song' && x.r && x.r.songs > 1) { lAskSong(x); return; }
    if (dbl && dbl.dataset.dbl === 'len') { lAskLen(x); return; }
    lPlay(x.i); return;
  }
  LS.lastTap = {i: x.i, t: now};
  lSelect(x, ev);
});
$('lrows').addEventListener('contextmenu', ev => { const x = rowOf(ev.target); if (!x) return; ev.preventDefault(); if (!LS.sel.has(x.i)) lSelect(x); lRowMenu(x); });
$('lwin').addEventListener('keydown', ev => {
  const sel = selList();
  if (ev.key === 'Enter' && sel.length) { ev.preventDefault(); lPlay(sel[0]); }
  else if ((ev.key === 'Delete' || ev.key === 'Backspace') && sel.length) { ev.preventDefault(); lRemove(sel); }
  else if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
    ev.preventDefault();
    const pos = LS.anchor < 0 ? 0 : Math.max(0, Math.min(LS.count - 1, LS.anchor + (ev.key === 'ArrowDown' ? 1 : -1)));
    const r = LS.rows.get(pos);
    if (r) { LS.sel.clear(); LS.sel.add(r.i); LS.anchor = pos; const win = $('lwin'), rh = RH();
      if (pos * rh < win.scrollTop + rh) win.scrollTop = pos * rh - rh; else if ((pos + 2) * rh > win.scrollTop + win.clientHeight) win.scrollTop = (pos + 2) * rh - win.clientHeight;
      lRender(); }
  }
});
/* drag & drop: one row to another place (not while searching, like the PC program) */
let dragI = -1;
$('lrows').addEventListener('dragstart', ev => { const x = rowOf(ev.target); if (!x || LS.q || LS.fav) { ev.preventDefault(); return; } dragI = x.i; ev.dataTransfer.effectAllowed = 'move'; ev.dataTransfer.setData('text/plain', String(x.i)); });
$('lrows').addEventListener('dragover', ev => { if (dragI < 0) return; ev.preventDefault(); document.querySelectorAll('.lrow.drop').forEach(e => e.classList.remove('drop')); const x = rowOf(ev.target); if (x) x.el.classList.add('drop'); });
$('lrows').addEventListener('drop', ev => {
  ev.preventDefault(); const x = rowOf(ev.target); const from = dragI; dragI = -1;
  if (x && from >= 0 && x.i !== from) api('ctl', {c: 'move', i: from, j: x.i, over: LS.over}).then(() => { LS.rows.clear(); lFetch(Math.floor($('lwin').scrollTop / RH()) - 50); }).catch(errToast);
});
$('lrows').addEventListener('dragend', () => { dragI = -1; document.querySelectorAll('.lrow.drop').forEach(e => e.classList.remove('drop')); });

function lPlay(i) { ctl('goto', {i, over: LS.over}); }
function lStale(e) { if (/geändert/.test(e.message)) { LS.sel.clear(); LS.rows.clear(); poll(); } errToast(e); }
function lRemove(is) {
  if (!is.length) { toast('Erst Titel auswählen (antippen, mit Strg/Shift mehrere)'); return; }
  api('ctl', {c: 'remove', is, over: LS.over}).then(() => { LS.sel.clear(); LS.rows.clear(); toast(is.length + ' Titel entfernt'); poll(); }).catch(lStale);
}
function lNext(is) {
  if (!is.length) { toast('Erst Titel auswählen'); return; }
  api('ctl', {c: 'nextup', is, over: LS.over}).then(r => { toast(r.n === 1 ? 'Kommt als Nächstes' : r.n + ' Titel kommen als Nächstes'); LS.rows.clear(); poll(); }).catch(lStale);
}
function lFav(i) { api('ctl', {c: 'fav', i, over: LS.over}).then(r => { toast(r.fav ? '★ Favorit' : 'kein Favorit mehr'); LS.rows.clear(); lFetch(Math.floor($('lwin').scrollTop / RH()) - 50); }).catch(lStale); }
async function lAskSong(x) {
  const r = x.r; if (!r || !(r.songs > 1)) { toast('Dieser Titel hat nur ein Stück'); return; }
  const v = await ask('Stück (1–' + r.songs + ') für „' + (r.title || r.name) + '“', String(r.song || 1));
  if (!v) return;
  const n = parseInt(v, 10);
  if (!(n >= 1 && n <= r.songs)) { toast('Bitte eine Zahl von 1 bis ' + r.songs); return; }
  api('ctl', {c: 'setsong', i: x.i, n, over: LS.over}).then(() => { LS.rows.clear(); poll(); }).catch(lStale);
}
async function lAskLen(x) {
  const r = x.r;
  const v = await ask('Eigene Länge für „' + ((r && (r.title || r.name)) || '') + '“ (m:ss, leer = HVSC/Standard)', r && r.lk === 'user' ? fmt(r.len) : '');
  if (v === null || (v === '' && !(r && r.lk === 'user'))) return;
  let secs = null;
  if (v) {
    const m = /^(\d+):(\d{1,2})$/.exec(v.trim()), s = /^\d+$/.test(v.trim()) ? +v.trim() : null;
    secs = m ? +m[1] * 60 + +m[2] : s;
    if (!secs || secs < 1 || secs > 9999) { toast('Bitte als m:ss angeben, z. B. 3:05'); return; }
  }
  api('ctl', {c: 'setlen', i: x.i, secs, over: LS.over}).then(() => { toast(secs ? 'Länge ' + fmt(secs) + '* gemerkt' : 'Eigene Länge entfernt'); LS.rows.clear(); poll(); }).catch(lStale);
}
function menu(title, items) {
  $('menutitle').textContent = title;
  $('menubtns').innerHTML = items.map((m, k) => '<button type=button data-k=' + k + (m.danger ? ' class=danger' : '') + '>' + m.label + '</button>').join('');
  $('menubtns').onclick = ev => { const b = ev.target.closest('button'); if (!b) return; $('menudlg').close(); items[+b.dataset.k].fn(); };
  $('menudlg').showModal();
}
function lRowMenu(x) {
  const r = x.r || {}, many = LS.sel.size > 1 && LS.sel.has(x.i) ? selList() : [x.i];
  const items = [{label: '▶ Abspielen', fn: () => lPlay(x.i)},
    {label: many.length > 1 ? many.length + ' Titel als Nächstes' : 'Als Nächstes spielen', fn: () => lNext(many)}];
  if (r.songs > 1) items.push({label: 'Stück wählen … (' + (r.song || 1) + '/' + r.songs + ')', fn: () => lAskSong(x)});
  items.push({label: 'Eigene Länge …', fn: () => lAskLen(x)}, {label: r.fav ? '☆ kein Favorit mehr' : '★ Favorit', fn: () => lFav(x.i)});
  if (r.src) items.push({label: 'Im Tab Dateien zeigen', fn: () => { tab('files'); F.items = []; openDir(r.src, r.path.replace(/\/[^/]*$/, '') || '/'); }});
  items.push({label: many.length > 1 ? many.length + ' Titel entfernen' : 'Aus der Liste nehmen', danger: true, fn: () => lRemove(many)});
  menu(r.title || r.name || 'Titel', items);
}
$('lplay').onclick = () => { const s = selList(); s.length ? lPlay(s[0]) : ctl('play'); };
$('lnext').onclick = () => lNext(selList());
$('ldel').onclick = () => lRemove(selList());
$('lfocus').onclick = () => { LS.userAt = 0; lFetch(Math.max(0, LS.curRow - 50), true); };
$('lcheck').onclick = async () => {
  const m = $('plmsg');
  $('lcheck').disabled = true;
  m.innerHTML = scanBar({pct: 0}) + 'Längen prüfen …';
  try {
    const r = await api('list/check', {});
    const res = await waitJob(r.job, (p, j) => { m.innerHTML = scanBar(j) + H(p || 'Längen prüfen …'); });
    let t = res.read + ' Dateien gelesen' + (res.bad ? ', ' + res.bad + ' nicht lesbar' : '');
    if (res.nolen) t += ' · ' + res.nolen + ' Titel ohne Länge' + (res.taken ? ', ' + res.taken + ' Längen aus der HVSC übernommen'
      : res.found ? ', davon ' + res.found + ' in der HVSC gefunden (andere Fassung derselben Datei)' : '');
    else t += ' · alle Titel haben eine Länge';
    m.textContent = t;
    if (res.found && !res.taken) {
      const b = document.createElement('button');
      b.className = 'primary'; b.textContent = res.found + ' Längen übernehmen';
      b.onclick = () => api('ctl', {c: 'takenames'}).then(x => { m.textContent = x.n + ' Längen übernommen'; LS.rows.clear(); poll(); }).catch(errToast);
      m.append(' ', b);
    }
    LS.rows.clear(); poll();
  } catch (e) { m.textContent = e.message; }
  $('lcheck').disabled = false;
};
function scanBar(j) { return j.pct != null ? '<div class=jprog><div style="width:' + j.pct + '%"></div></div>' : ''; }
$('lsave').onclick = async () => {
  const name = await ask('Liste speichern als', store.get('plname', ''));
  if (!name) return;
  store.set('plname', name);
  try { await api('playlist/save', {name}); toast('Gespeichert: ' + name); } catch (e) { errToast(e); }
};
$('lmenu').onclick = () => menu('Wiedergabeliste', [
  {label: 'Playlist der PC-Jukebox importieren …', fn: impOpen},
  {label: 'Für die PC-Jukebox exportieren (.json)', fn: () => exportShared('')},
  {label: 'Entdecken: ein nie gespielter Titel', fn: () => api('ctl', {c: 'discover'}).then(() => { toast('Entdeckt!'); poll(); }).catch(errToast)},
  {label: 'Entdecken: ein neuer Komponist', fn: () => api('ctl', {c: 'discover', author: true}).then(() => { toast('Entdeckt!'); poll(); }).catch(errToast)},
  {label: 'Stopp nach … (Titel oder Minuten)', fn: stopAfter},
  {label: 'Doppelte entfernen (gleiche Datei)', fn: () => api('ctl', {c: 'dedupe'}).then(r => { toast(r.n ? r.n + ' doppelte Titel entfernt' : 'Keine doppelten Titel'); LS.rows.clear(); poll(); }).catch(errToast)},
  {label: 'Alles auswählen', fn: () => lIds().then(ids => { if (!ids) return; LS.sel = new Set(ids); lRender(); toast(LS.sel.size + ' ausgewählt'); })},
  {label: 'Liste leeren', danger: true, fn: () => { if (confirm('Die ganze Wiedergabeliste leeren?')) ctl('clear'); }}]);
async function stopAfter() {
  const v = await ask('Stopp nach … – Anzahl Titel (z. B. 5) oder Minuten (z. B. 30m); leer = aus', '');
  if (v === null) return;
  const t = v.trim().toLowerCase();
  const d = !t || t === '0' ? {} : /m(in)?$/.test(t) ? {minutes: parseFloat(t)} : {songs: parseInt(t, 10)};
  api('ctl', Object.assign({c: 'stopafter'}, d)).then(() => { toast(d.songs ? 'Stopp nach ' + d.songs + ' Titel(n)' : d.minutes ? 'Stopp in ' + d.minutes + ' min' : 'Stopp nach … aus'); poll(); }).catch(errToast);
}
async function exportShared(name) {
  try {
    toast('Export wird vorbereitet …');
    const r = await api('export/shared', {name});
    const res = await waitJob(r.job);
    const nm = (res.json.name || 'playlist').replace(/[^A-Za-z0-9 _-]/g, '_').trim() || 'playlist';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(res.json, null, 2)], {type: 'application/json'}));
    a.download = nm + '_u64playlist.json'; document.body.appendChild(a); a.click(); a.remove();
    toast(res.json.songs.length + ' Titel exportiert' + (res.skipped ? ', ' + res.skipped + ' ohne MD5 ausgelassen' : ''));
  } catch (e) { errToast(e); }
}
/* import of a play list of the PC program */
let impText = '', impKind = '', impName = '';
async function impOpen() {
  $('impres').innerHTML = ''; $('impprog').innerHTML = ''; $('impname').textContent = ''; impText = ''; impKind = '';
  $('impgo').disabled = false;
  $('imppath').value = F.src ? F.path : '/';
  $('impdlg').showModal();
  try { SRC = (await api('sources')).sources; } catch (e) { errToast(e); return; }
  $('impsrc').innerHTML = '<option value="">(keine – nur u64://-Einträge)</option>' + SRC.map(s => '<option value="' + H(s.id) + '">' + H(s.label) + '</option>').join('');
  $('impsrc').value = F.src || (SRC[0] ? SRC[0].id : '');
}
$('impfile').onchange = async () => {
  const f = $('impfile').files[0]; if (!f) return;
  impText = await f.text(); impName = f.name.replace(/(_u64playlist)?\.(json|u64pl|txt)$/i, '');
  impKind = /^\s*\{/.test(impText) ? 'shared' : 'u64pl';
  let n = 0;
  if (impKind === 'shared') { try { const d = JSON.parse(impText); n = (d.songs || []).length; impName = d.name || impName; } catch (e) { impKind = ''; } }
  else n = impText.split('\n').filter(l => l.trim() && !l.startsWith('#')).length;
  $('impname').textContent = impKind ? f.name + ': ' + n + ' Titel (' + (impKind === 'shared' ? 'geteilte Playlist' : '.u64pl') + ')' : 'Datei nicht lesbar';
  $('impfile').value = '';
};
$('impclose').onclick = () => $('impdlg').close();
$('impgo').onclick = async () => {
  if (!impKind) { toast('Erst eine Datei wählen'); return; }
  const src = $('impsrc').value, path = $('imppath').value.trim() || '/';
  if (impKind === 'shared' && !src) { toast('Für die geteilte Playlist eine Quelle zum Suchen wählen'); return; }
  $('impgo').disabled = true; $('impres').innerHTML = '';
  const qs = 'src=' + encodeURIComponent(src) + '&path=' + encodeURIComponent(path) + '&save=' + ($('impsave').checked ? 1 : 0) + '&name=' + encodeURIComponent(impName);
  try {
    const r = await api('import/' + impKind + '?' + qs, impText, true);
    const res = await waitJob(r.job, (p, j) => { $('impprog').innerHTML = scanBar(j) + '<div class=hint>' + H(p) + '</div>'; });
    $('impprog').innerHTML = '';
    $('impres').innerHTML = '<p class=okc>' + res.found + ' von ' + res.total + ' Titeln gefunden' + (res.saved ? ' – gespeichert als „' + H(res.saved) + '“' : '') + '.</p>' +
      (res.missing.length ? '<p>Nicht gefunden (' + res.missing.length + '):</p><ul>' + res.missing.slice(0, 300).map(m => '<li>' + H(m) + '</li>').join('') + '</ul>' : '');
    LS.rows.clear(); poll();
  } catch (e) { $('impprog').innerHTML = '<p class=bad>' + H(e.message) + '</p>'; }
  $('impgo').disabled = false;
};
/* keys outside text fields: Space = play/pause, arrows = previous/next tune */
document.addEventListener('keydown', ev => {
  if (ev.target.closest && ev.target.closest('input,select,textarea,dialog') || document.querySelector('section[data-tab=play].off')) return;
  if (ev.key === ' ' && ev.target === document.body) { ev.preventDefault(); $('bplay').click(); }
  else if (ev.key === 'ArrowRight' && ev.target === document.body) ctl('next');
  else if (ev.key === 'ArrowLeft' && ev.target === document.body) ctl('prev');
});

/* small question dialog (prompt() is clumsy on phones) */
function ask(title, value) {
  return new Promise(res => {
    const d = $('askdlg'); $('asktitle').textContent = title; $('askin').value = value || '';
    const done = v => { d.close(); res(v); };
    $('askok').onclick = () => done($('askin').value.trim());
    $('askno').onclick = () => done(null);                  /* cancel: null, an empty answer: '' */
    d.oncancel = () => res(null);
    $('askin').onkeydown = ev => { if (ev.key === 'Enter') done($('askin').value.trim()); };
    d.showModal(); $('askin').focus();
  });
}

/* ---------------------------------------------------------------- sources and files */
const KIND = {smb: ['&#128452;', 'Netzwerkfreigabe'], ftp: ['&#127760;', 'FTP-Server'], u64: ['&#128190;', 'Ultimate-USB'], local: ['&#128204;', 'am Pi']};
let SRC = [], F = {src: '', path: '/', items: [], token: 0, search: null};
async function filesShow() {
  try { SRC = (await api('sources')).sources; } catch (e) { errToast(e); return; }
  srcBar();
  const last = store.get('src', '');
  const s = SRC.find(x => x.id === (F.src || last)) || SRC[0];
  if (s && !F.items.length) openDir(s.id, store.get('path.' + s.id, s.kind === 'u64' ? '/' : '/'));
  else if (!s) { $('flist').innerHTML = ''; $('crumbs').innerHTML = ''; $('fstatus').textContent = 'Noch keine Quelle – oben auf „+ Quelle“ tippen.'; }
}
function srcDesc(s) {
  if (s.kind === 'smb') return '\\\\' + (s.host || '?') + '\\' + (s.share || '');
  if (s.kind === 'ftp') return 'ftp://' + (s.host || '?');
  if (s.kind === 'u64') { const u = S && S.ultimates[s.u64 >= 0 ? s.u64 : S.sel]; return u ? (u.label || u.addr) : 'Ultimate'; }
  return s.path || '/';
}
function srcBar() {
  $('srcbar').innerHTML = SRC.map(s => '<div class="src' + (s.id === F.src ? ' on' : '') + '" data-id="' + H(s.id) + '"><span class=ico>' + KIND[s.kind][0] +
    '</span><div class=meta><div class=sl>' + H(s.label) + '</div><div class=sk>' + H(srcDesc(s)) + '</div></div>' +
    '<button class=ed data-ed="' + H(s.id) + '" title="Bearbeiten" aria-label="Quelle bearbeiten">&#9998;</button></div>').join('') +
    '<div class="src add" id="srcnew">+ Quelle</div>';
}
$('srcbar').onclick = ev => {
  const ed = ev.target.closest('[data-ed]');
  if (ed) { ev.stopPropagation(); srcEdit(SRC.find(s => s.id === ed.dataset.ed)); return; }
  if (ev.target.closest('#srcnew')) { srcEdit(null); return; }
  const c = ev.target.closest('.src');
  if (c) { F.items = []; openDir(c.dataset.id, store.get('path.' + c.dataset.id, '/')); }
};
function crumbs() {
  const parts = F.path.split('/').filter(Boolean), s = SRC.find(x => x.id === F.src);
  let html = '<a href="#" data-p="/">' + H(s ? s.label : '/') + '</a>', acc = '';
  parts.forEach(p => { acc += '/' + p; html += '<span class=sep>›</span><a href="#" data-p="' + H(acc) + '">' + H(p) + '</a>'; });
  if (F.search) html += '<span class=sep>›</span><span>Suche „' + H(F.search) + '“</span> <a href="#" data-p="' + H(F.path) + '">✕</a>';
  $('crumbs').innerHTML = html;
}
$('crumbs').onclick = ev => { const a = ev.target.closest('a[data-p]'); if (a) { ev.preventDefault(); openDir(F.src, a.dataset.p); } };
async function openDir(src, path, keepFilter) {
  const token = ++F.token;
  F.src = src; F.path = path || '/'; F.search = null;
  store.set('src', src); store.set('path.' + src, F.path);
  if (!keepFilter) $('ffilter').value = '';
  srcBar(); crumbs();
  $('fstatus').textContent = 'Lese Ordner …'; $('flist').innerHTML = '';
  try {
    const r = await api('ls?src=' + encodeURIComponent(src) + '&path=' + encodeURIComponent(F.path));
    if (token !== F.token) return;
    F.items = r.items.map(e => Object.assign(e, {p: (F.path === '/' ? '' : F.path) + '/' + e.n}));
    filesRender();
    fetchInfo(token);
  } catch (e) {
    if (token !== F.token) return;
    F.items = [];
    $('fstatus').innerHTML = '<span class=bad>' + H(e.message) + '</span>' + (path !== '/' ? ' <a href="#" onclick="openDir(F.src,\'/\');return false">zum Hauptordner</a>' : '');
  }
}
const isSid = e => !e.d && /\.sid$/i.test(e.n);
const isSl = e => !e.d && (/\.md5$/i.test(e.n) || (/\.txt$/i.test(e.n) && /songlength/i.test(e.n)));
const isStil = e => !e.d && /^stil\.txt$/i.test(e.n);
function visible() {
  const f = $('ffilter').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return F.items.filter(e => {
    if (!e.d && !isSid(e) && !isSl(e) && !isStil(e)) return false;
    if (!f.length) return true;
    const i = e.i || {}, hay = (e.n + ' ' + (i.t || '') + ' ' + (i.a || '') + ' ' + (i.r || '') + ' ' + (F.search ? e.p : '')).toLowerCase();
    return f.every(w => hay.includes(w));
  });
}
function sidLine(e) {
  const i = e.i;
  if (!i) return '<div class=meta><div class=t>' + H(e.n.replace(/\.sid$/i, '')) + '</div><div class=s>' + (e.err ? '<span class=bad>' + H(e.err) + '</span>' : '…') + '</div>' +
    (F.search ? '<div class=f>' + H(e.p) + '</div>' : '') + '</div>';
  const len = i.lens && i.lens[(i.st || 1) - 1];
  const s = [i.a, i.y, i.n > 1 ? i.n + ' Lieder' : '', len ? fmt(len) : ''].filter(Boolean).map(H);
  if (i.c > 1) s.push('<span class=st2>' + i.c + ' SIDs</span>');
  return '<div class=meta><div class=t>' + H(i.t || e.n) + '</div><div class=s>' + s.join(' · ') + '</div><div class=f>' + H(F.search ? e.p : e.n) + '</div></div>';
}
function filesRender() {
  const v = visible(), sids = F.items.filter(isSid).length, dirs = F.items.filter(e => e.d).length;
  $('flist').innerHTML = v.map((e, k) => {
    if (e.d) return '<li class=dir data-k=' + k + '><span class=ico>&#128193;</span><div class=meta><div class=t>' + H(e.n) + '</div></div><span class=chev>›</span></li>';
    if (isStil(e)) return '<li class=other data-k=' + k + '><span class=ico>&#128196;</span><div class=meta><div class=t>' + H(e.n) + '</div><div class=s>Hintergründe zu den Stücken (HVSC)</div></div>' +
      '<button data-stil=1 data-k=' + k + '>als STIL laden</button></li>';
    if (isSl(e)) return '<li class=other data-k=' + k + '><span class=ico>&#128196;</span><div class=meta><div class=t>' + H(e.n) + '</div><div class=s>Songlängen-Datei?</div></div>' +
      '<button data-sl=hvsc data-k=' + k + '>als HVSC-Längen laden</button><button data-sl=custom data-k=' + k + '>als eigene</button></li>';
    return '<li class=sid data-k=' + k + '><span class=ico>&#9835;</span>' + sidLine(e) +
      '<button class=add data-add=' + k + ' title="An die Liste anhängen" aria-label="An die Liste anhängen">+</button><button class=play data-k=' + k + ' title="Abspielen" aria-label="Abspielen">&#9654;</button></li>';
  }).join('');
  F.vis = v;
  const fl = $('ffilter').value.trim();
  $('fstatus').textContent = F.search ? (sids + ' Treffer' + (fl ? ', ' + v.filter(isSid).length + ' nach Filter' : ''))
    : (dirs + ' Ordner, ' + sids + ' SIDs' + (fl ? ' – ' + v.length + ' passen zum Filter' : ''));
  $('fplay').disabled = $('fadd').disabled = !!F.search && !sids;
}
async function fetchInfo(token) {
  const todo = F.items.filter(e => isSid(e) && !e.i);
  for (let k = 0; k < todo.length && token === F.token; k += 20) {
    const part = todo.slice(k, k + 20);
    try {
      const r = await api('info', {src: F.src, paths: part.map(e => e.p)});
      if (token !== F.token) return;
      part.forEach(e => { const i = r.info[e.p]; if (i && !i.err) e.i = i; else if (i) e.err = i.err; });
      filesRender();
    } catch (e) { return; }
  }
}
$('ffilter').oninput = () => filesRender();
$('flist').onclick = ev => {
  const sl = ev.target.closest('[data-sl]'), add = ev.target.closest('[data-add]'), li = ev.target.closest('li');
  if (sl) { ev.stopPropagation(); slLoad(F.vis[+sl.dataset.k], sl.dataset.sl); return; }
  const st = ev.target.closest('[data-stil]');
  if (st) { ev.stopPropagation(); stilLoad(F.vis[+st.dataset.k]); return; }
  if (add) { ev.stopPropagation(); const e = F.vis[+add.dataset.add]; api('queue', {mode: 'add', items: [toItem(e)], play: true}).then(() => { toast('An die Liste angehängt'); poll(); }).catch(errToast); return; }
  if (!li) return;
  const e = F.vis[+li.dataset.k];
  if (e.d) { openDir(F.src, e.p); return; }
  if (isSid(e)) {             // play the tunes shown here, starting with this one
    const list = F.vis.filter(isSid);
    api('queue', {mode: 'replace', items: list.map(toItem), start: list.indexOf(e), play: true})
      .then(() => { toast('▶ ' + ((e.i && e.i.t) || e.n)); poll(); }).catch(errToast);
  }
};
function toItem(e) { const it = {src: F.src, path: e.p, name: e.n}; if (e.i) { it.title = e.i.t; it.author = e.i.a; } return it; }
async function folderGo(mode) {
  if (F.search) {             // search results: take what is shown
    const list = F.vis.filter(isSid);
    if (!list.length) return;
    if ($('fshuf').checked !== !!(S && S.opts.shuffle)) await api('ctl', {c: 'shuffle', on: $('fshuf').checked});
    await api('queue', {mode, items: list.map(toItem), start: 0, play: true}).catch(errToast);
    toast(list.length + ' Titel ' + (mode === 'add' ? 'angehängt' : 'in der Liste')); poll(); return;
  }
  $('fstatus').textContent = 'Sammle SIDs …';
  try {
    const r = await api('folder', {src: F.src, path: F.path, recursive: $('frec').checked, shuffle: $('fshuf').checked, mode});
    const res = await waitJob(r.job, (p, j) => { $('fstatus').textContent = 'Sammle SIDs … ' + p + (j.info && j.info.dir ? ' – liest ' + j.info.dir : ''); });
    toast(res.n + ' Titel ' + (mode === 'add' ? 'angehängt' : 'in der Liste') + (res.trunc ? ' (gekürzt)' : ''));
    filesRender(); poll();
  } catch (e) { $('fstatus').innerHTML = '<span class=bad>' + H(e.message) + '</span>'; }
}
$('fplay').onclick = () => folderGo('replace');
$('fadd').onclick = () => folderGo('add');
$('fsearch').onclick = async () => {
  const q = $('ffilter').value.trim();
  if (q.length < 2) { toast('Erst oben ins Filterfeld schreiben, wonach gesucht wird'); $('ffilter').focus(); return; }
  const token = ++F.token;
  $('fstatus').textContent = 'Suche …'; $('flist').innerHTML = '';
  try {
    const r = await api('search', {src: F.src, path: F.path, q});
    const res = await waitJob(r.job, (p, j) => { if (token === F.token) $('fstatus').textContent = 'Suche … ' + p + (j.info && j.info.dir ? ' – durchsucht ' + j.info.dir : ''); });
    if (token !== F.token) return;
    F.search = q; F.items = res; $('ffilter').value = '';
    crumbs(); filesRender(); fetchInfo(token);
  } catch (e) { $('fstatus').innerHTML = '<span class=bad>' + H(e.message) + '</span>'; }
};
async function stilLoad(e) {
  $('fstatus').textContent = 'Lese STIL …';
  try {
    const r = await api('stil/load', {src: F.src, path: e.p});
    const res = await waitJob(r.job, p => { $('fstatus').textContent = 'STIL: ' + p; });
    toast(res.n + ' STIL-Einträge geladen'); $('fstatus').textContent = res.n + ' STIL-Einträge geladen'; poll();
  } catch (err) { $('fstatus').innerHTML = '<span class=bad>' + H(err.message) + '</span>'; }
}
async function slLoad(e, kind) {
  $('fstatus').textContent = 'Lese Songlängen …';
  try {
    const r = await api('songlengths/load', {src: F.src, path: e.p, kind});
    const res = await waitJob(r.job, p => { $('fstatus').textContent = 'Songlängen: ' + p; });
    toast(res.n + ' Songlängen geladen'); $('fstatus').textContent = res.n + ' Songlängen geladen';
    F.items.forEach(x => { delete x.i; }); fetchInfo(F.token);
  } catch (err) { $('fstatus').innerHTML = '<span class=bad>' + H(err.message) + '</span>'; }
}

/* source editor */
let editing = null;
function srcEdit(s) {
  editing = s;
  const d = $('srcdlg');
  $('sdtitle').textContent = s ? 'Quelle bearbeiten' : 'Neue Quelle';
  $('sk').value = s ? s.kind : 'smb';
  $('sl').value = s ? s.label : ''; $('sh').value = s ? s.host || '' : ''; $('ss').value = s ? s.share || '' : '';
  $('su').value = s ? s.user || '' : ''; $('sw').value = s ? s.pw || '' : ''; $('sp').value = s ? s.port || 21 : 21;
  $('sd').value = s ? s.path || '/' : '/';
  $('sx').innerHTML = '<option value=-1>das gerade gewählte</option>' + (S ? S.ultimates : []).map((u, i) => '<option value=' + i + '>' + H(u.label || u.addr) + '</option>').join('');
  $('sx').value = s && s.u64 != null ? s.u64 : -1;
  $('sdel').hidden = !s; $('smsg').textContent = ''; $('sscanres').innerHTML = ''; $('sshareres').innerHTML = '';
  $('sscanst').textContent = ''; $('ssharest').textContent = ''; $('sscanprog').innerHTML = '';
  d.dataset.k = $('sk').value;
  if (!s) $('sd').value = '/';
  d.showModal();
}
$('sk').onchange = () => {
  const k = $('sk').value; $('srcdlg').dataset.k = k;
  if (k === 'local' && (!$('sd').value || $('sd').value === '/')) $('sd').value = '/media/usb';
  if (k === 'u64' && $('sd').value === '/media/usb') $('sd').value = '/';
};
function srcForm() {
  const k = $('sk').value, s = {kind: k, label: $('sl').value.trim(), path: $('sd').value.trim() || '/'};
  if (editing) s.id = editing.id;
  if (k === 'smb' || k === 'ftp') { s.host = $('sh').value.trim().replace(/^(smb|ftp):\/\//i, '').replace(/^\\\\/, '').replace(/[\/\\].*$/, ''); s.user = $('su').value.trim(); s.pw = $('sw').value; }
  if (k === 'smb') s.share = $('ss').value.trim().replace(/^[\/\\]+|[\/\\]+$/g, '');
  if (k === 'ftp' || k === 'u64') s.port = +$('sp').value || 21;
  if (k === 'u64') { s.u64 = +$('sx').value; if (s.port === 21) delete s.port; }
  if (!s.label) s.label = k === 'smb' ? (s.share || s.host || 'Freigabe') : k === 'ftp' ? (s.host || 'FTP') : k === 'u64' ? 'USB-Stick am Ultimate' : 'Ordner am Pi';
  return s;
}
$('scancel').onclick = () => $('srcdlg').close();
$('ssave').onclick = async () => {
  const s = srcForm();
  if ((s.kind === 'smb' || s.kind === 'ftp') && !s.host) { $('smsg').textContent = 'Bitte einen Server eintragen.'; return; }
  if (s.kind === 'smb' && !s.share) { $('smsg').textContent = 'Bitte eine Freigabe wählen („Freigaben anzeigen“).'; return; }
  const list = SRC.map(x => x.id === s.id ? s : x);
  if (!editing) list.push(s);
  try {
    SRC = (await api('sources', {sources: list})).sources;
    $('srcdlg').close();
    const id = editing ? editing.id : SRC[SRC.length - 1].id;
    F.items = []; openDir(id, editing && editing.path === s.path ? store.get('path.' + id, '/') : '/');
  } catch (e) { $('smsg').textContent = e.message; }
};
$('sdel').onclick = async () => {
  if (!editing || !confirm('Quelle „' + editing.label + '“ löschen? (Die Dateien selbst bleiben, wo sie sind.)')) return;
  try {
    SRC = (await api('sources', {sources: SRC.filter(x => x.id !== editing.id)})).sources;
    $('srcdlg').close(); if (F.src === editing.id) { F.src = ''; F.items = []; }
    filesShow();
  } catch (e) { $('smsg').textContent = e.message; }
};
$('stest').onclick = async () => {
  $('smsg').textContent = 'Teste …';
  try { $('smsg').innerHTML = '<span class=okc>' + H((await api('sources/test', {source: srcForm()})).msg) + '</span>'; }
  catch (e) { $('smsg').textContent = e.message; }
};
$('sscan').onclick = async () => {
  const k = $('sk').value;
  $('sscanst').textContent = 'Suche im Netz …'; $('sscanres').innerHTML = '';
  const want = k === 'smb' ? /SMB/ : /FTP/;
  try {
    const r = await api('scan', {});
    const hosts = await waitJob(r.job, (p, j) => { $('sscanst').textContent = ''; $('sscanprog').innerHTML = scanHtml(j, want); });
    $('sscanprog').innerHTML = '';
    const fit = hosts.filter(h => k === 'smb' ? h.smb : h.ftp);
    $('sscanst').textContent = fit.length ? 'Gefunden – antippen zum Übernehmen:' : 'Nichts gefunden' + (k === 'smb' ? ' (SMB, Port 445).' : ' (FTP, Port 21).');
    $('sscanres').innerHTML = fit.map(h => '<button type=button data-h="' + H(h.host || h.ip) + '" data-n="' + H(h.name || '') + '">' +
      H(h.name || h.ip) + (h.name ? ' <span class=hint>' + H(h.ip) + '</span>' : '') + (h.u64 ? ' <span class=hint>(' + H(h.u64.product) + ')</span>' : '') + '</button>').join('');
  } catch (e) { $('sscanprog').innerHTML = ''; $('sscanst').textContent = e.message; }
};
$('sscanres').onclick = ev => {
  const b = ev.target.closest('button'); if (!b) return;
  $('sh').value = b.dataset.h;
  if (!$('sl').value) $('sl').value = b.dataset.n ? b.dataset.n.split('.')[0] : b.dataset.h;
  $('sscanres').innerHTML = ''; $('sscanst').textContent = '';
  if ($('sk').value === 'smb') $('sshares').click();
};
$('sshares').onclick = async () => {
  const host = $('sh').value.trim();
  if (!host) { $('ssharest').textContent = 'Erst den Server eintragen.'; return; }
  $('ssharest').textContent = 'Frage ' + host + ' …'; $('sshareres').innerHTML = '';
  try {
    const r = await api('shares', {host, user: $('su').value.trim(), pw: $('sw').value, id: editing ? editing.id : ''});
    $('ssharest').textContent = r.shares.length ? 'Freigaben – antippen:' : 'Keine Freigaben sichtbar (Benutzer/Passwort nötig?)';
    $('sshareres').innerHTML = r.shares.map(s => '<button type=button data-s="' + H(s.name) + '">' + H(s.name) + (s.comment ? ' <span class=hint>' + H(s.comment) + '</span>' : '') + '</button>').join('');
  } catch (e) { $('ssharest').textContent = e.message; }
};
$('sshareres').onclick = ev => {
  const b = ev.target.closest('button'); if (!b) return;
  $('ss').value = b.dataset.s; if (!editing || !$('sl').value) $('sl').value = b.dataset.s;
  $('sshareres').innerHTML = ''; $('ssharest').textContent = '';
};

/* ---------------------------------------------------------------- saved play lists */
async function statsLoad() {
  try {
    const s = await api('statistics');
    const max = s.top.length ? s.top[0][1] : 1;
    $('statbox').innerHTML = '<p>' + s.plays + ' Starts von ' + s.tunes + ' verschiedenen Titeln · ' + s.favs + ' Favoriten · gehört etwa ' +
      fmtLong(s.listened) + ' (Titel der Liste mit bekannter Länge)</p>' +
      (s.top.length ? '<h4>Meistgespielte Komponisten</h4>' + s.top.map(([a, n]) => '<div class=bar><span>' + H(a) + '</span><i style="width:' +
        Math.max(4, 100 * n / max) + '%"></i><b>' + n + '</b></div>').join('') : '<p class=hint>Noch nichts gespielt.</p>') +
      '<h4>Titel der Liste nach SIDs</h4><p>1 SID: ' + s.chips[1] + ' · 2 SIDs: ' + s.chips[2] + ' · 3 SIDs: ' + s.chips[3] + '</p>';
  } catch (e) { $('statbox').textContent = e.message; }
}
/* the last tunes played (newest first): again at the end of the list, as the next one, or all as a new list */
let HIST = [];
function histWhen(t, now) {
  const d = new Date(t * 1000), today = new Date(now * 1000).toDateString() === d.toDateString();
  const hm = d.toLocaleTimeString('de-DE', {hour: '2-digit', minute: '2-digit'});
  return today ? hm : d.toLocaleDateString('de-DE', {day: '2-digit', month: '2-digit'}) + ' ' + hm;
}
async function histLoad() {
  try {
    const r = await api('history');
    HIST = r.items;
    $('hist').innerHTML = HIST.slice(0, 50).map((e, k) => '<li data-k=' + k + '><span class="hint htime">' + histWhen(e.t, r.now) + '</span>' +
      '<div class=meta><div class=t>' + H(e.title || e.name) + '</div><div class=s>' + H([e.author, e.songs > 1 ? 'Lied ' + e.song + '/' + e.songs : ''].filter(Boolean).join(' · ')) + '</div></div>' +
      '<button data-a=next title="Als Nächstes spielen">&#9654;</button><button data-a=add title="Hinten anhängen">+</button></li>').join('') ||
      '<li class=hint>Noch nichts gespielt.</li>';
    $('histall').disabled = $('histclr').disabled = !HIST.length;
  } catch (e) { errToast(e); }
}
const histItem = e => ({src: e.src, path: e.path, name: e.name, title: e.title, author: e.author, song: e.song, md5: e.md5});
$('hist').onclick = async ev => {
  const b = ev.target.closest('button'), li = ev.target.closest('li[data-k]');
  if (!b || !li) return;
  const e = HIST[+li.dataset.k];
  try {
    await api('queue', {mode: b.dataset.a === 'next' ? 'next' : 'add', items: [histItem(e)], play: true});
    toast(b.dataset.a === 'next' ? 'Kommt als Nächstes' : 'An die Liste angehängt'); poll();
  } catch (err) { errToast(err); }
};
$('histall').onclick = async () => {
  const seen = new Set(), items = [];
  for (const e of HIST.slice().reverse()) {                /* in the order they played, each once */
    const k = e.src + '\n' + e.path + '\n' + e.song;
    if (!seen.has(k)) { seen.add(k); items.push(histItem(e)); }
  }
  if (!confirm('Die aktuelle Wiedergabeliste durch die ' + items.length + ' zuletzt gespielten Titel ersetzen?')) return;
  try { await api('queue', {mode: 'replace', items, play: false, source: 'Zuletzt gespielt'}); toast(items.length + ' Titel übernommen'); poll(); tab('play'); }
  catch (e) { errToast(e); }
};
$('histclr').onclick = async () => {
  if (!confirm('Verlauf löschen?')) return;
  try { await api('history/clear', {}); histLoad(); } catch (e) { errToast(e); }
};
/* lists put together from the HVSC (Songlengths.md5), the play counts and the favourites */
async function smLoad() {
  try {
    const r = await api('smart');
    $('smpre').innerHTML = Object.entries(r.presets).map(([k, v]) => '<button type="button" data-pre="' + k + '">' + H(v) + '</button>').join('');
    $('smstate').textContent = r.hvsc ? r.hvsc.toLocaleString('de-DE') + ' Stücke der HVSC bekannt (' + r.root + ') · ' + r.favs + ' Favoriten · Tippen spielt die Auswahl'
      : 'Für die HVSC-Auswahl zuerst die Songlängen der HVSC aus einer Quelle laden (Tab „Dateien“) · ' + r.favs + ' Favoriten';
  } catch (e) { $('smstate').textContent = e.message; }
}
function smFilter() {
  return {area: $('smarea').value, text: $('smtext').value.trim(), min_s: (+$('smmin').value || 0) * 60, max_s: (+$('smmax').value || 0) * 60,
    sids: $('smmulti').checked ? 'multi' : '', stil: $('smstil').checked, never: $('smnever').checked, sort: $('smsort').value, n: +$('smn').value || 50};
}
async function smRun(filter, mode, name) {
  try {
    const r = await api('smart', {filter, mode, name: name || ''});
    toast(r.n + ' Titel ' + (mode === 'add' ? 'angehängt' : mode === 'save' ? 'als Liste „' + name + '“ gespeichert' : 'in der Liste'));
    poll(); if (mode === 'save') plsLoad(); else if (mode === 'play') tab('play');
  } catch (e) { errToast(e); }
}
$('smpre').onclick = ev => { const b = ev.target.closest('[data-pre]'); if (b) smRun({preset: b.dataset.pre}, 'play'); };
$('smplay').onclick = () => smRun(smFilter(), 'play');
$('smadd').onclick = () => smRun(smFilter(), 'add');
$('smsave').onclick = async () => {
  const name = await ask('Name der neuen Liste', $('smtext').value.trim() || 'Zusammengestellt');
  if (name) smRun(smFilter(), 'save', name);
};
async function plsLoad() {
  statsLoad(); histLoad(); smLoad();
  try {
    const r = await api('playlists');
    $('pls').innerHTML = r.lists.map(p => '<li data-n="' + H(p.name) + '"><div class=meta><div class=t>' + H(p.name) + '</div><div class=s>' + p.n + ' Titel' +
      (p.saved ? ' · ' + H(p.saved) : '') + '</div></div><button data-a=load title="Laden und abspielen">&#9654; Laden</button><button data-a=add title="Hinten anhängen">+</button>' +
      '<button data-a=exp title="Für die PC-Jukebox exportieren (.json)">&#8599;</button>' +
      '<button data-a=ren title="Umbenennen" aria-label="Umbenennen">&#9998;</button>' +
      '<button data-a=del class=danger title="Löschen" aria-label="Löschen">&#128465;</button></li>').join('') || '<li class=hint>Noch keine Listen gespeichert.</li>';
  } catch (e) { errToast(e); }
}
$('pls').onclick = async ev => {
  const b = ev.target.closest('button'), li = ev.target.closest('li[data-n]');
  if (!li) return;
  const name = li.dataset.n, a = b ? b.dataset.a : 'load';
  try {
    if (a === 'del') { if (!confirm('Liste „' + name + '“ löschen?')) return; await api('playlist/delete', {name}); plsLoad(); return; }
    if (a === 'exp') { exportShared(name); return; }
    if (a === 'ren') {
      const nn = await ask('Neuer Name der Liste', name);
      if (nn && nn.trim() && nn.trim() !== name) { await api('playlist/rename', {name, new: nn.trim()}); toast('Umbenannt'); plsLoad(); }
      return;
    }
    const r = await api('playlist/load', {name, mode: a === 'add' ? 'add' : 'replace', play: true});
    store.set('plname', name);
    toast(r.n + ' Titel ' + (a === 'add' ? 'angehängt' : 'geladen')); poll(); if (a !== 'add') tab('play');
  } catch (e) { errToast(e); }
};

/* ---------------------------------------------------------------- devices */
let CFG = null;
async function devShow() {
  try { CFG = await api('config'); } catch (e) { errToast(e); return; }
  u64Rows(); picoRows(); stShow(); devLoad();
  $('pname').value = CFG.name;
}
/* tab "Anzeige": the TV (HDMI) and the small display on the Pi */
async function showShow() {
  try { CFG = await api('config'); } catch (e) { errToast(e); return; }
  dispShow(); hdmiShow();
}
/* the HDMI output (service c64pi-hdmi): every change is taken over at once */
let HD = null;
async function hdmiShow() {
  try { HD = await api('hdmi'); } catch (e) { return; }
  const c = HD.cfg;
  if (!$('hmode').options.length) {
    $('hmode').innerHTML = Object.entries(HD.modes).map(([k, v]) => '<option value="' + k + '">' + H(v) + '</option>').join('');
    $('hautomodes').innerHTML = Object.entries(HD.modes).filter(([k]) => k !== 'none').map(([k, v]) =>
      '<label class="chip"><input type="checkbox" value="' + k + '"> ' + H(v) + '</label>').join('');
  }
  $('hon').checked = c.on; $('hmode').value = c.mode; $('hbg').value = c.bg;
  if (!hdTimer.op) { $('hop').value = c.opacity; $('hopv').textContent = c.opacity + ' %'; }   /* a slider being moved keeps its value until saved */
  if (!hdTimer.vol) { $('hvol').value = c.volume != null ? c.volume : 100; $('hvolv').textContent = $('hvol').value + ' %'; }
  $('hosd').checked = c.osd; $('himgs').value = c.img_s;
  $('hshuf').checked = c.shuffle; $('hauto').checked = c.auto; $('hautos').value = c.auto_s; $('hsound').checked = !!c.sound;
  $('hfade').checked = !!c.fade; $('hfades').value = c.fade_s; $('hfade').disabled = $('hfades').disabled = !c.sound;
  $('hautomodes').querySelectorAll('input').forEach(i => { i.checked = c.auto_modes.includes(i.value); });
  $('hstil').checked = c.osd_stil !== false;
  $('hqr').checked = c.osd_qr !== false;
  $('hbig').checked = c.osd_big !== false; $('hbigs').value = c.osd_big_s || 6;
  $('hidle').checked = c.idle_hide !== false; $('hidles').value = c.idle_s || 20;
  $('nidle').checked = !!c.news_idle; $('nticker').checked = !!c.news_ticker; $('nevery').value = c.news_s || 15;
  if (!NF.dirty) newsRows((HD.news || {}).feeds || []);
  newsState(HD.news);
  $('himgbox').hidden = c.bg !== 'images';
  const srcs = (CFG && CFG.sources) || [], cur = srcs.find(s => s.id === c.img_src);
  $('hsrc').value = c.img_src ? '*' : ''; $('hsub').checked = !!c.img_sub;
  $('hfolder').textContent = cur ? cur.label + (c.img_path && c.img_path !== '/' ? ' › ' + c.img_path.split('/').filter(Boolean).join(' › ') : '') : '';
  $('hsrcbox').hidden = !c.img_src; $('hupbox').hidden = !!c.img_src;
  hdmiSyncShow(HD.sync, HD.src_images);
  hdmiImages(HD.images);
  hdmiState();
  cecShow();
}
/* the TV's remote control (HDMI-CEC) */
function cecShow() {
  const c = HD.cec || {}, s = c.status || {};
  $('con').checked = !!c.on; $('cecbox').hidden = !c.on;
  $('ctvon').checked = !!c.tv_on; $('cclaim').checked = c.claim !== false;
  if (document.activeElement !== $('ctvoff')) $('ctvoff').value = c.tv_off_min || 0;
  $('ctvnow').disabled = $('ctvsb').disabled = !s.ready;
  let t = '';
  if (c.on) {
    if (s.err) t = '<span class=warn>' + H(s.err) + '</span>';
    else if (!s.ready) t = 'Warte auf den Fernseher … (eingeschaltet und am HDMI-Kabel?)';
    else t = '<span class=okc>bereit</span> · Adresse ' + H(s.phys || '?') + (s.active ? ' · der Fernseher zeigt den Pi' : '') +
      ((s.recent || []).length ? ' · zuletzt: ' + H(s.recent.slice(-4).join(', ')) : '');
  }
  $('cecstate').innerHTML = t;
}
async function cecSave(d) {
  try { const r = await api('cec', d); HD.cec = r.cec; cecShow(); toast('Übernommen'); } catch (e) { errToast(e); }
}
$('con').onchange = () => cecSave({on: $('con').checked});
$('ctvon').onchange = () => cecSave({tv_on: $('ctvon').checked});
$('cclaim').onchange = () => cecSave({claim: $('cclaim').checked});
$('ctvoff').onchange = () => cecSave({tv_off_min: +$('ctvoff').value || 0});
$('ctvnow').onclick = () => cecSave({tv: 'on'});
$('ctvsb').onclick = () => cecSave({tv: 'standby'});
function hdmiState() {
  const s = HD.status || {}, c = HD.cfg;
  let t;
  if (!c.on) t = 'aus – am HDMI-Ausgang steht die Textanzeige des Pi';
  else if (s.age == null || s.age > 10) t = '<span class=warn>Der HDMI-Dienst meldet sich nicht</span> (läuft er? <code>systemctl status c64pi-hdmi</code>)';
  else {
    t = '<span class=okc>läuft</span>, ' + s.fps + ' Bilder/s' + (s.screen ? ' · ' + H(s.screen) : '');
    t += s.audio_age != null && s.audio_age < 2 ? ' · Ton kommt an' : ' · <span class=warn>kein Ton</span> (Stream-Verteiler/Ultimate)';
    if (c.bg === 'video') t += s.video_age != null && s.video_age < 2 ? ' · Bild des C64 kommt an' : ' · <span class=warn>kein Bild vom C64</span>' + (s.video_msg ? ' (' + H(s.video_msg) + ')' : '');
    if (s.sid_want) t += s.sid_age != null && s.sid_age < 2 ? ' · SID-Daten kommen an' + (s.sid && s.sid.chips.length ? ' (' + H(s.sid.chips.join(', ')) + ')' : '')
      : ' · <span class=warn>keine SID-Daten vom Ultimate</span>' + (s.sid_msg ? ' (' + H(s.sid_msg) + ')' : '');
    else if (s.mode === 'sidvoices' && c.bg === 'video') t += ' · <span class=warn>SID-Stimmen gehen nicht zusammen mit dem C64-Bild</span>';
    if (c.sound) t += s.sound ? ' · Ton über HDMI' : ' · <span class=warn>Ton über HDMI startet nicht</span>' + (s.sound_msg ? ' (' + H(s.sound_msg) + ')' : '');
    if (s.msg) t += ' · ' + H(s.msg);
  }
  $('hstate').innerHTML = t;
}
function hdmiSyncShow(job, n) {
  let t = n + ' Bild' + (n === 1 ? '' : 'er') + ' von der Quelle übernommen';
  if (job && !job.done) t = 'gleicht ab … ' + H(job.progress || '');
  else if (job && job.error) t = '<span class=warn>' + H(job.error) + '</span>';
  else if (job && job.progress) t = H(job.progress);
  $('hsyncmsg').innerHTML = t + ' · alle 10 min wird erneut abgeglichen';
}
async function hdmiSyncWatch(id) {
  try { await waitJob(id, (p, j) => hdmiSyncShow(j, 0)); } catch (e) { errToast(e); }
  hdmiShow();
}
function hdmiImages(list) {
  $('hlist').innerHTML = list.length ? list.map(i => '<figure><img loading="lazy" alt="" src="/api/hdmi/image?name=' +
    encodeURIComponent(i.name) + '"><figcaption>' + H(i.name) + '</figcaption><button class="danger" data-n="' + H(i.name) +
    '" title="Löschen" aria-label="Löschen">&#10005;</button></figure>').join('') : '<p class="hint">Noch keine Bilder.</p>';
}
const hdTimer = {op: null, vol: null};        /* one per slider: one must not cancel the other's save */
async function hdmiSave(d) {
  try {
    const r = await api('hdmi', d);
    HD.cfg = r.cfg; hdmiShow(); toast('Übernommen');
    if (r.job) hdmiSyncWatch(r.job);
  } catch (e) { errToast(e); }
}
['hon', 'hmode', 'hbg', 'hosd', 'hshuf', 'hauto', 'hsound', 'hfade'].forEach(id => {
  $(id).onchange = () => {
    const k = {hon: 'on', hmode: 'mode', hbg: 'bg', hosd: 'osd', hshuf: 'shuffle', hauto: 'auto', hsound: 'sound', hfade: 'fade'}[id];
    hdmiSave({[k]: $(id).type === 'checkbox' ? $(id).checked : $(id).value});
  };
});
$('hop').oninput = () => {
  $('hopv').textContent = $('hop').value + ' %';
  const v = +$('hop').value;
  clearTimeout(hdTimer.op); hdTimer.op = setTimeout(() => { hdTimer.op = null; hdmiSave({opacity: v}); }, 400);
};
$('himgs').onchange = () => hdmiSave({img_s: +$('himgs').value || 20});
$('hfades').onchange = () => hdmiSave({fade_s: +$('hfades').value || 2});
$('hvol').oninput = () => {
  $('hvolv').textContent = $('hvol').value + ' %';
  const v = +$('hvol').value;
  clearTimeout(hdTimer.vol); hdTimer.vol = setTimeout(() => { hdTimer.vol = null; hdmiSave({volume: v}); }, 300);
};
$('hsrc').onchange = () => {
  if ($('hsrc').value === '*') { $('hsrc').value = HD.cfg.img_src ? '*' : ''; picOpen(); }
  else hdmiSave({img_src: ''});
};
$('hsub').onchange = () => hdmiSave({img_sub: $('hsub').checked});
$('hidle').onchange = () => hdmiSave({idle_hide: $('hidle').checked});
$('hstil').onchange = () => hdmiSave({osd_stil: $('hstil').checked});
$('hbig').onchange = () => hdmiSave({osd_big: $('hbig').checked});
$('hqr').onchange = () => hdmiSave({osd_qr: $('hqr').checked});
$('hbigs').onchange = () => hdmiSave({osd_big_s: +$('hbigs').value || 6});
$('hidles').onchange = () => hdmiSave({idle_s: +$('hidles').value || 20});
$('nidle').onchange = () => hdmiSave({news_idle: $('nidle').checked});
$('nticker').onchange = () => hdmiSave({news_ticker: $('nticker').checked});
$('nevery').onchange = () => hdmiSave({news_s: +$('nevery').value || 15});
/* retro news: the feeds as rows (name, address), saved together */
const NF = {dirty: false};
function newsRows(feeds) {
  $('nfeeds').innerHTML = feeds.map(f => '<div class="erow nrow"><input type=checkbox class=non' + (f.on !== false ? ' checked' : '') +
    ' title="anzeigen" aria-label="anzeigen"><input class=nl placeholder="Name" value="' + H(f.label || '') +
    '" aria-label="Name"><input class=nu placeholder="https://…/rss.xml" value="' + H(f.url || '') + '" aria-label="Adresse" autocapitalize=off>' +
    '<span class="hint nfs">' + (f.on === false ? 'aus' : f.err ? '<span class=warn>' + H(f.err) + '</span>' : f.n != null ? f.n + ' Meldungen' : '') + '</span>' +
    '<div class=eend><button class="danger nx" type=button title="Entfernen" aria-label="Entfernen">&#10005;</button></div></div>').join('');
}
function newsState(n) {
  if (!n) return;
  const on = $('nidle').checked || $('nticker').checked;
  $('nstate').textContent = n.busy ? 'lädt …' : on ? n.n + ' Meldungen geladen' + (n.default ? ' (Standard-Quellen)' : '') + ' · alle 30 min neu'
    : 'aus – zum Einschalten einen Haken setzen';
}
function newsCollect() {
  return [...$('nfeeds').querySelectorAll('.nrow')].map(r => ({on: r.querySelector('.non').checked,
    label: r.querySelector('.nl').value.trim(), url: r.querySelector('.nu').value.trim()}));
}
$('nfeeds').oninput = ev => { if (!ev.target.classList.contains('non')) NF.dirty = true; };
$('nfeeds').onchange = ev => {                      /* a tick takes effect at once */
  if (ev.target.classList.contains('non')) { NF.dirty = false; hdmiSave({news_feeds: newsCollect().filter(f => f.url)}); }
};
$('nfeeds').onclick = ev => { const x = ev.target.closest('.nx'); if (x) { x.closest('.nrow').remove(); NF.dirty = true; } };
$('nadd').onclick = () => {
  newsRows(newsCollect().concat([{label: '', url: '', on: true}])); NF.dirty = true;
  $('nfeeds').querySelector('.nrow:last-child .nl').focus();
};
$('nsave').onclick = async () => {
  NF.dirty = false; await hdmiSave({news_feeds: newsCollect().filter(f => f.url)});
};
$('ndefault').onclick = async () => { NF.dirty = false; await hdmiSave({news_feeds: []}); };
$('nload').onclick = async () => {
  $('nstate').textContent = 'lädt … (bis 30 s)';
  try { const r = await api('hdmi/news', {}); HD.news = r.news; NF.dirty = false; newsRows(r.news.feeds); newsState(r.news); }
  catch (e) { errToast(e); }
};
$('hpick').onclick = () => picOpen();
/* the folder picker for the pictures: sources as tiles, folders, filter, previews - like the "Dateien" tab */
const isPic = e => !e.d && /\.(jpe?g|png)$/i.test(e.n);
let P = {src: '', path: '/', items: [], token: 0};
async function picOpen() {
  try { SRC = (await api('sources')).sources; } catch (e) { errToast(e); return; }
  if (!SRC.length) { toast('Noch keine Quelle – im Tab „Dateien“ oben „+ Quelle“ anlegen'); return; }
  const c = HD.cfg, s = SRC.find(x => x.id === (c.img_src || store.get('picsrc', ''))) || SRC[0];
  $('picsub').checked = !!c.img_sub; $('picfilter').value = '';
  $('picdlg').showModal();
  picDir(s.id, s.id === c.img_src ? c.img_path : store.get('picpath.' + s.id, '/'));
}
async function picDir(src, path) {
  const token = ++P.token;
  P.src = src; P.path = path || '/';
  store.set('picsrc', src); store.set('picpath.' + src, P.path);
  $('picsrc').innerHTML = SRC.map(s => '<div class="src' + (s.id === src ? ' on' : '') + '" data-id="' + H(s.id) + '"><span class=ico>' +
    KIND[s.kind][0] + '</span><div class=meta><div class=sl>' + H(s.label) + '</div><div class=sk>' + H(srcDesc(s)) + '</div></div></div>').join('');
  const parts = P.path.split('/').filter(Boolean), s = SRC.find(x => x.id === src);
  let html = '<a href="#" data-p="/">' + H(s ? s.label : '/') + '</a>', acc = '';
  parts.forEach(p => { acc += '/' + p; html += '<span class=sep>›</span><a href="#" data-p="' + H(acc) + '">' + H(p) + '</a>'; });
  $('piccrumbs').innerHTML = html;
  $('picstatus').textContent = 'Lese Ordner …'; $('piclist').innerHTML = '';
  try {
    const r = await api('ls?src=' + encodeURIComponent(src) + '&path=' + encodeURIComponent(P.path));
    if (token !== P.token) return;
    P.items = r.items.filter(e => e.d || isPic(e)).map(e => Object.assign(e, {p: (P.path === '/' ? '' : P.path) + '/' + e.n}));
    picRender();
  } catch (e) {
    if (token !== P.token) return;
    P.items = []; $('picstatus').innerHTML = '<span class=bad>' + H(e.message) + '</span>';
  }
}
function picRender() {
  const f = $('picfilter').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const v = P.items.filter(e => f.every(w => e.n.toLowerCase().includes(w)));
  const pics = P.items.filter(isPic).length, dirs = P.items.filter(e => e.d).length;
  $('picstatus').textContent = pics + ' Bild' + (pics === 1 ? '' : 'er') + (dirs ? ', ' + dirs + ' Ordner' : '') +
    (v.length < P.items.length ? ' – ' + v.length + ' passen zum Filter' : '') + (pics ? '' : ' – in diesem Ordner liegen keine Bilder');
  $('piclist').innerHTML = v.map((e, k) => e.d
    ? '<li class=dir data-p="' + H(e.p) + '"><span class=ico>&#128193;</span><div class=meta><div class=t>' + H(e.n) + '</div></div><span class=chev>›</span></li>'
    : '<li class=img><img loading=lazy alt="" src="/api/hdmi/thumb?src=' + encodeURIComponent(P.src) + '&path=' + encodeURIComponent(e.p) +
      '"><div class=meta><div class=t>' + H(e.n) + '</div><div class=s>' + (e.s ? Math.round(e.s / 1024) + ' KB' : '') + '</div></div></li>').join('');
}
$('picsrc').onclick = ev => { const c = ev.target.closest('.src'); if (c) picDir(c.dataset.id, store.get('picpath.' + c.dataset.id, '/')); };
$('piccrumbs').onclick = ev => { const a = ev.target.closest('a[data-p]'); if (a) { ev.preventDefault(); picDir(P.src, a.dataset.p); } };
$('piclist').onclick = ev => { const li = ev.target.closest('li.dir'); if (li) { $('picfilter').value = ''; picDir(P.src, li.dataset.p); } };
$('picfilter').oninput = () => picRender();
$('picno').onclick = () => $('picdlg').close();
$('picok').onclick = () => { $('picdlg').close(); hdmiSave({img_src: P.src, img_path: P.path, img_sub: $('picsub').checked}); };
$('hsync').onclick = async () => {
  try { const r = await api('hdmi/sync', {}); hdmiSyncWatch(r.job); } catch (e) { errToast(e); }
};
$('hautos').onchange = () => hdmiSave({auto_s: +$('hautos').value || 180});
$('hautomodes').onchange = () => hdmiSave({auto_modes: [...$('hautomodes').querySelectorAll('input:checked')].map(i => i.value)});
$('hfiles').onchange = async () => {
  const files = [...$('hfiles').files];
  let n = 0;
  for (const f of files) {
    $('hupmsg').textContent = 'lade hoch … ' + (n + 1) + ' von ' + files.length;
    try { const r = await api('hdmi/upload?name=' + encodeURIComponent(f.name), await f.arrayBuffer(), true); hdmiImages(r.images); n++; }
    catch (e) { errToast(e); }
  }
  $('hupmsg').textContent = n + ' Bild' + (n === 1 ? '' : 'er') + ' hochgeladen';
  $('hfiles').value = '';
};
$('hlist').onclick = async ev => {
  const b = ev.target.closest('button[data-n]'); if (!b) return;
  if (!confirm('Bild „' + b.dataset.n + '“ löschen?')) return;
  try { hdmiImages((await api('hdmi/delete', {name: b.dataset.n})).images); } catch (e) { errToast(e); }
};
setInterval(async () => {
  if (!HD || document.hidden || !$('hcard').offsetParent) return;
  try { const r = await api('hdmi'); HD.status = r.status; HD.cec = r.cec; hdmiState(); cecShow(); } catch (e) { /* next time */ }
}, 3000);
/* the Pi's network (service c64pi-net) and its display */
let NET = null;
/* party mode: the Pi's access point under the home WLAN's name, the Ultimate on its cable */
async function partyShow() {
  try {
    const p = await api('party');
    $('pon').checked = p.on;
    if (document.activeElement !== $('pssid')) $('pssid').value = p.ssid;
    $('psaved').innerHTML = p.saved.map(s => '<option value="' + H(s) + '">').join('');
    $('ppw').placeholder = p.pw_set ? 'gespeichert (leer lassen)' : 'leer = das im Pi gespeicherte';
    const s = p.state || {};
    $('pstate').innerHTML = !p.on ? '' : s.state === 'aktiv'
      ? '<span class=okc>läuft</span>: WLAN „' + H(s.ssid) + '“, Seite unter http://' + H(s.ap_ip) + '/' +
        (s.eth ? ' · Ultimate am Kabel: ' + H(s.u64) : ' · am Kabel noch kein Ultimate (es dauert 40 s nach dem Einstecken)')
      : s.state === 'fehler' ? '<span class=warn>' + H(s.why) + '</span>'
      : 'wartet' + (s.why ? ': ' + H(s.why) : '') + ' – zu Hause bleibt er still';
  } catch (e) { $('pstate').textContent = e.message; }
}
$('psave2').onclick = async () => {
  try {
    await api('party', {on: $('pon').checked, ssid: $('pssid').value.trim(), pw: $('ppw').value});
    $('ppw').value = ''; toast('Party-Modus gespeichert'); partyShow();
  } catch (e) { errToast(e); }
};
async function netShow() {
  partyShow();
  try { NET = await api('wlan'); } catch (e) { NET = {mode: 'unknown'}; }
  const n = NET, m = n.mode;
  let t;
  if (m === 'lan') t = '<span class=okc>Netzwerkkabel</span>, Adresse ' + H(n.eth_ip);
  else if (m === 'wlan') t = '<span class=okc>WLAN „' + H(n.wlan_ssid) + '“</span>, Adresse ' + H(n.wlan_ip);
  else if (m === 'ap' && n.ap) t = '<span class=warn>Eigenes WLAN „' + H(n.ap.ssid) + '“</span> (Passwort ' + H(n.ap.pw) + '), Seite unter http://' + H(n.ap.ip) + '/';
  else if (m === 'party' && n.ap) t = '<span class=okc>Party-Modus: WLAN „' + H(n.ap.ssid) + '“</span>, Seite unter http://' + H(n.ap.ip) + '/';
  else if (m === 'party') t = '<span class=okc>Party-Modus</span> startet …';
  else if (m === 'none') t = '<span class=warn>Kein Netz – sucht …</span>';
  else t = '<span class=hint>Der Netzwerk-Dienst meldet sich nicht (läuft er? <code>systemctl status c64pi-net</code>)</span>';
  if (n.radio === false && m === 'lan') t += ' <span class=hint>(WLAN ist ausgeschaltet)</span>';
  $('netstate').innerHTML = t;
  $('wforget').hidden = m !== 'wlan';
  $('wapnote').hidden = m !== 'ap';
  netList(n.scan || []);
  const w = CFG.wlan || {};
  $('apon').checked = w.ap !== false; $('apssid').value = w.ap_ssid || ''; $('appw').value = w.ap_pw || '';
}
function dispShow() {
  const d = CFG.display || {};
  $('dtype').value = d.type === 'ssd1306' ? 'auto' : (d.type || 'auto'); $('doff').value = d.off_min != null ? d.off_min : 10;
  $('dflip').checked = !!d.flip; $('dtouch').value = d.touch === 'shared' ? 'shared' : 'own'; $('ddc').value = String(d.dc || 24); $('dtft').hidden = $('dtype').value !== 'tft';
  $('dstate').textContent = S && S.display ? 'Display: ' + S.display +
    (d.type === 'tft' && !d.cal ? ' – Touch noch nicht eingerichtet: auf die Kreuze am Display tippen' : '') : '';
}
$('dtype').onchange = () => { $('dtft').hidden = $('dtype').value !== 'tft'; };
$('dcal').onclick = async () => {
  try { await api('display/calibrate', {}); toast('Am Display nacheinander genau auf die drei Kreuze tippen'); }
  catch (e) { errToast(e); }
};
function netList(list) {
  $('wlist').innerHTML = list.map(x => '<button type=button data-ssid="' + H(x.ssid) + '" data-open="' + (x.sec ? 0 : 1) + '">' + H(x.ssid) +
    ' <span class=sig>' + x.signal + ' %' + (x.sec ? '' : ', offen') + '</span></button>').join('');
}
$('wscan').onclick = async () => {
  $('wmsg').textContent = 'Suche … (bis 20 s)';
  try { const r = await api('wlan', {action: 'scan'}); $('wmsg').textContent = r.msg; netList(r.scan || []); }
  catch (e) { $('wmsg').textContent = e.message; }
};
$('wlist').onclick = async ev => {
  const b = ev.target.closest('button[data-ssid]'); if (!b) return;
  const ssid = b.dataset.ssid;
  let pw = '';
  if (b.dataset.open !== '1') { pw = await ask('Passwort für „' + ssid + '“', ''); if (!pw) return; }
  if (!confirm('Mit „' + ssid + '“ verbinden? Hängt der Pi am Kabel, bleibt er auch darüber erreichbar; sonst ist er danach unter einer neuen Adresse im WLAN „' + ssid + '“.')) return;
  $('wmsg').textContent = 'Verbinde … (bis 1 min)';
  try { const r = await api('wlan', {action: 'connect', ssid, pw}); $('wmsg').textContent = r.msg; netShow(); }
  catch (e) { $('wmsg').textContent = e.message; }
};
$('wforget').onclick = async () => {
  if (!NET || !confirm('WLAN „' + NET.wlan_ssid + '“ vergessen? Ohne Kabel öffnet der Pi danach sein eigenes WLAN.')) return;
  try { const r = await api('wlan', {action: 'forget', ssid: NET.wlan_ssid}); $('wmsg').textContent = r.msg; netShow(); }
  catch (e) { $('wmsg').textContent = e.message; }
};
$('netsave').onclick = async () => {
  try {
    CFG = (await api('config', {wlan: {ap: $('apon').checked, ap_ssid: $('apssid').value.trim(), ap_pw: $('appw').value}})).config;
    toast('Gespeichert'); setTimeout(netShow, 1500);
  } catch (e) { errToast(e); }
};
$('dsave').onclick = async () => {
  try {
    CFG = (await api('config', {display: {type: $('dtype').value, off_min: +$('doff').value || 0, flip: $('dflip').checked, touch: $('dtouch').value, dc: +$('ddc').value}})).config;
    toast('Gespeichert'); setTimeout(async () => { await poll(); dispShow(); }, 1500);
  } catch (e) { errToast(e); }
};
function u64Rows() {
  $('u64rows').innerHTML = CFG.ultimates.map((u, i) => '<div class="erow u64r" data-i=' + i + '>' +
    '<input class=ul placeholder="Name" value="' + H(u.label) + '" aria-label="Name">' +
    '<input class=ua placeholder="Adresse, z. B. 192.168.1.168" value="' + H(u.addr) + '" aria-label="Adresse" autocapitalize=off>' +
    '<input class=up type=password placeholder="Netzwerk-Passwort" value="' + H(u.pw) + '" aria-label="Netzwerk-Passwort" autocomplete=new-password>' +
    '<div class=eend><label title="Dieses Ultimate spielt"><input type=radio name=u64sel value=' + i + (i === CFG.u64_sel ? ' checked' : '') + '> aktiv</label>' +
    '<button class=uon title="Über das WLAN einschalten (Wake-Up on WiFi)">&#9211; Ein</button>' +
    '<button class=uoff title="Ausschalten">Aus</button>' +
    '<button class="danger ux" title="Entfernen" aria-label="Entfernen">&#10005;</button></div>' +
    '<input class=uw placeholder="WLAN-MAC zum Einschalten über WLAN (wird gemerkt)" value="' + H(u.wmac || '') + '" aria-label="WLAN-MAC" autocapitalize=off spellcheck=false></div>').join('');
}
function u64Read() {
  return [...document.querySelectorAll('#u64rows .erow')].map(r => ({label: r.querySelector('.ul').value.trim(), addr: r.querySelector('.ua').value.trim(), pw: r.querySelector('.up').value,
    wmac: r.querySelector('.uw').value.trim()}));
}
$('u64rows').onclick = async ev => {
  if (ev.target.closest('.ux')) { CFG.ultimates = u64Read(); CFG.ultimates.splice(+ev.target.closest('.erow').dataset.i, 1); u64Rows(); return; }
  const on = ev.target.closest('.uon'), off = ev.target.closest('.uoff');
  if (!on && !off) return;
  const i = +ev.target.closest('.erow').dataset.i, u = CFG.ultimates[i] || {};
  if (off && !confirm('\u201e' + (u.label || u.addr) + '\u201c ausschalten? Die Wiedergabe stoppt.')) return;
  try { const r = await api('u64/power', {i, on: !!on}); $('u64power').textContent = r.msg; toast(r.msg); poll(); }
  catch (e) { errToast(e); }
};
$('u64add').onclick = () => { CFG.ultimates = u64Read(); CFG.ultimates.push({label: '', addr: '', pw: ''}); u64Rows(); };
$('u64save').onclick = async () => {
  const sel = document.querySelector('input[name=u64sel]:checked');
  try {
    CFG = (await api('config', {ultimates: u64Read(), u64_sel: sel ? +sel.value : 0})).config;
    u64Rows(); toast('Gespeichert'); poll();
  } catch (e) { errToast(e); }
};
$('u64scan').onclick = async () => {
  $('u64found').innerHTML = '<p class=hint>Suche im Netz …</p>';
  try {
    const r = await api('scan/u64', {});
    const res = await waitJob(r.job, (p, j) => { $('u64found').innerHTML = scanHtml(j, /Ultimate/i); });
    $('u64found').innerHTML = res.length ? '<p class=hint>Gefunden – antippen zum Übernehmen:</p><div class=chips>' + res.map(h => '<button data-ip="' + H(h.ip) + '" data-n="' + H(h.u64.product || h.name) + '">' +
      H(h.u64.product || 'Ultimate') + ' <span class=hint>' + H(h.ip) + (h.alt ? ' (WLAN: ' + H(h.alt) + ')' : '') + '</span></button>').join('') + '</div>'
      : '<p class=hint>Kein Ultimate gefunden. Im Ultimate muss die Web-Fernsteuerung (Network → Web Remote Control) an sein.</p>';
  } catch (e) { $('u64found').innerHTML = '<p class=bad>' + H(e.message) + '</p>'; }
};
$('u64found').onclick = ev => {
  const b = ev.target.closest('button'); if (!b) return;
  CFG.ultimates = u64Read();
  if (CFG.ultimates.some(u => u.addr === b.dataset.ip)) { toast('Schon eingetragen'); return; }
  const empty = CFG.ultimates.find(u => !u.addr);
  if (empty) { empty.addr = b.dataset.ip; empty.label = empty.label || b.dataset.n; } else CFG.ultimates.push({label: b.dataset.n, addr: b.dataset.ip, pw: ''});
  u64Rows(); toast('Übernommen – noch „Speichern“ drücken');
};
function picoRows() {
  $('picorows').innerHTML = (CFG.picos.length ? '' : '<p class=hint>Noch kein Pico eingetragen. Unten unter „Geräte im Netz“ antippen oder „+ Pico“.</p>') +
    CFG.picos.map((p, i) => '<div class="erow pico" data-i=' + i + '>' +
    '<input class=pa placeholder="c64viz.local oder IP" value="' + H(p.addr) + '" aria-label="Adresse" autocapitalize=off>' +
    '<select class=pn aria-label="Titelmeldung"><option value=udp>Titel per UDP</option><option value=http>Titel per Webseite</option><option value=off>keine Titel</option></select>' +
    '<input class=pp type=password placeholder="Web-Passwort (für Webseite)" value="' + H(p.pw || '') + '" aria-label="Web-Passwort" autocomplete=new-password>' +
    '<div class=eend><label title="Audio-Stream an diesen Pico weiterreichen"><input type=checkbox class=ps' + (p.stream !== false ? ' checked' : '') + '> Stream</label>' +
    '<button class="danger px" title="Entfernen" aria-label="Entfernen">&#10005;</button></div></div>').join('');
  document.querySelectorAll('#picorows .erow').forEach((r, i) => { r.querySelector('.pn').value = CFG.picos[i].np || 'udp'; });
}
function picoRead() {
  return [...document.querySelectorAll('#picorows .erow')].map(r => ({addr: r.querySelector('.pa').value.trim(), stream: r.querySelector('.ps').checked,
    np: r.querySelector('.pn').value, pw: r.querySelector('.pp').value}));
}
$('picorows').onclick = ev => {
  if (ev.target.closest('.px')) { CFG.picos = picoRead(); CFG.picos.splice(+ev.target.closest('.erow').dataset.i, 1); picoRows(); }
};
$('picoadd').onclick = () => { CFG.picos = picoRead(); CFG.picos.push({addr: '', stream: true, np: 'udp', pw: ''}); picoRows(); };
$('picosave').onclick = async () => {
  try { CFG = (await api('config', {picos: picoRead()})).config; picoRows(); toast('Gespeichert'); poll(); } catch (e) { errToast(e); }
};
$('pnews').onchange = async () => {
  try { CFG = (await api('config', {pico_news: $('pnews').checked})).config; poll(); } catch (e) { errToast(e); }
};
$('ston').onchange = async () => {
  try { await api('config', {stream: {on: $('ston').checked}}); poll(); } catch (e) { errToast(e); }
};
function stShow() {
  if (!S) return;
  const st = S.stream;
  $('ston').checked = st.on;
  if (S.power_msg) $('u64power').textContent = S.power_msg;
  $('pnews').checked = !!(CFG && CFG.pico_news);
  const pn = S.pico_news || {};
  $('pnstate').innerHTML = !$('pnews').checked ? '' : pn.n ? pn.n + ' Schlagzeilen, alle 15 Minuten neu – Picos ohne Stream vom Pi brauchen „Titel per Webseite“ (mit Passwort)'
    : 'Noch keine Schlagzeilen – Quellen in „Anzeige“ → Retro-News';
  let t = st.on ? (st.active ? '<span class=okc>Stream kommt: ' + st.pps + ' Pakete/s von ' + H(st.from) + '</span>' : '<span class=warn>Wartet auf den Stream …</span>') : 'Aus – der Pi reicht keinen Stream weiter.';
  if (st.msg) t += ' <span class=hint>(' + H(st.msg) + ')</span>';
  if (st.foreign) t += '<br><span class=warn>' + st.foreign + ' Pakete von ' + H(st.foreign_ip) + ' verworfen</span> – Stream nur von den eingetragenen Adressen (Kabel) der Ultimates';
  if (st.on && st.targets.length) t += '<br>' + st.targets.map(x => H(x.addr) + ': ' + (x.ip ? x.pps + '/s' : '<span class=bad>Name nicht gefunden</span>') + (x.np ? ', Titel ' + H(x.np) : '') + (x.dropped ? ' <span class=hint>(' + x.dropped + ' verworfen – Gerät aus?)</span>' : '')).join('<br>');
  $('ststate').innerHTML = t;
}
$('devq').onclick = () => api('devices/query', {}).then(() => setTimeout(devLoad, 900)).catch(errToast);
async function devLoad() {
  let r;
  try { r = await api('devices'); } catch (e) { return; }
  const L2 = (r.list || []).map(e => { try { const d = JSON.parse(e.j); d.self = !!e.self; d.age = e.age; return d; } catch (x) { return null; } }).filter(d => d && d.ip);
  const by = {}; L2.forEach(d => { by[d.ip] = d; });
  const kind = d => ({audio: 'Audio-Empfänger', viz: 'Visualizer', pi: 'Raspberry Pi'}[d.t] || d.t || '?');
  const who = (d, ip) => by[ip] ? H(by[ip].n) : (ip && ip === d.src ? H(d.srcl || 'Ultimate') + ' (' + H(ip) + ')' : H(ip));
  /* the stream's way, as a tree: whoever gets it from a device we know hangs under that device */
  const walk = (d, seen) => {
    seen[d.ip] = 1;
    const kids = L2.filter(x => x.from === d.ip && x.rx > 0 && !seen[x.ip]);
    return H(d.n) + ' <b>' + d.rx + '/s</b>' + (kids.length ? ' &rarr; ' + (kids.length > 1 ? '[' + kids.map(k => walk(k, seen)).join(', ') + ']' : walk(kids[0], seen)) : '');
  };
  const roots = L2.filter(d => d.rx > 0 && !by[d.from]);
  $('devchain').innerHTML = roots.length ? 'Weg des Tons: ' + roots.map(d => who(d, d.from) + ' &rarr; ' + walk(d, {})).join('<br>') : 'Gerade fließt kein Audio-Stream.';
  const known = new Set((CFG ? CFG.picos : []).map(p => p.addr.replace(/\.local$/, '')));
  $('devlist').innerHTML = L2.map(d => '<div class=dev><a href="http://' + H(d.n) + '.local/" target=_blank rel=noopener>' + H(d.n) + '</a> – ' + H(kind(d)) + ', ' + H(d.ip) +
    (d.self ? ' (dieser Pi)' : '') + (d.b ? ' <span class=hint>Stand ' + H(String(d.b).replace(/:\d\d$/, '')) + '</span>' : '') +
    (d.age > 15 ? ' <span class=warn>(seit ' + d.age + ' s still)</span>' : '') + '<br>' +
    (d.rx > 0 ? 'Stream ' + d.rx + '/s von ' + who(d, d.from) : (d.st ? 'wartet auf Stream' : 'Stream aus')) +
    (d.fw && d.st ? ' &rarr; leitet weiter an ' + H(d.fw) + (d.fp ? ' (' + d.fp + '/s)' : '') : '') +
    (d.title ? '<br>♪ ' + H(d.title) : '') +
    (!d.self && d.t !== 'pi' && !known.has(d.n) && !known.has(d.ip) ? '<br><button data-add="' + H(d.n) + '.local">als Pico eintragen</button>' : '') + '</div>').join('') || 'Keine Geräte gefunden.';
}
$('devlist').onclick = ev => {
  const b = ev.target.closest('button[data-add]'); if (!b || !CFG) return;
  CFG.picos = picoRead(); CFG.picos.push({addr: b.dataset.add, stream: true, np: 'udp', pw: ''}); picoRows(); b.remove();
  toast('Eingetragen – noch „Speichern“ drücken');
};

/* ---------------------------------------------------------------- settings */
/* the timer ("Zeitplan"): weekdays + time -> play a list / stop, the TV with it */
const DAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
let SCH = {entries: [], lists: []};
function schRow(e) {
  const lists = '<option value="">aktuelle Liste</option>' + SCH.lists.map(n => '<option' + (n === e.list ? ' selected' : '') + '>' + H(n) + '</option>').join('');
  return '<div class="srow" data-id="' + H(e.id || '') + '"><label><input type="checkbox" class="son"' + (e.on !== false ? ' checked' : '') + '> an</label>' +
    '<span class="days">' + DAYS.map((d, i) => '<label><input type="checkbox" value="' + i + '"' + ((e.days || []).includes(i) ? ' checked' : '') + '>' + d + '</label>').join('') + '</span>' +
    '<input type="time" class="stime" value="' + H(e.time || '18:00') + '" aria-label="Uhrzeit">' +
    '<select class="sdo"><option value="play"' + (e.do !== 'stop' ? ' selected' : '') + '>abspielen</option><option value="stop"' + (e.do === 'stop' ? ' selected' : '') + '>stoppen</option></select>' +
    '<select class="slist"' + (e.do === 'stop' ? ' hidden' : '') + '>' + lists + '</select>' +
    '<label><input type="checkbox" class="stv"' + (e.tv ? ' checked' : '') + '> Fernseher mit</label>' +
    '<button class="danger sx" type="button" title="Eintrag löschen" aria-label="Eintrag löschen">&#10005;</button></div>';
}
function schShow(d) {
  SCH = d;
  $('schrows').innerHTML = d.entries.map(schRow).join('') || '<p class="hint">Noch keine Einträge.</p>';
  $('schstate').textContent = [d.next ? 'Als Nächstes: ' + d.next : '', d.last ? 'Zuletzt: ' + d.last : ''].filter(Boolean).join(' · ');
}
async function schLoad() { try { schShow(await api('schedule')); } catch (e) { errToast(e); } }
function schCollect() {
  return [...document.querySelectorAll('#schrows .srow')].map((r, k) => ({
    id: r.dataset.id || 'e' + Date.now().toString(36) + k, on: r.querySelector('.son').checked,
    days: [...r.querySelectorAll('.days input:checked')].map(i => +i.value), time: r.querySelector('.stime').value,
    do: r.querySelector('.sdo').value, list: r.querySelector('.slist').value, tv: r.querySelector('.stv').checked}));
}
$('schadd').onclick = () => {
  const cur = document.querySelectorAll('#schrows .srow').length ? schCollect() : [];
  schShow(Object.assign({}, SCH, {entries: cur.concat([{on: true, days: [0, 1, 2, 3, 4], time: '18:00', do: 'play', list: '', tv: false}])}));
};
$('schrows').onclick = ev => {
  if (!ev.target.closest('.sx')) return;
  ev.target.closest('.srow').remove();
};
$('schrows').onchange = ev => {
  if (ev.target.classList.contains('sdo')) ev.target.closest('.srow').querySelector('.slist').hidden = ev.target.value === 'stop';
};
$('schsave').onclick = async () => {
  try { schShow(await api('schedule', {entries: schCollect()})); toast('Zeitplan gespeichert'); } catch (e) { errToast(e); }
};
async function setShow() {
  schLoad();
  try { CFG = await api('config'); } catch (e) { errToast(e); return; }
  const p = CFG.player;
  $('plim').value = p.limit_min; $('psil').checked = p.silence; $('psils').value = p.silence_s; $('psub').value = p.subsongs; $('psid').checked = p.sidauto !== false;
  $('ploop').value = p.loopfind || 'suggest'; $('pname').value = p.hvsc_name || 'suggest';
  $('ver').textContent = 'C64-Jukebox ' + (S ? S.version : '');
  slShow(); netShow();
}
function slShow() {
  const c = S ? S.sl : {hvsc: 0, custom: 0}, o = CFG ? CFG.songlengths : {};
  const line = (k, title) => '<div class=row><span><b>' + title + ':</b> ' + (c[k] ? c[k] + ' Einträge' + (o[k] && o[k].label ? ' <span class=hint>(' + H(o[k].label) + ')</span>' : '') : '<span class=hint>keine</span>') +
    '</span><span class=grow></span>' + (c[k] ? '<button data-slc=' + k + '>Entfernen</button>' : '') + '</div>';
  $('slstate').innerHTML = line('hvsc', 'HVSC') + line('custom', 'Eigene Längen (Vorrang)') + line('stil', 'STIL (Hintergründe)');
}
$('slstate').onclick = async ev => {
  const b = ev.target.closest('[data-slc]'); if (!b || !confirm(b.dataset.slc === 'stil' ? 'STIL entfernen?' : 'Songlängen entfernen?')) return;
  try { await api(b.dataset.slc === 'stil' ? 'stil/clear' : 'songlengths/clear', {kind: b.dataset.slc}); await poll(); slShow(); } catch (e) { errToast(e); }
};
async function slUpload(input, kind) {
  const f = input.files[0]; if (!f) return;
  try {
    const r = await api('songlengths/upload?kind=' + kind + '&name=' + encodeURIComponent(f.name), await f.arrayBuffer(), true);
    toast(r.n + ' Songlängen geladen'); await poll(); CFG = await api('config'); slShow();
  } catch (e) { errToast(e); }
  input.value = '';
}
$('slup').onchange = () => slUpload($('slup'), 'hvsc');
$('slupc').onchange = () => slUpload($('slupc'), 'custom');
/* data of the PC program: play counts, favorites, own song lengths (merged) */
async function pcUpload(input, path) {
  const f = input.files[0]; if (!f) return;
  try { const r = await api(path, await f.text(), true); toast(r.msg || (r.added + ' neu, ' + r.changed + ' geändert, ' + r.kept + ' behalten')); LS.rows.clear(); await poll(); CFG = await api('config'); slShow(); }
  catch (e) { errToast(e); }
  input.value = '';
}
$('pcplays').onchange = () => pcUpload($('pcplays'), 'import/pcstats?kind=plays');
$('pcfavs').onchange = () => pcUpload($('pcfavs'), 'import/pcstats?kind=favs');
$('pclens').onchange = () => pcUpload($('pclens'), 'songlengths/upload?kind=custom&merge=1&overwrite=' + ($('pclensow').checked ? 1 : 0));
$('psave').onclick = async () => {
  try {
    await api('config', {player: {limit_min: +$('plim').value || 0, silence: $('psil').checked, silence_s: +$('psils').value || 5, subsongs: $('psub').value, sidauto: $('psid').checked, loopfind: $('ploop').value, hvsc_name: $('pname').value}});
    toast('Gespeichert'); poll();
  } catch (e) { errToast(e); }
};
$('pnsave').onclick = async () => {
  try { CFG = (await api('config', {name: $('pname').value})).config; $('pname').value = CFG.name; toast('Gespeichert'); } catch (e) { errToast(e); }
};
$('pwsave').onclick = async () => {
  try { await api('password', {old: $('pwold').value, new: $('pwnew').value}); $('pwold').value = $('pwnew').value = ''; toast('Passwort geändert'); poll(); }
  catch (e) { errToast(e); }
};
$('bkup').onchange = async () => {
  const f = $('bkup').files[0]; if (!f) return;
  if (!confirm('Sicherung „' + f.name + '“ einspielen? Die jetzigen Einstellungen werden ersetzt.')) { $('bkup').value = ''; return; }
  try { const r = await api('restore', await f.text(), true); toast(r.msg); setShow(); poll(); } catch (e) { errToast(e); }
  $('bkup').value = '';
};

/* ---------------------------------------------------------------- start */
let timer = null, ticks = 0;
async function start() {
  try {
    const h = await api('hello');
    if (!h.login) { showLogin(); return; }
  } catch (e) { showLogin(); return; }
  $('login').hidden = true; $('app').hidden = false;
  await poll();
  tab(store.get('tab', 'play'));
  if (!timer) timer = setInterval(() => { poll(); if (++ticks % 10 === 0 && document.querySelector('section[data-tab=dev]:not(.off)')) devLoad(); }, 1000);
}
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') poll(); });
start();

/* the SID addresses of the Ultimate (like "Check SID Addresses..." of the PC jukebox) */
$('psidchk').onclick = async () => {
  $('psidcfg').textContent = 'lese …';
  try {
    const r = await api('sidcfg');
    const rows = Object.entries(r.cfg || {}).filter(([k]) => /address/i.test(k)).map(([k, v]) => H(k.replace(' Address', '')) + ': <b>' + H(v) + '</b>');
    $('psidcfg').innerHTML = (rows.join(' · ') || 'keine Angaben') +
      (r.pending ? '<br>gerade umgestellt: Sockel ' + r.pending.sock + ' auf ' + H(r.pending.new) + ' (sonst ' + H(r.pending.orig) + ')' : '') +
      (r.msg ? '<br>' + H(r.msg) : '');
  } catch (e) { $('psidcfg').innerHTML = '<span class=bad>' + H(e.message) + '</span>'; }
};
