// Litigation Tracker page. All data arrives in the #data JSON block, already masked; the map geometry is local.
// The look and the common parts (header, tabs, tiles, tables, drawer, dropdown, dates) come from the Callagy UI kit
// 1.0 (static\vendor\callagy-ui\1.0\callagy.js, window.CUI); this file is the tracker's own map and lists.
(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('data').textContent);

  // Map colours carry meaning and never follow the brand palette (tokens --lt-* in app.css). The win share is
  // always shown as text as well.
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
  let openState = null;  // the state open in the drawer, kept in the link (#st=NJ)
  let linkedState = null;  // a state named in the link the page was opened with, opened after the first draw
  const viewKey = () => (tab === 'state' ? 'state' : fedView);
  const V = () => D.views[viewKey()];
  // Insurer filter: the chosen standard company names. Empty = all insurers (the views the page arrived with).
  let selected = new Set();
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
  // Dates in the kit's one format ("10 Nov 2026").
  const fmtDate = (iso) => (/^\d{4}-\d{2}-\d{2}/.test(iso || '') ? CUI.fmt.date(iso.slice(0, 10)) : iso || '—');
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

  // ---------- header ----------
  function renderHeader() {
    const logo = document.getElementById('logo');
    if (!D.hasLogo) logo.hidden = true;
    logo.addEventListener('error', () => { logo.hidden = true; });
    // "Data as of" is the newest of the report and the daily update that added to it.
    const run = D.report.autoRun && new Date(D.report.autoRun);
    const updated = run && !isNaN(run) && D.report.autoRun.slice(0, 10) >= D.report.date;
    CUI.header('#hdr', { asOf: updated ? D.report.autoRun.slice(0, 10) : D.report.date, expectedEveryDays: 1,
      staleNote: D.published ? undefined : 'Run the daily update to refresh it.' });
  }

  // ---------- summary tiles ----------
  // Clicking a tile shows only that tile's data on the map; the other states turn grey. Click it again to undo.
  let focus = null;
  function pick(k) { focus = focus === k ? null : k; renderStrip(); if (geo) paintMap(); renderLegend(); hideTip(); }
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
    if (!strip.children.length) {  // the tiles' boxes and their clicks are made once; the kit redraws what is inside
      for (const [k] of tiles) {
        const host = el('div', { 'data-k': k, role: 'button', tabindex: '0' });
        host.addEventListener('click', () => pick(k));
        host.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(k); } });
        strip.append(host);
      }
    }
    for (const [k, label, value, sub] of tiles) {
      const host = strip.querySelector(`[data-k="${k}"]`);
      CUI.tile(host, { id: 'lt-' + k, label, value, format: 'num' });  // counts up the first time only
      host.classList.add('lt-tile-' + k);
      host.classList.toggle('lt-tile-on', focus === k);
      host.setAttribute('aria-pressed', String(focus === k));
      host.title = focus === k ? 'Click to show everything again' : `Show ${FOCUS[k].label.toLowerCase()} on the map`;
      host.dataset.value = String(value);
      if (sub) host.append(el('div', { class: 'lt-tile-sub', text: sub }));
    }
  }
  const excludedStates = () => new Set(D.excludedList
    .filter((d) => (viewKey() === 'state' ? d.level === 'state' : d.level === 'federal' && (viewKey() !== 'appellate' || d.appellate)))
    .map((d) => d.state));
  const decisionsOnly = { label: 'Decisions only, without pending cases', colour: null, band: (s) => (s.decisions ? s.colour : 'grey'), hatch: true };
  const FOCUS = {
    included: decisionsOnly,
    states: decisionsOnly,
    wins: { label: 'States with at least one win', colour: 'green', band: (s) => (s.wins ? 'green' : 'grey') },
    losses: { label: 'States with at least one loss', colour: 'red', band: (s) => (s.losses ? 'red' : 'grey') },
    pending: { label: 'States with pending cases', colour: 'blue', band: (s) => (s.pending ? 'blue' : 'grey') },
    excluded: { label: 'States with a ruling excluded under the methodology', colour: 'slate',
                band: (s, ab) => (excludedStates().has(ab) ? 'slate' : 'grey') },
  };
  const bandOf = (s, ab) => (focus ? FOCUS[focus].band(s, ab) : s.colour);
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
    node.dataset.st = ab;
    node.addEventListener('mouseenter', (e) => showTip(ab, e.clientX, e.clientY));
    node.addEventListener('mousemove', (e) => moveTip(e.clientX, e.clientY));
    node.addEventListener('mouseleave', hideTip);
    node.addEventListener('focus', () => { const r = node.getBoundingClientRect(); showTip(ab, r.left + r.width / 2, r.top + r.height / 2); });
    node.addEventListener('blur', hideTip);
    node.addEventListener('click', () => openPanel(ab));
    node.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openPanel(ab); } });
  }
  // The map is drawn once (buildMap); a tab, view, filter or tile change only recolours it (paintMap), with a short
  // fade (app.css), instead of rebuilding every shape.
  const nodes = {};  // state -> { shape, hatch, box, boxHatch, boxCircuit }
  let circuitLines = null;
  let circuitBadges = null;
  function buildMap() {
    const map = document.getElementById('map');
    const defs = svg('defs');
    const pat = svg('pattern', { id: 'hatch', patternUnits: 'userSpaceOnUse', width: 7, height: 7, patternTransform: 'rotate(45)' });
    pat.append(svg('rect', { width: 2.4, height: 7, fill: 'rgba(255,255,255,0.85)' }));
    pat.append(svg('rect', { x: 2.4, width: 1.2, height: 7, fill: 'rgba(17,24,39,0.35)' }));
    defs.append(pat);
    const shapes = svg('g', { class: 'shapes' });
    const hatches = svg('g', { class: 'hatches', 'pointer-events': 'none' });
    for (const [ab, g] of Object.entries(geo)) {
      const p = svg('path', { d: g.d, class: 'state' });
      p.append(svg('title'));
      wire(p, ab);
      shapes.append(p);
      const h = svg('path', { d: g.d, fill: 'url(#hatch)', class: 'hatch', display: 'none' });
      hatches.append(h);
      nodes[ab] = { shape: p, hatch: h };
    }
    const boxes = svg('g', { class: 'boxes' });
    BOXES.forEach((ab, i) => {
      const y = 188 + i * 26;
      const g = svg('g', { class: 'box' });
      const r = svg('rect', { x: 916, y, width: 20, height: 20, rx: 4, class: 'state' });
      const h = svg('rect', { x: 916, y, width: 20, height: 20, rx: 4, fill: 'url(#hatch)', 'pointer-events': 'none', display: 'none' });
      const t = svg('text', { x: 942, y: y + 15, class: 'box-label' });
      t.textContent = ab;
      const c = svg('tspan', { class: 'box-circuit' });
      t.append(c);
      g.append(r, h, t);
      wire(r, ab);
      boxes.append(g);
      Object.assign(nodes[ab] = nodes[ab] || {}, { box: r, boxHatch: h, boxCircuit: c });
    });
    [circuitLines, circuitBadges] = circuitLayer(defs);
    map.replaceChildren(defs, shapes, hatches, circuitLines, boxes, circuitBadges);
    paintMap();
  }
  function paintMap() {
    const states = V().states;
    const circuits = circuitsShown();
    for (const [ab, n] of Object.entries(nodes)) {
      const s = states[ab];
      if (!s) continue;
      const band = bandOf(s, ab);
      const hatched = !!hatchOf(s);
      const label = describe(ab);
      for (const node of [n.shape, n.box]) {
        if (!node) continue;
        node.style.fill = `var(--lt-${band})`;
        node.dataset.band = band;
        node.dataset.hatched = String(hatched);
        node.setAttribute('aria-label', label);
        if (node.firstChild) node.firstChild.textContent = label;
      }
      for (const h of [n.hatch, n.boxHatch]) if (h) h.setAttribute('display', hatched ? 'inline' : 'none');
      if (n.boxCircuit) n.boxCircuit.textContent = circuits && CIRCUIT_OF[ab] ? ` · ${circuitShort(CIRCUIT_OF[ab])}` : '';
    }
    for (const layer of [circuitLines, circuitBadges]) layer.setAttribute('display', circuits ? 'inline' : 'none');
    document.getElementById('map').setAttribute('aria-label', `Map of ${viewTitle()}. Each state can be focused and opened for its decisions.`);
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

  // ---------- legend, footnote ----------
  function renderLegend() {
    const f = focus && FOCUS[focus];
    const items = f && f.colour
      ? [el('li', {}, el('span', { class: `sw sw-${f.colour}` }), f.label), el('li', {}, el('span', { class: 'sw sw-grey' }), 'Other states')]
      : LEGEND.filter(([k]) => !f || k !== 'blue').map(([k, label]) => el('li', {}, el('span', { class: `sw sw-${k}` }), label));
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

  // ---------- tables (the kit's: sort, search, CSV on the H: dashboard only) ----------
  // The website offers no download (removed by request, 30 Oct 2026), so its tables have no CSV button.
  const csvName = (n) => (D.published ? null : n);
  const stateTable = CUI.table('#table', {
    title: 'States in this view', searchPlaceholder: 'Search states', pageSize: 100, csv: csvName('litigation-tracker-states'),
    sort: { key: 'decisions', dir: 'desc' }, emptyText: 'No state has decisions or pending cases in this view.',
    onRowClick: (r) => openPanel(r.ab),
    columns: [
      { key: 'state', label: 'State' },
      { key: 'decisions', label: 'Decisions', format: 'num' },
      { key: 'wins', label: 'Wins', format: 'num' },
      { key: 'losses', label: 'Losses', format: 'num' },
      { key: 'share', label: 'Win share', format: pct, align: 'right' },  // the round-down rule, never the kit's rounding
      { key: 'pending', label: 'Pending', format: 'num' },
      { key: 'colour', label: 'Colour' },
    ],
    rows: [],
  });
  function renderTable() {
    stateTable.setRows(Object.entries(V().states).filter(([, s]) => s.decisions || s.pending)
      .sort((a, b) => b[1].decisions - a[1].decisions || a[1].name.localeCompare(b[1].name))
      .map(([ab, s]) => ({ ab, state: s.name + (s.via ? ` (${s.via})` : ''), decisions: s.decisions, wins: s.wins, losses: s.losses,
                           share: s.share, pending: s.pending, colour: COLOUR_NAMES[s.colour] + (s.hatched ? ', hatched' : '') })));
  }
  // Rows the daily update added (Daily Update\Litigation Tracker Daily Update.exe); the report's own rows have no flag.
  const autoText = (x) => (x.byHand ? 'Checked by a person' : x.fromOrder ? 'From court order' : x.fromNews ? 'From ' + x.fromNews : 'Read automatically');
  const autoBadge = (x) => (!x.auto ? null : el('span', { class: 'cui-chip lt-chip-auto', text: autoText(x), title: x.byHand
    ? 'The AI readers could not confirm it, so a person checked it. Not in the report yet.'
    : x.fromOrder ? "Listed in the District of New Jersey's stay order of Jan 16, 2026 as a suit to enforce an IDR award. Not read by AI; not in the report yet."
    : x.fromNews ? `Read from a ${x.fromNews} about the case, not the court's own order: two AI readers agreed on it. Not reviewed by a person; not in the report yet.`
    : 'Found and read by the daily update: two AI readers agreed on it. Not reviewed by a person.' }));
  const resultText = (c, pending) => (pending ? 'Pending' : c.win ? 'Positive · win' : 'Negative · loss') + (c.auto ? ' ' + autoText(c) : '');
  const caseTable = CUI.table('#cases', {
    title: 'All cases in this view', searchPlaceholder: 'Search cases: name, court, state, insurer, result', pageSize: 1000,
    csv: csvName('litigation-tracker-cases'), sort: { key: 'date', dir: 'desc' }, emptyText: 'No cases in this view.',
    onRowClick: (r) => { if (V().states[r.state]) openPanel(r.state); },
    columns: [
      { key: 'date', label: 'Date', format: 'date' },
      { key: 'case', label: 'Case' },
      { key: 'court', label: 'Court' },
      { key: 'state', label: 'State' },
      { key: 'insurer', label: 'Insurer' },
      { key: 'result', label: 'Result' },
      { key: 'status', label: 'Status' },
    ],
    rows: [],
  });
  function renderCases() {
    const v = V();
    document.getElementById('cases-card').hidden = !v.caseIds;  // older exe: no case lists in the data
    if (!v.caseIds) return;
    caseTable.setRows([
      ...v.caseIds.map((id) => [D.decisions[id], D.decisions[id].date, false]),
      ...v.pendingIds.map((id) => [D.pending[id], D.pending[id].filed, true]),
    ].map(([c, date, pending]) => ({ date: date || '', case: c.case, court: c.court, state: c.state,
      insurer: c.insurers.join(', ') || c.payer || '—', result: resultText(c, pending), status: c.status || '—' })));
  }

  // ---------- the state's decisions and pending cases (the kit's drawer) ----------
  const drawerOpen = () => document.getElementById('drawer').classList.contains('is-open');
  function decisionCard(d) {
    const finality = /interlocutory|nonfinal|non-final|not final/i.test(d.status) ? ['cui-chip--stale', 'Not final']
      : /final/i.test(d.status) ? ['cui-chip--good', 'Final'] : null;
    return el('li', { class: 'decision' },
      el('div', { class: 'decision-top' },
        el('span', { class: `cui-chip ${d.win ? 'cui-chip--good' : 'cui-chip--bad'}`, text: d.win ? 'Positive · win' : 'Negative · loss' }),
        autoBadge(d), el('span', { class: 'lt-note', text: fmtDate(d.date) })),
      el('h3', { text: d.case }),
      el('p', { class: 'lt-note', text: [d.court, d.levelText].filter(Boolean).join(' · ') }),
      el('p', { class: 'status' },
        finality ? el('span', { class: `cui-chip ${finality[0]}`, text: finality[1] }) : null,
        finality ? ' ' : null, d.status || 'Status not stated'),
      d.holding ? el('p', { class: 'holding', text: d.holding, title: d.holding }) : null,
      sourceLink(d.url, 'Open source'));
  }
  function openPanel(ab) {
    const s = V().states[ab];
    if (!s) return;
    hideTip();
    document.getElementById('panel-title').textContent = s.name;
    const circuit = CIRCUIT_OF[ab];
    const sub = { state: 'State courts', federal: `Federal courts · all decisions${circuit ? ' · ' + circuit : ''}`,
      appellate: `Federal appellate authority · ${s.via || 'no circuit'}` }[viewKey()];
    document.getElementById('panel-sub').textContent = `${sub} · ${tally(s)}, win share ${pct(s.share)}`;
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
          el('div', { class: 'decision-top' }, el('span', { class: 'cui-chip cui-chip--info', text: 'Pending' }), autoBadge(p),
            el('span', { class: 'lt-note', text: 'Filed ' + fmtDate(p.filed) })),
          el('h3', { text: p.case }),
          el('p', { class: 'lt-note', text: [p.court, p.docket].filter(Boolean).join(' · ') }),
          p.status ? el('p', { class: 'status', text: p.status }) : null,
          sourceLink(p.url, 'Open source'));
      })));
    } else if (!D.hasPendingSheet) {
      body.push(el('p', { class: 'lt-note', text: 'This report has no Pending Cases sheet yet.' }));
    }
    if (tab === 'federal' && CIRCUIT_SITES[circuit]) {
      body.push(el('p', { class: 'lt-note circuit-site' }, `${s.name} is in the ${circuit}. `, sourceLink(CIRCUIT_SITES[circuit], `${circuit} court website`)));
    }
    document.getElementById('panel-body').replaceChildren(...body);
    openState = ab;
    writeHash();
    // The kit's drawer keeps Tab inside it, closes on Esc, the backdrop or ×, and returns focus to what opened it.
    if (!drawerOpen()) CUI.drawer.open('#drawer', { onClose: () => { openState = null; writeHash(); } });
  }
  function closePanel() { if (drawerOpen()) CUI.drawer.close(); }

  // ---------- DOL, notes, about, resources ----------
  function statusTone(s) {
    const t = (s || '').toLowerCase();
    if (/supersed|replaced/.test(t)) return 'plain';
    if (/vacat|withdrawn|rescind|struck|enjoin|invalid/.test(t)) return 'bad';
    if (/propos|pending|comment|review|delay|stay/.test(t)) return 'stale';
    if (/final|effective|in effect|issued|active|adopted/.test(t)) return 'good';
    return 'plain';
  }
  function renderDol() {
    const box = document.getElementById('dol');
    document.getElementById('dol-count').textContent = D.dol && D.dol.length ? `(${D.dol.length})` : '';
    if (D.dol === null) { box.replaceChildren(el('p', { class: 'empty', text: 'No Department of Labor data in this report.' })); return; }
    if (!D.dol.length) { box.replaceChildren(el('p', { class: 'empty', text: 'The DOL Actions sheet has no rows yet.' })); return; }
    box.replaceChildren(el('ol', { class: 'timeline' }, D.dol.map((a) => el('li', {},
      el('div', { class: 'tl-date' }, el('strong', { text: fmtDate(a.issued) }), el('span', { class: 'lt-note', text: 'Issued' })),
      el('div', { class: 'tl-body' },
        el('div', { class: 'tl-head' }, el('h3', { text: a.title || 'Untitled' }), autoBadge(a), a.status ? el('span', { class: `cui-chip cui-chip--${statusTone(a.status)}`, text: a.status }) : null),
        el('p', { class: 'lt-note', text: [a.agency, a.type, a.effective ? 'Effective ' + fmtDate(a.effective) : ''].filter(Boolean).join(' · ') }),
        a.summary ? el('p', { class: 'status', text: a.summary }) : null,
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
      ...(detail.length ? detail : [el('p', { class: 'lt-note', text: 'No unknown values and no unreadable resource files.' })]));
  }
  function renderAbout() {
    const out = [];
    if (D.methodology && D.methodology.length) {
      out.push(el('h3', { text: 'Methodology and coding (from the report)' }));
      out.push(el('dl', { class: 'method' }, D.methodology.flatMap((m) => [m.field ? el('dt', { text: m.field }) : null, el('dd', { text: m.text })])));
    } else {
      out.push(el('p', { class: 'lt-note', text: 'This report has no Methodology & Coding sheet.' }));
    }
    out.push(el('h3', { text: 'How this dashboard counts' }));
    out.push(el('ul', {},
      el('li', { text: 'Only rows with Heat Map Include (Recommended) = Yes are counted. A win is Outcome = Positive; a loss is Outcome = Negative.' }),
      el('li', { text: 'Interlocutory denials of dismissal are coded Positive by the report, so they count as wins; the decision panel shows each decision\'s status so final and interlocutory wins can be told apart.' }),
      el('li', { text: 'Everything is computed from the decision rows; the report\'s Dashboard Summary sheet is not used.' }),
      el('li', { text: 'Patient initials in case captions (after a/s/o, o/b/o, as subrogee of, as assignee of, on behalf of) are replaced with ***.' })));
    if (D.excludedList.length) {
      out.push(el('h3', { text: 'Rows excluded under the methodology' }));
      out.push(el('div', { class: 'cui-table-scroll' }, el('table', { class: 'cui-table lt-static' },
        el('thead', {}, el('tr', {}, ['ID', 'Case', 'Court level', 'Status', 'Note'].map((h) => el('th', { scope: 'col', text: h })))),
        el('tbody', {}, D.excludedList.map((d) => el('tr', {},
          el('td', { text: d.id }), el('td', { text: d.case }), el('td', { text: d.levelText }), el('td', { text: d.status }), el('td', { text: d.caution })))))));
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
          el('span', { class: 'lt-note', text: `${r.type} · ${fmtDate(r.date)}` })));
    }
    const [badge, cls] = BADGES[r.category] || ['LINK', 'link'];
    return el('a', { href: r.url, class: 'res', target: '_blank', rel: 'noopener noreferrer', title: r.summary || r.title },
      el('span', { class: `ftype ftype-${cls}`, text: badge }),
      el('span', { class: 'res-text' }, el('span', { class: 'res-title', text: r.title }),
        el('span', { class: 'lt-note', text: [r.category, r.source, r.date ? fmtDate(r.date) : ''].filter(Boolean).join(' · ') }),
        r.summary ? el('span', { class: 'res-sum', text: r.summary }) : null));
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
    const say = (text, bad) => { msg.textContent = text; msg.className = 'lt-note ' + (bad ? 'signup-bad' : 'signup-good'); };
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
          el('span', { class: `cui-chip ${d.win ? 'cui-chip--good' : 'cui-chip--bad'}`, text: (d.win ? 'Win' : 'Loss') + ' · ' + final }),
          autoBadge(d), el('span', { class: 'lt-note', text: fmtDate(d.date) })),
        el('h3', {}, el('button', { type: 'button', text: d.case, title: `Open ${(v.states[d.state] || {}).name || d.state} in the side panel`,
                                    onclick: () => (v.states[d.state] ? openPanel(d.state) : null) })),
        el('p', { class: 'lt-note', text: [d.court, d.state].filter(Boolean).join(' · ') }),
        d.summary
          ? el('p', { class: 'latest-sum' }, el('span', { class: 'sum-label sum-ai', text: 'AI summary', title: 'Written by the daily update and checked against the order by a second reader. Not reviewed by a person.' }), d.summary)
          : d.holding ? el('p', { class: 'latest-sum' }, el('span', { class: 'sum-label', text: 'Holding' }), d.holding) : null,
        sourceLink(d.url, 'Open the order'));
    }));
    more.hidden = ids.length <= latestShown;
    more.textContent = `Show ${Math.min(5, ids.length - latestShown)} more`;
  }
  document.getElementById('latest-more').addEventListener('click', () => { latestShown += 5; renderLatest(); });

  // ---------- links: #tab=federal&view=appellate&ins=Aetna (CVS Health)|Cigna&st=NJ ----------
  // The kit's tabs keep "tab" (and remember the last one); the tracker adds its view, insurers and open state.
  function writeHash(push) {
    CUI.hash.set({ tab, view: tab === 'federal' && fedView === 'appellate' ? 'appellate' : null,
                   ins: selected.size ? [...selected].join('|') : null, st: openState }, push);
  }
  const fromHash = () => {
    const h = CUI.hash.get();
    return { view: h.view === 'appellate' ? 'appellate' : 'federal', ins: new Set((h.ins || '').split('|').filter(Boolean)), st: h.st || null, tab: h.tab };
  };

  // ---------- insurer filter (the kit's dropdown) ----------
  let request = 0;  // only the newest answer is applied when choices change quickly
  let viewsFor = '';  // the insurer choice D.views was worked out for ('' = all)
  const choiceKey = () => [...selected].sort().join('|');
  function applyFilter() {
    const names = [...selected];
    document.getElementById('ins-clear').hidden = !names.length;
    const note = document.getElementById('ins-note');
    note.textContent = names.length ? `Map, numbers and lists show only cases against: ${names.join('; ')}.` : '';
    writeHash();
    const key = choiceKey();
    if (!names.length) { D.views = allViews; viewsFor = ''; render(); return; }
    if (D.published) {  // the website has no server to ask: work the views out here (static/views.js)
      D.views = window.LTViews.views(Object.values(D.decisions), Object.values(D.pending), names, allViews);
      viewsFor = key;
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
        viewsFor = key;
        render();
      })
      .catch(() => { if (mine === request) note.textContent = 'The filter could not be applied. Is the dashboard still running? Refresh the page.'; });
  }
  // An older exe still running from the shared folder sends no case lists: the filter is hidden instead of failing.
  const canFilter = Array.isArray(allViews.state.caseIds);
  let insSelect = null;
  // The list holds only insurers with cases in the current view, counted in that view. A chosen insurer with no
  // cases here is dropped from the choice.
  function renderInsurers() {
    const v = allViews[viewKey()];
    const counts = {};
    for (const c of [...v.caseIds.map((id) => D.decisions[id]), ...v.pendingIds.map((id) => D.pending[id])])
      for (const n of c.insurers) counts[n] = (counts[n] || 0) + 1;
    for (const n of selected) if (!(n in counts)) selected.delete(n);
    insSelect = CUI.select('#ins-select', {
      label: 'Insurers', labelledBy: 'ins-label', multiple: true, placeholder: 'All', value: [...selected],
      options: Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name, n]) => ({ value: name, label: `${name} (${n})` })),
      onChange: (values) => { selected = new Set(values); applyFilter(); },
    });
    document.getElementById('ins-clear').hidden = !selected.size;
  }
  function switchView() {
    if (canFilter) renderInsurers();
    if (choiceKey() === viewsFor) render(); else applyFilter();
  }
  if (canFilter) {
    document.getElementById('ins-clear').addEventListener('click', () => { selected.clear(); insSelect.clear(); applyFilter(); });
  } else {
    document.getElementById('ins-filter').hidden = true;
  }

  // ---------- circuits ----------
  const circuitToggle = document.getElementById('circuit-toggle');
  const circuitCheck = document.getElementById('circuit-check');
  circuitCheck.checked = showCircuits;
  circuitCheck.addEventListener('change', () => {
    showCircuits = circuitCheck.checked;
    try { localStorage.setItem('lt-circuits', showCircuits ? 'on' : 'off'); } catch (e) { /* remembered for this visit only */ }
    if (geo) paintMap();
    renderLegend();
  });
  // "States in each federal circuit": each circuit's states (click one for its panel), its territories and its
  // court's website, then the Federal Circuit, which has no region. A plain table in the kit's look: it holds links.
  const CIRCUIT_TERRITORIES = { '1st Circuit': 'Puerto Rico', '3rd Circuit': 'U.S. Virgin Islands', '9th Circuit': 'Guam, Northern Mariana Islands' };
  function renderCircuitList() {
    const names = (ab) => allViews.appellate.states[ab].name;
    const rows = Object.keys(CIRCUIT_BADGES).map((c) => {
      const states = Object.keys(CIRCUIT_OF).filter((ab) => CIRCUIT_OF[ab] === c).sort((a, b) => names(a).localeCompare(names(b)));
      return el('tr', {},
        el('th', { scope: 'row' }, el('span', { class: 'circuit-pill', text: circuitShort(c) }), ' ', c),
        el('td', {}, states.flatMap((ab, i) => [i ? ', ' : '', el('button', { type: 'button', class: 'linkish', text: names(ab), onclick: () => openPanel(ab) })])),
        el('td', { text: CIRCUIT_TERRITORIES[c] || '—' }),
        el('td', {}, sourceLink(CIRCUIT_SITES[c], 'Court website')));
    });
    rows.push(el('tr', {},
      el('th', { scope: 'row' }, el('span', { class: 'circuit-pill', text: 'Fed.' }), ' ', 'Federal Circuit'),
      el('td', { text: 'No region: it hears certain kinds of appeals from the whole country, such as patent cases and claims against the federal government. Not shown on the map.' }),
      el('td', { text: '—' }),
      el('td', {}, sourceLink('https://www.cafc.uscourts.gov', 'Court website'))));
    document.getElementById('circuit-states').replaceChildren(el('div', { class: 'cui-table-scroll' }, el('table', { class: 'cui-table lt-static' },
      el('thead', {}, el('tr', {}, ['Circuit', 'States', 'Territories (not on the map)', 'Court'].map((h) => el('th', { scope: 'col', text: h })))),
      el('tbody', {}, rows))));
  }

  // ---------- one render for the tab, view and filter ----------
  function render() {
    document.getElementById('view-switch').hidden = tab !== 'federal';
    circuitToggle.hidden = tab !== 'federal';
    document.getElementById('circuit-list').hidden = tab !== 'federal';
    for (const b of document.querySelectorAll('#view-switch [role=radio]')) b.setAttribute('aria-checked', b.dataset.view === fedView);
    renderStrip();
    if (geo) paintMap();
    renderLegend();
    renderTable();
    renderCases();
    latestShown = 5;
    renderLatest();
    hideTip();  // a hover box left open would otherwise show the old view's numbers
    closePanel();
    if (linkedState) {  // a link's #st= opens once the numbers it belongs with are drawn
      const ab = linkedState;
      linkedState = null;
      if (V().states[ab]) openPanel(ab);
    }
  }
  for (const b of document.querySelectorAll('#view-switch [role=radio]')) {
    b.addEventListener('click', () => { fedView = b.dataset.view; writeHash(true); switchView(); });
  }

  // ---------- start ----------
  renderHeader();
  renderSignup();
  watchForNewData();
  renderDol();
  renderNotes();
  renderAbout();
  renderResources();
  renderCircuitList();
  const start = fromHash();
  fedView = start.view;
  selected = start.ins;
  linkedState = start.st;
  // Back and Forward, and a pasted link, restore the view, insurers and open state (the kit's tabs do the tab).
  const restore = () => {
    const h = fromHash();
    const same = h.view === fedView && choiceKey() === [...h.ins].sort().join('|');
    fedView = h.view;
    selected = h.ins;
    if (!same && (!h.tab || h.tab === tab)) switchView();
    setTimeout(() => { if (h.st !== openState) { if (h.st && V().states[h.st]) openPanel(h.st); else closePanel(); } }, 0);
  };
  window.addEventListener('popstate', restore);
  window.addEventListener('hashchange', restore);
  // The kit's tabs: the last tab is remembered, links carry #tab=, and the content moves into the open tab's panel.
  const content = document.getElementById('content');
  CUI.tabs('#tabs', { key: 'litigation-tracker', onChange: (name, panel) => { tab = name; panel.append(content); switchView(); } });
  // The map's shapes load separately: a loading shape shows until they arrive.
  const mapWrap = document.getElementById('map-wrap');
  CUI.skeleton.show(mapWrap, 'chart');
  fetch('static/us_states.json').then((r) => r.json()).then((g) => { geo = g; buildMap(); CUI.skeleton.hide(mapWrap); })
    .catch(() => {
      CUI.skeleton.hide(mapWrap);
      document.getElementById('map').replaceChildren();
      mapWrap.append(el('p', { class: 'empty', text: 'The map shapes could not be loaded. Use the table of states below.' }));
    });
})();
