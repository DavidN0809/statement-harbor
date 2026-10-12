// PaperPull Server, where the panel is in a browser on another computer.
const SERVER = __SERVER__;
async function saveRoot() {
  const root = $('rootinput').value.trim();
  $('rootmsg').textContent = '';
  if (!root) { $('rootmsg').textContent = 'paste the folder path first'; return; }
  let r;
  try {
    r = await fetch('/api/root', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({root})});
  } catch (e) { $('rootmsg').textContent = 'could not reach the control panel'; return; }
  const d = await r.json();
  if (!r.ok) { $('rootmsg').textContent = d.detail || 'that did not work'; return; }
  if (d.apps === 0) {
    $('rootmsg').textContent = 'saved, but no downloaders were found there yet';
  } else {
    $('rootmsg').textContent = 'found ' + d.apps + ' downloader' + (d.apps === 1 ? '' : 's');
  }
  STATUS_LOADED = false; XL_LOADED = false;
  await load();
}

function changeRoot() {
  $('setup').style.display = 'block';
  $('rootinput').value = META.apps_root || '';
  $('rootinput').focus();
}

async function setSample(on) {
  const r = await fetch('/api/sample', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                        body: JSON.stringify({on: on})});
  if (!r.ok) { alert(((await r.json()).detail) || 'could not switch'); return; }
  STATUS_LOADED = false; XL_LOADED = false;
  showTab('out');
  await load();
}
const openSample = () => setSample(true);
const leaveSample = () => setSample(false);

let PROVIDERS = null;

function showSetup(on) {
  $('setup').style.display = on ? 'block' : 'none';
  document.querySelector('main').style.display = on ? 'none' : '';
}

function toggleExisting() {
  const e = $('existing');
  e.style.display = e.style.display === 'none' ? 'block' : 'none';
  if (e.style.display === 'block') $('rootinput').focus();
}

async function loadProviders(onlyMissing) {
  const d = await (await fetch('/api/providers')).json();
  PROVIDERS = d;
  if (!$('newroot').value) $('newroot').value = d.suggested_root || '';
  const box = $('providers');
  if (!d.templates) { box.textContent = 'No provider templates are available in this copy.'; return; }
  const rows = d.providers.filter(p => !onlyMissing || !p.installed);
  if (!rows.length) { box.textContent = 'Every provider is already set up.'; return; }
  box.innerHTML = rows.map(p =>
    '<label><input type="checkbox" value="' + esc(p.slug) + '"' +
    (p.installed ? ' disabled checked' : '') + '>' +
    '<span><b>' + esc(p.provider) + '</b>' +
    (p.documents ? '<span class="hint">' + esc(p.documents) + '</span>' : '') +
    (p.tested === false ? '<span class="hint warn">Not run on a real account yet</span>' : '') +
    (p.note ? '<span class="hint">' + esc(p.note) + '</span>' : '') +
    (p.installed ? '<span class="hint">already set up</span>' : '') +
    '</span></label>').join('');
}

async function createInstalls() {
  const root = $('newroot').value.trim();
  const picked = [...document.querySelectorAll('#providers input:checked:not(:disabled)')].map(i => i.value);
  $('newmsg').textContent = '';
  if (!root) { $('newmsg').textContent = 'choose a folder first'; return; }
  if (!picked.length) { $('newmsg').textContent = 'tick at least one provider'; return; }
  // Asked here because an app started from this panel has no stdin to
  // ask on, and without it redaction cannot take this person's name out
  // of a survey or a recording.
  const owner = (prompt(
    'Whose documents are these?\n\n' +
    'The name on the account, as the provider writes it. It never leaves ' +
    'this computer. It is what lets PaperPull remove your name from a file ' +
    'before you send it to anyone.\n\n' +
    'Leave it blank to skip.') || '').trim();
  $('newmsg').textContent = 'setting up...';
  let r;
  try {
    r = await fetch('/api/create', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({root, providers: picked, owner})});
  } catch (e) { $('newmsg').textContent = 'could not reach the control panel'; return; }
  const d = await r.json();
  if (!r.ok) { $('newmsg').textContent = d.detail || 'that did not work'; return; }
  STATUS_LOADED = false; XL_LOADED = false;
  await load();
  const n = d.created.length;
  $('console').textContent =
    'Set up ' + n + ' provider' + (n === 1 ? '' : 's') + ' under\n' + d.root +
    (d.owner ? '\nDocuments will be filed under ' + d.owner + '.' :
     '\nNo name was given, so nothing can be removed from a file for you.') +
    '\n\nNext: pick one above, click Login, and sign in when the browser opens.';
}

async function addProvider() {
  showSetup(true);
  $('newuser').style.display = 'block';
  $('existing').style.display = 'none';
  $('newroot').value = META.apps_root || '';
  await loadProviders(true);
}

async function addAccount() {
  const name = $('app').value;
  if (!name) return;
  const label = (prompt(
    'A second person on "' + name + '".\n\n' +
    'They get their own folder beside this one, their own sign-in window and their own ' +
    'download history, so nothing mixes with the first account.\n\n' +
    'Short label for the account (letters, digits, - or _), for example spouse or alex:') || '').trim();
  if (!label) return;
  const owner = (prompt('Their name, as it should appear on the documents (optional):') || '').trim();
  let r;
  try {
    r = await fetch('/api/account', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({app: name, label, owner})});
  } catch (e) { $('console').textContent = 'could not reach the control panel'; return; }
  const d = await r.json();
  if (!r.ok) { $('console').textContent = d.detail || 'that did not work'; return; }
  STATUS_LOADED = false;
  await load();
  $('app').value = name; onApp();
  $('account').value = d.account;
  $('console').textContent =
    'Added "' + d.account + '" to ' + name + (d.owner ? ' for ' + d.owner : '') + '.\n\n' +
    'Downloads go to ' + d.output_dir + '\n' +
    (d.cdp_url ? 'Sign-in browser on ' + d.cdp_url + '\n' : '') +
    '\nThe Account box above is set to it. Click Login, sign in as that person in the window ' +
    'that opens, then Pilot.';
}

