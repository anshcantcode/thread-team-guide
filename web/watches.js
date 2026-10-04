// Standing Watches in the workspace rail. Shows only what the host's /api/watches returns: topics, cadence,
// actual check times and the attributed headlines it saved. "New" means newer than what this browser has shown
// before (remembered locally); nothing is summarised or invented. Links open only when they are http(s).

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const SEEN_KEY = 'thread-watch-seen';

export function cadence(minutes) {
  if (!Number.isFinite(minutes) || minutes <= 0) return '';
  if (minutes % 1440 === 0) return minutes === 1440 ? 'daily' : `every ${minutes / 1440} days`;
  if (minutes % 60 === 0) return minutes === 60 ? 'hourly' : `every ${minutes / 60} h`;
  return `every ${minutes} min`;
}

export function relative(ms, now = Date.now()) {
  if (!Number.isFinite(ms)) return '';
  const diff = Math.round((ms - now) / 60000), abs = Math.abs(diff);
  const text = abs < 1 ? 'now' : abs < 60 ? `${abs} min` : abs < 1440 ? `${Math.round(abs / 60)} h` : `${Math.round(abs / 1440)} d`;
  return abs < 1 ? 'just now' : diff > 0 ? `in ~${text}` : `${text} ago`;
}

/** Google News titles end with " - Source"; the source is shown on its own line, so drop the repeat. */
export function headline(title, source) {
  const text = String(title ?? ''), suffix = ` - ${source ?? ''}`;
  return source && text.endsWith(suffix) && text.length > suffix.length ? text.slice(0, -suffix.length) : text;
}

function safeLink(url) {
  try { const parsed = new URL(url); return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : null; } catch { return null; }
}

function readSeen() { try { return JSON.parse(localStorage.getItem(SEEN_KEY) || '{}'); } catch { return {}; } }
function writeSeen(seen) { try { localStorage.setItem(SEEN_KEY, JSON.stringify(seen)); } catch { /* per-browser convenience only */ } }

/** Items checked after this browser last looked at the Watch, from the host's own history. */
export function unseenIds(watch, seenAt) {
  const fresh = new Set();
  for (const entry of watch.history || []) {
    if (Number.isFinite(entry.checked_at) && entry.checked_at > (seenAt || 0)) for (const id of entry.new_ids || []) fresh.add(id);
  }
  return fresh;
}

export function mountWatches(host, {fetchImpl = fetch, every = 60000, onChange = () => {}} = {}) {
  const box = document.createElement('section');
  box.className = 'watch-strip'; box.hidden = true; box.setAttribute('aria-label', 'Standing watches');
  host.prepend(box);
  // "New" is judged against what this browser had seen when the page opened, so badges stay until the next visit.
  const seenAtOpen = readSeen();
  let timer = 0, watches = [];

  async function call(path, method = 'GET') {
    const response = await fetchImpl(path, {method, headers: {'Content-Type': 'application/json'}});
    if (!response.ok) throw new Error(`Watches unavailable (${response.status})`);
    return response.json();
  }

  function render() {
    const active = watches.filter(w => w.active);
    box.hidden = !active.length;
    if (!active.length) return;
    const seen = readSeen(), now = Date.now();
    box.innerHTML = `<header><span class="eyebrow">WATCHING · ${active.length}</span><small>New reports only · Google News, attributed</small></header>` +
      active.map(w => {
        const fresh = unseenIds(w, seenAtOpen[w.id]);
        const top = (w.items || [])[0];
        const link = top ? safeLink(top.link) : null;
        const published = top && Number.isFinite(top.published_at) ? relative(top.published_at, now) : 'date not given';
        return `<article class="watch${fresh.size ? ' has-new' : ''}" data-id="${esc(w.id)}">
          <div class="watch-top"><b>${esc(w.topic)}</b>${fresh.size ? `<span class="watch-new">${fresh.size} new</span>` : ''}</div>
          <p class="watch-meta">${esc(cadence(w.every_minutes))} · ${Number.isFinite(w.last_checked) ? `checked ${esc(relative(w.last_checked, now))}` : 'not checked yet'} · next ${esc(relative(w.next_check, now) || '—')} (approx.)</p>
          ${top ? `<p class="watch-headline">${link ? `<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(headline(top.title, top.source))}</a>` : esc(headline(top.title, top.source))}<small>${esc(top.source || 'Unknown source')} · ${esc(published)}</small></p>`
                : `<p class="watch-headline muted">${w.baseline ? 'No reports saved yet.' : 'Waiting for the first check.'}</p>`}
          <div class="watch-actions"><button data-act="check">Check now</button><button data-act="stop">Stop</button></div>
        </article>`;
      }).join('');
    // Viewing the strip marks what is now on screen as seen, in this browser only.
    for (const w of active) seen[w.id] = Math.max(seen[w.id] || 0, ...(w.history || []).map(h => h.checked_at || 0));
    writeSeen(seen);
  }

  async function refresh() {
    try { watches = (await call('/api/watches')).watches || []; render(); onChange(watches); }
    catch { box.hidden = true; }
  }

  box.addEventListener('click', async event => {
    const button = event.target.closest('button[data-act]'); if (!button) return;
    const id = button.closest('.watch')?.dataset.id; if (!id) return;
    button.disabled = true; button.closest('.watch').classList.add('checking');
    try {
      if (button.dataset.act === 'check') await call(`/api/watches/${encodeURIComponent(id)}/check`, 'POST');
      else await call(`/api/watches/${encodeURIComponent(id)}`, 'DELETE');
    } catch { /* the next refresh shows the real state */ }
    await refresh();
  });

  refresh(); timer = setInterval(refresh, every);
  return {refresh, stop() { clearInterval(timer); box.remove(); }};
}
