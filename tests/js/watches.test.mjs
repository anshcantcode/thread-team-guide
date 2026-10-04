// node tests/js/watches.test.mjs — formatting and "new since last seen" logic for the Watches strip.
import assert from 'node:assert/strict';
import {cadence, headline, relative, unseenIds} from '../../web/watches.js';

assert.equal(cadence(120), 'every 2 h');
assert.equal(cadence(60), 'hourly');
assert.equal(cadence(15), 'every 15 min');
assert.equal(cadence(1440), 'daily');
assert.equal(cadence(2880), 'every 2 days');
assert.equal(cadence(0), '');
const now = 1_800_000_000_000;
assert.equal(relative(now + 30 * 60000, now), 'in ~30 min');
assert.equal(relative(now - 2 * 3600000, now), '2 h ago');
assert.equal(relative(now, now), 'just now');
assert.equal(relative(null, now), '');
const watch = {history: [
  {checked_at: now, new_ids: ['b', 'c']},
  {checked_at: now - 7200000, new_ids: ['a']},
  {checked_at: now - 14400000, new_ids: []},
]};
assert.deepEqual([...unseenIds(watch, now - 3600000)].sort(), ['b', 'c']);
assert.deepEqual([...unseenIds(watch, 0)].sort(), ['a', 'b', 'c']);
assert.equal(unseenIds(watch, now).size, 0);
assert.equal(headline('City appeal delayed - Manchester Evening News', 'Manchester Evening News'), 'City appeal delayed');
assert.equal(headline('Title only', 'BBC'), 'Title only');
assert.equal(headline(' - BBC', 'BBC'), ' - BBC', 'never empties a title');
console.log('watches: all checks passed');