async function removeProvider() {
  const name = $('app').value;
  if (!name) return;
  const ok = confirm(
    'Remove "' + name + '" from PaperPull?\n\n' +
    'Nothing is deleted. Its folder is moved into a "Removed" folder beside the ' +
    'others, with its PDFs, download history and signed-in browser profile all ' +
    'still inside. Delete that folder yourself whenever you are sure.\n\n' +
    'It will no longer appear in this list.');
  if (!ok) return;
  let r;
  try {
    r = await fetch('/api/remove', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({app: name})});
  } catch (e) { $('console').textContent = 'could not reach the control panel'; return; }
  const d = await r.json();
  if (!r.ok) { $('console').textContent = d.detail || 'that did not work'; return; }
  STATUS_LOADED = false; XL_LOADED = false;
  await load();
  const kept = [];
  if (d.pdfs) kept.push(d.pdfs + ' PDF' + (d.pdfs === 1 ? '' : 's'));
  if (d.history) kept.push('a history of ' + d.history + ' document' + (d.history === 1 ? '' : 's'));
  if (d.profile) kept.push('a signed-in browser profile');
  $('console').textContent =
    'Removed "' + d.app + '" from the list.\n\nIts folder was moved to\n' + d.moved_to +
    (kept.length ? '\n\nStill inside it: ' + kept.join(', ') + '.' : '') +
    '\n\nNothing was deleted. Delete that folder yourself when you are sure you no longer ' +
    'need what is in it. Until then, moving it back restores the provider.';
}

// -- moving to another computer (#67) -----------------------------------------
// One box. On the welcome page of a new computer it brings a history file in,
// setting up what the file names. On the Status tab it writes one too.
const HX_LEAD_WELCOME =
  'Choose the history file you saved with Export history on the Status tab of your ' +
  'other computer. Each provider and person in it is set up here with their settings, ' +
  'and every document they already downloaded is marked as downloaded, so none of them ' +
  'is downloaded here again. No sign-in comes with the file, so you sign in to each ' +
  'provider here yourself.';
const HX_LEAD_STATUS =
  'Export history saves a file that lists each provider and person here, their settings, ' +
  'and every document each one has already downloaded. Import it on another computer, or ' +
  'on PaperPull Server, and nothing you already have is downloaded there again. It holds ' +
  'no password, no sign-in and no PDF. It does hold document titles, order numbers, totals ' +
  'and the account holders\' names, so keep it as private as your documents.';
const HX_PLAN = {'set up': 'set up here', 'add person': 'added here', 'fill in': 'already here'};
const HX_DONE = {'set up': 'set up', 'add person': 'added', 'fill in': 'filled in'};
let HX_FILE = '';

function placeMove(welcome) {
  (welcome ? $('setupmove') : $('stmove')).append($('movebox'));
  $('hxhead').style.display = welcome ? 'none' : '';
  $('hxexportrow').style.display = welcome ? 'none' : '';
  $('hxlead').textContent = welcome ? HX_LEAD_WELCOME : HX_LEAD_STATUS;
}
function toggleMove() {
  const b = $('setupmove');
  b.style.display = b.style.display === 'none' ? 'block' : 'none';
}
function hxWelcome() { return $('setup').style.display === 'block'; }
function hxReset() {
  HX_FILE = ''; $('hxfile').value = '';
  $('hximport').style.display = 'none';
}

async function exportHistory() {
  $('hxmsg').textContent = 'writing the file...';
  let r;
  try { r = await fetch('/api/history/export'); }
  catch (e) { $('hxmsg').textContent = 'could not reach the control panel'; return; }
  if (!r.ok) {
    let d = {}; try { d = await r.json(); } catch (e) {}
    $('hxmsg').textContent = d.detail || 'that did not work'; return;
  }
  const blob = await r.blob();
  const named = /filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') || '');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = named ? named[1] : 'PaperPull history.ppz';
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  $('hxmsg').textContent = 'Saved ' + a.download + ' with your downloads. Keep it as private as your documents.';
}

async function hxPost(url) {
  const body = {file: HX_FILE, root: hxWelcome() ? $('newroot').value.trim() : ''};
  let r;
  try {
    r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                          body: JSON.stringify(body)});
  } catch (e) { $('hxmsg').textContent = 'could not reach the control panel'; return null; }
  let d = {}; try { d = await r.json(); } catch (e) {}
  if (!r.ok) { $('hxmsg').textContent = d.detail || 'that did not work'; return null; }
  return d;
}

function hxTable(d, done) {
  const why = r => r.failed ? r.failed : r.action === 'skipped' ? 'skipped, ' + r.why
                 : (done ? HX_DONE : HX_PLAN)[r.action];
  const rows = d.rows.map(r =>
    '<tr><td>' + esc(r.provider) + '</td><td>' + esc(r.account === 'primary' ? '' : r.account) +
    '</td><td>' + esc(why(r)) + '</td><td class="num">' + r.records + '</td>' +
    '<td class="num">' + r.downloaded + '</td></tr>').join('');
  return '<table class="st"><thead><tr><th>Provider</th><th>Person</th><th>Here</th>' +
    '<th class="num">Documents</th><th class="num">Downloaded</th></tr></thead><tbody>' +
    rows + '</tbody></table>';
}

function hxCounts(d) {
  const ok = d.rows.filter(r => r.action !== 'skipped' && !r.failed);
  const n = a => ok.filter(r => r.action === a).length;
  return {setUp: n('set up'), people: n('add person'), filled: n('fill in'),
          skipped: d.rows.length - ok.length,
          docs: ok.reduce((s, r) => s + r.downloaded, 0),
          changes: n('set up') + n('add person') +
                   ok.reduce((s, r) => s + (r.new || 0) + (r.marked || 0), 0)};
}

