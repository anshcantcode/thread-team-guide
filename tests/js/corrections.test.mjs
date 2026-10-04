// node tests/js/corrections.test.mjs — the workspace keeps a replaced slot value only across a real revision.
import assert from 'node:assert/strict';
globalThis.document = {getElementById: () => null, addEventListener() {}, querySelectorAll: () => []};
const {trackCorrections} = await import('../../web/workspace.js');
let m = {domain: null, revision: null, slots: {}, changed: {}};
m = trackCorrections(m, {domain: 'travel', revision: 1, slots: {date: '2026-10-08', after: '18:00'}});
assert.deepEqual(m.changed, {});
m = trackCorrections(m, {domain: 'travel', revision: 2, slots: {date: '2026-10-09', after: '18:00'}});
assert.deepEqual(m.changed, {date: '2026-10-08'});
assert.equal(trackCorrections(m, {domain: 'travel', revision: 2, slots: {date: '2026-10-09', after: '18:00'}}), m, 'same revision keeps the strike-through');
m = trackCorrections(m, {domain: 'travel', revision: 3, slots: {date: '2026-10-09', after: '18:00', passengers: 2}});
assert.deepEqual(m.changed, {}, 'a newly added value is not a correction');
m = trackCorrections(m, {domain: 'weather', revision: 4, slots: {city: 'Chennai'}});
assert.deepEqual(m.changed, {}, 'a new task never shows the old task as corrected');
console.log('corrections: all checks passed');
process.exit(0); // workspace.js starts its clock timer on import
