// Device-owned persistence and admission. No server-provided success is accepted as a write.
const reference = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
const id = () => crypto.randomUUID().replaceAll('-', '');
const KEY = 'thread.fdb3.kitchen.v1';
export class KitchenStore {
  constructor(storage = localStorage) {
    this.storage = storage;
    const raw = storage.getItem(KEY);
    if (raw === null) this.save({session_id: id(), input_token: id(), items: [], requests: {}, last_receipt: null});
    const state = this.read();
    this.sessionId = state.session_id;
    this.inputToken = this.newInput();
  }
  read() {
    const state = JSON.parse(this.storage.getItem(KEY));
    if (!state || !reference(state.session_id) || !reference(state.input_token) || !Array.isArray(state.items) ||
        !state.requests || typeof state.requests !== 'object' || Array.isArray(state.requests)) throw Error('Saved checklist is unreadable; its data was retained.');
    return state;
  }
  save(state) { this.storage.setItem(KEY, JSON.stringify(state)); }
  newInput() {
    const state = this.read();
    if (this.sessionId && state.session_id !== this.sessionId) throw Error('The local checklist session changed. Reload to continue.');
    this.inputToken = id(); state.input_token = this.inputToken; this.save(state); return this.inputToken;
  }
  execute(request) {
    const reply = (status, detail, error) => ({status, detail, session_id: this.sessionId, request_id: request.request_id, ...(error ? {error} : {})});
    try {
      const state = this.read();
      if (!reference(request.request_id) || request.session_id !== this.sessionId || state.session_id !== this.sessionId ||
          request.input_token !== state.input_token || request.input_token !== this.inputToken)
        return reply('error', 'A newer input or ended conversation replaced this request. No action was submitted.', 'invalid_args');
      const args = request.args;
      const schema = {read_checklist: [], add_checklist_item: ['text'], set_checklist_item: ['item_id', 'checked']}[request.command];
      if (!schema || !args || typeof args !== 'object' || Array.isArray(args) ||
          Object.keys(args).sort().join(',') !== [...schema].sort().join(','))
        return reply('error', 'Invalid checklist tool or arguments.', 'invalid_args');
      if (request.command === 'add_checklist_item' && (typeof args.text !== 'string' || !args.text.trim() || args.text.length > 300 || args.text.includes('\0')))
        return reply('error', 'Invalid checklist text.', 'invalid_args');
      if (request.command === 'set_checklist_item' && (!reference(args.item_id) || typeof args.checked !== 'boolean'))
        return reply('error', 'Invalid checklist item reference or state.', 'invalid_args');
      const fingerprint = JSON.stringify([request.command, schema.map(key => [key, args[key]])]);
      if (Object.hasOwn(state.requests, request.request_id)) {
        const old = state.requests[request.request_id];
        return old.fingerprint === fingerprint ? old.result : reply('error', 'Request reference already belongs to different arguments.', 'invalid_args');
      }
      if (Object.keys(state.requests).length >= 500) return reply('error', 'The local receipt journal is full. Export and review it before starting a new checklist.', 'invalid_args');
      let result;
      if (request.command === 'read_checklist') result = {...reply('success', state.items.length ?
        state.items.map(row => `${row.checked ? 'Checked' : 'Unchecked'}: ${row.text}`).join('; ') : 'The checklist is empty.'), items: state.items};
      else if (request.command === 'add_checklist_item') {
        if (state.items.length >= 100) return reply('error', 'The checklist is full.', 'invalid_args');
        const row = {item_id: id(), text: args.text.trim(), checked: false};
        state.items.push(row);
        result = {...reply('success', `Added checklist step: ${row.text}`), item_id: row.item_id, items: state.items};
      } else {
        const row = state.items.find(row => row.item_id === args.item_id);
        if (!row) result = reply('error', 'The checklist item does not exist.', 'not_found');
        else {
          row.checked = args.checked;
          result = {...reply('success', `${row.checked ? 'Checked' : 'Unchecked'}: ${row.text}`), item_id: row.item_id, items: state.items};
        }
      }
      // One atomic localStorage replacement stores the effect and its no-replay receipt together.
      state.requests[request.request_id] = {fingerprint, result: structuredClone(result)};
      state.last_receipt = structuredClone(result); this.save(state);
      return result;
    } catch (_) {
      return reply('error', 'The local receipt could not be verified. No retry was submitted; inspect the saved checklist.', 'outcome_unknown');
    }
  }
}