function hxSaying(c, done) {
  const parts = [];
  const many = (k, one, more) => k + ' ' + (k === 1 ? one : more);
  if (c.setUp) parts.push((done ? 'set up ' : 'sets up ') + many(c.setUp, 'provider', 'providers'));
  if (c.people) parts.push((done ? 'added ' : 'adds ') + many(c.people, 'person', 'people'));
  if (c.filled) parts.push((done ? 'added to ' : 'adds to ') + 'the history of ' +
                           c.filled + ' already here');
  const said = parts.length > 1
    ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts.join('');
  let s = (done ? 'Imported. It ' : 'Importing ') + said + '. ' +
    many(c.docs, 'document', 'documents') + ' downloaded on the other computer ' +
    (done ? 'will' : 'would') + ' never be downloaded here again.';
  if (c.skipped) s += ' ' + many(c.skipped, 'line was', 'lines were') + ' skipped, as the table says.';
  return s;
}

async function planHistory() {
  const f = $('hxfile').files[0];
  HX_FILE = ''; $('hxplan').innerHTML = ''; $('hximport').style.display = 'none';
  $('hxmsg').textContent = '';
  if (!f) return;
  if (f.size > 12 * 1024 * 1024) { $('hxmsg').textContent = 'that file is far larger than any download history'; return; }
  $('hxmsg').textContent = 'reading the file...';
  try {
    const url = await new Promise((ok, no) => {
      const rd = new FileReader();
      rd.onload = () => ok(String(rd.result)); rd.onerror = () => no(rd.error);
      rd.readAsDataURL(f);
    });
    HX_FILE = url.slice(url.indexOf(',') + 1);
  } catch (e) { $('hxmsg').textContent = 'that file could not be read'; return; }
  const d = await hxPost('/api/history/plan');
  if (!d) return;
  const c = hxCounts(d);
  $('hxplan').innerHTML = hxTable(d, false);
  if (!c.setUp && !c.people && !c.filled) {
    $('hxmsg').textContent = 'Nothing in that file can be imported here, as the table says.';
    return;
  }
  if (!c.changes) {
    $('hxmsg').textContent = 'Everything in that file is already here, so importing it ' +
      'would change nothing.';
    return;
  }
  $('hxmsg').textContent = hxSaying(c, false) + ' Nothing is downloaded now.';
  $('hximport').textContent = c.setUp || c.people ? 'Set up and import' : 'Import';
  $('hximport').style.display = '';
}

async function importHistory() {
  if (!HX_FILE) return;
  $('hximport').disabled = true;
  $('hxmsg').textContent = 'importing...';
  const d = await hxPost('/api/history/import');
  $('hximport').disabled = false;
  if (!d) return;
  hxReset();
  const c = hxCounts(d);
  $('hxplan').innerHTML = hxTable(d, true);
  $('hxmsg').textContent = hxSaying(c, true);
  const welcome = hxWelcome();
  STATUS_LOADED = false; XL_LOADED = false;
  await load();
  if (welcome) {
    showTab('out');
    $('console').textContent = hxSaying(c, true) + '\n\nNothing was downloaded, and no ' +
      'sign-in came with the file. Next, pick a provider above, press Login, and sign in ' +
      (SERVER ? 'on the Browser Screen' : 'when the browser opens') +
      '. Run All then downloads only what is new.';
  }
}

let STATUS_LOADED = false;

// Which providers get a spreadsheet. Receipt archives have line items, so
// they are listed, each with its second-account folders folded in. Statement
// archives are not offered one, since they have documents, not purchases.
let XL_LOADED = false;
async function loadExportProviders() {
  const sel = $('xlprovider'); sel.innerHTML = '';
  let d;
  try { d = await (await fetch('/api/export/providers')).json(); }
  catch (e) { d = {available: false, providers: []}; }
  XL_LOADED = true;
  const provs = (d.providers || []);
  sel.append(new Option('All providers', ''));
  for (const p of provs) sel.append(new Option(p.provider, p.provider));
  const names = provs.map(p => p.provider).join(', ');
  $('xlnote').textContent = provs.length
    ? 'Receipt archives found, ' + names + '. Statement archives have no line items and are not offered.'
    : 'No receipt archive found under this folder. Amazon, Target, Walmart and Gap write one after a run.';
  $('xlbuild').disabled = !provs.length;
}
async function loadTransactionProviders() {
  const sel = $('txprovider'); sel.innerHTML = '';
  let d;
  try { d = await (await fetch('/api/export/transactions/providers')).json(); }
  catch (e) { d = {available: false, providers: []}; }
  const provs = d.providers || [];
  sel.append(new Option('All statement archives', ''));
  for (const p of provs) sel.append(new Option(p.provider + ' (' + p.pdfs + ' PDFs)', p.provider));
  $('txnote').textContent = provs.length
    ? 'Archives with PDFs on disk, ' + provs.map(p => p.provider).join(', ') + '.'
    : (d.reason || 'No statement PDFs on disk under this folder.');
  $('txbuild').disabled = !provs.length; $('txcsv').disabled = !provs.length;
}
let txes = null;
function buildTransactions(asCsv) {
  if (txes) txes.close();
  const log = $('txlog'); log.textContent = ''; log.style.display = 'block';
  $('txreveal').style.display = 'none';
  $('txbuild').disabled = true; $('txcsv').disabled = true;
  const q = new URLSearchParams({provider: $('txprovider').value, csv: asCsv ? '1' : ''});
  txes = new EventSource('/api/export/transactions?' + q.toString());
  txes.onmessage = e => { log.textContent += e.data + '\n'; log.scrollTop = log.scrollHeight; };
  txes.addEventListener('result', e => { $('txreveal').style.display = ''; });
  txes.addEventListener('done', e => {
    txes.close(); txes = null;
    $('txbuild').disabled = false; $('txcsv').disabled = false;
    if (e.data !== '0') log.textContent += '(ended with code ' + e.data + ')\n';
  });
  txes.onerror = () => { if (txes) { txes.close(); txes = null; } $('txbuild').disabled = false; $('txcsv').disabled = false; };
}
async function buildSpreadsheet(asCsv) {
  $('xlbody').textContent = 'building...';
  $('xlreveal').style.display = 'none';
  let d;
  const provider = $('xlprovider').value;
  try {
    d = await (await fetch('/api/export', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({csv: asCsv, provider})})).json();
  } catch (e) { $('xlbody').textContent = 'could not reach the control panel'; return; }
  if (!d.ok) { $('xlbody').textContent = d.reason || 'the export failed'; return; }
  let html = '<table class="st"><tr><th>Provider</th><th class="num">Line items</th></tr>';
  for (const [p, n] of Object.entries(d.providers).sort()) {
    html += '<tr><td>' + esc(p) + '</td><td class="num">' + n + '</td></tr>';
  }
  html += '</table>';
  html += '<p style="margin-top:14px"><b>' + d.purchases + ' purchases</b> across ' + d.orders + ' orders.</p>';
  html += '<p class="hint">Wrote <code>' + esc(d.path) + '</code></p>';
  if (d.openpyxl_missing) html += '<p class="hint warn">openpyxl is not installed here, so this is a .csv. Run <code>pip install openpyxl</code> in the panel\'s environment for an .xlsx.</p>';
  $('xlbody').innerHTML = html;
  $('xlreveal').style.display = '';
}
async function revealSpreadsheet() {
  // A server cannot open a folder on the computer the page is on, so it
  // hands the spreadsheet to the browser instead.
  if (SERVER) { location.href = '/api/export/download'; return; }
  try { await fetch('/api/export/reveal', {method: 'POST'}); } catch (e) {}
}
function showTab(which) {
  const isSt = which === 'st', isXl = which === 'xl', isNm = which === 'nm';
  const other = isSt || isXl || isNm;
  $('paneout').style.display = other ? 'none' : 'flex';
  $('panest').style.display  = isSt ? 'block' : 'none';
  $('panexl').style.display  = isXl ? 'block' : 'none';
  $('panenm').style.display  = isNm ? 'block' : 'none';
  $('tabout').className = other ? '' : 'on';
  $('tabst').className  = isSt ? 'on' : '';
  $('tabxl').className  = isXl ? 'on' : '';
  $('tabnm').className  = isNm ? 'on' : '';
  if (isSt && !STATUS_LOADED) loadStatus();
  if (isXl && !XL_LOADED) { loadExportProviders(); loadTransactionProviders(); }
  if (isNm) loadNaming();
}

