// Only explicit user paste/send actions move text into the remote browser.
// Clipboard APIs, storage and clipboard synchronization are deliberately absent.
(() => {
  'use strict';
  const frame = document.getElementById('remote-screen');
  const form = document.getElementById('paste-form');
  const accounts = document.getElementById('paste-account');
  const input = document.getElementById('paste-text');
  const send = document.getElementById('paste-send');
  const status = document.getElementById('paste-status');
  const maxLength = 16384;
  const encoder = new TextEncoder();
  let connected = false;
  let sending = false;
  let pasted = null;
  let pending = null;
  let generation = 0;

  function clear() {
    pasted = null;
    input.value = '';
  }

  function update() {
    send.disabled = !connected || sending || !accounts.value;
  }

  function stop() {
    generation++;
    clear();
    if (pending) pending.abort();
    pending = null;
    sending = false;
    update();
  }

  async function paste(text) {
    clear();
    if (sending) return;
    if (!connected) {
      status.textContent = 'Wait for the remote browser to connect, then paste again.';
      return;
    }
    if (!accounts.value) {
      status.textContent = 'Select the destination account, focus its remote field, then paste again.';
      return;
    }
    if (typeof text !== 'string' || !text.length || encoder.encode(text).length > maxLength || text.includes('\u0000')) {
      status.textContent = 'Paste nonempty text up to 16 KB without null characters.';
      return;
    }
    let destination;
    try { destination = JSON.parse(accounts.value); }
    catch (_) {
      status.textContent = 'Select a destination account, then paste again.';
      return;
    }
    const attempt = generation;
    const controller = new AbortController();
    pending = controller;
    sending = true;
    update();
    status.textContent = 'Pasting into the selected remote field…';
    let body = JSON.stringify({...destination, text});
    text = '';
    try {
      const response = await fetch('/api/screen/paste', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json'}, body,
        signal: controller.signal,
      });
      body = '';
      if (attempt !== generation) return;
      if (!response.ok) throw new Error('Paste unavailable');
      const result = await response.json();
      if (attempt !== generation) return;
      if (result.ok !== true) throw new Error('Paste unavailable');
      status.textContent = 'Text pasted. Continue signing in in the remote browser.';
      frame.focus();
    } catch (_) {
      if (attempt === generation) {
        status.textContent = 'Could not paste. Select the correct account and focus its editable remote field, then try again.';
      }
    } finally {
      body = '';
      clear();
      if (pending === controller) {
        pending = null;
        sending = false;
        update();
      }
    }
  }

  // A password input normalizes newlines. Preserve only the most recent explicit
  // paste until submission so Unicode and multiline text arrive unchanged.
  input.addEventListener('paste', event => {
    if (!event.clipboardData) return;
    event.preventDefault();
    clear();
    const text = event.clipboardData.getData('text/plain');
    if (encoder.encode(text).length > maxLength || text.includes('\u0000')) {
      status.textContent = 'Paste nonempty text up to 16 KB without null characters.';
      return;
    }
    pasted = text;
    input.value = text;
  });
  input.addEventListener('input', () => { pasted = null; });
  accounts.addEventListener('change', () => {
    stop();
    status.textContent = 'Click a field in the selected account’s remote sign-in page, then paste.';
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    void paste(pasted === null ? input.value : pasted);
  });

  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== frame.contentWindow || !event.data) return;
    if (event.data.type === 'harbor-screen-connection' && typeof event.data.connected === 'boolean') {
      connected = event.data.connected;
      if (!connected) {
        stop();
        status.textContent = 'Remote browser disconnected. Reconnect before pasting.';
      } else {
        update();
        status.textContent = accounts.value
          ? 'Click a field in the selected account’s remote sign-in page, then paste.'
          : 'Select a destination account before pasting.';
      }
    } else if (event.data.type === 'harbor-user-paste' && typeof event.data.text === 'string') {
      void paste(event.data.text);
    }
  });
  frame.addEventListener('load', () => {
    connected = false;
    stop();
    status.textContent = 'Connecting to the remote browser…';
    // The child reports its current state after startup and responds to this
    // request, covering both event orders without opening another connection.
    frame.contentWindow.postMessage({type: 'harbor-screen-status'}, location.origin);
  });
  window.addEventListener('pagehide', stop);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stop();
      status.textContent = 'Pasted text cleared. Focus the remote field before pasting again.';
    }
  });

  void (async () => {
    try {
      const response = await fetch('/api/screen/accounts', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) throw new Error('Accounts unavailable');
      const data = await response.json();
      accounts.replaceChildren(new Option('Choose an account…', ''));
      for (const account of data.accounts || []) {
        if (typeof account.app !== 'string' || typeof account.account !== 'string') continue;
        accounts.add(new Option(account.app + ' / ' + account.account, JSON.stringify({app: account.app, account: account.account})));
      }
      if (accounts.options.length === 1) {
        accounts.options[0].textContent = 'No accounts available';
        status.textContent = 'Add a provider account in the dashboard, then reopen this sign-in window.';
      }
      update();
    } catch (_) {
      accounts.replaceChildren(new Option('Accounts unavailable', ''));
      status.textContent = 'Could not load accounts. Return to the dashboard and reopen this sign-in window.';
      update();
    }
  })();
})();
