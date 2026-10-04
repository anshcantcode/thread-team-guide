// "What THREAD is doing" for the Kitchen page, built only from real events: the controller's own decisions
// (forwarded by the host as {type:'controller', stage, api_name, args, call_id, text}) and receipts the browser
// produced when it executed a checklist change. Withdrawn work is shown struck through; if a receipt later proves
// it had already run, the row says so instead of pretending it was never sent.

const LABELS = {
  add_checklist_item: args => `Add “${args.text ?? ''}” to the checklist`,
  set_checklist_item: args => `${args.checked === false ? 'Uncheck' : 'Check off'} ${args.item_id ?? 'an item'}`,
  read_checklist: () => 'Read the checklist',
};

export function describe(row) {
  if (!row) return '';
  const label = LABELS[row.api_name];
  return label ? label(row.args || {}) : String(row.api_name || '').replaceAll('_', ' ');
}

const same = (a, b) => Boolean(a && b && a.api_name === b.api_name && JSON.stringify(a.args || {}) === JSON.stringify(b.args || {}));

export function intentView() {
  let current = null;
  const history = [];
  return {
    state: () => current,
    history: () => history.slice(-3),
    /** Returns the kind of change it applied ('sending', 'withdrawn', 'held', 'asked', 'listening', 'answered'), else null. */
    controller(update) {
      switch (update?.stage) {
        case 'sending':
          current = {api_name: update.api_name, args: update.args || {}, call_id: update.call_id, stage: 'sending'};
          return 'sending';
        case 'withdrawn':
          if (current && current.stage === 'sending' && (!update.call_id || current.call_id === update.call_id)) {
            history.push({...current, stage: 'withdrawn'}); current = null; return 'withdrawn';
          }
          return null;
        case 'held': {
          const keep = current && (!update.api_name || current.api_name === update.api_name);
          current = {api_name: update.api_name || current?.api_name, args: keep ? current?.args || {} : {}, stage: 'held',
                     note: update.text || 'Waiting for your go-ahead. Nothing was sent.'};
          return 'held';
        }
        case 'asked':
          current = {...(current || {}), stage: 'asked', question: update.text || ''};
          return 'asked';
        case 'listening':
          if (!current || current.stage !== 'sending') current = {stage: 'listening', question: 'Take your time. THREAD is waiting for the rest.'};
          return 'listening';
        case 'answered':
          if (current && ['asked', 'listening', 'held'].includes(current.stage)) current = null;
          return 'answered';
        default:
          return null;
      }
    },
    /** Applies a browser-produced receipt. Returns true for success, false for a failure, null if not a receipt. */
    receipt(event) {
      if (!event || typeof event.tool !== 'string') return null;
      const ok = event.result?.status === 'success';
      const row = {api_name: event.tool, args: event.args || {}};
      const earlier = history.find(item => item.stage === 'withdrawn' && same(item, row));
      if (earlier) { earlier.stage = ok ? 'done-before-correction' : 'withdrawn'; return ok; }
      current = {...row, stage: ok ? 'done' : 'failed', note: event.result?.detail || ''};
      return ok;
    },
  };
}

const BADGE = {sending: 'sending', held: 'held · not sent yet', done: 'done', failed: 'failed', asked: 'asked you', listening: 'take your time'};

/** Renders the card into #intent, #intent-history, #intent-badge, #intent-text and #intent-note of [doc]. */
export function renderIntentCard(view, doc) {
  const $ = id => doc.getElementById(id), now = view.state(), past = view.history();
  $('intent').hidden = !now && !past.length;
  $('intent-history').replaceChildren(...past.map(row => {
    const item = doc.createElement('li'), ran = row.stage === 'done-before-correction';
    const text = doc.createElement(ran ? 'span' : 'del'); text.textContent = describe(row); item.append(text);
    const tag = doc.createElement('span'); tag.textContent = ran ? 'already done before your correction' : 'withdrawn';
    item.append(tag); return item;
  }));
  $('intent-badge').className = 'badge ' + (now?.stage || '');
  $('intent-badge').textContent = now ? (BADGE[now.stage] || now.stage) : '';
  $('intent-text').textContent = now ? (now.question || describe(now)) : '';
  $('intent-note').textContent = now?.note || '';
}