// -- file names (#50) --------------------------------------------------------
let NM = null, NM_TIMER = null;
function nmScopeValue() { return document.querySelector('input[name=nmscope]:checked').value; }
async function loadNaming() {
  const app = $('app').value;
  if (!app) return;
  let d;
  try { d = await (await fetch('/api/naming?app=' + encodeURIComponent(app))).json(); }
  catch (e) { return; }
  $('nmunavail').style.display = d.available ? 'none' : 'block';
  $('nmbody').style.display = d.available ? 'block' : 'none';
  if (!d.available) return;
  NM = d;
  const kind = d.kind === 'receipts' ? 'receipts' : 'statements';
  $('nmapp').textContent = d.provider;
  $('nmkind').textContent = 'a ' + kind + ' app';
  $('nmsharedlabel').textContent = 'every ' + kind + ' app';
  $('nmownlabel').textContent = 'only ' + d.provider;
  document.querySelector('input[name=nmscope][value=' + (d.own ? 'own' : 'shared') + ']').checked = true;
  $('nmpattern').value = d.own || d.shared || d.default;
  $('nmnote').textContent = '';
  const box = $('nmfields'); box.innerHTML = '';
  const n = d.fill.records;
  const receipts = d.kind === 'receipts';
  for (const f of d.fields) {
    // An order total, a store and online or in store are things a receipt
    // has. On a statements app they would only ever come out empty.
    if (!receipts && (f === 'total' || f === 'store' || f === 'type')) continue;
    const b = document.createElement('button');
    b.className = 'nmchip';
    const got = d.fill.filled[f] || 0;
    const name = document.createElement('span');
    name.textContent = nmLabel(f, receipts);
    const how = document.createElement('small');
    how.textContent = nmHowMany(f, got, n);
    b.append(name, how);
    b.title = 'Adds {' + f + '} to the pattern';
    if (n && f !== 'owner' && f !== 'part' && !got) b.classList.add('nmnone');
    b.onclick = () => nmInsert(f);
    box.append(b);
  }
  nmChanged();
}
function nmLabel(f, receipts) {
  return ({date: 'Date', year: 'Year', month: 'Month', provider: 'Provider',
           owner: 'Account holder', kind: 'Document type', summary: 'Description',
           number: receipts ? 'Order number' : 'Document number', account: 'Account',
           total: 'Order total', store: 'Store', type: 'Online or in store',
           part: 'Part, like 1 of 3'})[f] || f;
}
// How many of the files already downloaded have this part, in words, so
// nobody builds a name on something this provider never gives.
function nmHowMany(f, got, n) {
  if (f === 'owner') return 'from your settings';
  if (f === 'part') return 'only on a split order';
  if (!n) return '';
  if (got >= n) return 'on every file';
  if (got === 0) return 'on none of your files';
  const pct = Math.round(100 * got / n);
  return pct >= 90 ? 'on almost every file' : 'on ' + got + ' of ' + n + ' files';
}
function nmScope() {
  if (!NM) return;
  $('nmpattern').value = (nmScopeValue() === 'own' ? NM.own : '') || NM.shared || NM.default;
  nmChanged();
}
function nmInsert(field) {
  const inp = $('nmpattern');
  const text = inp.value;
  const at = inp.selectionStart == null ? text.length : inp.selectionStart;
  const sep = at > 0 ? $('nmsep').value : '';
  const f = field === 'date' ? '{date:' + $('nmdate').value + '}' : '{' + field + '}';
  // A date and a provider are always there, so they are never optional.
  const skip = $('nmskip').checked && field !== 'date' && field !== 'provider';
  const part = skip ? '[' + sep + f + ']' : sep + f;
  inp.value = text.slice(0, at) + part + text.slice(at);
  inp.focus();
  inp.selectionStart = inp.selectionEnd = at + part.length;
  nmChanged();
}
function nmChanged() {
  clearTimeout(NM_TIMER);
  NM_TIMER = setTimeout(nmPreview, 250);
}
async function nmPreview() {
  const pattern = $('nmpattern').value;
  let d;
  try {
    d = await (await fetch('/api/naming/preview', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({app: $('app').value, pattern})})).json();
  } catch (e) { return; }
  const pr = $('nmproblem');
  pr.style.display = d.problem ? 'block' : 'none';
  pr.textContent = d.problem || '';
  const box = $('nmpreview'); box.innerHTML = '';
  if (!d.names || !d.names.length) {
    box.innerHTML = '<p class="hint">No files from this app yet, so there is nothing to preview.</p>';
    return;
  }
  const t = document.createElement('table'); t.className = 'st';
  t.innerHTML = '<thead><tr><th>Your newest files now</th><th>With this pattern</th></tr></thead>';
  const tb = document.createElement('tbody');
  for (const n of d.names) {
    const tr = document.createElement('tr');
    const a = document.createElement('td'); a.textContent = n.current;
    const b = document.createElement('td'); b.textContent = n.new;
    if (n.new !== n.current) b.style.fontWeight = '600';
    tr.append(a, b); tb.append(tr);
  }
  t.append(tb); box.append(t);
}
async function nmSave() {
  let r, d;
  try {
    r = await fetch('/api/naming/save', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({app: $('app').value, scope: nmScopeValue(),
                            pattern: $('nmpattern').value})});
    d = await r.json();
  } catch (e) { $('nmnote').textContent = 'could not reach the control panel'; return; }
  if (!r.ok) { $('nmnote').textContent = d.detail || 'not saved'; return; }
  await loadNaming();
  $('nmnote').textContent = d.written ? 'Saved. New downloads use it.' : 'Nothing to change.';
  if (d.changed && d.changed.length) nmOffer(d.changed);
}

