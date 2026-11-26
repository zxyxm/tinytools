
  // Run in Scripta's editor closure so all three writing modes share the same Markdown.
  let workstationToken = null;
  let workstationBridge = null;
  let workstationText = null;
  let workstationRevision = 0;

  persist = function () {
    if (workstationToken && markdown !== workstationText) {
      workstationText = markdown;
      workstationRevision++;
      workstationBridge?.edited(workstationToken, workstationRevision, markdown);
    }
  };

  new QWebChannel(qt.webChannelTransport, channel => {
    workstationBridge = channel.objects.notes;
    if (workstationToken && workstationRevision) {
      workstationBridge.edited(workstationToken, workstationRevision, markdown);
    }
  });

  window.workstationNotes = {
    open(token, title, text) {
      workstationToken = null;
      replaceDocument(text, title || '未命名笔记');
      workstationText = markdown;
      workstationRevision = 0;
      workstationToken = token;
      viewport.scrollTop = 0;
      return true;
    },
    snapshot() {
      return JSON.stringify([workstationToken, workstationRevision, markdown]);
    },
  };

  document.querySelector('.topbar').hidden = true;
  byId('filename').hidden = true;
  byId('status').textContent = '随记 · 思刻 Markdown';
  setMode('visual');
  document.addEventListener('keydown', event => {
    const key = event.key.toLowerCase();
    if (!(event.ctrlKey || event.metaKey) || event.isComposing || !['n', 'o', 's'].includes(key)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (key === 's') {
      persist();
      workstationBridge?.save();
    }
  }, true);
