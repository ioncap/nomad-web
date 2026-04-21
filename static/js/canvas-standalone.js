// canvas-standalone.js — standalone canvas tab synced via BroadcastChannel
(function(){
  var ta         = document.getElementById('csTA');
  var lnEl       = document.getElementById('csLineNums');
  var syncEl     = document.getElementById('csSyncEl');
  var syncTxt    = document.getElementById('csSyncText');
  var nameEl     = document.getElementById('csName');
  var wEl        = document.getElementById('csWriting');
  var statsEl    = document.getElementById('csStats');
  var goalProgEl = document.getElementById('csGoalProgress');

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

  // ── Word goal ─────────────────────────────────────────────────────────────
  var csWordGoal = 0;

  function updateStats() {
    var t = ta.value;
    var w = t.trim() ? t.trim().split(/\s+/).length : 0;
    if (statsEl) statsEl.textContent = w + ' words · ' + t.length + ' chars';
    if (csWordGoal > 0 && goalProgEl) {
      goalProgEl.style.width = Math.min(100, Math.round(w / csWordGoal * 100)) + '%';
    }
  }

  // ── Line numbers ──────────────────────────────────────────────────────────
  function updateLN() {
    var n = ta.value.split('\n').length, h = '';
    for (var i = 1; i <= n; i++) h += i + '<br>';
    lnEl.innerHTML = h;
    updateStats();
  }

  // ── Language detection ────────────────────────────────────────────────────
  function detectLang(c) {
    if (!c) return 'plaintext';
    var l = c.toLowerCase();
    if (l.indexOf('def ') !== -1 || (l.indexOf('import ') !== -1 && l.indexOf('from ') !== -1)) return 'python';
    if (l.indexOf('function') !== -1 || l.indexOf('const ') !== -1 || l.indexOf('let ') !== -1) return 'javascript';
    if (l.indexOf('<!doctype') !== -1 || l.indexOf('<html') !== -1) return 'html';
    if (l.indexOf('#!/bin/bash') !== -1 || l.indexOf('#!/bin/sh') !== -1) return 'bash';
    try { JSON.parse(c); return 'json'; } catch(e) {}
    return 'plaintext';
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
  var offlineTimer = null;

  function resetOfflineTimer() {
    clearTimeout(offlineTimer);
    offlineTimer = setTimeout(function() { setSync('offline'); }, 12000);
  }

  if (typeof BroadcastChannel !== 'undefined') {
    bc = new BroadcastChannel('nomad-canvas');

    bc.onmessage = function(ev) {
      var p = ev.data;
      if (!p || !p.type) return;
      resetOfflineTimer();
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
        case 'canvas_pong':
          setSync('live');
          break;
      }
    };

    // Request initial content from the main tab
    bc.postMessage({ type: 'canvas_request_sync' });
    setSync('waiting');

    // Show offline if no response within 3 s
    offlineTimer = setTimeout(function() {
      if (syncTxt.textContent === 'waiting…') setSync('offline');
    }, 3000);

    // Heartbeat every 5 s — keeps main tab's _popoutActive flag alive
    setInterval(function() { bc.postMessage({ type: 'canvas_ping' }); }, 5000);

  } else {
    document.getElementById('csBody').innerHTML =
      '<div class="cs-no-bc">BroadcastChannel not supported in this browser.</div>';
  }

  // ── Broadcast helper ──────────────────────────────────────────────────────
  function broadcastEdit() {
    if (bc) bc.postMessage({ type: 'canvas_edited', content: ta.value, name: nameEl.textContent });
  }

  // ── User edits → broadcast back to main tab ───────────────────────────────
  var editTimer = null;
  ta.addEventListener('input', function() {
    updateLN();
    histPush();
    clearTimeout(editTimer);
    editTimer = setTimeout(function() { broadcastEdit(); setSync('live'); }, 800);
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

  // Keyboard shortcuts
  document.addEventListener('keydown', function(e) {
    if (e.ctrlKey || e.metaKey) {
      if (e.key === 'z' && !e.shiftKey)                       { e.preventDefault(); window.csUndo(); }
      else if (e.key === 'y' || (e.key === 'z' && e.shiftKey)){ e.preventDefault(); window.csRedo(); }
      else if (e.key === 'f')                                  { e.preventDefault(); window.csFind(); }
      else if (e.key === 'h')                                  { e.preventDefault(); window.csReplace(); }
      else if (e.key === 's')                                  { e.preventDefault(); window.csDownload(); }
    }
  });

  updateLN();

  // ── Global functions (called by HTML buttons) ─────────────────────────────

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

  window.csFind = function() {
    var t = prompt('Find:');
    if (!t) return;
    var from = ta.selectionEnd || 0;
    var p = ta.value.indexOf(t, from);
    if (p < 0) p = ta.value.indexOf(t); // wrap around
    if (p >= 0) { ta.setSelectionRange(p, p + t.length); ta.focus(); }
    else alert('Not found');
  };

  window.csReplace = function() {
    var f = prompt('Find:');
    if (!f) return;
    var r = prompt('Replace with:');
    if (r === null) return;
    ta.value = ta.value.split(f).join(r);
    updateLN(); histPush(); broadcastEdit();
  };

  window.csBeautify = function() {
    var text = ta.value;
    if (!text.trim()) return;
    var lang = detectLang(text);

    // Client-side JSON
    if (lang === 'json') {
      try {
        ta.value = JSON.stringify(JSON.parse(text), null, 2);
        updateLN(); histPush(); broadcastEdit();
      } catch(e) { alert('Invalid JSON: ' + e.message); }
      return;
    }

    // LLM beautify via /canvas-generate
    var prompts = {
      python:     'Format this Python code with PEP8 style: proper indentation (4 spaces), blank lines between functions/classes. Output ONLY the formatted code.',
      javascript: 'Format this JavaScript with 2-space indentation, consistent spacing. Output ONLY the formatted code.',
      html:       'Format this HTML with 2-space indentation. Output ONLY the formatted code.',
      bash:       'Format this shell script with consistent 2-space indentation. Output ONLY the formatted code.',
      markdown:   'Clean up this markdown: fix heading levels, consistent list style, proper spacing. Output ONLY the improved markdown.',
      sql:        'Format this SQL: uppercase keywords, proper indentation, one clause per line. Output ONLY the formatted SQL.',
      plaintext:  'Reformat this text for readability: proper paragraphs, consistent spacing. Output ONLY the reformatted text.'
    };

    showWriting(true);
    var buf = '';
    var origText = text;

    fetch('/canvas-generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: (prompts[lang] || prompts.plaintext) + '\n\n```\n' + text + '\n```',
        canvas_content: null
      })
    }).then(async function(r) {
      var reader = r.body.getReader(), decoder = new TextDecoder(), lineBuf = '';
      ta.value = '';
      while (true) {
        var rd = await reader.read();
        if (rd.done) break;
        lineBuf += decoder.decode(rd.value, { stream: true });
        var lines = lineBuf.split('\n'); lineBuf = lines.pop();
        for (var line of lines) {
          if (!line.startsWith('data: ')) continue;
          var d = line.substring(6); if (d === '[DONE]') continue;
          try {
            var p = JSON.parse(d);
            if (p.type === 'canvas_token') {
              buf += p.token; ta.value = buf; updateLN(); ta.scrollTop = ta.scrollHeight;
            } else if (p.type === 'canvas_done' || p.type === 'done') {
              ta.value = ta.value.replace(/^```[a-zA-Z]*\n?/, '').replace(/\n?```\s*$/, '').trim();
              updateLN(); histPush(); showWriting(false); broadcastEdit();
            }
          } catch(e) {}
        }
      }
      showWriting(false);
    }).catch(function() {
      showWriting(false); ta.value = origText; updateLN();
      alert('Beautify failed — is the LLM running?');
    });
  };

  window.csLoadFile = function(input) {
    var f = input.files[0];
    if (!f) return;
    input.value = '';
    if (f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')) {
      var fd = new FormData(); fd.append('file', f);
      fetch('/extract-pdf', { method: 'POST', body: fd })
        .then(function(r) { return r.json(); })
        .then(function(d) {
          if (d.text) { setContent(d.text, f.name.replace(/\.pdf$/i, '.txt')); broadcastEdit(); }
          else alert('PDF extraction failed: ' + (d.error || 'unknown'));
        })
        .catch(function() { alert('PDF extraction unavailable'); });
    } else {
      var reader = new FileReader();
      reader.onload = function(e) { setContent(e.target.result, f.name); broadcastEdit(); };
      reader.readAsText(f);
    }
  };

  window.csSetGoal = function() {
    var g = parseInt(prompt('Word count goal (0 to clear):'));
    if (isNaN(g)) return;
    csWordGoal = g;
    var btn = document.getElementById('csGoalBtn');
    if (btn) btn.style.color = g > 0 ? 'var(--cv-active)' : '';
    if (goalProgEl) goalProgEl.style.width = '0%';
    updateStats();
  };
})();