// The offer to bring files already on disk into line, one app and one
// account at a time, through the app's own --rename. Renaming is never
// offered until a preview of the same apps has finished cleanly.
let NM_OFFER = null, NM_PREVIEWED = false;
function nmOffer(apps) {
  NM_OFFER = apps; NM_PREVIEWED = false;
  $('nmoffer').style.display = apps ? 'block' : 'none';
  if (!apps) return;
  $('nmofferapps').textContent = (apps.length === 1 ? 'In ' : 'In these ' + apps.length + ' apps, ') +
    apps.join(', ') + ', every account.';
  $('nmapplybtn').disabled = true;
  $('nmprevbtn').disabled = false;
  $('nmofferstate').textContent = '';
  $('nmoffer').scrollIntoView({block: 'nearest'});
}
function nmPairs() {
  const pairs = [];
  for (const a of NM_OFFER || []) {
    const m = META.apps[a];
    if (!m) continue;
    for (const acc of (m.accounts && m.accounts.length ? m.accounts : ['primary'])) pairs.push([a, acc]);
  }
  return pairs;
}
function nmRename(apply) {
  const pairs = nmPairs();
  if (!pairs.length) return;
  if (apply && !NM_PREVIEWED) return;
  if (apply && !confirm('Rename the files the preview listed, in ' + NM_OFFER.length +
      (NM_OFFER.length === 1 ? ' app?' : ' apps?') +
      ' Nothing is downloaded or deleted, and each app\'s index follows its files.')) return;
  const action = apply ? 'rename_apply' : 'rename';
  showTab('out');
  $('console').textContent = '';
  let i = 0;
  const next = (code) => {
    if (code !== undefined && code !== '0') {
      $('nmofferstate').textContent = 'Stopped at ' + pairs[i - 1].join(', ') +
        ', which did not finish. Its output says why.';
      return;
    }
    if (i >= pairs.length) {
      if (apply) {
        $('nmofferstate').textContent = 'Renamed. The Output tab lists each file.';
        $('nmapplybtn').disabled = true; $('nmprevbtn').disabled = true;
        loadNaming();
      } else {
        NM_PREVIEWED = true;
        $('nmapplybtn').disabled = false;
        $('console').textContent += '\n== That is the whole preview. Nothing has been changed. ' +
          'To rename these files, go back to File names and press Rename them. ==\n';
        $('console').scrollTop = $('console').scrollHeight;
        $('nmofferstate').textContent = 'Preview done. Read it in the Output tab, then rename here.';
      }
      return;
    }
    const [app, account] = pairs[i++];
    $('console').textContent += (i > 1 ? '\n' : '') + '== ' + app +
      (account === 'primary' ? '' : ', ' + account) + ' ==\n';
    run(action, {app, account, append: true, onDone: next});
  };
  $('nmofferstate').textContent = apply ? 'Renaming...' : 'Previewing...';
  next();
}
function nmDefault() { $('nmpattern').value = NM ? NM.default : ''; nmChanged(); }
function nmClear() { $('nmpattern').value = ''; $('nmpattern').focus(); nmChanged(); }

