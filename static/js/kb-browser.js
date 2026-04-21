(function () {
  'use strict';

  var KB = {
    page: 1,
    perPage: 20,
    query: '',
    total: 0,
    pages: 0,
  };

  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $$(sel, ctx) { return (ctx || document).querySelectorAll(sel); }

  function esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Stats ──────────────────────────────────────────────────────────────────

  function loadStats() {
    var el = $('#kb-stats');
    if (!el) return;
    el.innerHTML = '<div class="skeleton skeleton-text" style="width:40%"></div><div class="skeleton skeleton-text" style="width:60%"></div><div class="skeleton skeleton-text" style="width:50%"></div>';
    fetch('/kb/stats')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { el.innerHTML = '<span class="kb-err">' + esc(d.error) + '</span>'; return; }
        el.innerHTML =
          '<div class="kb-stat"><span class="kb-stat-label">Collection</span><span class="kb-stat-val">' + esc(d.name) + '</span></div>' +
          '<div class="kb-stat"><span class="kb-stat-label">Documents</span><span class="kb-stat-val">' + Number(d.points_count).toLocaleString() + '</span></div>' +
          '<div class="kb-stat"><span class="kb-stat-label">Vector size</span><span class="kb-stat-val">' + d.vector_size + '</span></div>' +
          '<div class="kb-stat"><span class="kb-stat-label">Distance</span><span class="kb-stat-val">' + esc(d.distance) + '</span></div>' +
          '<div class="kb-stat"><span class="kb-stat-label">Status</span><span class="kb-stat-val">' + esc(d.status) + '</span></div>';
      })
      .catch(function (e) { el.innerHTML = '<span class="kb-err">Failed to load stats</span>'; });
  }

  // ── Document list ──────────────────────────────────────────────────────────

  function loadDocuments(page, query) {
    KB.page = page || 1;
    KB.query = (query !== undefined) ? query : KB.query;
    var list = $('#kb-doc-list');
    var pager = $('#kb-pager');
    if (!list) return;
    list.innerHTML = '<div class="kb-doc-skeleton"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text" style="width:70%"></div></div>'.repeat(5);
    if (pager) pager.innerHTML = '';

    var url = '/kb/documents?page=' + KB.page + '&per_page=' + KB.perPage;
    if (KB.query) url += '&q=' + encodeURIComponent(KB.query);

    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { list.innerHTML = '<div class="kb-err">' + esc(d.error) + '</div>'; return; }
        KB.total = d.total;
        KB.pages = d.pages;
        renderDocList(list, d.documents);
        renderPager(pager, d);
      })
      .catch(function () { list.innerHTML = '<div class="kb-err">Failed to load documents</div>'; });
  }

  function renderDocList(container, docs) {
    if (!docs.length) {
      container.innerHTML = '<div class="kb-empty">No documents found.</div>';
      return;
    }
    var html = '';
    docs.forEach(function (doc) {
      html +=
        '<div class="kb-doc-row" data-id="' + esc(doc.id) + '">' +
          '<div class="kb-doc-title">' + esc(doc.title) + '</div>' +
          '<div class="kb-doc-meta">' +
            '<span class="kb-doc-src">' + esc(doc.source) + '</span>' +
            (doc.created_at ? '<span class="kb-doc-date">' + esc(doc.created_at.slice(0, 10)) + '</span>' : '') +
          '</div>' +
          '<div class="kb-doc-preview">' + esc(doc.content_preview) + '</div>' +
          '<div class="kb-doc-actions">' +
            '<button class="kb-btn kb-btn-view" data-id="' + esc(doc.id) + '">View</button>' +
            '<button class="kb-btn kb-btn-del" data-id="' + esc(doc.id) + '">Delete</button>' +
          '</div>' +
        '</div>';
    });
    container.innerHTML = html;

    $$('.kb-btn-view', container).forEach(function (btn) {
      btn.addEventListener('click', function () { openDoc(btn.dataset.id); });
    });
    $$('.kb-btn-del', container).forEach(function (btn) {
      btn.addEventListener('click', function () { deleteDoc(btn.dataset.id, btn); });
    });
  }

  function renderPager(container, d) {
    if (!container || d.pages <= 1) return;
    var html = '';
    if (d.page > 1)
      html += '<button class="kb-btn kb-pager-btn" data-page="' + (d.page - 1) + '">&laquo; Prev</button>';
    html += '<span class="kb-pager-info">Page ' + d.page + ' / ' + d.pages + ' (' + d.total.toLocaleString() + ' docs)</span>';
    if (d.page < d.pages)
      html += '<button class="kb-btn kb-pager-btn" data-page="' + (d.page + 1) + '">Next &raquo;</button>';
    container.innerHTML = html;
    $$('.kb-pager-btn', container).forEach(function (btn) {
      btn.addEventListener('click', function () { loadDocuments(parseInt(btn.dataset.page)); });
    });
  }

  // ── Single document modal ──────────────────────────────────────────────────

  function openDoc(id) {
    var modal = $('#kb-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    $('#kb-modal-body').innerHTML = '<div class="kb-loading">Loading…</div>';
    fetch('/kb/documents/' + encodeURIComponent(id))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { $('#kb-modal-body').innerHTML = '<div class="kb-err">' + esc(d.error) + '</div>'; return; }
        var payload = d.payload || {};
        var html = '<h3 class="kb-modal-title">' + esc(d.title) + '</h3>';
        html += '<div class="kb-modal-meta">';
        if (payload.source) html += '<span>Source: ' + esc(payload.source) + '</span> ';
        if (payload.generated_at) html += '<span>Date: ' + esc(payload.generated_at.slice(0, 10)) + '</span>';
        html += '</div>';
        html += '<pre class="kb-modal-content">' + esc(d.content) + '</pre>';
        $('#kb-modal-body').innerHTML = html;
      })
      .catch(function () { $('#kb-modal-body').innerHTML = '<div class="kb-err">Failed to load document</div>'; });
  }

  function closeModal() {
    var modal = $('#kb-modal');
    if (modal) modal.style.display = 'none';
  }

  // ── Delete ─────────────────────────────────────────────────────────────────

  function deleteDoc(id, btn) {
    if (!confirm('Delete this document from the knowledge base?')) return;
    btn.disabled = true;
    btn.textContent = 'Deleting…';
    fetch('/kb/documents/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { alert('Error: ' + d.error); btn.disabled = false; btn.textContent = 'Delete'; return; }
        var row = btn.closest('.kb-doc-row');
        if (row) row.remove();
        loadStats();
      })
      .catch(function () { alert('Delete failed'); btn.disabled = false; btn.textContent = 'Delete'; });
  }

  // ── Export ─────────────────────────────────────────────────────────────────

  function exportKB() {
    fetch('/kb/export')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'knowledge_base_export.json';
        a.click();
      })
      .catch(function () { alert('Export failed'); });
  }

  // ── Purge ──────────────────────────────────────────────────────────────────

  function purgeKB() {
    if (!confirm('WARNING: This will delete ALL documents from the knowledge base. This cannot be undone.\n\nType "yes" in the next prompt to confirm.')) return;
    var ans = prompt('Type YES to confirm purge:');
    if (!ans || ans.trim().toUpperCase() !== 'YES') { alert('Purge cancelled.'); return; }
    fetch('/kb/purge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: 'yes' })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { alert('Error: ' + d.error); return; }
        alert('Knowledge base purged and recreated.');
        loadStats();
        loadDocuments(1, '');
        var searchEl = $('#kb-search');
        if (searchEl) searchEl.value = '';
      })
      .catch(function () { alert('Purge failed'); });
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  function init() {
    loadStats();
    loadDocuments(1);

    var searchEl = $('#kb-search');
    if (searchEl) {
      var timer;
      searchEl.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { loadDocuments(1, searchEl.value); }, 400);
      });
    }

    var exportBtn = $('#kb-export-btn');
    if (exportBtn) exportBtn.addEventListener('click', exportKB);

    var purgeBtn = $('#kb-purge-btn');
    if (purgeBtn) purgeBtn.addEventListener('click', purgeKB);

    var closeBtn = $('#kb-modal-close');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);

    var modal = $('#kb-modal');
    if (modal) {
      modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
