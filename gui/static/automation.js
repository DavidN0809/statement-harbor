'use strict';
const $ = id => document.getElementById(id);
let model, editingSettings = false;
const say = text => { $('message').textContent = text; };
const date = value => value ? new Date(value * 1000).toLocaleString() : '—';
const advice = {
  AUTH_REQUIRED: 'Sign in again through Accounts, close the sign-in screen, then resume.',
  CHALLENGE_REQUIRED: 'Complete MFA or the security challenge yourself, close the screen, then resume.',
  PAUSED: 'Inspect the provider page through Accounts before explicitly resuming.',
  FAILED: 'Check the provider and archive. Automatic retries are bounded.',
  RATE_LIMITED: 'Wait for provider backoff before trying again.'
};

async function post(operation, data) {
  const response = await fetch('/api/automation/' + operation, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
  });
  if (!response.ok) throw Error('Request refused. Check the account state, schedule and enabled controls.');
  say('Saved.');
  await refresh();
}

function button(text, action) {
  const element = document.createElement('button');
  element.type = 'button';
  element.textContent = text;
  element.onclick = () => Promise.resolve(action()).catch(error => say(error.message));
  return element;
}

function options(element, values) {
  const previous = element.value;
  // Avoid interrupting an operator's open dropdown on every poll.
  if (JSON.stringify([...element.options].map(o => o.value)) === JSON.stringify(values)) return;
  element.replaceChildren();
  for (const value of values) {
    const option = document.createElement('option');
    option.value = option.textContent = value;
    element.append(option);
  }
  if (values.includes(previous)) element.value = previous;
}

function accounts() {
  options($('account'), model.accounts[$('provider').value] || []);
}

function nextRun(row) {
  if (['AUTH_REQUIRED', 'CHALLENGE_REQUIRED', 'PAUSED'].includes(row.state)) return 'Human action';
  if (row.failures > model.settings.max_retries) return 'Retries exhausted';
  if (row.requested === 1) return 'Queued now';
  if (!model.settings.enabled || !row.enabled || !row.provider_enabled) return 'Disabled';
  return date(Math.max(row.next, (row.attempted || 0) + model.settings.min_interval));
}