function pillClass(s) {
  if (s === 'OVERDUE') return 'overdue';
  if (s === 'due') return 'due';
  if (s === 'current') return 'current';
  return 'other';
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function loadStatus() {
  $('stbody').textContent = 'scanning...';
  $('stnote').textContent = '';
  let d;
  try { d = await (await fetch('/api/status')).json(); }
  catch (e) { $('stbody').textContent = 'could not reach the control panel'; return; }
  STATUS_LOADED = true;
  if (!d.available) { $('stbody').textContent = d.reason || 'status is unavailable'; return; }
  if (!d.rows.length) { $('stbody').textContent = 'no archives found under ' + d.root; return; }
  const body = d.rows.map(r =>
    '<tr><td>' + esc(r.provider || r.folder) + '</td>' +
    '<td class="num">' + (r.documents == null ? '' : r.documents) + '</td>' +
    '<td>' + esc(r.newest || '') + '</td>' +
    '<td class="num">' + (r.age_days == null ? '' : r.age_days + ' d') + '</td>' +
    '<td>' + esc(r.cadence || '') + '</td>' +
    '<td><span class="pill ' + pillClass(r.label) + '">' + esc(r.label) + '</span></td></tr>'
  ).join('');
  let html = '<table class="st"><thead><tr><th>Provider</th><th class="num">Docs</th>' +
    '<th>Newest</th><th class="num">Age</th><th>Every</th><th>Status</th></tr></thead><tbody>' +
    body + '</tbody></table>';
  if (d.gaps.length) {
    html += '<div class="gapbox"><h3>Possible gaps</h3>' +
      '<p>A run that looks current can still be missing periods in the middle.</p>';
    for (const g of d.gaps) {
      html += '<p style="margin-top:8px"><b>' + esc(g.provider) + '</b></p>';
      for (const w of g.windows) {
        const who = w.count > 1
          ? (w.count + ' series, including ' + (w.labels[0] || ''))
          : (w.labels[0] || '');
        html += '<p>' + esc(w.after) + ' to ' + esc(w.before) + ' &middot; ' +
                esc(String(w.missing)) + ' missing &middot; ' + esc(who) + '</p>';
      }
    }
    html += '</div>';
  }
  $('stbody').innerHTML = html;
  $('stnote').textContent = 'scanned ' + d.root;
}

let META = null, es = null;
const $ = id => document.getElementById(id);

async function load() {
  META = await (await fetch('/api/apps')).json();
  const inSample = META.root_source === 'sample';
  $('samplebar').style.display = inSample ? 'flex' : 'none';
  $('root').innerHTML = 'apps root: ' + esc(META.apps_root) +
    (inSample ? ' <span class="hint">(the sample)</span>'
     : SERVER ? ' <span class="hint">(the data folder beside compose.yaml on your server)</span>'
     : (META.root_source === 'environment' ? ' <span class="hint">(from APPS_ROOT)</span>'
        : ' <a href="#" onclick="changeRoot(); return false;" style="color:var(--accent)">change</a>')
       // Reachable with an archive already open, not just from the welcome
       // screen, or the only people who could ever see it are new ones.
       + ' <a href="#" onclick="openSample(); return false;" style="color:var(--muted)">see the sample</a>');
  const fresh = Object.keys(META.refreshed || {});
  if (fresh.length) {
    $('root').innerHTML += '<br><span class="hint">updated to this version\'s code: ' +
      esc(fresh.join(', ')) + ' (the old files are in each folder\'s Backups)</span>';
  }
  const appSel = $('app');
  appSel.innerHTML = '';
  const keys = Object.keys(META.apps);
  // Nothing in the sample is moved anywhere, and nothing is moved into it.
  $('movebox').style.display = inSample ? 'none' : '';
  placeMove(!keys.length);
  $('movelink').style.display = keys.length ? 'none' : '';
  if (!keys.length) {
    showSetup(true);
    $('newuser').style.display = 'block';
    $('existing').style.display = 'none';
    $('addlink').style.display = 'none';
    $('removelink').style.display = 'none';
    loadProviders(false);
    if (META.root_source !== 'environment') $('newroot').focus();
    return;
  }
  showSetup(false);
  // Nothing in the sample can be added to, renamed or removed, so the links
  // that would try are not offered.
  $('addlink').style.display = inSample ? 'none' : '';
  $('removelink').style.display = inSample ? 'none' : '';
  $('addacct').style.display = inSample ? 'none' : '';
  for (const k of keys) appSel.append(new Option(META.apps[k].name, k));
  appSel.onchange = onApp;
  fillScope();
  clearAgain();
  const acts = $('actions'); acts.innerHTML = '';
  const more = $('moreactions'); more.innerHTML = '';
  const tucked = new Set(META.more_actions || []);
  for (const [k, label] of Object.entries(META.actions)) {
    const b = document.createElement('button');
    b.textContent = label; b.className = (k === 'all') ? 'primary' : '';
    b.onclick = () => run(k);
    (tucked.has(k) ? more : acts).append(b);
  }
  let open = false;
  try { open = localStorage.getItem('moreactions') === '1'; } catch (e) {}
  showMore(open);
  onApp();
}
// The rarely wanted actions sit behind one link. Open or closed is
// remembered in this browser only, like the scope.
function showMore(on) {
  $('morebox').style.display = on ? 'block' : 'none';
  $('morelink').textContent = on ? 'fewer' : 'more';
  try { localStorage.setItem('moreactions', on ? '1' : '0'); } catch (e) {}
}
function toggleMore() { showMore($('morebox').style.display === 'none'); }
function onApp() {
  const m = META.apps[$('app').value];
  if ($('panenm').style.display === 'block') loadNaming();
  const accSel = $('account'); accSel.innerHTML = '';
  for (const a of m.accounts) accSel.append(new Option(a, a));
  const warn = $('venvwarn');
  if (m.runnable === false) { warn.style.display='block';
    warn.textContent = '⚠ This folder does not match a provider PaperPull ships, so it will not run. Its folder must hold exactly one provider script whose name is one PaperPull ships.'; }
  else if (m.needs_setup) { warn.style.display='block';
    warn.textContent = '⚠ This provider is not set up yet. Run setup-all in the PaperPull folder, then reload this page.'; }
  else warn.style.display='none';
}
function setStatus(cls, text) { $('dot').className = 'dot ' + cls; $('statustext').textContent = text; }
// Scope. "All years" is the default and walks everything, which is what keeps
// each archive's discovery complete for the Status tab. One year, or a date
// range, makes the run skip the years outside it on sites with a year picker.
// The choice is remembered in this browser only.
function fillScope() {
  const sel = $('year'); sel.innerHTML = '';
  sel.append(new Option('All years (default)', ''));
  const now = new Date().getFullYear();
  for (let y = now; y >= now - 15; y--) sel.append(new Option(String(y), String(y)));
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('scope') || '{}'); } catch (e) {}
  sel.value = saved.year || '';
  if (sel.value !== (saved.year || '')) sel.value = '';
  $('start').value = saved.start || '';
  $('end').value = saved.end || '';
  onScope();
}
function scopeValues() {
  return { year: $('year').value, start: $('start').value, end: $('end').value };
}
function onScope() {
  const s = scopeValues();
  const oneYear = s.year !== '';
  $('start').disabled = oneYear; $('end').disabled = oneYear;
  let text;
  if (oneYear) text = `Only ${s.year}. Years outside it are skipped where the site has a year picker.`;
  else if (s.start || s.end) text = `${s.start || 'the beginning'} to ${s.end || 'today'}. Years outside that are skipped where the site has a year picker.`;
  else text = 'Every year. Slower on sites with a year picker, and the only way the Status tab sees the whole archive.';
  $('scopehint').textContent = text;
  try { localStorage.setItem('scope', JSON.stringify(s)); } catch (e) {}
}
// Download again. Unlike the scope it is never remembered. It starts clear
// on every visit and clears itself once a run that uses it starts, so a
// later ordinary Run All never downloads again by surprise.
function onAgain() { $('againhint').style.display = $('again').checked ? 'block' : 'none'; }
function clearAgain() { $('again').checked = false; onAgain(); }
// A page the browser brings back from its back and forward cache keeps
// what was ticked, and load() does not run again for it.
window.addEventListener('pageshow', e => { if (e.persisted) clearAgain(); });
// Only a year, or both ends of a range. One date alone is open at the
// other end, and From 1990 or To today is a whole history.
function againScoped(s) { return Boolean(s.year || (s.start && s.end)); }
// What it does is said so it holds for every app. Each goes through the
// range again and fetches again what is gone. Most also save a second copy
// of a file still there, and Target leaves an invoice still on file as it is.
function againQuestion(action, app, account, s) {
  const range = s.year ? 'dated ' + s.year : 'dated ' + s.start + ' to ' + s.end;
  return 'Download again from ' + app + (account === 'primary' ? '' : ', account ' + account) + '?\n\n' +
    (action === 'pilot' ? 'Pilot goes through the newest few documents ' + range + ' again'
                        : 'Run All goes through every document ' + range + ' again') +
    ', the ones this app already downloaded included, and fetches again each one whose ' +
    'file is gone.\n\n' +
    'Nothing is overwritten. A file you still have stays as it is, and the app may save ' +
    'a second copy beside it, under a name of its own.\n\n' +
    'This asks the provider again for each document it fetches, just as the first download did.';
}
// Said when a run that downloads again ends before it is through. Resume
// never downloads again, so it would skip the rest and call the run done,
// and the same range again would fetch again what this run restored.
const AGAIN_LEFT = 'Resume will not download again, and Download again for the same range ' +
  'fetches again what this run already restored, so choose the range that is left';
