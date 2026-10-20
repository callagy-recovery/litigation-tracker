// Litigation Tracker page. All data arrives in the #data JSON block, already masked; the map geometry is local.
(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('data').textContent);

  // Map colours carry meaning and never follow the brand palette. Checked with a colour-vision-deficiency
  // validator (worst adjacent pair ΔE 8.4 deutan); the win share is always shown as text as well.
  const COLOURS = { red: '#b91c1c', orange: '#f97316', lightgreen: '#a3d977', green: '#047857', blue: '#2563eb', grey: '#cbd5e1' };
  const LEGEND = [
    ['red', 'Under 20% wins'], ['orange', '20% to under 50%'], ['lightgreen', '50% to under 80%'],
    ['green', '80% and above'], ['blue', 'No decisions, cases pending'], ['grey', 'No decisions, nothing pending'],
  ];
  const COLOUR_NAMES = { red: 'Red', orange: 'Orange', lightgreen: 'Light green', green: 'Green', blue: 'Blue', grey: 'Grey' };
  // Small north-eastern states and DC get a clickable box offshore, so they can be hovered and clicked.
  const BOXES = ['VT', 'NH', 'MA', 'RI', 'CT', 'NJ', 'DE', 'MD', 'DC'];

  let tab = 'state';
  let fedView = 'federal';
  let geo = null;
  let lastFocus = null;
  const viewKey = () => (tab === 'state' ? 'state' : fedView);
  const V = () => D.views[viewKey()];
  // Insurer filter: the chosen standard company names. Empty = all insurers (the views the page arrived with).
  const selected = new Set();
  const allViews = D.views;

  // ---------- federal circuits ----------
  // Which circuit each state is in, from the appellate view the server sends (data.CIRCUIT_STATES), so the map,
  // the appellate colouring and the overlay always agree.
  const CIRCUIT_OF = Object.fromEntries(Object.entries(allViews.appellate.states).filter(([, s]) => s.via).map(([ab, s]) => [ab, s.via]));
  // Each circuit court's website, as listed on uscourts.gov ("Court Website Links").
  const CIRCUIT_SITES = {
    '1st Circuit': 'https://www.ca1.uscourts.gov', '2nd Circuit': 'https://www.ca2.uscourts.gov', '3rd Circuit': 'https://www.ca3.uscourts.gov',
    '4th Circuit': 'https://www.ca4.uscourts.gov', '5th Circuit': 'https://www.ca5.uscourts.gov', '6th Circuit': 'https://www.ca6.uscourts.gov/',
    '7th Circuit': 'https://www.ca7.uscourts.gov/', '8th Circuit': 'https://www.ca8.uscourts.gov', '9th Circuit': 'https://www.ca9.uscourts.gov/',
    '10th Circuit': 'https://www.ca10.uscourts.gov/', '11th Circuit': 'https://www.ca11.uscourts.gov', 'D.C. Circuit': 'https://www.cadc.uscourts.gov',
  };
  // Where each circuit's number sits on the map (its 975x610 drawing space): the middle of the circuit, moved by hand
  // in the north-east so no badge covers another or the small-state boxes.
  const CIRCUIT_BADGES = {
    '1st Circuit': [919, 104], '2nd Circuit': [828, 168], '3rd Circuit': [800, 228], '4th Circuit': [790, 334],
    '5th Circuit': [520, 470], '6th Circuit': [690, 300], '7th Circuit': [625, 238], '8th Circuit': [497, 225],
    '9th Circuit': [140, 232], '10th Circuit': [351, 305], '11th Circuit': [725, 462], 'D.C. Circuit': [886, 326],
  };
  const circuitShort = (c) => (c === 'D.C. Circuit' ? 'D.C.' : c.replace(' Circuit', ''));
  let showCircuits = true;
  try { showCircuits = localStorage.getItem('lt-circuits') !== 'off'; } catch (e) { /* storage blocked: shown */ }
  const circuitsShown = () => tab === 'federal' && showCircuits;

  // ---------- helpers ----------
  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k === 'text') e.textContent = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid);
    return e;
  }
  function svg(tag, attrs) {
    const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    return e;
  }
  function fmtDate(iso) {
    if (!/^\d{4}-\d{2}-\d{2}/.test(iso || '')) return iso || '—';
    const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }
  function pct(share) {
    if (share == null) return '—';
    const v = Math.floor(share * 1000 + 1e-9) / 10; // never round up across a colour boundary
    return (Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1)) + '%';
  }
  const plural = (n, word, many) => `${n} ${n === 1 ? word : many || word + 's'}`;
  const tally = (s) => `${plural(s.decisions, 'decision')}, ${plural(s.wins, 'win')}, ${plural(s.losses, 'loss', 'losses')}`;
  function sourceLink(url, label) {
    return url ? el('a', { href: url, target: '_blank', rel: 'noopener noreferrer', class: 'src' }, label || 'Source', el('span', { 'aria-hidden': 'true', text: ' ↗' })) : null;
  }

  // ---------- header, theme ----------
  function applyTheme() {
    const r = document.documentElement.style;
    r.setProperty('--brand', D.theme.brand);
    r.setProperty('--brand-dark', D.theme.brandDark);
    r.setProperty('--accent', D.theme.accent);
    r.setProperty('--tint', D.theme.tint);
    const logo = document.getElementById('logo');
    const tile = document.getElementById('logo-tile');
    if (!D.hasLogo) tile.hidden = true;
    logo.addEventListener('error', () => { tile.hidden = true; });
    // "Data as of" is the newest of the report and the daily update that added to it; both are named underneath.
    const run = D.report.autoRun && new Date(D.report.autoRun);
    const updated = run && !isNaN(run) && D.report.autoRun.slice(0, 10) >= D.report.date;
    const time = updated ? run.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : '';
    document.getElementById('asof').append(
      el('span', { class: 'asof-label', text: 'Data as of' }), ' ',
      el('strong', { text: fmtDate(updated ? D.report.autoRun.slice(0, 10) : D.report.date) }),
      updated ? el('span', { class: 'asof-label', text: `, ${time}` }) : null,
      // The report's file name is not shown, by request; its date is.
      updated ? el('br') : null,
      updated ? el('span', { class: 'asof-file', text: `Report of ${fmtDate(D.report.date)} plus the daily update` }) : null,
      D.dataDownload ? el('br') : null,
      D.dataDownload ? el('a', { class: 'asof-download', href: D.dataDownload, download: '', text: 'Download the data (Excel)' }) : null);
  }

  // ---------- summary strip ----------
  function renderStrip() {
    const s = V().summary;
    const tiles = [
      ['included', 'Decisions included', s.included, viewKey() === 'appellate' ? 'appellate only' : ''],
      ['wins', 'Wins', s.wins, s.included ? pct(s.wins / s.included) + ' win share' : ''],
      ['losses', 'Losses', s.losses, ''],
      ['states', 'States with decisions', s.statesWithDecisions, viewKey() === 'appellate' ? 'coloured through their circuit' : ''],
      ['pending', 'Pending cases', s.pending, D.hasPendingSheet ? '' : 'no Pending Cases sheet yet'],
      ['excluded', 'Excluded under methodology', s.excluded, 'not mapped'],
    ];
    const strip = document.getElementById('strip');
    strip.classList.toggle('has-focus', !!focus);
    strip.replaceChildren(...tiles.map(([k, label, value, sub]) => {
      const t = el('div', { class: `tile tile-${k}${focus === k ? ' tile-on' : ''}`, role: 'button', tabindex: '0',
                            'aria-pressed': String(focus === k), title: focus === k ? 'Click to show everything again' : `Show ${FOCUS[k].label.toLowerCase()} on the map` },
        el('span', { class: 'tile-label', text: label }),
        el('span', { class: 'tile-value', text: String(value) }),
        sub ? el('span', { class: 'tile-sub', text: sub }) : null);
      const pick = () => { focus = focus === k ? null : k; renderStrip(); if (geo) renderMap(); renderLegend(); hideTip(); };
      t.addEventListener('click', pick);
      t.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
      return t;
    }));
  }

  // Clicking a card shows only that card's data on the map; the other states turn grey. Click it again to undo.
  let focus = null;
  const excludedStates = () => new Set(D.excludedList
    .filter((d) => (viewKey() === 'state' ? d.level === 'state' : d.level === 'federal' && (viewKey() !== 'appellate' || d.appellate)))
    .map((d) => d.state));
  const decisionsOnly = { label: 'Decisions only, without pending cases', colour: null, fill: (s) => (s.decisions ? COLOURS[s.colour] : COLOURS.grey), hatch: true };
  const FOCUS = {
    included: decisionsOnly,
    states: decisionsOnly,
    wins: { label: 'States with at least one win', colour: COLOURS.green, fill: (s) => (s.wins ? COLOURS.green : COLOURS.grey) },
    losses: { label: 'States with at least one loss', colour: COLOURS.red, fill: (s) => (s.losses ? COLOURS.red : COLOURS.grey) },
    pending: { label: 'States with pending cases', colour: COLOURS.blue, fill: (s) => (s.pending ? COLOURS.blue : COLOURS.grey) },
    excluded: { label: 'States with a ruling excluded under the methodology', colour: '#64748b',
                fill: (s, ab) => (excludedStates().has(ab) ? '#64748b' : COLOURS.grey) },
  };
  const fillOf = (s, ab) => (focus ? FOCUS[focus].fill(s, ab) : COLOURS[s.colour]);
  const hatchOf = (s) => s.hatched && (!focus || FOCUS[focus].hatch);

  // ---------- map ----------
  // Callagy's own litigation in the state, from the firm's case list (callagy\ folder); not limited to this view.
  const callagyIn = (ab) => {
    if (!D.callagy) return 0;
    if (!selected.size) return D.callagy.byState[ab] || 0;
    return [...selected].reduce((n, c) => n + (((D.callagy.byInsurer || {})[c] || {})[ab] || 0), 0);
  };
  function describe(ab) {
    const s = V().states[ab];
    const via = s.via && (s.decisions || s.pending) ? ` (${s.via})` : '';
    const callagy = D.callagy ? `, ${plural(callagyIn(ab), 'Callagy case')} in all litigation` : '';
    return `${s.name}${via}: ${plural(s.total, 'case')} in total${callagy}; ${tally(s)}, win share ${pct(s.share)}, ${plural(s.pending, 'pending case')}`;
  }
  function wire(node, ab) {
    node.setAttribute('tabindex', '0');
    node.setAttribute('role', 'button');
    node.setAttribute('aria-label', describe(ab));
    node.dataset.st = ab;
    node.addEventListener('mouseenter', (e) => showTip(ab, e.clientX, e.clientY));
    node.addEventListener('mousemove', (e) => moveTip(e.clientX, e.clientY));
    node.addEventListener('mouseleave', hideTip);
    node.addEventListener('focus', () => { const r = node.getBoundingClientRect(); showTip(ab, r.left + r.width / 2, r.top + r.height / 2); });
    node.addEventListener('blur', hideTip);
    node.addEventListener('click', () => openPanel(ab));
    node.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openPanel(ab); } });
  }
  function renderMap() {
    const map = document.getElementById('map');
    const states = V().states;
    const defs = svg('defs');
    const pat = svg('pattern', { id: 'hatch', patternUnits: 'userSpaceOnUse', width: 7, height: 7, patternTransform: 'rotate(45)' });
    pat.append(svg('rect', { width: 2.4, height: 7, fill: 'rgba(255,255,255,0.85)' }));
    pat.append(svg('rect', { x: 2.4, width: 1.2, height: 7, fill: 'rgba(17,24,39,0.35)' }));
    defs.append(pat);
    const shapes = svg('g', { class: 'shapes' });
    const hatches = svg('g', { class: 'hatches', 'pointer-events': 'none' });
    for (const [ab, g] of Object.entries(geo)) {
      const s = states[ab];
      const p = svg('path', { d: g.d, class: 'state', fill: fillOf(s, ab) });
      p.append(svg('title'));
      p.firstChild.textContent = describe(ab);
      wire(p, ab);
      shapes.append(p);
      if (hatchOf(s)) hatches.append(svg('path', { d: g.d, fill: 'url(#hatch)' }));
    }
    const boxes = svg('g', { class: 'boxes' });
    BOXES.forEach((ab, i) => {
      const s = states[ab];
      const y = 188 + i * 26;
      const g = svg('g', { class: 'box' });
      const r = svg('rect', { x: 916, y, width: 20, height: 20, rx: 4, fill: fillOf(s, ab), class: 'state' });
      g.append(r);
      if (hatchOf(s)) g.append(svg('rect', { x: 916, y, width: 20, height: 20, rx: 4, fill: 'url(#hatch)', 'pointer-events': 'none' }));
      const t = svg('text', { x: 942, y: y + 15, class: 'box-label' });
      t.textContent = ab;
      if (circuitsShown() && CIRCUIT_OF[ab]) {
        const c = svg('tspan', { class: 'box-circuit' });
        c.textContent = ` · ${circuitShort(CIRCUIT_OF[ab])}`;
        t.append(c);
      }
      g.append(t);
      wire(r, ab);
      boxes.append(g);
    });
    const [lines, badges] = circuitsShown() ? circuitLayer(defs) : [null, null];
    map.replaceChildren(...[defs, shapes, hatches, lines, boxes, badges].filter(Boolean));
    map.setAttribute('aria-label', `Map of ${viewTitle()}. Each state can be focused and opened for its decisions.`);
  }
  // Lines only where two circuits meet. Each circuit's states are drawn with a wide stroke and masked so only the
  // part outside the circuit shows; the neighbouring circuit does the same from its side, so the two halves make one
  // line centred on the border. The layer is clipped to the land, so coasts and borders inside a circuit stay plain.
  function circuitLayer(defs) {
    const land = svg('clipPath', { id: 'land' });
    for (const g of Object.values(geo)) land.append(svg('path', { d: g.d }));
    defs.append(land);
    const lines = svg('g', { class: 'circuits', 'clip-path': 'url(#land)', 'pointer-events': 'none', 'aria-hidden': 'true' });
    const groups = {};
    for (const [ab, c] of Object.entries(CIRCUIT_OF)) if (geo[ab]) (groups[c] = groups[c] || []).push(geo[ab].d);
    Object.values(groups).forEach((ds, i) => {
      const m = svg('mask', { id: `circuit-mask-${i}`, maskUnits: 'userSpaceOnUse', x: -20, y: -20, width: 1060, height: 660 });
      m.append(svg('rect', { x: -20, y: -20, width: 1060, height: 660, fill: '#fff' }));
      for (const d of ds) m.append(svg('path', { d, fill: '#000' }));
      defs.append(m);
      const g = svg('g', { mask: `url(#circuit-mask-${i})` });
      for (const d of ds) g.append(svg('path', { d, class: 'circuit-casing' }));  // a white edge either side of the line
      for (const d of ds) g.append(svg('path', { d, class: 'circuit-edge' }));
      lines.append(g);
    });
    const badges = svg('g', { class: 'circuit-badges', 'pointer-events': 'none', 'aria-hidden': 'true' });
    for (const [c, [x, y]] of Object.entries(CIRCUIT_BADGES)) {
      if (c === 'D.C. Circuit' && geo.DC) badges.append(svg('line', { x1: x, y1: y, x2: geo.DC.c[0], y2: geo.DC.c[1], class: 'circuit-leader' }));
      const t = circuitShort(c);
      badges.append(svg('circle', { cx: x, cy: y, r: t.length > 3 ? 19 : 17, class: 'circuit-badge' }));
      const label = svg('text', { x, y: y + 4.5, class: 'circuit-num', 'text-anchor': 'middle' });
      label.textContent = t;
      badges.append(label);
    }
    return [lines, badges];
  }
  function viewTitle() {
    return { state: 'state court decisions', federal: 'all federal court decisions', appellate: 'federal appellate decisions, coloured by circuit' }[viewKey()];
  }

  // ---------- tooltip ----------
  const tip = document.getElementById('tooltip');
  function showTip(ab, x, y) {
    const s = V().states[ab];
    const rows = [['Total cases', s.total], ...(D.callagy ? [['Callagy cases (all litigation)', callagyIn(ab)]] : []),
      ['Decisions', s.decisions], ['Wins', s.wins], ['Losses', s.losses], ['Win share', pct(s.share)], ['Pending cases', s.pending]];
    tip.replaceChildren(...[
      el('strong', { text: s.name }),
      tab === 'federal' && CIRCUIT_OF[ab] ? el('span', { class: 'tip-via', text: CIRCUIT_OF[ab] }) : null,
      el('dl', {}, rows.flatMap(([k, v]) => [el('dt', { text: k }), el('dd', { text: String(v) })])),
      s.hatched ? el('span', { class: 'tip-note', text: 'Limited data: only ' + plural(s.decisions, 'decision') }) : null,
      D.callagy || D.published ? null : el('span', { class: 'tip-note', text: 'No Callagy case list found in the callagy folder.' }),
    ].filter(Boolean));
    tip.hidden = false;
    moveTip(x, y);
  }
  function moveTip(x, y) {
    const wrap = tip.parentElement.getBoundingClientRect();
    let left = x - wrap.left + 14;
    let top = y - wrap.top + 14;
    if (left + tip.offsetWidth > wrap.width) left = x - wrap.left - tip.offsetWidth - 14;
    if (top + tip.offsetHeight > wrap.height) top = y - wrap.top - tip.offsetHeight - 14;
    tip.style.left = Math.max(0, left) + 'px';
    tip.style.top = Math.max(0, top) + 'px';
  }
  function hideTip() { tip.hidden = true; }

  // ---------- legend, footnote, table ----------
  function renderLegend() {
    const f = focus && FOCUS[focus];
    const items = f && f.colour
      ? [el('li', {}, el('span', { class: 'sw', style: `background:${f.colour}` }), f.label), el('li', {}, el('span', { class: 'sw', style: `background:${COLOURS.grey}` }), 'Other states')]
      : LEGEND.filter(([k]) => !f || k !== 'blue').map(([k, label]) => el('li', {}, el('span', { class: 'sw', style: `background:${COLOURS[k]}` }), label));
    if (!f || f.hatch) items.push(el('li', {}, el('span', { class: 'sw sw-hatch' }), 'Hatched: only 1 or 2 decisions, limited data'));
    document.getElementById('legend').replaceChildren(el('ul', {}, items),
      f ? el('p', { class: 'focus-note', text: `Showing: ${f.label.toLowerCase()}. Click the card again to show everything.` }) : '');
    const notes = {
      state: 'Each state court decision colours the state where the court sits (Court State).',
      federal: 'Each federal decision, district or appellate, colours the state where the court sits (Court State).',
      appellate: 'Only Federal Appellate decisions. Each colours every state in its circuit; where a circuit has more than one, the colour uses their combined win share.',
    };
    const circuits = circuitsShown() ? ' Dark lines and numbers show the 12 regional federal circuits (1st to 11th and D.C.); the Federal Circuit has no region, as it hears certain kinds of appeals, such as patent cases, from the whole country.' : '';
    const territories = tab === 'federal'
      ? 'Territories are not drawn: Puerto Rico (1st Circuit), the U.S. Virgin Islands (3rd), and Guam and the Northern Mariana Islands (9th).'
      : 'Territories (such as Puerto Rico, Guam, the U.S. Virgin Islands and the Northern Mariana Islands) are not drawn.';
    document.getElementById('footnote').textContent =
      `${notes[viewKey()]} Win share is wins divided by included decisions.${circuits} ${territories}`;
  }
  function renderTable() {
    const rows = Object.entries(V().states).filter(([, s]) => s.decisions || s.pending)
      .sort((a, b) => b[1].decisions - a[1].decisions || a[1].name.localeCompare(b[1].name));
    const box = document.getElementById('table');
    if (!rows.length) { box.replaceChildren(el('p', { class: 'muted', text: 'No state has decisions or pending cases in this view.' })); return; }
    box.replaceChildren(el('table', { class: 'data' },
      el('thead', {}, el('tr', {}, ['State', 'Decisions', 'Wins', 'Losses', 'Win share', 'Pending', 'Colour'].map((h) => el('th', { scope: 'col', text: h })))),
      el('tbody', {}, rows.map(([ab, s]) => el('tr', {},
        el('th', { scope: 'row' }, el('button', { class: 'linkish', text: s.name + (s.via ? ` (${s.via})` : ''), onclick: () => openPanel(ab) })),
        el('td', { text: s.decisions }), el('td', { text: s.wins }), el('td', { text: s.losses }), el('td', { text: pct(s.share) }),
        el('td', { text: s.pending }),
        el('td', {}, el('span', { class: 'sw', style: `background:${COLOURS[s.colour]}` }), ' ', COLOUR_NAMES[s.colour] + (s.hatched ? ', hatched' : '')))))));
  }

  // ---------- side panel ----------
  // Rows the daily update added (Daily Update\Litigation Tracker Daily Update.exe); the report's own rows have no flag.
  const autoBadge = (x) => (!x.auto ? null : x.byHand
    ? el('span', { class: 'badge badge-auto', text: 'Checked by a person', title: 'The AI readers could not confirm it, so a person checked it. Not in the report yet.' })
    : el('span', { class: 'badge badge-auto', text: 'Read automatically', title: 'Found and read by the daily update: two AI readers agreed on it. Not reviewed by a person.' }));
  const panel = document.getElementById('panel');
  const backdrop = document.getElementById('backdrop');
  function decisionCard(d) {
    const finality = /interlocutory|nonfinal|non-final|not final/i.test(d.status) ? ['chip-warn', 'Not final']
      : /final/i.test(d.status) ? ['chip-good', 'Final'] : null;
    return el('li', { class: 'decision' },
      el('div', { class: 'decision-top' },
        el('span', { class: `badge ${d.win ? 'badge-win' : 'badge-loss'}`, text: d.win ? 'Positive · win' : 'Negative · loss' }),
        autoBadge(d), el('span', { class: 'muted small', text: fmtDate(d.date) })),
      el('h3', { text: d.case }),
      el('p', { class: 'muted small', text: [d.court, d.levelText].filter(Boolean).join(' · ') }),
      el('p', { class: 'status' },
        finality ? el('span', { class: `chip ${finality[0]}`, text: finality[1] }) : null,
        finality ? ' ' : null, d.status || 'Status not stated'),
      d.holding ? el('p', { class: 'holding', text: d.holding, title: d.holding }) : null,
      sourceLink(d.url, 'Open source'));
  }
  function openPanel(ab) {
    const s = V().states[ab];
    lastFocus = document.activeElement;
    hideTip();
    document.getElementById('panel-title').textContent = s.name;
    const circuit = CIRCUIT_OF[ab];
    const sub = { state: 'State courts', federal: `Federal courts · all decisions${circuit ? ' · ' + circuit : ''}`,
      appellate: `Federal appellate authority · ${s.via || 'no circuit'}` }[viewKey()];
    document.getElementById('panel-sub').textContent =
      `${sub} · ${tally(s)}, win share ${pct(s.share)}`;
    const body = [];
    if (s.ids.length) {
      body.push(el('h3', { class: 'panel-h', text: 'Decisions, newest first' }));
      body.push(el('ul', { class: 'decisions' }, s.ids.map((id) => decisionCard(D.decisions[id]))));
    } else {
      body.push(el('p', { class: 'empty', text: 'No included decisions for this state in this view.' }));
    }
    if (s.pendingIds.length) {
      body.push(el('h3', { class: 'panel-h', text: 'Pending cases' }));
      body.push(el('ul', { class: 'decisions' }, s.pendingIds.map((id) => {
        const p = D.pending[id];
        return el('li', { class: 'decision' },
          el('div', { class: 'decision-top' }, el('span', { class: 'badge badge-pending', text: 'Pending' }), autoBadge(p),
            el('span', { class: 'muted small', text: 'Filed ' + fmtDate(p.filed) })),
          el('h3', { text: p.case }),
          el('p', { class: 'muted small', text: [p.court, p.docket].filter(Boolean).join(' · ') }),
          p.status ? el('p', { class: 'status', text: p.status }) : null,
          sourceLink(p.url, 'Open source'));
      })));
    } else if (!D.hasPendingSheet) {
      body.push(el('p', { class: 'muted small', text: 'This report has no Pending Cases sheet yet.' }));
    }
    if (tab === 'federal' && CIRCUIT_SITES[circuit]) {
      body.push(el('p', { class: 'muted small circuit-site' }, `${s.name} is in the ${circuit}. `, sourceLink(CIRCUIT_SITES[circuit], `${circuit} court website`)));
    }
    document.getElementById('panel-body').replaceChildren(...body);
    panel.hidden = false;
    backdrop.hidden = false;
    requestAnimationFrame(() => panel.classList.add('open'));
    document.getElementById('panel-close').focus();
  }
  function closePanel() {
    if (panel.hidden) return;
    panel.classList.remove('open');
    panel.hidden = true;
    backdrop.hidden = true;
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  }
  document.getElementById('panel-close').addEventListener('click', closePanel);
  backdrop.addEventListener('click', closePanel);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closePanel(); });

  // ---------- DOL, notes, about, resources ----------
  function statusTone(s) {
    const t = (s || '').toLowerCase();
    if (/supersed|replaced/.test(t)) return 'neutral';
    if (/vacat|withdrawn|rescind|struck|enjoin|invalid/.test(t)) return 'bad';
    if (/propos|pending|comment|review|delay|stay/.test(t)) return 'warn';
    if (/final|effective|in effect|issued|active|adopted/.test(t)) return 'good';
    return 'neutral';
  }
  function renderDol() {
    const box = document.getElementById('dol');
    document.getElementById('dol-count').textContent = D.dol && D.dol.length ? `(${D.dol.length})` : '';
    if (D.dol === null) { box.replaceChildren(el('p', { class: 'empty', text: 'No Department of Labor data in this report.' })); return; }
    if (!D.dol.length) { box.replaceChildren(el('p', { class: 'empty', text: 'The DOL Actions sheet has no rows yet.' })); return; }
    box.replaceChildren(el('ol', { class: 'timeline' }, D.dol.map((a) => el('li', {},
      el('div', { class: 'tl-date' }, el('strong', { text: fmtDate(a.issued) }), el('span', { class: 'muted small', text: 'Issued' })),
      el('div', { class: 'tl-body' },
        el('div', { class: 'tl-head' }, el('h3', { text: a.title || 'Untitled' }), autoBadge(a), a.status ? el('span', { class: `chip chip-${statusTone(a.status)}`, text: a.status }) : null),
        el('p', { class: 'muted small', text: [a.agency, a.type, a.effective ? 'Effective ' + fmtDate(a.effective) : ''].filter(Boolean).join(' · ') }),
        a.summary ? el('p', { class: 'small', text: a.summary }) : null,
        sourceLink(a.url, 'Open source'))))));
  }
  function renderNotes() {
    const c = D.counts;
    const disagree = D.notes.filter((n) => n.kind === 'Outcome and Heat Map Code disagree');
    const items = [
      el('li', { text: `${c.read} decision rows read; ${c.included} included on the map; ${c.excluded} excluded under the methodology (Heat Map Include is not Yes).` }),
      el('li', { text: disagree.length ? `${plural(disagree.length, 'row')} where Outcome and Heat Map Code disagree; Outcome is used (listed below).` : `Outcome and Heat Map Code agree on all ${c.read} rows.` }),
    ];
    const groups = {};
    for (const n of D.notes) (groups[n.kind] = groups[n.kind] || []).push(n.text);
    const detail = Object.entries(groups).map(([kind, texts]) => el('div', { class: 'note-group' },
      el('h3', { text: `${kind} (${texts.length})` }), el('ul', {}, texts.map((t) => el('li', { text: t })))));
    document.getElementById('notes').replaceChildren(el('ul', { class: 'note-summary' }, items),
      ...(detail.length ? detail : [el('p', { class: 'muted small', text: 'No unknown values and no unreadable resource files.' })]));
  }
  function renderAbout() {
    const out = [];
    if (D.methodology && D.methodology.length) {
      out.push(el('h3', { text: 'Methodology and coding (from the report)' }));
      out.push(el('dl', { class: 'method' }, D.methodology.flatMap((m) => [m.field ? el('dt', { text: m.field }) : null, el('dd', { text: m.text })])));
    } else {
      out.push(el('p', { class: 'muted', text: 'This report has no Methodology & Coding sheet.' }));
    }
    out.push(el('h3', { text: 'How this dashboard counts' }));
    out.push(el('ul', {},
      el('li', { text: 'Only rows with Heat Map Include (Recommended) = Yes are counted. A win is Outcome = Positive; a loss is Outcome = Negative.' }),
      el('li', { text: 'Interlocutory denials of dismissal are coded Positive by the report, so they count as wins; the decision panel shows each decision\'s status so final and interlocutory wins can be told apart.' }),
      el('li', { text: 'Everything is computed from the decision rows; the report\'s Dashboard Summary sheet is not used.' }),
      el('li', { text: 'Patient initials in case captions (after a/s/o, o/b/o, as subrogee of, as assignee of, on behalf of) are replaced with ***.' })));
    if (D.excludedList.length) {
      out.push(el('h3', { text: 'Rows excluded under the methodology' }));
      out.push(el('table', { class: 'data' },
        el('thead', {}, el('tr', {}, ['ID', 'Case', 'Court level', 'Status', 'Note'].map((h) => el('th', { scope: 'col', text: h })))),
        el('tbody', {}, D.excludedList.map((d) => el('tr', {},
          el('td', { text: d.id }), el('td', { text: d.case }), el('td', { text: d.levelText }), el('td', { text: d.status }), el('td', { text: d.caution }))))));
    }
    document.getElementById('about').replaceChildren(...out);
  }
  // Links (resources\links.csv) open in a new tab; files download. Badge: file type, or the link's category.
  const BADGES = { 'Court opinion': ['CASE', 'case'], Government: ['GOV', 'gov'], News: ['NEWS', 'news'], Callagy: ['CLG', 'clg'] };
  function resourceItem(r) {
    if (r.type !== 'Link') {
      return el('a', { href: '/download/' + r.token, class: 'res', download: '' },
        el('span', { class: `ftype ftype-${r.type.toLowerCase()}`, text: r.type === 'Word' ? 'DOC' : r.type }),
        el('span', { class: 'res-text' }, el('span', { class: 'res-title', text: r.title }),
          el('span', { class: 'muted small', text: `${r.type} · ${fmtDate(r.date)}` })));
    }
    const [badge, cls] = BADGES[r.category] || ['LINK', 'link'];
    return el('a', { href: r.url, class: 'res', target: '_blank', rel: 'noopener noreferrer', title: r.summary || r.title },
      el('span', { class: `ftype ftype-${cls}`, text: badge }),
      el('span', { class: 'res-text' }, el('span', { class: 'res-title', text: r.title }),
        el('span', { class: 'muted small', text: [r.category, r.source, r.date ? fmtDate(r.date) : ''].filter(Boolean).join(' · ') }),
        r.summary ? el('span', { class: 'res-sum small', text: r.summary }) : null));
  }
  function renderResources() {
    const list = document.getElementById('resources');
    const search = document.getElementById('res-search');
    const count = document.getElementById('res-count');
    if (!D.resources.length) {
      list.replaceChildren(el('li', { class: 'empty', text: 'No articles yet. Save PDF, Word or HTML files in the resources folder, or list web links in resources\\links.csv, then refresh.' }));
      return;
    }
    search.hidden = false;
    const text = (r) => [r.title, r.category, r.source, r.summary, r.type].join(' ').toLowerCase();
    const show = () => {
      const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
      const hits = D.resources.filter((r) => words.every((w) => text(r).includes(w)));
      list.replaceChildren(...(hits.length ? hits.map((r) => el('li', {}, resourceItem(r)))
        : [el('li', { class: 'empty', text: 'Nothing matches that search.' })]));
      count.textContent = words.length ? `${hits.length} of ${D.resources.length}` : `${D.resources.length} items`;
    };
    search.addEventListener('input', show);
    show();
  }

  // ---------- all cases in this view ----------
  function renderCases() {
    const v = V();
    const holder = document.getElementById('cases-summary').closest('details');
    holder.hidden = !v.caseIds;  // older exe: no case lists in the data
    if (!v.caseIds) return;
    const rows = [
      ...v.caseIds.map((id) => ({ c: D.decisions[id], date: D.decisions[id].date, pending: false })),
      ...v.pendingIds.map((id) => ({ c: D.pending[id], date: D.pending[id].filed, pending: true })),
    ].sort((a, b) => (b.date || '').localeCompare(a.date || ''));
    const box = document.getElementById('cases');
    if (!rows.length) {
      document.getElementById('cases-summary').textContent = 'All cases in this view (0)';
      box.replaceChildren(el('p', { class: 'muted', text: 'No cases in this view.' }));
      return;
    }
    const result = (c, pending) => (pending ? 'Pending' : c.win ? 'Positive win' : 'Negative loss') + (c.auto ? (c.byHand ? ' checked by a person' : ' read automatically') : '');
    box.replaceChildren(
      el('table', { class: 'data cases' },
        el('thead', {}, el('tr', {}, ['Date', 'Case', 'Court', 'State', 'Insurer', 'Result', 'Status', 'Source'].map((h) => el('th', { scope: 'col', text: h })))),
        el('tbody', {}, rows.map(({ c, date, pending }) => el('tr', {
          'data-text': words([c.case, c.court, c.state, (v.states[c.state] || {}).name, c.insurers.join(' '), c.payer, c.docket,
            result(c, pending), c.status, c.holding].filter(Boolean).join(' ')),
        },
          el('td', { text: (pending ? 'Filed ' : '') + fmtDate(date) }),
          el('td', { text: c.case }),
          el('td', { text: c.court }),
          el('td', { text: c.state }),
          el('td', { text: c.insurers.join(', ') || c.payer || '—' }),
          el('td', {}, pending ? el('span', { class: 'badge badge-pending', text: 'Pending' })
            : el('span', { class: `badge ${c.win ? 'badge-win' : 'badge-loss'}`, text: c.win ? 'Positive · win' : 'Negative · loss' }),
            c.auto ? ' ' : null, autoBadge(c)),
          el('td', { text: c.status || '—' }),
          el('td', {}, sourceLink(c.url, 'Open') || '—'))))),
      el('p', { class: 'empty', id: 'cases-none', text: 'No case in this view matches that search.', hidden: true }));
    searchCases();
  }
  // ---------- newsletter sign-up (header) ----------
  // The page's only write: the local server adds or flips a row in newsletter\Newsletter sign-ups.xlsx.
  function renderSignup() {
    const s = D.signup;
    const btn = document.getElementById('signup-btn');
    const pop = document.getElementById('signup-pop');
    if (!s) return;  // an older exe: no sign-up
    if (D.published) {  // the website cannot save anything: the button opens the newsletter's sign-up form
      if (!s.formUrl) return;
      btn.textContent = '✉ Get the newsletter';
      btn.hidden = false;
      btn.addEventListener('click', () => window.open(s.formUrl, '_blank', 'noopener'));
      return;
    }
    const input = document.getElementById('signup-email');
    const msg = document.getElementById('signup-msg');
    const yes = document.getElementById('signup-yes');
    const no = document.getElementById('signup-no');
    const show = (status) => {
      s.status = status;
      btn.textContent = status === 'Subscribed' ? '✓ Newsletter: signed up' : '✉ Get the newsletter';
      yes.hidden = status === 'Subscribed';
      no.hidden = status !== 'Subscribed';
    };
    const say = (text, bad) => { msg.textContent = text; msg.className = 'small ' + (bad ? 'signup-bad' : 'signup-good'); };
    const post = (action) => fetch('/signup', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-LT-Token': s.token },
      body: JSON.stringify({ email: input.value, action }),
    }).then((r) => r.json());
    const words = {
      added: "You're signed up. You'll get the newsletter on days with new rulings or cases.",
      resubscribed: "Welcome back: you're signed up again.", already: "You're already signed up.",
      removed: "You're unsubscribed.", 'not on the list': "That address isn't on the list.",
    };
    const act = (action) => {
      yes.disabled = no.disabled = true;
      post(action).then((j) => {
        if (j.error) say(j.error, true);
        else { show(j.status); say(words[j.result] || '', false); }
      }).catch(() => say('The dashboard could not be reached. Is it still running? Refresh the page.', true))
        .finally(() => { yes.disabled = no.disabled = false; });
    };
    show(s.status);
    btn.hidden = false;
    input.value = s.email || '';
    btn.addEventListener('click', () => {
      pop.hidden = !pop.hidden;
      btn.setAttribute('aria-expanded', String(!pop.hidden));
      if (!pop.hidden) { msg.textContent = ''; input.focus(); }
    });
    document.getElementById('signup-close').addEventListener('click', () => { pop.hidden = true; btn.setAttribute('aria-expanded', 'false'); btn.focus(); });
    yes.addEventListener('click', () => act('subscribe'));
    no.addEventListener('click', () => act('unsubscribe'));
    input.addEventListener('change', () => post('status').then((j) => { if (!j.error) show(j.status); }).catch(() => {}));
  }

  // ---------- "new data" banner ----------
  // Every 5 minutes, and when the tab is shown again, ask the local server for its data fingerprint; a change means a
  // new report, the daily update or a new resource landed since this page loaded. /version does not count as use, so
  // an unused dashboard still closes itself after an hour.
  function watchForNewData() {
    if (!D.version) return;  // an older exe
    const banner = document.getElementById('refresh-banner');
    const text = document.getElementById('refresh-text');
    const btn = document.getElementById('refresh-btn');
    btn.addEventListener('click', () => location.reload());
    const check = () => fetch('/version', { cache: 'no-store' }).then((r) => r.json()).then((j) => {
      if (j.version && j.version !== D.version) {
        text.textContent = 'New data is available.';
        btn.hidden = false;
        banner.hidden = false;
      }
    }).catch(() => {
      text.textContent = 'The dashboard has closed. Open it again from the desktop shortcut.';
      btn.hidden = true;
      banner.hidden = false;
    });
    setInterval(check, 5 * 60 * 1000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
  }

  // ---------- latest rulings (right column) ----------
  // The newest rulings in the current tab, view and insurer filter. The summary is the daily update's two-reader AI
  // summary when there is one for this ruling and outcome; otherwise the report's own holding.
  let latestShown = 5;
  function renderLatest() {
    const v = V();
    const list = document.getElementById('latest');
    const more = document.getElementById('latest-more');
    const ids = v.caseIds || [];
    if (!ids.length) {
      list.replaceChildren(el('li', { class: 'empty', text: 'No rulings in this view.' }));
      more.hidden = true;
      return;
    }
    list.replaceChildren(...ids.slice(0, latestShown).map((id) => {
      const d = D.decisions[id];
      const final = /interlocutory|nonfinal|non-final|not final|recommendation/i.test(d.status) ? 'Not final' : 'Final';
      return el('li', { class: 'latest-item' },
        el('div', { class: 'latest-top' },
          el('span', { class: `badge ${d.win ? 'badge-win' : 'badge-loss'}`, text: (d.win ? 'Win' : 'Loss') + ' · ' + final }),
          autoBadge(d), el('span', { class: 'muted small', text: fmtDate(d.date) })),
        el('h3', {}, el('button', { type: 'button', text: d.case, title: `Open ${(v.states[d.state] || {}).name || d.state} in the side panel`,
                                    onclick: () => (v.states[d.state] ? openPanel(d.state) : null) })),
        el('p', { class: 'muted small', text: [d.court, d.state].filter(Boolean).join(' · ') }),
        d.summary
          ? el('p', { class: 'latest-sum' }, el('span', { class: 'sum-label sum-ai', text: 'AI summary', title: 'Written by the daily update and checked against the order by a second reader. Not reviewed by a person.' }), d.summary)
          : d.holding ? el('p', { class: 'latest-sum' }, el('span', { class: 'sum-label', text: 'Holding' }), d.holding) : null,
        sourceLink(d.url, 'Open the order'));
    }));
    more.hidden = ids.length <= latestShown;
    more.textContent = `Show ${Math.min(5, ids.length - latestShown)} more`;
  }
  document.getElementById('latest-more').addEventListener('click', () => { latestShown += 5; renderLatest(); });

  // The search box stays as typed when the tab, view or insurer filter changes, and is applied to the new list.
  const casesSearch = document.getElementById('cases-search');
  // Each search word must start a word in the row, so "win" finds "win" but not "following", and "conn" finds "Connecticut".
  function words(text) { return ' ' + (text || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }
  function searchCases() {
    const terms = words(casesSearch.value).trim().split(' ').filter(Boolean);
    const trs = [...document.querySelectorAll('#cases tbody tr')];
    let shown = 0;
    for (const tr of trs) {
      tr.hidden = !terms.every((w) => tr.dataset.text.includes(' ' + w));
      if (!tr.hidden) shown += 1;
    }
    const none = document.getElementById('cases-none');
    if (none) none.hidden = shown > 0 || !trs.length;
    document.getElementById('cases-summary').textContent =
      `All cases in this view (${terms.length ? `${shown} of ${trs.length}` : trs.length})`;
  }
  casesSearch.addEventListener('input', searchCases);

  // ---------- insurer filter ----------
  let request = 0;  // only the newest answer is applied when choices change quickly
  function applyFilter() {
    const names = [...selected];
    document.getElementById('ins-label').textContent = !names.length ? 'All' : names.length === 1 ? names[0] : `${names.length} selected`;
    const note = document.getElementById('ins-note');
    note.textContent = names.length ? `Map, numbers and lists show only cases against: ${names.join('; ')}.` : '';
    if (!names.length) { D.views = allViews; render(); return; }
    if (D.published) {  // the website has no server to ask: work the views out here (static/views.js)
      D.views = window.LTViews.views(Object.values(D.decisions), Object.values(D.pending), names, allViews);
      render();
      return;
    }
    const mine = ++request;
    const q = new URLSearchParams([['report', D.report.name], ...names.map((n) => ['insurer', n])]);
    fetch('/views?' + q).then((r) => r.json().then((j) => [r.ok, j]))
      .then(([ok, j]) => {
        if (mine !== request) return;
        if (!ok) { note.textContent = j.error || 'The filter could not be applied. Refresh the page.'; return; }
        D.views = j;
        render();
      })
      .catch(() => { if (mine === request) note.textContent = 'The filter could not be applied. Is the dashboard still running? Refresh the page.'; });
  }
  // An older exe still running from the shared folder sends no case lists: the filter is hidden instead of failing.
  const canFilter = Array.isArray(allViews.state.caseIds);
  const insList = document.getElementById('ins-list');
  const insSearch = document.getElementById('ins-search');
  function searchInsurers() {
    const q = insSearch.value.trim().toLowerCase();
    for (const li of insList.children) li.hidden = !!q && !li.dataset.name.includes(q);
  }
  // The list holds only insurers with cases in the current view, counted in that view. A ticked insurer with no
  // cases here is unticked; returns true when that happened, so the caller re-applies the filter.
  function renderInsurers() {
    const v = allViews[viewKey()];
    const tally = {};
    for (const c of [...v.caseIds.map((id) => D.decisions[id]), ...v.pendingIds.map((id) => D.pending[id])])
      for (const n of c.insurers) tally[n] = (tally[n] || 0) + 1;
    let dropped = false;
    for (const n of selected) if (!(n in tally)) { selected.delete(n); dropped = true; }
    insList.replaceChildren(...Object.entries(tally).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name, cases]) => {
      const box = el('input', { type: 'checkbox', value: name, checked: selected.has(name) });
      box.addEventListener('change', () => { if (box.checked) selected.add(name); else selected.delete(name); applyFilter(); });
      return el('li', { 'data-name': name.toLowerCase() }, el('label', {}, box, ' ', name, el('span', { class: 'muted small', text: ` (${cases})` })));
    }));
    searchInsurers();
    return dropped;
  }
  function switchView() {
    if (canFilter && renderInsurers()) applyFilter(); else render();
  }
  if (canFilter) {
    insSearch.addEventListener('input', searchInsurers);
    document.getElementById('ins-clear').addEventListener('click', () => { selected.clear(); renderInsurers(); applyFilter(); });
  } else {
    document.getElementById('ins-filter').hidden = true;
  }

  // ---------- tabs ----------
  const circuitToggle = document.getElementById('circuit-toggle');
  const circuitCheck = document.getElementById('circuit-check');
  circuitCheck.checked = showCircuits;
  circuitCheck.addEventListener('change', () => {
    showCircuits = circuitCheck.checked;
    try { localStorage.setItem('lt-circuits', showCircuits ? 'on' : 'off'); } catch (e) { /* remembered for this visit only */ }
    if (geo) renderMap();
    renderLegend();
  });
  // "States in each federal circuit" under the map: each circuit's states (click one for its panel), its territories
  // and its court's website, then the Federal Circuit, which has no region.
  const CIRCUIT_TERRITORIES = { '1st Circuit': 'Puerto Rico', '3rd Circuit': 'U.S. Virgin Islands', '9th Circuit': 'Guam, Northern Mariana Islands' };
  function renderCircuitList() {
    const names = (ab) => allViews.appellate.states[ab].name;
    const rows = Object.keys(CIRCUIT_BADGES).map((c) => {
      const states = Object.keys(CIRCUIT_OF).filter((ab) => CIRCUIT_OF[ab] === c).sort((a, b) => names(a).localeCompare(names(b)));
      return el('tr', {},
        el('th', { scope: 'row' }, el('span', { class: 'circuit-pill', text: circuitShort(c) }), ' ', c),
        el('td', {}, states.flatMap((ab, i) => [i ? ', ' : '', el('button', { class: 'linkish', text: names(ab), onclick: () => openPanel(ab) })])),
        el('td', { text: CIRCUIT_TERRITORIES[c] || '—' }),
        el('td', {}, sourceLink(CIRCUIT_SITES[c], 'Court website')));
    });
    rows.push(el('tr', {},
      el('th', { scope: 'row' }, el('span', { class: 'circuit-pill', text: 'Fed.' }), ' ', 'Federal Circuit'),
      el('td', { text: 'No region: it hears certain kinds of appeals from the whole country, such as patent cases and claims against the federal government. Not shown on the map.' }),
      el('td', { text: '—' }),
      el('td', {}, sourceLink('https://www.cafc.uscourts.gov', 'Court website'))));
    document.getElementById('circuit-states').replaceChildren(el('table', { class: 'data circuit-table' },
      el('thead', {}, el('tr', {}, ['Circuit', 'States', 'Territories (not on the map)', 'Court'].map((h) => el('th', { scope: 'col', text: h })))),
      el('tbody', {}, rows)));
  }
  renderCircuitList();
  function render() {
    document.getElementById('view-switch').hidden = tab !== 'federal';
    circuitToggle.hidden = tab !== 'federal';
    document.getElementById('circuit-list').hidden = tab !== 'federal';
    for (const b of document.querySelectorAll('[role=tab]')) {
      const on = b.dataset.tab === tab;
      b.setAttribute('aria-selected', on);
      b.tabIndex = on ? 0 : -1;
    }
    for (const b of document.querySelectorAll('[role=radio]')) b.setAttribute('aria-checked', b.dataset.view === fedView);
    renderStrip();
    if (geo) renderMap();
    renderLegend();
    renderTable();
    renderCases();
    latestShown = 5;
    renderLatest();
    hideTip();  // a hover box left open would otherwise show the old view's numbers
    closePanel();
  }
  const tabs = [...document.querySelectorAll('[role=tab]')];
  tabs.forEach((b, i) => {
    b.addEventListener('click', () => { tab = b.dataset.tab; switchView(); });
    b.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      tab = next.dataset.tab; switchView(); next.focus();
    });
  });
  for (const b of document.querySelectorAll('[role=radio]')) b.addEventListener('click', () => { fedView = b.dataset.view; switchView(); });

  applyTheme();
  renderSignup();
  watchForNewData();
  if (canFilter) renderInsurers();
  renderDol();
  renderNotes();
  renderAbout();
  renderResources();
  render();
  fetch('static/us_states.json').then((r) => r.json()).then((g) => { geo = g; renderMap(); })
    .catch(() => { document.getElementById('map').replaceChildren(); document.querySelector('.map-wrap').append(el('p', { class: 'empty', text: 'The map shapes could not be loaded. Use the table view below.' })); });
})();
