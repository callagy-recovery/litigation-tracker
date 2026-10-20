// One-off: turns us-atlas (states-albers-10m, already projected to 975x610) into app/static/us_states.json,
// so the dashboard draws the map offline with plain SVG and no JavaScript library.
// Usage: npm install us-atlas@3 topojson-client@3 d3-geo@3   then
//        node make_map.cjs <path to that node_modules> <output json>
const path = require('path');
const fs = require('fs');
const [mods, out] = process.argv.slice(2);
const req = (m) => require(path.join(mods, m));
const topo = req('us-atlas/states-albers-10m.json');
const { feature } = req('topojson-client');
const { geoPath } = req('d3-geo');

const FIPS = {
  '01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA', '08': 'CO', '09': 'CT', '10': 'DE', '11': 'DC',
  '12': 'FL', '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN', '19': 'IA', '20': 'KS', '21': 'KY',
  '22': 'LA', '23': 'ME', '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS', '29': 'MO', '30': 'MT',
  '31': 'NE', '32': 'NV', '33': 'NH', '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND', '39': 'OH',
  '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI', '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT',
  '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI', '56': 'WY',
};
const p = geoPath().digits(1);
const states = {};
for (const f of feature(topo, topo.objects.states).features) {
  const c = p.centroid(f).map((v) => Math.round(v));
  states[FIPS[f.id]] = { name: f.properties.name, d: p(f), c };
}
fs.writeFileSync(out, JSON.stringify(states));
console.log(Object.keys(states).length, 'states written to', out);