// A run that downloads again is asked for in a POST body, so the ticked box
// and the answer to the question arrive as true and false, never as text in
// an address. EventSource can only GET, so this reads the same stream with
// fetch and hands its events to the same handlers.
function postRun(body) {
  const stop = new AbortController(), on = {};
  const src = { onmessage: null, onerror: null, refused: '',
                addEventListener(name, fn) { on[name] = fn; }, close() { stop.abort(); } };
  const lost = () => { if (!stop.signal.aborted && src.onerror) src.onerror(); };
  (async () => {
    let r;
    try {
      r = await fetch('/api/run', { method: 'POST', signal: stop.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    } catch (e) { lost(); return; }
    if (!r.ok) {
      try { const d = await r.json(); if (typeof d.detail === 'string') src.refused = d.detail; } catch (e) {}
      src.refused = src.refused || 'the panel refused this run';
      lost(); return;
    }
    const reader = r.body.getReader(), text = new TextDecoder();
    let buf = '', ended = false;
    try {
      for (;;) {
        const part = await reader.read();
        if (part.done) break;
        buf += text.decode(part.value, { stream: true });
        let cut;
        while ((cut = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          let name = 'message';
          const data = [];
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) name = line.slice(6).trim();
            else if (line.startsWith('data:')) data.push(line.slice(line.startsWith('data: ') ? 6 : 5));
          }
          if (name === 'done') ended = true;
          const e = { data: data.join('\n') };
          if (name === 'message') { if (src.onmessage) src.onmessage(e); }
          else if (on[name]) on[name](e);
        }
      }
    } catch (e) { lost(); return; }
    if (!ended) lost();
  })();
  return src;
}
// opts is for a run the page starts for itself rather than from a button,
// the File names page's renames. It names the app and account, leaves the
// Scope out, adds to the console instead of clearing it, and is told when
// the run ends.
function run(action, opts) {
  opts = opts || {};
  if (es) es.close();
  const app = opts.app || $('app').value, account = opts.account || $('account').value;
  const s = opts.app ? {year: '', start: '', end: ''} : scopeValues();
  if (s.year === '' && s.start && s.end && s.start > s.end) {
    setStatus('err', 'the From date is after the To date'); return;
  }
  const ticked = !opts.app && $('again').checked;
  const again = ticked && (META.redownload_actions || []).includes(action);
  if (again && !againScoped(s)) {
    setStatus('err', 'Download again needs a year, or both a From and a To date, chosen in Scope first');
    return;
  }
  if (again && !confirm(againQuestion(action, app, account, s))) return;
  if (again) clearAgain();
  const q = new URLSearchParams({ app, account, action });
  if (s.year) q.set('year', s.year); else { if (s.start) q.set('start', s.start); if (s.end) q.set('end', s.end); }
  if (!opts.append) $('console').textContent = '';
  // Any other button leaves the box ticked for the Pilot or Run All it is
  // for, and says so where this run's output starts.
  if (ticked && !again) {
    $('console').textContent += 'Download again stays ticked. It applies only to Pilot and Run All, ' +
      'so this ' + ((META.actions || {})[action] || action) + ' runs as usual.\n';
  }
  $('failnote').style.display = 'none';
  const scoped = s.year ? ` (${s.year})` : (s.start || s.end) ? ` (${s.start || '…'} to ${s.end || '…'})` : '';
  setStatus('run', `running ${action}${again ? ', downloading again,' : ''} on ${app} / ${account}${scoped}`);
  // Only the buttons this run locked are unlocked at the end. The Spreadsheet
  // tab's build buttons stay disabled when there is nothing to build from.
  document.querySelectorAll('button:not(#tabout):not(#tabst):not(#tabxl):not(#tabnm):not(#stoprec):not(:disabled)')
    .forEach(b => { b.disabled = true; b.dataset.runlock = '1'; });
  // A recording waits for the person, so it needs a way to say when. The
  // app this run belongs to is remembered here rather than read back off
  // the App list when Stop is pressed, because the App list is not locked
  // during a run and a recording stopped against the wrong provider would
  // never stop at all.
  recordingApp = (action === 'record') ? app : null;
  $('stoprec').style.display = recordingApp ? 'block' : 'none';
  es = again ? postRun(Object.assign({ app, account, action, redownload: true, confirmed: true },
                                     Object.fromEntries(q.entries())))
             : new EventSource(`/api/run?${q.toString()}`);
  const con = $('console');
  let result = null;
  es.addEventListener('result', e => { result = JSON.parse(e.data); });
  es.onmessage = e => { con.textContent += e.data + '\n'; con.scrollTop = con.scrollHeight; };
  es.addEventListener('done', e => {
    const code = e.data;
    const unfinished = code !== '0' || Boolean(result && result.stopped);
    if (code !== '0') {
      setStatus('err', (code === '130' ? 'interrupted, progress saved' : `exited (code ${code}), check output`) +
                       (again ? '. ' + AGAIN_LEFT : ''));
    } else if (result && result.stopped) {
      setStatus('warn', again ? 'stopped before finishing. ' + AGAIN_LEFT
                              : 'stopped before finishing, see the output, then press Resume');
    } else if (result && result.attention) {
      const details = [];
      if (result.wrong_document) details.push(`${result.wrong_document} refused as the wrong document`);
      if (result.manual_review) details.push(`${result.manual_review} need review`);
      if (result.failed) details.push(`${result.failed} failed`);
      if (result.validation_failures) details.push(`${result.validation_failures} PDF validation failures`);
      setStatus('warn', `finished, needs attention (${details.join(', ')})`);
    } else if (result) {
      setStatus('ok', 'finished, no issues reported');
    } else if (META && META.root_source === 'sample') {
      setStatus('ok', 'nothing to run in the sample');
    } else {
      setStatus('warn', 'finished, check output (no run summary)');
    }
    // The app's own last lines may say to press Resume, so this goes below them.
    if (again && unfinished) {
      con.textContent += 'This download again ended before it was through. ' + AGAIN_LEFT + '.\n';
      con.scrollTop = con.scrollHeight;
    }
    $('stoprec').style.display = 'none';
    recordingApp = null;
    unlockButtons();
    es.close(); es = null;
    if (code !== '0' || (result && result.attention)) checkFailure(app);
    if (opts.onDone) opts.onDone(code);
  });
  es.onerror = () => { if (es) { if (es.refused) con.textContent += es.refused + '\n'; setStatus('err', es.refused || ('connection lost' + (again ? '. ' + AGAIN_LEFT : ''))); $('stoprec').style.display = 'none'; recordingApp = null; unlockButtons(); es.close(); es=null; if (opts.onDone) opts.onDone('lost'); } };
}
let failureApp = null;
async function checkFailure(app) {
  try {
    const r = await fetch(`/api/failure/latest?app=${encodeURIComponent(app)}`);
    const d = await r.json();
    if (d.found) { failureApp = app; $('failnote').style.display = ''; }
  } catch (e) {}
}
async function revealFailure() {
  if (!failureApp) return;
  if (SERVER) { location.href = '/api/failure/download?app=' + encodeURIComponent(failureApp); return; }
  try {
    await fetch('/api/failure/reveal', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app: failureApp }) });
  } catch (e) {}
}
let recordingApp = null;
async function stopRecording() {
  if (!recordingApp) return;
  const b = $('stoprec');
  b.disabled = true; b.textContent = 'Stopping...';
  try {
    await fetch('/api/record/stop', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app: recordingApp }) });
  } catch (e) {}
  b.disabled = false; b.textContent = 'Stop recording';
}
function unlockButtons() {
  document.querySelectorAll('button[data-runlock]').forEach(b => { b.disabled = false; delete b.dataset.runlock; });
}
// On the server the downloads folder is the shared folder the container was
// given, so it is shown and not asked for, with where to find it on the
// server, and what would open a folder on this computer downloads the file
// instead.
function serverPage() {
  if (!SERVER) return;
  $('newlead').textContent = 'Tick the providers you have accounts with. Each one '
    + 'gets a folder of its own, and nothing is downloaded until you ask.';
  $('newrootlabel').textContent = 'Where your downloads go';
  $('serverroot').style.display = 'block';
  $('steplogin').innerHTML = '<b>Login</b> opens the provider\'s sign-in window on the '
    + '<b>Browser Screen</b>, the button at the top. Sign in there yourself and leave it open.';
  $('newroot').readOnly = true;
  $('existinglink').style.display = 'none';
  // Download again is not offered here, see _redownload_ok.
  $('againrow').style.display = 'none';
  $('againnote').style.display = 'none';
  $('failreveal').textContent = 'Download the file to attach';
  $('xlreveal').textContent = 'Download';
  $('txreveal').textContent = 'Download';
}
serverPage();
load();
