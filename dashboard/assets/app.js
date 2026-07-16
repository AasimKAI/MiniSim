/* MiniSim dashboard shared runtime — utils + canvas chart renderers.
   Every chart reads its colors from the CSS tokens in theme.css, renders at
   devicePixelRatio, and ships a pointer hover layer (crosshair + tooltip). */
(function () {
  const MS = (window.MS = {});

  /* ── formatting ─────────────────────────────────────────────────────── */
  MS.fmt = (n) => n == null ? '—'
    : Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  MS.fmtp = (n) => n == null ? '—'
    : (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%';
  MS.esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  MS.fmtPrice = (p) => {
    if (p == null) return '—';
    if (p >= 1000) return '$' + Number(p).toLocaleString(undefined, { maximumFractionDigits: 0 });
    if (p >= 1) return '$' + Number(p).toLocaleString(undefined, { maximumFractionDigits: 2 });
    return '$' + Number(p).toPrecision(4);
  };
  MS.sigAge = (ts) => {
    if (!ts) return '';
    const s = (Date.now() - new Date(ts).getTime()) / 1000;
    if (s < 60) return Math.round(s) + 's';
    if (s < 3600) return Math.round(s / 60) + 'm';
    return Math.round(s / 3600) + 'h';
  };
  MS.isStale = (ts) => !ts || (Date.now() - new Date(ts).getTime()) > 14 * 60 * 1000;
  MS.timeInPos = (openedAt) => {
    if (!openedAt) return '';
    const s = Date.now() / 1000 - openedAt;
    if (s < 3600) return Math.round(s / 60) + 'm';
    if (s < 86400) return (s / 3600).toFixed(1) + 'h';
    return Math.round(s / 86400) + 'd';
  };
  MS.regimeCls = (regime) => {
    const r = String(regime || '').toLowerCase();
    if (r.includes('bull') || r.includes('trend')) return 'bull';
    if (r.includes('bear')) return 'bear';
    if (r.includes('rang')) return 'range';
    if (r.includes('vol')) return 'vol';
    return '';
  };

  /* ── constants ──────────────────────────────────────────────────────── */
  MS.ALL_COINS = ['BTC', 'ETH', 'XRP', 'ADA', 'SOL', 'BNB', 'DOGE', 'AVAX',
    'DOT', 'LINK', 'LTC', 'NEAR', 'UNI', 'ARB', 'ATOM'];
  MS.ANALYST_ORDER = ['technical', 'volume', 'order_book', 'on_chain', 'sentiment'];
  MS.COIN_COLORS = {
    BTC: '#F7931A', ETH: '#627EEA', XRP: '#346AA9', ADA: '#0033AD', SOL: '#9945FF',
    BNB: '#F3BA2F', DOGE: '#C2A633', AVAX: '#E84142', DOT: '#E6007A', LINK: '#2A5ADA',
    LTC: '#345D9D', NEAR: '#00C08B', UNI: '#FF007A', ARB: '#28A0F0', ATOM: '#5064FB',
  };
  MS.coinDot = (coin, px) => {
    const c = MS.COIN_COLORS[coin] || '#3987e5';
    const fs = Math.max(6, Math.round(px * 0.34));
    return `<span class="coin-dot" style="width:${px}px;height:${px}px;background:${c};font-size:${fs}px">${MS.esc(String(coin).slice(0, 2))}</span>`;
  };

  /* ── theme tokens (canvas colors come from CSS) ─────────────────────── */
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  MS.tok = () => ({
    up: css('--up') || '#0ca30c', dn: css('--dn') || '#d03b3b',
    warn: css('--warn') || '#fab219', acc: css('--acc') || '#3987e5',
    ink: css('--ink') || '#fff', ink2: css('--ink2') || '#c3c2b7',
    muted: css('--muted') || '#898781', grid: css('--line') || '#2c2c2a',
    baseline: css('--baseline') || '#383835', surface: css('--surface') || '#1a1a19',
  });

  /* ── api / auth ─────────────────────────────────────────────────────── */
  const CSRF = (document.querySelector('meta[name=csrf-token]') || {}).content || '';
  const hdrs = (x) => {
    const h = Object.assign({ 'X-CSRF-Token': CSRF }, x || {});
    const t = localStorage.getItem('minisim_token');
    if (t) h['X-Auth-Token'] = t;
    return h;
  };
  MS.api = async (url, o) => {
    o = o || {}; o.headers = hdrs(o.headers);
    let r = await fetch(url, o);
    if (r.status === 401) {
      const t = prompt('Dashboard token:');
      if (t) { localStorage.setItem('minisim_token', t); o.headers = hdrs(o.headers); r = await fetch(url, o); }
    }
    return r;
  };

  /* ── analyst verdict widgets ────────────────────────────────────────── */
  MS.analystDots = (analysts) => {
    const t = MS.tok();
    const map = {}; (analysts || []).forEach((a) => (map[a.a] = a.v));
    return MS.ANALYST_ORDER.map((name) => {
      const v = map[name];
      const col = v === 'bullish' ? t.up : v === 'bearish' ? t.dn : t.baseline;
      const title = name.replace('_', ' ') + ': ' + (v || 'n/a');
      return `<span class="adot" style="background:${col}" title="${MS.esc(title)}"></span>`;
    }).join('');
  };
  MS.analystChips = (analysts) => (analysts || []).map((a) => {
    const cls = a.v === 'bullish' ? 'bull' : a.v === 'bearish' ? 'bear' : 'neut';
    return `<span class="av ${cls}"><b>${MS.esc(a.v)}</b> ${MS.esc(String(a.a).replace('_', ' '))} ${Math.round((a.c || 0) * 100)}%</span>`;
  }).join('');

  /* ── shared tooltip ─────────────────────────────────────────────────── */
  let tipEl = null;
  const tip = () => {
    if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'viz-tip'; document.body.appendChild(tipEl); }
    return tipEl;
  };
  MS.hideTip = () => { if (tipEl) tipEl.style.display = 'none'; };
  const showTip = (x, y, html) => {
    const el = tip();
    el.innerHTML = html;
    el.style.display = 'block';
    const r = el.getBoundingClientRect();
    let lx = x + 14, ly = y - r.height - 10;
    if (lx + r.width > innerWidth - 8) lx = x - r.width - 14;
    if (ly < 8) ly = y + 14;
    el.style.left = lx + 'px';
    el.style.top = ly + 'px';
  };

  const sizeCanvas = (cv) => {
    const dpr = window.devicePixelRatio || 1;
    const rc = cv.getBoundingClientRect();
    cv.width = Math.max(1, Math.round(rc.width * dpr));
    cv.height = Math.max(1, Math.round(rc.height * dpr));
    return { ctx: cv.getContext('2d'), dpr, W: cv.width, H: cv.height };
  };

  const hhmm = (sec) => new Date(sec * 1000)
    .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  /* ── equity area chart (single series → no legend; hover crosshair) ─── */
  MS.drawEquity = (cv, pts, hover) => {
    if (!cv || !pts || pts.length < 2) return;
    const { ctx, dpr, W, H } = sizeCanvas(cv);
    if (H < 24 * dpr) return;
    const t = MS.tok();
    ctx.clearRect(0, 0, W, H);
    const PL = 46 * dpr, PR = 8 * dpr, PT = 6 * dpr, PB = 16 * dpr;
    const CW = W - PL - PR, CH = H - PT - PB;
    if (CW < 8 || CH < 8) return;
    const vs = pts.map((p) => p.equity);
    const lo = Math.min(...vs), hi = Math.max(...vs), rng = hi - lo || 1;
    const X = (i) => PL + (i / (pts.length - 1)) * CW;
    const Y = (v) => PT + (1 - (v - lo) / rng) * CH;
    const up = vs[vs.length - 1] >= vs[0];
    const col = up ? t.up : t.dn;

    // hairline grid + y labels (muted, tabular)
    ctx.font = `${9 * dpr}px ${'system-ui,sans-serif'}`;
    for (let i = 0; i <= 3; i++) {
      const y = PT + (i / 3) * CH;
      ctx.strokeStyle = t.grid; ctx.lineWidth = dpr;
      ctx.beginPath(); ctx.moveTo(PL, y); ctx.lineTo(W - PR, y); ctx.stroke();
      ctx.fillStyle = t.muted; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText('$' + Math.round(hi - (i / 3) * rng).toLocaleString(), PL - 5 * dpr, y);
    }
    // dotted session-start reference
    ctx.setLineDash([3 * dpr, 3 * dpr]);
    ctx.strokeStyle = t.baseline; ctx.lineWidth = dpr;
    ctx.beginPath(); ctx.moveTo(PL, Y(vs[0])); ctx.lineTo(W - PR, Y(vs[0])); ctx.stroke();
    ctx.setLineDash([]);
    // area (recessive) + 2px line
    const g = ctx.createLinearGradient(0, PT, 0, H - PB);
    g.addColorStop(0, up ? 'rgba(12,163,12,.18)' : 'rgba(208,59,59,.18)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(X(i), Y(p.equity)) : ctx.moveTo(X(i), Y(p.equity))));
    ctx.lineTo(X(pts.length - 1), H - PB); ctx.lineTo(PL, H - PB); ctx.closePath();
    ctx.fillStyle = g; ctx.fill();
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(X(i), Y(p.equity)) : ctx.moveTo(X(i), Y(p.equity))));
    ctx.strokeStyle = col; ctx.lineWidth = 2 * dpr; ctx.lineJoin = 'round'; ctx.stroke();
    // end dot with surface ring
    ctx.beginPath(); ctx.arc(X(pts.length - 1), Y(vs[vs.length - 1]), 4 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = t.surface; ctx.fill();
    ctx.beginPath(); ctx.arc(X(pts.length - 1), Y(vs[vs.length - 1]), 2.6 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = col; ctx.fill();
    // time endpoints
    ctx.fillStyle = t.muted; ctx.font = `${8.5 * dpr}px system-ui,sans-serif`; ctx.textBaseline = 'bottom';
    ctx.textAlign = 'left'; ctx.fillText(hhmm(pts[0].ts), PL, H - 2 * dpr);
    ctx.textAlign = 'right'; ctx.fillText(hhmm(pts[pts.length - 1].ts), W - PR, H - 2 * dpr);

    cv._viz = { pts, X, Y, PL, PR, PT, PB, dpr, col };
    if (hover !== false) bindEquityHover(cv);
  };

  function bindEquityHover(cv) {
    if (cv._hoverBound) return;
    cv._hoverBound = true;
    const move = (ev) => {
      const v = cv._viz; if (!v) return;
      const rc = cv.getBoundingClientRect();
      const px = (ev.clientX - rc.left) * v.dpr;
      const n = v.pts.length;
      const i = Math.max(0, Math.min(n - 1,
        Math.round(((px - v.PL) / (cv.width - v.PL - v.PR)) * (n - 1))));
      const p = v.pts[i];
      MS.drawEquity(cv, v.pts, false);           // re-render base
      const v2 = cv._viz, ctx = cv.getContext('2d'), t = MS.tok();
      const x = v2.X(i), y = v2.Y(p.equity);
      ctx.strokeStyle = t.baseline; ctx.lineWidth = v2.dpr;
      ctx.setLineDash([3 * v2.dpr, 3 * v2.dpr]);
      ctx.beginPath(); ctx.moveTo(x, v2.PT); ctx.lineTo(x, cv.height - v2.PB); ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath(); ctx.arc(x, y, 4.5 * v2.dpr, 0, Math.PI * 2);
      ctx.fillStyle = t.surface; ctx.fill();
      ctx.beginPath(); ctx.arc(x, y, 3 * v2.dpr, 0, Math.PI * 2);
      ctx.fillStyle = v2.col; ctx.fill();
      showTip(ev.clientX, ev.clientY,
        `${hhmm(p.ts)} · <b>$${MS.fmt(p.equity)}</b>`);
    };
    const leave = () => { MS.hideTip(); if (cv._viz) MS.drawEquity(cv, cv._viz.pts, false); };
    cv.addEventListener('pointermove', move);
    cv.addEventListener('pointerdown', move);
    cv.addEventListener('pointerleave', leave);
  }

  /* ── candlestick chart (status colors; per-candle hover tooltip) ────── */
  MS.drawCandles = (cv, candles, hover) => {
    if (!cv || !candles || candles.length < 2) return;
    const { ctx, dpr, W, H } = sizeCanvas(cv);
    const t = MS.tok();
    ctx.clearRect(0, 0, W, H);
    const PL = 52 * dpr, PR = 8 * dpr, PT = 8 * dpr, PB = 6 * dpr;
    const CW = W - PL - PR, CH = H - PT - PB;
    const lo = Math.min(...candles.map((c) => c[2]));
    const hi = Math.max(...candles.map((c) => c[1]));
    const rng = hi - lo || 1;
    const Y = (v) => PT + (1 - (v - lo) / rng) * CH;
    const n = candles.length;
    const gap = Math.max(1, Math.round(dpr));            // 1px surface gap
    const bw = Math.max(dpr, (CW - gap * (n - 1)) / n);

    ctx.font = `${9 * dpr}px system-ui,sans-serif`;
    for (let i = 0; i <= 3; i++) {
      const y = PT + (i / 3) * CH;
      ctx.strokeStyle = t.grid; ctx.lineWidth = dpr;
      ctx.beginPath(); ctx.moveTo(PL, y); ctx.lineTo(W - PR, y); ctx.stroke();
      ctx.fillStyle = t.muted; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText('$' + (hi - (i / 3) * rng).toLocaleString(undefined,
        { maximumFractionDigits: 2 }), PL - 5 * dpr, y);
    }
    candles.forEach((c, i) => {
      const [o, h, l, cl] = c;
      const x = PL + i * (bw + gap);
      const col = cl >= o ? t.up : t.dn;
      ctx.strokeStyle = col; ctx.lineWidth = dpr;
      ctx.beginPath(); ctx.moveTo(x + bw / 2, Y(h)); ctx.lineTo(x + bw / 2, Y(l)); ctx.stroke();
      const top = Y(Math.max(o, cl)), bot = Y(Math.min(o, cl));
      ctx.fillStyle = col;
      ctx.fillRect(x, top, bw, Math.max(bot - top, dpr));
    });
    cv._viz = { candles, PL, PR, PT, PB, bw, gap, dpr };
    if (hover !== false) bindCandleHover(cv);
  };

  function bindCandleHover(cv) {
    if (cv._hoverBound) return;
    cv._hoverBound = true;
    const move = (ev) => {
      const v = cv._viz; if (!v) return;
      const rc = cv.getBoundingClientRect();
      const px = (ev.clientX - rc.left) * v.dpr;
      const i = Math.max(0, Math.min(v.candles.length - 1,
        Math.floor((px - v.PL) / (v.bw + v.gap))));
      const [o, h, l, c] = v.candles[i];
      const dir = c >= o ? 'up' : 'dn';
      const f = (x) => Number(x).toLocaleString(undefined, { maximumFractionDigits: 4 });
      showTip(ev.clientX, ev.clientY,
        `O ${f(o)} · H ${f(h)} · L ${f(l)}<br>C <b class="${dir}">${f(c)}</b> ` +
        `<span class="${dir}">${MS.fmtp(((c - o) / o) * 100)}</span>`);
    };
    cv.addEventListener('pointermove', move);
    cv.addEventListener('pointerdown', move);
    cv.addEventListener('pointerleave', MS.hideTip);
  }

  /* ── win-rate donut (part-to-whole + hero number) ───────────────────── */
  MS.drawDonut = (cv, wins, total) => {
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr;
    const t = MS.tok();
    const ctx = cv.getContext('2d'), cx = cv.width / 2, cy = cv.height / 2;
    const r = Math.min(cv.width, cv.height) / 2 - 5 * dpr;
    const lw = Math.max(5 * dpr, r * 0.24);
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = t.grid; ctx.lineWidth = lw; ctx.stroke();
    if (total > 0 && wins > 0) {
      ctx.beginPath();
      ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + (wins / total) * Math.PI * 2);
      ctx.strokeStyle = t.up; ctx.lineWidth = lw; ctx.lineCap = 'round'; ctx.stroke();
    }
    const big = r * 0.52, small = r * 0.30;
    ctx.fillStyle = t.ink; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.font = `700 ${big}px system-ui,sans-serif`;
    ctx.fillText(total > 0 ? Math.round((wins / total) * 100) + '%' : '—', cx, cy - small * 0.5);
    ctx.fillStyle = t.muted; ctx.font = `${small}px system-ui,sans-serif`;
    ctx.fillText('win rate', cx, cy + big * 0.62);
  };

  /* ── fear & greed gauge (4 status segments + needle) ────────────────── */
  MS.drawGauge = (cv, value) => {
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth * dpr || 110 * dpr, H = cv.clientHeight * dpr || 70 * dpr;
    cv.width = W; cv.height = H;
    const t = MS.tok();
    const ctx = cv.getContext('2d');
    const cx = W / 2, cy = H * 0.9, r = Math.min(W / 2, H * 0.82) - 6 * dpr, lw = 9 * dpr;
    const segs = [t.dn, '#ec835a', t.warn, t.up];
    segs.forEach((col, i) => {
      ctx.beginPath();
      ctx.arc(cx, cy, r, Math.PI + (i / 4) * Math.PI, Math.PI + ((i + 1) / 4) * Math.PI);
      ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.lineCap = 'butt'; ctx.stroke();
    });
    const angle = Math.PI + (Math.max(0, Math.min(100, value)) / 100) * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx - Math.cos(angle) * 4 * dpr, cy - Math.sin(angle) * 4 * dpr);
    ctx.lineTo(cx + Math.cos(angle) * (r - lw), cy + Math.sin(angle) * (r - lw));
    ctx.strokeStyle = t.ink; ctx.lineWidth = 2.5 * dpr; ctx.lineCap = 'round'; ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, 4 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = t.ink; ctx.fill();
  };
  MS.fngColor = (v) => {
    const t = MS.tok();
    return v <= 25 ? t.dn : v <= 45 ? '#ec835a' : v <= 55 ? t.warn : t.up;
  };
})();
