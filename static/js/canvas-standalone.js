// canvas-standalone.js — standalone canvas tab synced via BroadcastChannel
(function(){
  var ta      = document.getElementById('csTA');
  var lnEl    = document.getElementById('csLineNums');
  var syncEl  = document.getElementById('csSyncEl');
  var syncTxt = document.getElementById('csSyncText');
  var nameEl  = document.getElementById('csName');
  var wEl     = document.getElementById('csWriting');

  // ── Undo/redo history ─────────────────────────────────────────────────────
  var hist = [''], hIdx = 0, pushTimer = null;
  function histPush() {
    clearTimeout(pushTimer);
    pushTimer = setTimeout(function() {
      var v = ta.value;
      if (v === hist[hIdx]) return;
      hist = hist.slice(0, hIdx + 1);
      hist.push(v);
      hIdx = hist.length - 1;
    }, 400);
  }

  // ── Line numbers ──────────────────────────────────────────────────────────
  function updateLN() {
    var n = ta.value.split('\n').length, h = '';
    for (var i = 1; i <= n; i++) h += i + '<br>';
    lnEl.innerHTML = h;
  }

  // ── Sync indicator ────────────────────────────────────────────────────────
  function setSync(state) {
    syncEl.className = 'cs-sync' + (state === 'live' ? ' live' : '');
    syncTxt.textContent = state === 'live' ? 'live'
                        : state === 'offline' ? 'no main tab'
                        : 'waiting…';
  }

  function showWriting(v) {
    wEl.className = 'cs-writing' + (v ? ' visible' : '');
  }

  // ── Content helpers ───────────────────────────────────────────────────────
  function setContent(content, name) {
    ta.value = content || '';
    if (name) nameEl.textContent = name;
    updateLN();
    setSync('live');
    hist = [ta.value]; hIdx = 0;
  }

  function appendContent(content, header, codeLang, filename) {
    var existing = ta.value.trim();
    var block = codeLang ? ('```' + codeLang + '\n' + content + '\n```') : content;
    var section = (header ? ('\n\n' + header + '\n\n') : '\n\n') + block;
    ta.value = existing ? existing + section : section.trim();
    if (filename && !existing) nameEl.textContent = filename;
    updateLN();
    ta.scrollTop = ta.scrollHeight;
    setSync('live');
    histPush();
  }

  // ── BroadcastChannel ──────────────────────────────────────────────────────
  var bc = null, streamBuf = '';
  if (typeof BroadcastChannel !== 'undefined') {
    bc = new BroadcastChannel('nomad-canvas');

    bc.onmessage = function(ev) {
      var p = ev.data;
      if (!p || !p.type) return;
      switch (p.type) {
        case 'canvas_sync':
        case 'canvas_sync_response':
          setContent(p.content, p.name);
          showWriting(false);
          break;
        case 'canvas_content':
          setContent(p.content, p.filename || p.name);
          showWriting(false);
          break;
        case 'canvas_start':
          streamBuf = '';
          showWriting(true);
          if (p.filename) nameEl.textContent = p.filename;
          setSync('live');
          break;
        case 'canvas_stream_token':
          streamBuf = p.buffer || streamBuf;
          ta.value = streamBuf;
          updateLN();
          ta.scrollTop = ta.scrollHeight;
          showWriting(true);
          setSync('live');
          break;
        case 'canvas_done':
          showWriting(false);
          if (streamBuf) { hist = [ta.value]; hIdx = 0; streamBuf = ''; }
          break;
        case 'canvas_append':
          appendContent(p.content || '', p.header || '', p.code_lang || '', p.filename || '');
          showWriting(false);
          break;
        case 'canvas_new_tab':
          var c = p.code_lang
            ? ('```' + p.code_lang + '\n' + (p.content || '') + '\n```')
            : (p.content || '');
          setContent(c, p.filename);
          showWriting(false);
          break;
      }
    };

    // Request initial content from the main tab
    bc.postMessage({ type: 'canvas_request_sync' });
    setSync('waiting');

    // Show offline if no response within 3 s
    setTimeout(function() {
      if (syncTxt.textContent === 'waiting…') setSync('offline');
    }, 3000);

  } else {
    document.getElementById('csBody').innerHTML =
      '<div class="cs-no-bc">BroadcastChannel not supported in this browser.</div>';
  }

  // ── User edits → broadcast back to main tab ───────────────────────────────
  var editTimer = null;
  ta.addEventListener('input', function() {
    updateLN();
    histPush();
    clearTimeout(editTimer);
    editTimer = setTimeout(function() {
      if (bc) {
        bc.postMessage({ type: 'canvas_edited', content: ta.value, name: nameEl.textContent });
        setSync('live');
      }
    }, 800);
  });

  ta.addEventListener('scroll', function() { lnEl.scrollTop = ta.scrollTop; });

  // Tab key → 2-space indent
  ta.addEventListener('keydown', function(e) {
    if (e.key === 'Tab') {
      e.preventDefault();
      var s = ta.selectionStart;
      ta.value = ta.value.substring(0, s) + '  ' + ta.value.substring(ta.selectionEnd);
      ta.selectionStart = ta.selectionEnd = s + 2;
      updateLN();
    }
  });

  // Ctrl+Z / Ctrl+Y keyboard shortcuts
  document.addEventListener('keydown', function(e) {
    if (e.ctrlKey || e.metaKey) {
      if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); window.csUndo(); }
      else if (e.key === 'y' || (e.key === 'z' && e.shiftKey)) { e.preventDefault(); window.csRedo(); }
    }
  });

  updateLN();

  // ── Global functions called by toolbar buttons ────────────────────────────
  window.csUndo = function() {
    clearTimeout(pushTimer);
    if (hIdx > 0) { ta.value = hist[--hIdx]; updateLN(); }
  };
  window.csRedo = function() {
    if (hIdx < hist.length - 1) { ta.value = hist[++hIdx]; updateLN(); }
  };
  window.csDownload = function() {
    var blob = new Blob([ta.value], { type: 'text/plain' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = nameEl.textContent || 'canvas.txt';
    a.click();
  };
})();
