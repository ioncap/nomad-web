// kb-browser.js
var KB = {
    currentPage: 1,
    perPage: 20,
    totalPages: 1,
    currentQuery: '',
    currentDocId: null
};

function toggleKbBrowser() {
    const panel = document.getElementById('kbPanel');
    if (panel.classList.contains('open')) {
        panel.classList.remove('open');
    } else {
        panel.classList.add('open');
        loadKbStats();
        loadDocuments();
    }
}

function loadKbStats() {
    fetch('/kb/stats')
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                document.getElementById('kbStats').innerHTML = `<span class="kb-error">Error: ${data.error}</span>`;
                return;
            }
            const html = `
                <span>📁 ${data.name}</span>
                <span>📈 ${data.points_count.toLocaleString()} vectors</span>
                <span>📐 ${data.vector_size} dims (${data.distance})</span>
                <span>🟢 ${data.status}</span>
            `;
            document.getElementById('kbStats').innerHTML = html;
        })
        .catch(err => {
            document.getElementById('kbStats').innerHTML = `<span class="kb-error">Failed to load stats</span>`;
        });
}

function loadDocuments(page = 1) {
    KB.currentPage = page;
    const query = KB.currentQuery;
    const url = `/kb/documents?page=${page}&per_page=${KB.perPage}&q=${encodeURIComponent(query)}`;
    
    document.getElementById('kbDocumentList').innerHTML = '<div class="kb-empty">Loading...</div>';
    
    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                document.getElementById('kbDocumentList').innerHTML = `<div class="kb-error">Error: ${data.error}</div>`;
                return;
            }
            
            KB.totalPages = data.pages;
            renderDocuments(data.documents);
            renderPagination(data.page, data.total, data.pages);
        })
        .catch(err => {
            document.getElementById('kbDocumentList').innerHTML = `<div class="kb-error">Failed to load documents</div>`;
        });
}

function renderDocuments(docs) {
    const container = document.getElementById('kbDocumentList');
    if (docs.length === 0) {
        container.innerHTML = '<div class="kb-empty">No documents found.</div>';
        return;
    }
    
    let html = '';
    docs.forEach(doc => {
        const title = escapeHtml(doc.title || 'Untitled');
        const preview = escapeHtml(doc.content_preview || '');
        const source = escapeHtml(doc.source || 'unknown');
        const created = doc.created_at ? new Date(doc.created_at).toLocaleString() : '';
        
        html += `
            <div class="kb-doc-item" onclick="viewDocument('${doc.id}')">
                <div class="kb-doc-title">${title}</div>
                <div class="kb-doc-preview">${preview}</div>
                <div class="kb-doc-meta">
                    <span>📌 ${source}</span>
                    ${created ? `<span>🕒 ${created}</span>` : ''}
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

function renderPagination(page, total, pages) {
    const info = document.getElementById('kbPaginationInfo');
    info.textContent = `${total} document${total !== 1 ? 's' : ''} | Page ${page} of ${pages}`;
    
    const paginationDiv = document.getElementById('kbPagination');
    let html = '';
    if (pages > 1) {
        html += `<button ${page === 1 ? 'disabled' : ''} onclick="loadDocuments(1)">« First</button>`;
        html += `<button ${page === 1 ? 'disabled' : ''} onclick="loadDocuments(${page-1})">‹ Prev</button>`;
        
        // Eenvoudige paginering: max 5 pagina's rondom huidige
        let start = Math.max(1, page - 2);
        let end = Math.min(pages, page + 2);
        for (let i = start; i <= end; i++) {
            html += `<button class="${i === page ? 'active' : ''}" onclick="loadDocuments(${i})">${i}</button>`;
        }
        
        html += `<button ${page === pages ? 'disabled' : ''} onclick="loadDocuments(${page+1})">Next ›</button>`;
        html += `<button ${page === pages ? 'disabled' : ''} onclick="loadDocuments(${pages})">Last »</button>`;
    }
    paginationDiv.innerHTML = html;
}

function kbSearch() {
    const input = document.getElementById('kbSearchInput');
    KB.currentQuery = input.value.trim();
    loadDocuments(1);
}

function kbResetSearch() {
    document.getElementById('kbSearchInput').value = '';
    KB.currentQuery = '';
    loadDocuments(1);
}

function viewDocument(id) {
    KB.currentDocId = id;
    fetch(`/kb/documents/${id}`)
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                showToast('Error loading document: ' + data.error);
                return;
            }
            document.getElementById('kbModalTitle').textContent = data.title || 'Document Details';
            // Toon volledige payload of alleen content
            let content = data.content;
            if (!content) {
                content = JSON.stringify(data.payload, null, 2);
            }
            document.getElementById('kbModalContent').textContent = content;
            document.getElementById('kbModal').classList.add('open');
        })
        .catch(err => {
            showToast('Failed to load document');
        });
}

function closeKbModal() {
    document.getElementById('kbModal').classList.remove('open');
    KB.currentDocId = null;
}

function kbDeleteDocument() {
    if (!KB.currentDocId) return;
    if (!confirm('Are you sure you want to delete this document?')) return;
    
    fetch(`/kb/documents/${KB.currentDocId}`, { method: 'DELETE' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'deleted') {
                showToast('Document deleted');
                closeKbModal();
                loadDocuments(KB.currentPage);
                loadKbStats();
            } else {
                showToast('Error: ' + (data.error || 'unknown'));
            }
        })
        .catch(err => {
            showToast('Failed to delete document');
        });
}

function kbPurgeConfirm() {
    if (!confirm('WARNING: This will delete ALL documents in the knowledge base. Are you absolutely sure?')) return;
    if (!confirm('Final confirmation: Type "yes" to proceed.')) return;
    
    fetch('/kb/purge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: 'yes' })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status) {
            showToast('Knowledge base purged and recreated');
            loadKbStats();
            loadDocuments(1);
        } else {
            showToast('Error: ' + (data.error || 'unknown'));
        }
    })
    .catch(err => {
        showToast('Failed to purge knowledge base');
    });
}

function kbExport() {
    window.location.href = '/kb/export';
}

// Helper (als niet al globaal)
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Integratie: voeg knop toe aan header navigatie
document.addEventListener('DOMContentLoaded', function() {
    // Voeg 'KB' knop toe aan nav (optioneel)
    const nav = document.querySelector('.nav');
    if (nav) {
        const kbBtn = document.createElement('button');
        kbBtn.className = 'nav-btn';
        kbBtn.textContent = '📚 KB';
        kbBtn.onclick = toggleKbBrowser;
        nav.insertBefore(kbBtn, nav.querySelector('.mode-toggle'));
    }
});