async function refresh() {
  const response = await fetch('/api/automation');
  if (!response.ok) throw Error('Sign in to the server to view automation.');
  model = await response.json();
  if (!editingSettings) {
    const settings = model.settings;
    $('global').checked = settings.enabled;
    $('concurrency').value = settings.concurrency;
    $('interval').value = settings.min_interval;
    $('backoff').value = settings.retry_seconds;
    $('retries').value = settings.max_retries;
  }
  options($('provider'), Object.keys(model.accounts));
  accounts();
  $('rows').replaceChildren();
  for (const row of model.schedules) {
    const tr = document.createElement('tr');
    const fields = [row.app + ' / ' + row.account,
      (row.enabled && row.provider_enabled ? 'Enabled' : 'Disabled') + ' · ' + row.cron + ' · ' + row.zone,
      row.state, date(row.attempted), date(row.successful), row.new_files, nextRun(row)];
    for (const text of fields) {
      const cell = document.createElement('td');
      cell.textContent = text;
      tr.append(cell);
    }
    tr.children[2].title = advice[row.state] || 'No intervention required.';
    const actions = document.createElement('td');
    actions.className = 'actions';
    const key = {app: row.app, account: row.account};
    actions.append(button('Edit', () => {
      $('provider').value = row.app;
      accounts();
      $('account').value = row.account;
      $('cron').value = row.cron;
      $('zone').value = row.zone;
      $('enabled').checked = !!row.enabled;
      $('frequency').value = 'custom';
      $('schedule').scrollIntoView({behavior: 'smooth'});
    }), button('Run now', () => post('run', key)),
    button('Resolved, resume', () => post('reauthenticated', key)),
    button(row.provider_enabled ? 'Disable provider' : 'Enable provider',
      () => post('provider', {...key, enabled: !row.provider_enabled})),
    button(model.integrations?.suppression[row.app] ? 'Enable notices' : 'Suppress notices',
      () => post('notifications', {...key, disabled: !model.integrations?.suppression[row.app]})));
    tr.append(actions);
    $('rows').append(tr);
  }
  $('delivery').textContent = Object.entries(model.delivery)
    .map(([state, count]) => state + ': ' + count).join(' · ') || 'No documents queued.';
  if (model.integrations) {
    const value = model.integrations;
    $('integrations').textContent = 'Configuration: ' + value.status + ' · Mail: ' + value.mail + ' · Notifications: ' + value.notifications;
    $('missing').textContent = value.missing.map(row => row.app + ' / ' + row.account + ': missing ' + row.periods.join(', ')).join(' · ') || 'No missing documents detected for configured expectations.';
  }
  $('deliveryRows').replaceChildren();
  $('pendingProviders').replaceChildren();
  for (const provider of model.pending_providers || []) {
    const li = document.createElement('li');
    li.textContent = provider.name + ' · ' + provider.verification + ' · ' + provider.products.join(', ');
    $('pendingProviders').append(li);
  }
  for (const row of model.documents || []) {
    const p = document.createElement('p');
    p.className = 'small';
    p.textContent = row.provider + ' / ' + row.account + ' · ' + row.state + (row.error ? ' · ' + row.error : '');
    if (row.state === 'API_FAILED') p.append(' ', button('Retry ingestion', () => post('delivery', {id: row.id})));
    $('deliveryRows').append(p);
  }
  const attention = model.schedules.filter(row => advice[row.state]);
  $('attention').textContent = attention.map(row => row.app + ': ' + advice[row.state]).join(' ');
  if (model.delivery.PENDING || model.delivery.CORRUPT || model.delivery.UNCERTAIN) {
    $('attention').textContent += ' Paperless delivery needs attention. Inspect the handoff states below.';
  }
  const events = $('events');
  events.replaceChildren();
  for (const entry of model.events) {
    const item = document.createElement('li');
    item.textContent = date(entry.at) + ' · ' + entry.app + ' · ' + entry.state;
    events.append(item);
  }
}

$('provider').onchange = accounts;
$('frequency').onchange = () => {
  if ($('frequency').value !== 'custom') $('cron').value = $('frequency').value;
};
$('settings').oninput = () => { editingSettings = true; };
$('settings').onsubmit = async event => {
  event.preventDefault();
  try {
    await post('settings', {enabled: $('global').checked, concurrency: +$('concurrency').value,
      min_interval: +$('interval').value, retry_seconds: +$('backoff').value,
      max_retries: +$('retries').value});
    editingSettings = false;
  } catch (error) { say(error.message); }
};
$('schedule').onsubmit = async event => {
  event.preventDefault();
  try {
    await post('schedule', {app: $('provider').value, account: $('account').value,
      cron: $('cron').value, zone: $('zone').value, enabled: $('enabled').checked});
  } catch (error) { say(error.message); }
};
$('retryDelivery').onclick = () => post('delivery', {}).catch(error => say(error.message));
$('loadRules').onclick = () => {
  const group = model.integrations.expectations.find(row => row.app === $('provider').value && row.account === $('account').value);
  $('rules').value = JSON.stringify(group?.rules || [], null, 2);
};
$('expectations').onsubmit = async event => {
  event.preventDefault();
  try {
    await post('expectations', {app: $('provider').value, account: $('account').value, rules: JSON.parse($('rules').value)});
  } catch (error) { say(error.message); }
};
refresh().catch(error => say(error.message));
setInterval(() => refresh().catch(error => say(error.message)), 10000);

$('backfill').onsubmit = async event => {
  event.preventDefault();
  try {
    await post('backfill', {app: $('provider').value, account: $('account').value,
      start: $('backfillStart').value, end: $('backfillEnd').value});
  } catch (error) { say(error.message); }
};
