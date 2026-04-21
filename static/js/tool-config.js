/**
 * N.O.M.A.D Tool Config Panel
 * Beheert het ⚙ Tools overlay-paneel: laden, renderen, en opslaan van tool-instellingen.
 */
(function () {
  'use strict';

  // ── Panel open/close ────────────────────────────────────────────────────────

  window.toggleToolConfig = function () {
    var p = document.getElementById('toolcfgPanel');
    if (p.classList.contains('open')) {
      p.classList.remove('open');
    } else {
      p.classList.add('open');
      loadToolConfig();
    }
  };

  window.loadToolConfig = function loadToolConfig() {
    var grid = document.getElementById('toolcfgGrid');
    grid.innerHTML = '<div class="toolcfg-loading">Loading tools…</div>';
    fetch('/api/tools')
      .then(function (r) { return r.json(); })
      .then(renderToolConfig)
      .catch(function (e) {
        grid.innerHTML =
          '<div style="color:var(--err);padding:16px;font-family:\'DM Mono\',monospace;font-size:12px">' +
          'Failed to load tools: ' + esc(String(e)) + '</div>';
      });
  };

  // ── Rendering ───────────────────────────────────────────────────────────────

  function esc(s) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(String(s == null ? '' : s)));
    return d.innerHTML;
  }

  function inferType(defaultVal) {
    if (typeof defaultVal === 'boolean') return 'checkbox';
    if (typeof defaultVal === 'number')  return 'number';
    return 'text';
  }

  function renderParam(toolName, key, currentVal, defaultVal) {
    var type  = inferType(defaultVal != null ? defaultVal : currentVal);
    var id    = 'param-' + toolName + '-' + key;
    var safeName = esc(toolName);
    var safeKey  = esc(key);
    var changed  = defaultVal != null && String(currentVal) !== String(defaultVal);

    var html = '<div class="tc-param">';
    html += '<span class="tc-param-label">' + safeKey + '</span>';

    if (type === 'checkbox') {
      html += '<input class="tc-param-check" type="checkbox" id="' + id + '"' +
              (currentVal ? ' checked' : '') +
              ' data-tool="' + safeName + '" data-key="' + safeKey + '"' +
              ' onchange="TC.paramChanged(\'' + safeName + '\')">';
    } else {
      html += '<input class="tc-param-input" type="' + (type === 'number' ? 'number' : 'text') + '"' +
              ' id="' + id + '" value="' + esc(currentVal) + '"' +
              ' data-tool="' + safeName + '" data-key="' + safeKey + '"' +
              ' oninput="TC.paramChanged(\'' + safeName + '\')">';
    }

    if (changed) {
      html += '<button class="tc-param-reset" title="Reset to default: ' + esc(defaultVal) + '"' +
              ' onclick="TC.resetParam(\'' + safeName + '\',\'' + safeKey + '\',' +
              esc(JSON.stringify(defaultVal)) + ')">↩</button>';
    }

    html += '</div>';
    return html;
  }

  function renderToolConfig(tools) {
    var grid = document.getElementById('toolcfgGrid');
    if (!tools || tools.length === 0) {
      grid.innerHTML =
        '<div style="color:var(--t3);padding:16px;font-family:\'DM Mono\',monospace;font-size:12px">No tools registered.</div>';
      return;
    }

    var html = '';
    tools.forEach(function (tool) {
      var enabled   = tool.enabled !== false;
      var params    = tool.params    || {};
      var defaults  = tool.default_params || {};
      var hasParams = Object.keys(params).length > 0;
      var safeName  = esc(tool.name);

      html += '<div class="tc-card' + (enabled ? '' : ' tc-card-disabled') + '" data-tool="' + safeName + '">';

      // ── Header: name + toggle ────────────────────────────────────────────
      html += '<div class="tc-card-header">';
      html += '<span class="tc-name">' + safeName + '</span>';
      html += '<label class="tc-toggle" title="' + (enabled ? 'Uitschakelen' : 'Inschakelen') + '">' +
              '<input type="checkbox"' + (enabled ? ' checked' : '') +
              ' onchange="TC.toggleTool(\'' + safeName + '\', this.checked)">' +
              '<span class="tc-toggle-slider"></span></label>';
      html += '</div>';

      // ── Description ──────────────────────────────────────────────────────
      html += '<div class="tc-desc">' + esc(tool.description) + '</div>';

      // ── Help block (collapsed) ────────────────────────────────────────────
      var showHelp = tool.help && tool.help !== tool.description;
      if (showHelp) {
        html += '<button class="tc-help-btn" onclick="TC.toggleHelp(\'' + safeName + '\')">? help</button>';
        html += '<div class="tc-help" id="help-' + safeName + '" style="display:none">';
        html += '<div class="tc-help-text">' + esc(tool.help) + '</div>';
        if (tool.example) {
          html += '<div class="tc-example">💬 “' + esc(tool.example) + '”</div>';
        }
        html += '</div>';
      }

      // ── Parameters ───────────────────────────────────────────────────────
      if (hasParams) {
        html += '<div class="tc-params" id="params-' + safeName + '">';
        Object.keys(params).forEach(function (key) {
          html += renderParam(tool.name, key, params[key], defaults[key]);
        });
        html += '<button class="tc-save-btn" id="save-' + safeName + '"' +
                ' onclick="TC.saveParams(\'' + safeName + '\')">opslaan</button>';
        html += '</div>';
      }

      html += '</div>'; // .tc-card
    });

    grid.innerHTML = html;
  }

  // ── Actions ─────────────────────────────────────────────────────────────────

  function toggleTool(name, enabled) {
    fetch('/api/tools/' + encodeURIComponent(name) + '/enable', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled }),
    })
      .then(function (r) { return r.json(); })
      .then(function () { loadToolConfig(); })
      .catch(function (e) { console.error('Toggle failed:', e); });
  }

  function paramChanged(toolName) {
    var btn = document.getElementById('save-' + toolName);
    if (btn) { btn.style.display = 'inline-block'; }
  }

  function resetParam(toolName, key, defaultVal) {
    var id  = 'param-' + toolName + '-' + key;
    var el  = document.getElementById(id);
    if (!el) return;
    if (el.type === 'checkbox') {
      el.checked = Boolean(defaultVal);
    } else {
      el.value = String(defaultVal);
    }
    paramChanged(toolName);
  }

  function saveParams(toolName) {
    var params  = {};
    var inputs  = document.querySelectorAll('[data-tool="' + toolName + '"][data-key]');
    inputs.forEach(function (el) {
      var key = el.dataset.key;
      if (el.type === 'checkbox') {
        params[key] = el.checked;
      } else if (el.type === 'number') {
        params[key] = parseFloat(el.value);
      } else {
        params[key] = el.value;
      }
    });

    fetch('/api/tools/' + encodeURIComponent(toolName), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
      .then(function (r) { return r.json(); })
      .then(function () {
        var btn = document.getElementById('save-' + toolName);
        if (btn) {
          var orig = btn.textContent;
          btn.textContent = '✓ opgeslagen';
          btn.style.color = 'var(--ok)';
          setTimeout(function () {
            btn.textContent  = orig;
            btn.style.color  = '';
            btn.style.display = 'none';
          }, 2000);
        }
        // Reload to reflect type-coerced values and reset markers.
        setTimeout(loadToolConfig, 2200);
      })
      .catch(function (e) { console.error('Save failed:', e); });
  }

  function toggleHelp(name) {
    var el  = document.getElementById('help-' + name);
    var btn = el ? el.previousElementSibling : null;
    if (!el) return;
    if (el.style.display === 'none') {
      el.style.display = 'block';
      if (btn) btn.textContent = '↑ help';
    } else {
      el.style.display = 'none';
      if (btn) btn.textContent = '? help';
    }
  }

  // ── Public API (used in inline event handlers) ────────────────────────────

  window.TC = {
    toggleTool:  toggleTool,
    paramChanged: paramChanged,
    resetParam:  resetParam,
    saveParams:  saveParams,
    toggleHelp:  toggleHelp,
  };
})();
