// node tests/js/fdb3-intent.test.mjs — the Kitchen intent card follows real controller events and receipts only.
import assert from 'node:assert/strict';
import {intentView, describe} from '../../web/fdb3-intent.js';

const view = intentView();
assert.equal(view.controller({stage: 'sending', api_name: 'add_checklist_item', args: {text: 'chop the celery'}, call_id: 'call-1'}), 'sending');
assert.equal(view.state().stage, 'sending');
// A correction withdraws the pending call: it moves to history, struck through.
assert.equal(view.controller({stage: 'withdrawn', call_id: 'call-1'}), 'withdrawn');
assert.equal(view.state(), null);
assert.deepEqual(view.history().map(row => [row.stage, describe(row)]), [['withdrawn', 'Add “chop the celery” to the checklist']]);
// The corrected call is sent and its real receipt marks it done.
view.controller({stage: 'sending', api_name: 'add_checklist_item', args: {text: 'wash the spinach'}, call_id: 'call-2'});
assert.equal(view.receipt({tool: 'add_checklist_item', args: {text: 'wash the spinach'}, result: {status: 'success', detail: 'Saved.'}}), true);
assert.equal(view.state().stage, 'done');
// A withdrawal of a different call id changes nothing.
assert.equal(view.controller({stage: 'withdrawn', call_id: 'call-9'}), null);
// If the withdrawn call had already run, a later receipt says so instead of hiding it.
assert.equal(view.receipt({tool: 'add_checklist_item', args: {text: 'chop the celery'}, result: {status: 'success'}}), true);
assert.equal(view.history()[0].stage, 'done-before-correction');
// A held write never shows as done; a failure is a failure.
view.controller({stage: 'held', api_name: 'set_checklist_item', text: 'Please explicitly confirm the action.'});
assert.equal(view.state().stage, 'held');
assert.equal(view.receipt({tool: 'set_checklist_item', args: {item_id: 'x', checked: true}, result: {status: 'error'}}), false);
assert.equal(view.state().stage, 'failed');
assert.equal(view.receipt({not: 'a receipt'}), null);
console.log('fdb3-intent: all checks passed');
