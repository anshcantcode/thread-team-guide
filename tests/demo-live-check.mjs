// CPU-only DOM fixture checks. No browser, worker, model, evaluator or device.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.textContent = ''; }
  append(...children) { this.children.push(...children); }
  replaceChildren(fragment) { this.children = fragment.children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  set src(value) { this.attributes.src = value; }
  scrollIntoView() {}
  get lastElementChild() { return this.children.at(-1); }
  querySelectorAll(selector) {
    assert.equal(selector, 'details[open]');
    return this.children.flatMap(child => [ ...(child.tagName === 'details' && child.open ? [child] : []),
      ...child.querySelectorAll(selector)]);
  }
}
const elements = new Map();
const document = {
  getElementById(id) { if (!elements.has(id)) elements.set(id, new Element('div')); return elements.get(id); },
  createElement(tag) { return new Element(tag); },
  createDocumentFragment() { return new Element('fragment'); },
};
const files = new Map();
const call = {call_id:'authored-call', function:'fixture_write', args:{item:'barley'}, outcome:'success', result:{status:'success'}};
const journal = rows => rows.map(row => JSON.stringify(row) + '\n').join('');
files.set('identity.json', JSON.stringify({source:{source_commit:'CPU-FIXTURE'},manifest_index:0,recording:'authored'}));
files.set('demo-status.json', JSON.stringify({status:'running',started_at:100}));
files.set('benchmark/stt-requests.jsonl', journal([
  {request_id:'in',filter_silence:false,outcome:'success',finished_at:101,text:'Add oats, actually barley.'},
  {request_id:'out',filter_silence:true,outcome:'success',finished_at:109,text:'OUTPUT-ASR-MUST-NOT-BE-HEARD'},
]));
files.set('benchmark/model-requests.jsonl', journal([
  {phase:'finished',recorded_at:102,request:{request_id:'model-1',content:'<img src=x onerror=alert(1)>',outcome:'cancelled'}},
]));
files.set('benchmark/controller-events.jsonl', journal([
  {action:'planning_held',bridge_received_at:101.5,payload:{seconds:0.4}},
  {action:'clarification_request',bridge_received_at:103,payload:{gate:{reasons:['authored refusal reason']}}},
  {action:'tool_call',bridge_received_at:104,payload:{call_id:call.call_id,api_name:call.function,args:call.args}},
]));
files.set('benchmark/tool-calls.jsonl', journal([{phase:'dispatch_intent',recorded_at:104,call}]));
files.set('benchmark/tts-requests.jsonl', journal([{started_at:108,outcome:'pending',text:'Authored reply line.'}]));
let scheduled;
let finishedTick;
let tickDone = new Promise(resolve => { finishedTick = resolve; });
const context = vm.createContext({document,AbortSignal,console,Map,Date,
  setTimeout(fn, ms) { assert.equal(ms,1000); scheduled = fn; finishedTick(); },
  async fetch(path, options) {
    assert.equal(options.cache,'no-store');
    assert.ok(!path.startsWith('http'), 'Viewer must never contact a model/service URL');
    return {status:files.has(path) ? 200 : 404,ok:files.has(path),text:async () => files.get(path)};
  },
});
const html = fs.readFileSync(new URL('../web/demo-live.html',import.meta.url),'utf8');
for (const match of html.matchAll(/\bid="([^"]+)"/g)) document.getElementById(match[1]);
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInContext(source, context);
await tickDone;
const rendered = () => JSON.stringify(elements.get('timeline').children);
assert.equal(elements.get('count').textContent,'0', 'Dispatch intent must not be counted as a finished execution');
assert.equal(elements.get('heard').textContent,'Add oats, actually barley.');
assert.ok(!rendered().includes('OUTPUT-ASR-MUST-NOT-BE-HEARD'));
assert.match(rendered(),/Held \/ deferred/);
assert.match(rendered(),/Refused \/ clarification/);
assert.match(rendered(),/authored refusal reason/);
assert.match(rendered(),/Admitted by controller/);
assert.match(rendered(),/not proof of invocation/);
assert.match(rendered(),/Authored reply line/);
assert.match(rendered(),/<img src=x onerror=alert\(1\)>/); // Remains textContent, no HTML parsing API is present.
assert.equal(elements.get('reply-file').getAttribute('src'),null);
assert.equal(elements.get('step-heard').getAttribute('data-on'),'true');
assert.equal(elements.get('step-executed').getAttribute('data-on'),'false', 'A dispatch intent must not light the finished step');
assert.equal(elements.get('step-replied').getAttribute('data-on'),'false', 'Pending TTS is not a spoken reply');
assert.equal(elements.get('stage').getAttribute('data-phase'),'speaking');
assert.match(elements.get('cue').textContent,/actually/);
const firstRaw = elements.get('timeline').children[0].children[2].children[1];
firstRaw.open = true;

files.set('benchmark/tool-calls.jsonl', journal([
  {phase:'dispatch_intent',recorded_at:104,call},
  {phase:'finished',recorded_at:105,call},
  {phase:'finished',recorded_at:105,call}, // Duplicate entry must not inflate unique-call count.
]) + '{"phase":');
await scheduled();
assert.equal(elements.get('count').textContent,'1');
assert.match(elements.get('status').textContent,/incomplete trailing line/);
assert.ok(elements.get('timeline').querySelectorAll('details[open]').some(el => el.dataset.key === firstRaw.dataset.key),
  'Polling must preserve an expanded raw entry while the operator inspects it');

files.set('demo-status.json', JSON.stringify({status:'completed',started_at:100}));
files.set('benchmark/result.json', JSON.stringify({status:'completed',actual_tool_calls:[call]}));
await scheduled();
assert.match(elements.get('outcomes').textContent,/Final worker actual calls: 1/);
assert.equal(elements.get('reply-file').getAttribute('src'),'benchmark/spoken.wav');
assert.equal(elements.get('stage').getAttribute('data-phase'),'done');
assert.equal(elements.get('step-executed').getAttribute('data-on'),'true');

files.set('benchmark/tool-calls.jsonl','{BROKEN COMPLETE LINE}\n');
await scheduled();
assert.match(elements.get('status').textContent,/OBSERVER ERROR/);
assert.match(elements.get('status').textContent,/stale/);
assert.equal(elements.get('stage').getAttribute('data-phase'),'error');
console.log('PASS: live viewer CPU fixtures (input-only ASR, raw proposals, real gate labels/reasons, intent vs finished, dedupe, partial/corrupt journals, TTS, fallback gating).');
