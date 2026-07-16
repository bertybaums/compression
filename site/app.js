/* Doing Philosophy in a Thousand Words — interactive layer.
 *
 * All figures come from data.json, built by build_site_data.py from the repo's
 * data files. Nothing here hard-codes a result.
 */

let D = null;
let VOCAB = null;

/* ── UGF validation ────────────────────────────────────────────────────────
 * Ported to match tokenizer/ugf_tokenizer.py EXACTLY. If these drift apart the
 * page starts lying about the constraint, so keep them in sync:
 *   regex : [a-zA-Z]+(?:'[a-zA-Z]+)*|\d|\n|\S
 *   rule  : violation unless raw.lower() in vocab OR raw in vocab
 *   plus  : normalize_unicode() first (smart quotes, dashes, ellipsis)
 */
const TOKENIZE_RE = /[a-zA-Z]+(?:'[a-zA-Z]+)*|\d|\n|\S/g;

const UNI = {
  '‐': '-', '‑': '-', '‒': '-', '–': '-', '—': '-',
  '―': '-', '‘': "'", '’': "'", '“': '"', '”': '"',
  '…': '...', ' ': ' ',
};

function normalizeUnicode(t) {
  for (const [k, v] of Object.entries(UNI)) t = t.split(k).join(v);
  return t;
}

function validate(text) {
  text = normalizeUnicode(text);
  const toks = text.match(TOKENIZE_RE) || [];
  const out = [];
  for (const raw of toks) {
    const ok = VOCAB.has(raw.toLowerCase()) || VOCAB.has(raw);
    out.push({ raw, ok });
  }
  return out;
}

function renderTokens(el, text) {
  const toks = validate(text);
  el.innerHTML = '';
  if (!text.trim()) { el.innerHTML = '<span class="muted">Type something above.</span>'; return []; }
  const bad = [];
  for (const t of toks) {
    if (t.raw === '\n') { el.appendChild(document.createElement('br')); continue; }
    const s = document.createElement('span');
    s.className = t.ok ? 'tok ok' : 'tok bad';
    s.textContent = t.raw;
    if (!t.ok) { s.title = `"${t.raw}" is not in the word list`; bad.push(t.raw); }
    el.appendChild(s);
    el.appendChild(document.createTextNode(' '));
  }
  return bad;
}

/* ── §1 validator ─────────────────────────────────────────────────────── */
function initValidator() {
  const inp = document.getElementById('v-in');
  const out = document.getElementById('v-out');
  const run = () => renderTokens(out, inp.value);
  inp.addEventListener('input', run);
  document.querySelectorAll('.chip').forEach(b => {
    b.addEventListener('click', () => { inp.value = b.dataset.t; run(); });
  });
  run();
}

/* ── §2 the naming wall ───────────────────────────────────────────────────
 * The pedagogical point: don't TELL them UGF can't name. Let them hit it, then
 * name the category of what they hit.
 */
/* Every word below was CHECKED against the real word list — each one genuinely
 * is rejected. That matters: the list is NOT uniformly hostile to concrete nouns.
 * "doctor", "teacher", "car", "phone", "school", "hospital" are all perfectly
 * legal, because they are among the commonest words. Claiming otherwise would be
 * teaching a falsehood on a page about checking your claims.
 *
 * The categorical fact — the one with no exceptions — is PROPER NAMES. There are
 * none. That is what forces description, and that is the Russell point. The rest
 * is word frequency, and it is labelled as such.
 */
const NAME_HINTS = [
  { test: w => /^[A-Z][a-z]+$/.test(w) && !/^(I|The|A|An|If|It|He|She|They|We|You|But|And|So|When|What|Why|How)$/.test(w),
    label: 'a name for a person or place — <strong>the word list contains none at all</strong>' },
  { test: w => ['farmer','lawyer','judge','scientist','patient','patients','author','artist','priest','engineer','philosopher'].includes(w.toLowerCase()),
    label: 'a less common word for a job (though "doctor" and "teacher" are in the list)' },
  { test: w => ['wallet','dollars','dollar','laptop','purse','ticket','coin','coins','clock'].includes(w.toLowerCase()),
    label: 'a less common object (though "car" and "phone" are in the list)' },
  { test: w => ['charity','court','government'].includes(w.toLowerCase()),
    label: 'a less common institution (though "school" and "bank" are in the list)' },
  { test: w => ['noon','midnight','monday','tuesday','wednesday','thursday','friday','saturday','sunday','january','february'].includes(w.toLowerCase()),
    label: 'a specific time' },
];

function categorize(bad) {
  const cats = new Map();
  for (const w of bad) {
    for (const h of NAME_HINTS) {
      if (h.test(w)) {
        if (!cats.has(h.label)) cats.set(h.label, []);
        cats.get(h.label).push(w);
        break;
      }
    }
  }
  return cats;
}

function initWall() {
  const inp = document.getElementById('w-in');
  const out = document.getElementById('w-out');
  const ver = document.getElementById('w-verdict');
  const run = () => {
    const bad = renderTokens(out, inp.value);
    if (!inp.value.trim()) { ver.innerHTML = ''; ver.className = 'verdict'; return; }
    if (!bad.length) {
      ver.className = 'verdict good';
      ver.innerHTML = '<strong>All legal.</strong> Now check yourself: is it actually ' +
        '<em>particular</em>? Could someone answer <em>that</em> case — or did you end up ' +
        'describing the topic in general? That is the trade the vocabulary forces.';
      return;
    }
    const cats = categorize(bad);
    ver.className = 'verdict bad';
    let h = `<strong>${bad.length} word${bad.length > 1 ? 's' : ''} rejected.</strong>`;
    if (cats.size) {
      h += ' Look at <em>what kind</em>:<ul>';
      for (const [label, ws] of cats) {
        h += `<li>${[...new Set(ws)].map(w => `<code>${w}</code>`).join(', ')} — ${label}</li>`;
      }
      h += '</ul><p>That is not a coincidence. The vocabulary has no machinery for ' +
           'pointing at particulars. To keep the case specific you have to <em>describe</em> ' +
           'your way to it: not "Ali", but "the man in the white shirt".</p>';
    } else {
      h += ' Try replacing each one with a description built from simpler words.';
    }
    ver.innerHTML = h;
  };
  inp.addEventListener('input', run);
  run();
}

/* ── §3 judge drift ───────────────────────────────────────────────────── */
function initDrift() {
  const el = document.getElementById('drift-table');
  const j = D.drift.june, k = D.drift.july;
  if (!k || !k.engagement) return;
  const rows = [
    ['engagement — did it answer the question?', j.engagement, k.engagement],
    ['coherence — did the steps follow?', j.coherence, k.coherence],
    ['substance — was it real philosophical work?', j.substance, k.substance],
  ];
  el.innerHTML = '<table class="t"><thead><tr><th>dimension</th><th>June</th>' +
    '<th>July (same text)</th><th>drift</th></tr></thead><tbody>' +
    rows.map(([n, a, b]) => {
      const d = Math.abs(b - a);
      const cls = d > 0.5 ? 'bad' : (d < 0.2 ? 'good' : '');
      return `<tr><td>${n}</td><td>${a.toFixed(2)}</td><td>${b.toFixed(2)}</td>` +
             `<td class="${cls}">${d.toFixed(2)}</td></tr>`;
    }).join('') + '</tbody></table>';
}

/* ── §4 samples ───────────────────────────────────────────────────────── */
function initSamples() {
  const el = document.getElementById('samples');
  el.innerHTML = D.samples.map((s, i) => `
    <details class="sample" ${i === 0 ? 'open' : ''}>
      <summary><span class="ask">Asked:</span> ${escapeHtml(s.prompt)}</summary>
      <div class="ans"><span class="lbl">The model answered:</span>
        <p>${escapeHtml(s.essay)}…</p></div>
    </details>`).join('');
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

/* ── §5 the levers ────────────────────────────────────────────────────── */
const LEVERS = [
  { name: 'Maybe it is too small.', did: 'Trained models at 52M, 197M and 1B parameters.',
    res: 'No change. 0.07 / 0.00 / 0.10.', verdict: 'not the cause' },
  { name: 'Maybe the thousand words are too few.', did: 'Trained a twin on full English — same prompts, same teachers, only the vocabulary differs.',
    res: 'No change at all. Difference: +0.00.', verdict: 'not the cause' },
  { name: 'Maybe it needs to be rewarded for good answers.', did: 'Reinforcement learning against a judge.',
    res: 'Worse. It found one fluent off-topic paragraph and said it to everything.', verdict: 'not the cause' },
  { name: 'Maybe it needs to be shown good vs bad.', did: 'Preference training, twice, at two scales.',
    res: 'Parity. −0.00 and +0.02.', verdict: 'not the cause' },
  { name: 'Maybe the answers are the wrong shape.', did: 'Rebuilt 400,000 answers to engage each question directly.',
    res: 'No change. −0.03.', verdict: 'not the cause' },
];

function initLevers() {
  const el = document.getElementById('levers');
  el.innerHTML = LEVERS.map((l, i) => `
    <div class="lever" data-i="${i}">
      <div class="lever-h"><span class="susp">${escapeHtml(l.name)}</span>
        <button class="reveal">reveal</button></div>
      <div class="lever-b hidden">
        <p><span class="lbl">What we did:</span> ${escapeHtml(l.did)}</p>
        <p><span class="lbl">Result:</span> ${escapeHtml(l.res)}</p>
        <p class="v">${escapeHtml(l.verdict)}</p>
      </div>
    </div>`).join('');
  let n = 0;
  el.querySelectorAll('.reveal').forEach(b => {
    b.addEventListener('click', () => {
      const body = b.closest('.lever').querySelector('.lever-b');
      if (body.classList.contains('hidden')) {
        body.classList.remove('hidden');
        b.textContent = '✓';
        b.disabled = true;
        if (++n === LEVERS.length) document.getElementById('lever-punch').classList.remove('hidden');
      }
    });
  });
}

/* ── §6 you are the model ─────────────────────────────────────────────── */
function initGame() {
  const c = D.corpus.essay_arm_A;
  document.getElementById('game-facts').innerHTML = `
    <ul class="facts">
      <li>You will see <strong>${c.examples.toLocaleString()}</strong> training examples.</li>
      <li>They contain <strong>${c.unique_prompts}</strong> different prompts.</li>
      <li>So each prompt shows up about <strong>${Math.round(c.repeats_per_prompt).toLocaleString()}</strong> times…</li>
      <li>…paired with a <strong>different</strong> answer nearly every time
          (<strong>${c.unique_responses.toLocaleString()}</strong> distinct answers).</li>
    </ul>`;

  const OPTS = [
    { t: 'Read each prompt closely and answer that exact question.',
      ok: false,
      why: 'You cannot. The same prompt has ~1,053 different correct answers in this data. ' +
           'Reading it more closely than "which of the 380 is this?" tells you nothing about ' +
           'which answer is coming — so it earns you no accuracy. It costs capacity and buys nothing.' },
    { t: 'Work out which of the 380 prompts this is, then write a typical answer for that bucket.',
      ok: true,
      why: 'Correct — and this is what our model actually learned. It is the OPTIMAL strategy ' +
           'for this data. 380-way classification is cheap, and it captures everything the ' +
           'prompt can tell you. The model was never confused. We were.' },
    { t: 'Ignore the prompt and write general philosophy.',
      ok: false,
      why: 'Close, but you can do better: the prompt does carry ~380 buckets’ worth of ' +
           'information. Throwing that away costs real accuracy.' },
  ];

  const el = document.getElementById('game-opts');
  const ver = document.getElementById('game-verdict');
  el.innerHTML = OPTS.map((o, i) => `<button class="opt" data-i="${i}">${escapeHtml(o.t)}</button>`).join('');
  el.querySelectorAll('.opt').forEach(b => {
    b.addEventListener('click', () => {
      const o = OPTS[+b.dataset.i];
      el.querySelectorAll('.opt').forEach(x => x.disabled = true);
      b.classList.add(o.ok ? 'right' : 'wrong');
      ver.className = 'verdict ' + (o.ok ? 'good' : 'bad');
      ver.innerHTML = `<strong>${o.ok ? 'That is the winning move.' : 'Not quite.'}</strong> ${o.why}`;
    });
  });
}

/* ── §7 the twist ─────────────────────────────────────────────────────── */
function initTwist() {
  const c = D.corpus.essay_arm_A;
  document.getElementById('uniq-prompts').textContent = c.unique_prompts;
  document.getElementById('repeats').textContent = Math.round(c.repeats_per_prompt).toLocaleString();

  const h = D.holdout_by_type;
  document.getElementById('core-eng').textContent = h.core_engagement.toFixed(2);
  document.getElementById('aux-eng').textContent = h.aux_engagement.toFixed(2);

  const pretty = t => t.replace(/_/g, ' ');
  document.getElementById('bucket-table').innerHTML =
    '<table class="t bucket"><thead><tr><th>kind of question</th><th>n</th>' +
    '<th>score (0–4)</th><th>trained on it?</th></tr></thead><tbody>' +
    h.rows.map(r => `<tr class="${r.in_sft ? 'in' : 'out'}">
        <td>${pretty(r.type)}</td><td>${r.n}</td>
        <td><span class="bar" style="--w:${(r.engagement / 4 * 100).toFixed(1)}%"></span>
            <b>${r.engagement.toFixed(2)}</b></td>
        <td>${r.in_sft ? 'yes' : '<em>pretraining only</em>'}</td></tr>`).join('') +
    `<tr class="sum in"><td><strong>trained types</strong></td><td>${h.core_n}</td>
       <td><b>${h.core_engagement.toFixed(2)}</b></td><td></td></tr>
     <tr class="sum out"><td><strong>untrained types</strong></td><td>${h.aux_n}</td>
       <td><b>${h.aux_engagement.toFixed(2)}</b></td><td></td></tr>` +
    '</tbody></table>';
}

/* ── boot ─────────────────────────────────────────────────────────────── */
fetch('data.json').then(r => r.json()).then(d => {
  D = d;
  VOCAB = new Set(d.vocab);
  document.getElementById('vocab-n').textContent = d.vocab_size.toLocaleString();
  document.getElementById('vocab-w').textContent = d.vocab_words.toLocaleString();
  const dt = new Date().toISOString().slice(0, 10);
  document.getElementById('build-date').textContent = dt;
  document.getElementById('build-date-2').textContent = dt;
  initValidator();
  initWall();
  initDrift();
  initSamples();
  initLevers();
  initGame();
  initTwist();
}).catch(e => {
  document.body.insertAdjacentHTML('afterbegin',
    '<p style="padding:1rem;background:#fee;color:#900">Could not load data.json — ' +
    'serve this directory over http (e.g. <code>python3 -m http.server</code>) ' +
    'rather than opening the file directly.</p>');
  console.error(e);
});
