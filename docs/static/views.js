// The three map views for a set of insurers, worked out in the page. The published website (docs\, GitHub Pages) has no
// server to ask, so this is a copy of data.views / data._view in app/data.py: keep the two in step
// (tests/test_publish.py runs both on the same data and compares them).
(function (root) {
  'use strict';
  const RED = 0.2, ORANGE = 0.5, LIGHT = 0.8;
  const band = (share) => (share < RED ? 'red' : share < ORANGE ? 'orange' : share < LIGHT ? 'lightgreen' : 'green');
  const stateColour = (wins, n, pending) => (n === 0 ? (pending ? 'blue' : 'grey') : band(wins / n));
  const byDateDesc = (key) => (a, b) => ((a[key] || '') < (b[key] || '') ? 1 : (a[key] || '') > (b[key] || '') ? -1 : 0);

  // base: the views the page arrived with (all insurers), which supply each state's name and circuit.
  function view(decisions, pending, level, appellate, base) {
    const names = base.state.states;
    const circuitOf = Object.fromEntries(Object.entries(base.appellate.states).map(([ab, s]) => [ab, s.via]));
    const circuitStates = {};
    for (const [ab, c] of Object.entries(circuitOf)) if (c) (circuitStates[c] = circuitStates[c] || []).push(ab);
    const label = (key) => (key === 'DC' ? 'D.C. Circuit' : `${key}${(() => { const n = Number(key); return n % 100 >= 10 && n % 100 <= 20 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th'); })()} Circuit`);
    const spread = (d) => (appellate ? circuitStates[label(d.circuit || '')] || [] : names[d.state] ? [d.state] : []);
    const ds = decisions.filter((d) => d.level === level && d.included && d.counted && (!appellate || d.appellate));
    const ps = pending.filter((p) => p.level === level && (!appellate || p.appellate));
    const states = {};
    for (const ab of Object.keys(names)) {
      const mine = ds.filter((d) => spread(d).includes(ab)).sort(byDateDesc('date'));
      const pend = ps.filter((p) => spread(p).includes(ab)).map((p) => p.id);
      const wins = mine.filter((d) => d.win).length;
      const n = mine.length;
      states[ab] = {
        name: names[ab].name, decisions: n, wins, losses: n - wins, share: n ? wins / n : null,
        colour: stateColour(wins, n, pend.length), hatched: n === 1 || n === 2, pending: pend.length, total: n + pend.length,
        ids: mine.map((d) => d.id), pendingIds: pend, via: appellate && circuitOf[ab] ? circuitOf[ab] : '',
      };
    }
    const wins = ds.filter((d) => d.win).length;
    const excluded = decisions.filter((d) => d.level === level && !d.included && (!appellate || d.appellate));
    return {
      summary: { included: ds.length, wins, losses: ds.length - wins, statesWithDecisions: Object.values(states).filter((s) => s.decisions).length,
        pending: ps.length, excluded: excluded.length },
      states,
      caseIds: [...ds].sort(byDateDesc('date')).map((d) => d.id),
      pendingIds: [...ps].sort(byDateDesc('filed')).map((p) => p.id),
    };
  }

  // only: the chosen standard insurer names (cases naming any of them); empty means everything.
  function views(decisions, pending, only, base) {
    if (only && only.length) {
      const set = new Set(only);
      decisions = decisions.filter((d) => (d.insurers || []).some((c) => set.has(c)));
      pending = pending.filter((p) => (p.insurers || []).some((c) => set.has(c)));
    }
    return {
      state: view(decisions, pending, 'state', false, base),
      federal: view(decisions, pending, 'federal', false, base),
      appellate: view(decisions, pending, 'federal', true, base),
    };
  }
  root.LTViews = { views };
})(typeof window !== 'undefined' ? window : globalThis);
