import UI from './app/ui.js';

// Only explicit paste events from the user's visible remote screen are relayed.
// The RFB clipboard helpers are disabled server-side, and no clipboard API is read.
const embedded = window.parent !== window;
const report = () => {
  if (embedded) parent.postMessage({type: 'harbor-screen-connection', connected: UI.connected === true}, location.origin);
};
// Stop noVNC from also sending Ctrl+V to the remote X clipboard. Keep the
// browser default action so its explicit paste event can deliver local text.
document.addEventListener('keydown', event => {
  if (embedded && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'v') {
    const target = event.target;
    if (target instanceof Element && target.closest('input,textarea') && target.id !== 'noVNC_keyboardinput') return;
    event.stopImmediatePropagation();
  }
}, true);
document.addEventListener('paste', event => {
  if (!embedded || !event.clipboardData) return;
  const target = event.target;
  if (target instanceof Element && target.closest('input,textarea') && target.id !== 'noVNC_keyboardinput') return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if (UI.connected !== true) return;
  let text = event.clipboardData.getData('text/plain');
  if (!text || text.includes('\u0000') || new TextEncoder().encode(text).length > 16384) return;
  parent.postMessage({type: 'harbor-user-paste', text}, location.origin);
  text = '';
}, true);
window.addEventListener('message', event => {
  if (embedded && event.origin === location.origin && event.source === parent &&
      event.data && event.data.type === 'harbor-screen-status') report();
});
window.addEventListener('pagehide', () => {
  if (embedded) parent.postMessage({type: 'harbor-screen-connection', connected: false}, location.origin);
});
// Observe only connection state. No text, DOM values or clipboard is polled.
let connection;
setInterval(() => {
  if (connection !== UI.rfb) {
    connection = UI.rfb;
    if (connection) {
      connection.addEventListener('connect', report);
      connection.addEventListener('disconnect', report);
    }
    report();
  }
}, 250);
const style = document.createElement('style');
style.textContent = '#noVNC_clipboard_button,#noVNC_clipboard{display:none!important}';
document.head.append(style);
report();
