(() => {
  'use strict';

  const DEFAULT_BASE = 'http://127.0.0.1:8000';
  const STORE_KEY = 'clouddoc.baseUrl';

  const EXAMPLES = [
    'What are the core findings and key points?',
    'What deadlines, dates, or schedules are mentioned?',
    'What does this document say about fees, prices, or costs?',
    'Who is responsible for executing the stated tasks?'
  ];

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  };

  const state = {
    base: loadBase(),
    docs: [],
    selectedDocId: null,
    busy: false,
    uploadsCount: 0,
    chatHistory: [],
    pendingDeleteDoc: null,
    provider: {
      provider: 'retrieval',
      ollama_available: false,
      ocr_available: false,
      details: ''
    }
  };

  /* ---------- Storage & URLs ---------- */
  function loadBase() {
    try {
      const saved = localStorage.getItem(STORE_KEY);
      if (saved) return saved;
      if (window.location && window.location.origin && window.location.origin.startsWith('http')) {
        return window.location.origin;
      }
      return DEFAULT_BASE;
    } catch {
      return DEFAULT_BASE;
    }
  }


  function normalizeBase(v) {
    const u = new URL(v.trim());
    if (!/^https?:$/.test(u.protocol)) throw new Error('Use an http or https URL.');
    return u.origin + u.pathname.replace(/\/+$/, '');
  }

  const url = (path) => state.base + path;

  /* ---------- Toast Notification ---------- */
  function showToast(message, type = 'info') {
    const container = $('toastContainer');
    if (!container) return;
    const toast = el('div', `toast ${type}`, message);
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.2s ease';
      setTimeout(() => toast.remove(), 250);
    }, 3200);
  }

  /* ---------- API Client ---------- */
  function messageFromBody(body, status) {
    if (body && typeof body === 'object') {
      const d = body.detail ?? body.error ?? body.message;
      if (typeof d === 'string') return d;
      if (Array.isArray(d)) return d.map((x) => (x && x.msg) || JSON.stringify(x)).join('; ');
      if (d && typeof d === 'object') return JSON.stringify(d);
    }
    return `The server returned an error (HTTP ${status}).`;
  }

  async function api(path, opts) {
    let res;
    try {
      res = await fetch(url(path), opts);
    } catch {
      throw new Error(`Can't reach backend at ${state.base}. Check that it is running and CORS allows this origin.`);
    }

    let body = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON response */
    }

    if (!res.ok) {
      throw new Error(messageFromBody(body, res.status));
    }
    return body;
  }

  /* ---------- System & Provider Status ---------- */
  async function checkHealth() {
    const dot = $('backendDot');
    const label = $('backendStatus');
    const badge = $('providerBadge');
    const ocrBadge = $('ocrBadge');

    dot.dataset.state = 'checking';
    label.textContent = 'Connecting to backend…';

    try {
      await api('/api/health');
      dot.dataset.state = 'ok';
      label.textContent = 'Backend connected';

      // Check provider details
      try {
        const prov = await api('/api/provider/status');
        state.provider = prov;
        if (prov.provider === 'ollama' && prov.ollama_available) {
          badge.textContent = `Model: ${prov.ollama_model}`;
          $('modeBadgeText').textContent = `Model: ${prov.ollama_model}`;
        } else if (prov.provider === 'ollama') {
          badge.textContent = 'Ollama offline';
          $('modeBadgeText').textContent = 'Retrieval only';
        } else {
          badge.textContent = 'Retrieval only';
          $('modeBadgeText').textContent = 'Retrieval only';
        }

        ocrBadge.textContent = prov.ocr_available ? 'OCR: on' : 'OCR: off';
      } catch {
        badge.textContent = 'Retrieval only';
        $('modeBadgeText').textContent = 'Retrieval only';
      }

      return true;
    } catch (e) {
      dot.dataset.state = 'down';
      label.textContent = 'Backend unavailable';
      label.title = e.message;
      badge.textContent = 'Not connected';
      $('modeBadgeText').textContent = 'Not connected';
      return false;
    }
  }

  /* ---------- Document Formatting Helpers ---------- */
  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
  }

  function formatDate(isoStr) {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    } catch {
      return '';
    }
  }

  function normalizeDoc(d) {
    if (!d || typeof d !== 'object') return null;
    const id = d.id ?? d.document_id;
    const filename = d.filename ?? d.name;
    if (!id || !filename) return null;

    const pageCount = d.page_count ?? d.pages;
    const sizeBytes = d.size_bytes ?? d.size;
    const dateStr = d.uploaded_at ?? d.uploaded;

    const metaParts = [];
    if (Number.isFinite(pageCount)) metaParts.push(`${pageCount} ${pageCount === 1 ? 'page' : 'pages'}`);
    if (Number.isFinite(sizeBytes)) metaParts.push(formatBytes(sizeBytes));
    if (dateStr) metaParts.push(formatDate(dateStr));

    return {
      id: String(id),
      filename: String(filename),
      meta: metaParts.join(' · ') || 'Ready',
      pageCount: pageCount || 1,
      sizeBytes: sizeBytes || 0,
      uploadedAt: dateStr || ''
    };
  }

  /* ---------- Document Library ---------- */
  async function loadDocs() {
    const listEl = $('docList');
    listEl.replaceChildren(el('p', 'settings-note', 'Loading documents…'));

    try {
      const body = await api('/api/documents');
      const raw = Array.isArray(body) ? body : (body && Array.isArray(body.documents) ? body.documents : []);
      state.docs = raw.map(normalizeDoc).filter(Boolean);

      // Validate selected doc
      if (state.selectedDocId && !state.docs.some((d) => d.id === state.selectedDocId)) {
        state.selectedDocId = null;
      }

      renderDocs();
    } catch (e) {
      state.docs = [];
      listEl.replaceChildren(el('p', 'settings-note', `Couldn't load documents: ${e.message}`));
      $('docCount').textContent = '0';
    }
  }

  function renderDocs() {
    const listEl = $('docList');
    listEl.replaceChildren();

    const filterVal = ($('docFilterInput').value || '').toLowerCase().trim();
    const visibleDocs = state.docs.filter((d) => d.filename.toLowerCase().includes(filterVal));

    $('docCount').textContent = String(state.docs.length);
    document.querySelector('.upload-section').classList.toggle('compact', state.docs.length > 0);

    // "All Documents" Scope Card
    const allCard = el('div', `doc-card ${state.selectedDocId === null ? 'selected' : ''}`);
    allCard.setAttribute('role', 'radio');
    allCard.setAttribute('aria-checked', String(state.selectedDocId === null));

    const allMain = el('div', 'doc-card-main');
    allMain.innerHTML = `
      <svg class="doc-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <rect x="2" y="7" width="20" height="14" rx="2" ry="2"/>
        <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>
      </svg>
      <div class="doc-card-details">
        <span class="doc-card-name">All Uploaded Documents</span>
        <span class="doc-card-meta">${state.docs.length} ${state.docs.length === 1 ? 'document' : 'documents'} indexed</span>
      </div>
    `;
    allCard.appendChild(allMain);
    allCard.addEventListener('click', () => {
      selectScope(null);
    });
    listEl.appendChild(allCard);

    if (!visibleDocs.length) {
      if (filterVal) {
        listEl.appendChild(el('p', 'settings-note', `No documents match "${filterVal}".`));
      } else {
        listEl.appendChild(el('p', 'settings-note', 'No documents uploaded yet. Drop a PDF above to get started.'));
      }
    } else {
      visibleDocs.forEach((d) => {
        const card = el('div', `doc-card ${state.selectedDocId === d.id ? 'selected' : ''}`);
        card.setAttribute('role', 'radio');
        card.setAttribute('aria-checked', String(state.selectedDocId === d.id));

        const main = el('div', 'doc-card-main');
        main.innerHTML = `
          <svg class="doc-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <div class="doc-card-details">
            <span class="doc-card-name"></span>
            <span class="doc-card-meta"></span>
          </div>
        `;
        const nameEl = main.querySelector('.doc-card-name');
        nameEl.textContent = d.filename;
        nameEl.title = d.filename;
        main.querySelector('.doc-card-meta').textContent = d.meta;
        main.addEventListener('click', () => selectScope(d.id));

        const actions = el('div', 'doc-card-actions');

        // View PDF button
        const viewBtn = el('button', 'icon-action-btn');
        viewBtn.type = 'button';
        viewBtn.title = 'View PDF at page 1';
        viewBtn.innerHTML = `
          <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M1 8s3-5 7-5 7 5 7 5-3 5-7 5-7-5-7-5z"/><circle cx="8" cy="8" r="2.5"/>
          </svg>
        `;
        viewBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          openPdfViewer(d.id, d.filename, 1);
        });

        // Delete button
        const delBtn = el('button', 'icon-action-btn delete-btn');
        delBtn.type = 'button';
        delBtn.title = 'Delete document';
        delBtn.innerHTML = `
          <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M2 4h12M5 4V2.5A1.5 1.5 0 0 1 6.5 1h3A1.5 1.5 0 0 1 11 2.5V4m2 0v9.5A1.5 1.5 0 0 1 11.5 15h-7A1.5 1.5 0 0 1 3 13.5V4"/>
          </svg>
        `;
        delBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          confirmDeleteDoc(d);
        });

        actions.append(viewBtn, delBtn);
        card.append(main, actions);
        listEl.appendChild(card);
      });
    }

    updateScopeDisplay();
  }

  function selectScope(id) {
    state.selectedDocId = id;
    renderDocs();
    closeSidebar();
  }

  function updateScopeDisplay() {
    const cur = state.docs.find((d) => d.id === state.selectedDocId);
    const scopeLabel = $('scopeLabel');
    const clearBtn = $('clearScopeBtn');

    if (cur) {
      scopeLabel.textContent = cur.filename;
      clearBtn.hidden = false;
    } else {
      scopeLabel.textContent = 'All uploaded documents';
      clearBtn.hidden = true;
    }
  }

  /* ---------- Document Deletion Modal ---------- */
  function confirmDeleteDoc(doc) {
    state.pendingDeleteDoc = doc;
    $('deleteTargetName').textContent = doc.filename;
    $('deleteModal').hidden = false;
  }

  function closeDeleteModal() {
    state.pendingDeleteDoc = null;
    $('deleteModal').hidden = true;
  }

  async function executeDelete() {
    if (!state.pendingDeleteDoc) return;
    const doc = state.pendingDeleteDoc;
    closeDeleteModal();

    try {
      await api(`/api/documents/${doc.id}`, { method: 'DELETE' });
      showToast(`Deleted "${doc.filename}" successfully.`, 'success');
      if (state.selectedDocId === doc.id) {
        state.selectedDocId = null;
      }
      await loadDocs();
    } catch (e) {
      showToast(`Delete failed: ${e.message}`, 'error');
    }
  }

  /* ---------- Upload Handling ---------- */
  function addUploadItem(name) {
    const li = el('li', 'upload-item');
    const head = el('div', 'upload-item-header');
    head.append(el('span', 'upload-filename', name), el('span', 'upload-pct', '0%'));
    const bar = el('div', 'upload-progress-bar');
    const fill = el('div', 'upload-progress-fill');
    bar.append(fill);
    const msg = el('div', 'upload-msg', 'Uploading to server…');
    li.append(head, bar, msg);
    $('uploads').prepend(li);

    return {
      progress(pct) {
        fill.style.width = pct + '%';
        head.lastChild.textContent = pct + '%';
      },
      processing() {
        msg.textContent = 'Extracting text (OCR runs on image-only pages) and building the search index…';
      },
      done(text) {
        li.className = 'upload-item done';
        bar.remove();
        head.lastChild.textContent = '';
        msg.textContent = text;
        setTimeout(() => li.remove(), 4000);
      },
      fail(text) {
        li.className = 'upload-item error';
        bar.remove();
        head.lastChild.textContent = '';
        msg.textContent = text;
        const x = el('button', 'icon-action-btn', '×');
        x.type = 'button';
        x.title = 'Dismiss';
        x.addEventListener('click', () => li.remove());
        head.lastChild.replaceWith(x);
      }
    };
  }

  function uploadSingleFile(file) {
    const row = addUploadItem(file.name);
    state.uploadsCount++;
    $('dropzone').disabled = true;

    const finish = () => {
      if (--state.uploadsCount === 0) $('dropzone').disabled = false;
    };

    const xhr = new XMLHttpRequest();
    xhr.open('POST', url('/api/documents'));
    xhr.responseType = 'json';

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const pct = Math.round((e.loaded / e.total) * 100);
      row.progress(pct);
      if (pct >= 100) row.processing();
    };

    xhr.onerror = () => {
      row.fail(`Upload failed: cannot connect to backend at ${state.base}.`);
      finish();
    };

    xhr.onabort = () => {
      row.fail('Upload aborted.');
      finish();
    };

    xhr.onload = async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        row.done('Indexed successfully.');
        showToast(`Uploaded and indexed "${file.name}"`, 'success');
        await loadDocs();
      } else {
        row.fail(`Upload failed: ${messageFromBody(xhr.response, xhr.status)}`);
      }
      finish();
    };

    const fd = new FormData();
    fd.append('file', file);
    xhr.send(fd);
  }

  function handleFiles(files) {
    Array.from(files || []).forEach((f) => {
      if (!f.size) {
        addUploadItem(f.name).fail('File is 0 bytes. Select a valid PDF.');
        return;
      }
      if (!f.name.toLowerCase().endsWith('.pdf')) {
        addUploadItem(f.name).fail('Only .pdf files are supported.');
        return;
      }
      uploadSingleFile(f);
    });
  }

  /* ---------- PDF Viewer Drawer ---------- */
  /* chunkId (optional): the backend serves a copy of the PDF with that evidence highlighted. */
  function openPdfViewer(docId, filename, page = 1, chunkId = null) {
    const drawer = $('pdfDrawer');
    $('pdfDrawerFilename').textContent = filename;
    $('pdfDrawerPage').textContent = chunkId ? `Page ${page} · evidence highlighted` : `Page ${page}`;

    const query = chunkId ? `?highlight=${encodeURIComponent(chunkId)}` : '';
    const pdfUrl = `${url(`/api/documents/${docId}/file`)}${query}#page=${page}`;
    $('pdfOpenExternal').href = pdfUrl;
    $('pdfFrame').src = pdfUrl;

    document.querySelector('.app-container').classList.add('drawer-open');
    drawer.setAttribute('aria-hidden', 'false');
  }

  function closePdfViewer() {
    const drawer = $('pdfDrawer');
    document.querySelector('.app-container').classList.remove('drawer-open');
    drawer.setAttribute('aria-hidden', 'true');
    $('pdfFrame').src = 'about:blank';
  }

  /* ---------- Chat UI & Rendering ---------- */
  const chatFeed = () => $('chat');
  const NEAR_BOTTOM_PX = 120;
  const isNearBottom = () => {
    const f = chatFeed();
    return f.scrollHeight - f.scrollTop - f.clientHeight < NEAR_BOTTOM_PX;
  };
  const scrollDown = (smooth = true) => {
    const f = chatFeed();
    f.scrollTo({ top: f.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  };
  /* After an answer lands: show its start if it is taller than the view, else jump to bottom */
  const revealMessage = (node) => {
    const f = chatFeed();
    if (node && node.offsetHeight > f.clientHeight - 80) {
      f.scrollTo({ top: Math.max(0, node.offsetTop - f.offsetTop - 16), behavior: 'smooth' });
    } else {
      scrollDown();
    }
  };
  const updateScrollBtn = () => {
    const btn = $('scrollBottomBtn');
    if (!btn) return;
    btn.hidden = isNearBottom();
    const comp = document.querySelector('.composer-container');
    if (comp) btn.style.bottom = (comp.offsetHeight + 10) + 'px';
  };

  function hideEmpty() {
    const e = $('emptyState');
    if (e) e.hidden = true;
  }

  function findDocByFilename(filename) {
    if (!filename) return null;
    const clean = filename.trim().toLowerCase();
    return state.docs.find((d) => d.filename.toLowerCase() === clean || d.filename.toLowerCase().includes(clean)) || null;
  }

  /* ---------- Notebook-style answer rendering ---------- */
  const CARET_SVG = '<svg class="thoughts-caret" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 10l4-4 4 4"/></svg>';

  function docForSource(s) {
    if (!s) return null;
    return state.docs.find((d) => d.id === String(s.document_id)) || findDocByFilename(s.filename);
  }

  function openSource(s, page) {
    const doc = docForSource(s);
    const id = doc ? doc.id : s && s.document_id;
    const name = doc ? doc.filename : (s && s.filename) || 'Document';
    if (!id) return;
    openPdfViewer(id, name, page || (s && s.page) || 1, (s && s.chunk_id) || null);
  }

  /* Collapsible "Thoughts" checklist.
     steps = [{title, text, status?: 'done' | 'running' | 'pending'}]  (default: done) */
  const CHECK_SVG = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';

  function buildThoughts(steps, { running = false, open = false, animate = true } = {}) {
    const wrap = el('div', 'thoughts' + (running ? ' running' : '') + (open ? ' open' : '') + (animate ? '' : ' static'));
    const doneCount = steps.filter((s) => (s.status || 'done') === 'done').length;

    const btn = el('button', 'thoughts-toggle');
    btn.type = 'button';
    btn.setAttribute('aria-expanded', String(open));
    btn.append(
      el('span', 'thoughts-dot'),
      el('span', '', running ? 'Working…' : 'Thoughts'),
      el('span', 'thoughts-count', `${doneCount}/${steps.length} done`)
    );
    btn.insertAdjacentHTML('beforeend', CARET_SVG);

    const list = el('ol', 'thoughts-list');
    steps.forEach((st, i) => {
      const status = st.status || 'done';
      const li = el('li', `thought-step is-${status}`);
      li.style.setProperty('--i', i);
      const icon = el('span', 'step-icon');
      icon.setAttribute('aria-hidden', 'true');
      if (status === 'done') icon.innerHTML = CHECK_SVG;
      const body = el('div', 'step-body');
      body.append(el('div', 'thought-title', st.title), el('div', 'thought-text', st.text));
      const sr = el('span', 'sr-only', status === 'done' ? 'Done: ' : status === 'running' ? 'In progress: ' : 'Waiting: ');
      li.append(icon, body);
      body.firstChild.prepend(sr);
      list.appendChild(li);
    });

    btn.addEventListener('click', () => {
      const isOpen = wrap.classList.toggle('open');
      btn.setAttribute('aria-expanded', String(isOpen));
    });
    wrap.append(btn, list);
    return wrap;
  }

  function scopeText() {
    const cur = state.docs.find((d) => d.id === state.selectedDocId);
    if (cur) return `“${cur.filename}”`;
    return `all ${state.docs.length} uploaded ${state.docs.length === 1 ? 'document' : 'documents'}`;
  }

  function thoughtsFromResponse(data) {
    const sources = Array.isArray(data.sources) ? data.sources : [];
    const files = new Set(sources.map((s) => s.filename).filter(Boolean));
    const steps = [
      { title: 'Searching documents', text: `Looked through ${scopeText()} for passages related to the question.` }
    ];
    if (sources.length) {
      const pages = [...new Set(sources.map((s) => s.page).filter((p) => p !== undefined && p !== null))];
      steps.push({
        title: 'Retrieving evidence',
        text: `Found ${sources.length} matching ${sources.length === 1 ? 'passage' : 'passages'}` +
          (files.size ? ` in ${files.size} ${files.size === 1 ? 'document' : 'documents'}` : '') +
          (pages.length ? ` (page${pages.length === 1 ? '' : 's'} ${pages.join(', ')})` : '') + '.'
      });
    } else {
      steps.push({ title: 'Retrieving evidence', text: 'No passages matched this question.' });
    }
    // Only describe what actually happened: with no retrieved passages nothing was composed from evidence.
    let composeText;
    if (!sources.length) {
      composeText = 'No answer was generated from documents because no passages were retrieved.';
    } else if (data.mode === 'generated_ai') {
      composeText = `Wrote the answer from the ${sources.length} retrieved ${sources.length === 1 ? 'passage' : 'passages'} using ${data.model || 'the local model'}.`;
    } else {
      composeText = 'Returned the retrieved passages directly, without a generative model.';
    }
    steps.push({ title: 'Composing the answer', text: composeText });
    return steps;
  }

  /* Inline tokens: [Doc: x, Page: n] citations and **bold** */
  function renderInline(text, parent, ctx) {
    const tokenRegex = /(\[Doc:\s*[^,\]]+,\s*Page:\s*\d+\]|\*\*[^*]+\*\*)/gi;
    text.split(tokenRegex).forEach((part) => {
      if (!part) return;
      const cm = part.match(/^\[Doc:\s*([^,\]]+),\s*Page:\s*(\d+)\]$/i);
      if (cm) {
        const fn = cm[1].trim();
        const page = parseInt(cm[2], 10) || 1;
        const fnLow = fn.toLowerCase();
        const idx = ctx.sources.findIndex((s) =>
          Number(s.page) === page && s.filename && (s.filename.toLowerCase() === fnLow || s.filename.toLowerCase().includes(fnLow) || fnLow.includes(s.filename.toLowerCase())));
        const chip = el('button', 'cite-chip', idx >= 0 ? String(idx + 1) : `p.${page}`);
        chip.type = 'button';
        chip.title = `${fn} · page ${page}`;
        chip.setAttribute('aria-label', `Open ${fn}, page ${page}`);
        chip.addEventListener('click', () => {
          const src = idx >= 0 ? ctx.sources[idx] : { filename: fn, page };
          if (!docForSource(src) && state.docs.length) {
            const t = state.selectedDocId ? state.docs.find((d) => d.id === state.selectedDocId) : state.docs[0];
            openPdfViewer(t.id, t.filename, page);
          } else {
            openSource(src, page);
          }
          if (idx >= 0 && ctx.flash) ctx.flash(idx);
        });
        parent.appendChild(chip);
      } else if (part.startsWith('**') && part.endsWith('**')) {
        parent.appendChild(el('strong', '', part.slice(2, -2)));
      } else {
        parent.appendChild(document.createTextNode(part));
      }
    });
  }

  /* Lightweight markdown: headings, bullet / numbered lists, paragraphs. textContent only. */
  function formatAnswerText(text, ctx) {
    const container = el('div', 'msg-bot-body');
    const lines = String(text || '').replace(/\r/g, '').split('\n');
    let para = [];
    let list = null;

    const flushPara = () => {
      if (!para.length) return;
      const p = el('p');
      renderInline(para.join(' '), p, ctx);
      container.appendChild(p);
      para = [];
    };
    const flushList = () => { list = null; };

    lines.forEach((raw) => {
      const line = raw.trimEnd();
      const h = line.match(/^#{1,4}\s+(.*)$/);
      const ul = line.match(/^\s*[-*•]\s+(.*)$/);
      const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);

      if (!line.trim()) { flushPara(); flushList(); return; }
      if (h) {
        flushPara(); flushList();
        const hd = el('h4');
        renderInline(h[1], hd, ctx);
        container.appendChild(hd);
      } else if (ul || ol) {
        flushPara();
        const kind = ul ? 'ul' : 'ol';
        if (!list || list.tagName.toLowerCase() !== kind) {
          list = el(kind);
          container.appendChild(list);
        }
        const li = el('li');
        renderInline((ul || ol)[1], li, ctx);
        list.appendChild(li);
      } else {
        flushList();
        para.push(line.trim());
      }
    });
    flushPara();
    return container;
  }

  function createSourceCard(s, n) {
    const card = el('div', 'source-card');
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.title = `Click to view ${s.filename} at Page ${s.page}`;

    const head = el('div', 'source-card-head');
    head.append(
      el('span', 'source-num', n),
      el('span', 'source-card-file', s.filename || 'Document'),
      el('span', 'source-page-pill', `Page ${s.page}`),
      el('span', 'source-score-pill', `Score: ${typeof s.score === 'number' ? (s.score * 100).toFixed(1) + '%' : 'Direct'}`)
    );

    card.append(head, el('p', 'source-card-text', s.text || ''));

    const jump = () => openSource(s, s.page || 1);
    card.addEventListener('click', jump);
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); jump(); }
    });
    return card;
  }

  function createBotMessage(data, userQuestion, opts = {}) {
    const msg = el('article', 'msg-bot nb');
    const sources = Array.isArray(data.sources) ? data.sources : [];

    // 1) Thoughts (collapsed)
    msg.appendChild(buildThoughts(thoughtsFromResponse(data), opts.played ? { open: true, animate: false } : {}));

    // 2) Sources (built first so citation chips can flash cards)
    let details = null;
    const cards = [];
    if (sources.length) {
      details = el('details', 'sources-details');
      details.appendChild(el('summary', '', `Sources (${sources.length})`));
      const grid = el('div', 'source-cards-grid');
      sources.forEach((s, i) => {
        const c = createSourceCard(s, i + 1);
        cards.push(c);
        grid.appendChild(c);
      });
      details.appendChild(grid);
    }

    const ctx = {
      sources,
      flash(i) {
        if (!details || !cards[i]) return;
        details.open = true;
        cards[i].classList.remove('flash');
        void cards[i].offsetWidth;
        cards[i].classList.add('flash');
      }
    };

    // 3) Answer body
    const bodyEl = formatAnswerText(data.answer || 'No evidence returned.', ctx);
    if (opts.played) bodyEl.classList.add('fade-in');
    msg.appendChild(bodyEl);

    // 4) Action row
    const actions = el('div', 'msg-actions');
    const copyBtn = el('button', 'copy-btn');
    copyBtn.type = 'button';
    copyBtn.innerHTML = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="5" width="8" height="8" rx="1.5"/><path d="M3 11V3a1 1 0 0 1 1-1h8"/></svg> Copy';
    copyBtn.addEventListener('click', () => {
      let t = (data.answer || '') + '\n\nSources:\n';
      sources.forEach((s, i) => { t += `[${i + 1}] ${s.filename} (Page ${s.page}): "${s.text}"\n`; });
      navigator.clipboard.writeText(t).then(
        () => showToast('Answer and sources copied.', 'success'),
        () => showToast('Copy failed. Clipboard access was blocked.', 'error')
      );
    });
    actions.appendChild(copyBtn);
    msg.appendChild(actions);

    if (details) msg.appendChild(details);

    state.chatHistory.push({ role: 'user', text: userQuestion, timestamp: new Date().toISOString() });
    state.chatHistory.push({ role: 'bot', text: data.answer, sources, mode: data.mode, timestamp: new Date().toISOString() });
    return msg;
  }

  function createErrorMessage(text) {
    const msg = el('article', 'msg-bot');
    msg.style.borderColor = 'rgba(239, 68, 68, 0.4)';
    msg.setAttribute('role', 'alert');
    const header = el('div', 'msg-bot-header');
    header.append(el('span', 'bot-tag', 'Error'));
    header.style.color = 'var(--status-err)';
    msg.appendChild(header);
    const body = el('div', 'msg-bot-body', text);
    body.style.color = 'var(--status-err)';
    msg.appendChild(body);
    return msg;
  }

  /* Tick the checklist one step at a time, then let the caller show the answer.
     The step texts are the real results from the response; only the reveal is staged. */
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  async function playSteps(loadingNode, steps) {
    const fresh = buildThoughts(
      steps.map((s, i) => ({ ...s, status: i === 0 ? 'running' : 'pending' })),
      { running: true, open: true }
    );
    loadingNode.querySelector('.thoughts').replaceWith(fresh);
    const items = [...fresh.querySelectorAll('.thought-step')];
    const count = fresh.querySelector('.thoughts-count');

    const setPending = (li) => { li.querySelector('.thought-text').textContent = 'Waiting…'; };
    const setRunning = (li, i) => {
      li.className = 'thought-step is-running';
      li.querySelector('.step-icon').innerHTML = '';
      li.querySelector('.thought-text').textContent = steps[i].text;
    };
    const setDone = (li, i) => {
      li.className = 'thought-step is-done just-done';
      li.querySelector('.step-icon').innerHTML = CHECK_SVG;
      li.querySelector('.thought-text').textContent = steps[i].text;
      count.textContent = `${i + 1}/${steps.length} done`;
    };

    items.forEach((li, i) => { if (i > 0) setPending(li); });
    count.textContent = `0/${steps.length} done`;

    const gap = reducedMotion() ? 0 : 400;
    for (let i = 0; i < items.length; i++) {
      await sleep(gap);
      setDone(items[i], i);
      if (items[i + 1]) setRunning(items[i + 1], i + 1);
      if (isNearBottom()) scrollDown();
      updateScrollBtn();
    }
    fresh.classList.remove('running');
    fresh.querySelector('.thoughts-toggle span:nth-child(2)').textContent = 'Thoughts';
    await sleep(reducedMotion() ? 0 : 250);
  }

  /* Live loader that looks like the finished Thoughts block */
  function createLoader(steps) {
    const box = el('article', 'msg-bot nb loading-nb');
    box.setAttribute('role', 'status');
    box.appendChild(buildThoughts(steps, { running: true, open: true }));
    return box;
  }

  async function askQuestion(question) {
    const q = question.trim();
    if (state.busy || !q) return;

    state.busy = true;
    $('sendBtn').disabled = true;
    hideEmpty();

    // User message row
    const urow = el('div', 'user-row');
    urow.append(el('div', 'msg-user', q));
    chatFeed().append(urow);

    // Live "thinking" block
    const loading = createLoader([
      { title: 'Searching documents', text: `Looking through ${scopeText()} for passages related to your question…`, status: 'running' },
      { title: 'Retrieving evidence', text: 'Waiting for matching passages.', status: 'pending' },
      { title: 'Composing the answer', text: 'Waiting for the answer to be written.', status: 'pending' }
    ]);
    chatFeed().append(loading);
    scrollDown();

    try {
      const data = await api('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: q,
          document_id: state.selectedDocId
        })
      });

      await playSteps(loading, thoughtsFromResponse(data));
      const done = createBotMessage(data, q, { played: true });
      loading.replaceWith(done);
      revealMessage(done);
      setTimeout(updateScrollBtn, 700);
    } catch (e) {
      const err = createErrorMessage(e.message);
      loading.replaceWith(err);
      revealMessage(err);
    } finally {
      state.busy = false;
      $('sendBtn').disabled = false;
      $('question').focus();
      updateScrollBtn();
    }
  }

  /* ---------- Operations Execution ---------- */
  async function executeOperation(opName) {
    if (state.busy) return;
    if (!state.docs.length) {
      showToast('Please upload a PDF document before running analysis.', 'error');
      return;
    }

    let targetDocIds = [];
    if (opName === 'compare') {
      if (state.docs.length < 2) {
        showToast('Multi-document comparison requires at least 2 uploaded PDFs.', 'error');
        return;
      }
      targetDocIds = state.docs.slice(0, 4).map((d) => d.id);
    } else {
      targetDocIds = state.selectedDocId ? [state.selectedDocId] : state.docs.map((d) => d.id);
    }

    state.busy = true;
    $('sendBtn').disabled = true;
    hideEmpty();

    const opTitles = {
      summarize: 'Document Summary',
      key_points: 'Key Points Extraction',
      deadlines: 'Deadlines & Timeline Analysis',
      people: 'Roles & Responsibilities',
      costs: 'Costs, Amounts & Fees',
      compare: 'Multi-Document Comparison'
    };
    const title = opTitles[opName] || opName;

    // Show synthetic user action in chat
    const urow = el('div', 'user-row');
    urow.append(el('div', 'msg-user', `[Analysis: ${title}]`));
    chatFeed().append(urow);

    const loading = createLoader([
      { title: title, text: `Running on ${opName === 'compare' ? `${targetDocIds.length} documents` : scopeText()}…`, status: 'running' },
      { title: 'Composing the result', text: 'Waiting for the result to be written.', status: 'pending' }
    ]);
    chatFeed().append(loading);
    scrollDown();

    try {
      const resp = await api('/api/operations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          operation: opName,
          document_ids: targetDocIds
        })
      });

      const synthData = {
        answer: resp.result,
        sources: resp.sources,
        mode: resp.mode,
        model: resp.model,
        provider: 'retrieval'
      };

      await playSteps(loading, thoughtsFromResponse(synthData));
      const done = createBotMessage(synthData, `[Analysis: ${title}]`, { played: true });
      loading.replaceWith(done);
      revealMessage(done);
    } catch (e) {
      const err = createErrorMessage(e.message);
      loading.replaceWith(err);
      revealMessage(err);
    } finally {
      state.busy = false;
      $('sendBtn').disabled = false;
      updateScrollBtn();
    }
  }

  /* ---------- Export Conversation ---------- */
  function exportConversation() {
    if (!state.chatHistory.length) {
      showToast('No conversation history to export.', 'info');
      return;
    }

    let md = `# CloudDoc AI conversation\n`;
    md += `Exported ${new Date().toLocaleString()}\n\n---\n\n`;

    state.chatHistory.forEach((item) => {
      if (item.role === 'user') {
        md += `### You\n${item.text}\n\n`;
      } else {
        md += `### CloudDoc AI\n`;
        md += `${item.text}\n\n`;
        if (item.sources && item.sources.length) {
          md += `**Sources:**\n`;
          item.sources.forEach((s) => {
            md += `- **[${s.filename} · Page ${s.page}]**: "${s.text}"\n`;
          });
          md += `\n`;
        }
      }
      md += `---\n\n`;
    });

    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8;' });
    const u = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = u;
    a.download = `clouddoc-export-${Date.now()}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(u);
    showToast('Conversation exported as a Markdown file.', 'success');
  }

  function clearChat() {
    state.chatHistory = [];
    const feed = chatFeed();
    feed.replaceChildren();

    // Recreate empty state
    const empty = $('emptyState');
    if (empty) {
      empty.hidden = false;
      feed.appendChild(empty);
    }
    updateScrollBtn();
    showToast('Conversation cleared.', 'info');
  }

  /* ---------- Sidebar Controls (Mobile) ---------- */
  function openSidebar() {
    $('sidebar').classList.add('open');
    $('scrim').hidden = false;
    $('menuBtn').setAttribute('aria-expanded', 'true');
  }

  function closeSidebar() {
    $('sidebar').classList.remove('open');
    $('scrim').hidden = true;
    $('menuBtn').setAttribute('aria-expanded', 'false');
  }

  /* Desktop collapse of the source panel (persisted) */
  const COLLAPSE_KEY = 'clouddoc.sidebarCollapsed';
  const isDesktop = () => window.matchMedia('(min-width: 1025px)').matches;

  function setSidebarCollapsed(collapsed, persist = true) {
    document.querySelector('.app-container').classList.toggle('sidebar-collapsed', collapsed);
    $('collapseSidebarBtn').setAttribute('aria-expanded', String(!collapsed));
    $('expandSidebarBtn').hidden = !collapsed;
    $('sidebar').inert = collapsed && isDesktop();
    if (persist) {
      try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
    }
    if (collapsed && isDesktop()) $('expandSidebarBtn').focus({ preventScroll: true });
    else if (!collapsed) $('collapseSidebarBtn').focus({ preventScroll: true });
  }

  /* ---------- Wiring & Initialization ---------- */
  function init() {
    // URL configuration
    $('baseUrl').value = state.base;
    $('saveUrl').addEventListener('click', async () => {
      try {
        state.base = normalizeBase($('baseUrl').value);
        $('baseUrl').value = state.base;
        try {
          localStorage.setItem(STORE_KEY, state.base);
        } catch {
          /* ignore */
        }
        showToast('Backend URL saved.', 'success');
        if (await checkHealth()) loadDocs();
      } catch (e) {
        showToast(e.message, 'error');
      }
    });

    $('retryHealth').addEventListener('click', async () => {
      if (await checkHealth()) loadDocs();
    });

    // Interactive example prompt cards in empty state
    document.querySelectorAll('.example-card').forEach((card) => {
      card.addEventListener('click', () => {
        const p = card.getAttribute('data-prompt');
        if (p) askQuestion(p);
      });
    });

    // Prompt chips bar above composer
    document.querySelectorAll('.prompt-chips-bar .chip-sm').forEach((btn) => {
      btn.addEventListener('click', () => {
        const p = btn.getAttribute('data-prompt');
        if (p) askQuestion(p);
      });
    });

    // Tool buttons (Quick Analysis)
    document.querySelectorAll('.tool-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const op = btn.getAttribute('data-op');
        if (op) executeOperation(op);
      });
    });
    $('compareBtn').addEventListener('click', () => executeOperation('compare'));

    // Upload dropzone interactions
    const dz = $('dropzone');
    const fi = $('fileInput');
    dz.addEventListener('click', () => fi.click());
    fi.addEventListener('change', () => {
      handleFiles(fi.files);
      fi.value = '';
    });

    ['dragenter', 'dragover'].forEach((eventName) => {
      dz.addEventListener(eventName, (e) => {
        e.preventDefault();
        dz.classList.add('drag-active');
      });
    });

    ['dragleave', 'drop'].forEach((eventName) => {
      dz.addEventListener(eventName, (e) => {
        e.preventDefault();
        dz.classList.remove('drag-active');
      });
    });

    dz.addEventListener('drop', (e) => {
      if (!dz.disabled) handleFiles(e.dataTransfer.files);
    });

    // Document Library actions
    $('refreshDocs').addEventListener('click', loadDocs);
    $('clearScopeBtn').addEventListener('click', () => selectScope(null));

    // Document filter search box
    const filterInput = $('docFilterInput');
    const clearFilterBtn = $('clearFilterBtn');
    filterInput.addEventListener('input', () => {
      clearFilterBtn.hidden = !filterInput.value;
      renderDocs();
    });
    clearFilterBtn.addEventListener('click', () => {
      filterInput.value = '';
      clearFilterBtn.hidden = true;
      renderDocs();
      filterInput.focus();
    });

    // Delete modal buttons
    $('cancelDeleteBtn').addEventListener('click', closeDeleteModal);
    $('confirmDeleteBtn').addEventListener('click', executeDelete);

    // PDF Drawer close
    $('pdfDrawerClose').addEventListener('click', closePdfViewer);

    // Topbar action buttons
    $('clearChatBtn').addEventListener('click', clearChat);
    $('exportChatBtn').addEventListener('click', exportConversation);

    // Composer input handling
    const q = $('question');
    const autoGrow = () => {
      q.style.height = 'auto';
      q.style.height = Math.min(q.scrollHeight, 160) + 'px';
    };
    q.addEventListener('input', autoGrow);
    q.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        $('composer').requestSubmit();
      }
    });

    $('composer').addEventListener('submit', (e) => {
      e.preventDefault();
      const val = q.value;
      q.value = '';
      autoGrow();
      askQuestion(val);
    });

    // Quick Analysis collapse (persisted)
    const TOOLS_KEY = 'clouddoc.toolsCollapsed';
    const applyTools = (collapsed) => {
      $('toolsGrid').hidden = collapsed;
      $('toolsToggle').setAttribute('aria-expanded', String(!collapsed));
      $('toolsToggle').classList.toggle('collapsed', collapsed);
    };
    try { applyTools(localStorage.getItem(TOOLS_KEY) === '1'); } catch { /* ignore */ }
    $('toolsToggle').addEventListener('click', () => {
      const next = !$('toolsGrid').hidden;
      applyTools(next);
      try { localStorage.setItem(TOOLS_KEY, next ? '1' : '0'); } catch { /* ignore */ }
    });

    // Source panel collapse / expand
    $('collapseSidebarBtn').addEventListener('click', () => {
      if (isDesktop()) setSidebarCollapsed(true);
      else closeSidebar();
    });
    $('expandSidebarBtn').addEventListener('click', () => setSidebarCollapsed(false));
    try {
      if (localStorage.getItem(COLLAPSE_KEY) === '1' && isDesktop()) {
        document.querySelector('.app-container').classList.add('sidebar-collapsed');
        $('expandSidebarBtn').hidden = false;
        $('sidebar').inert = true;
        $('collapseSidebarBtn').setAttribute('aria-expanded', 'false');
      }
    } catch { /* ignore */ }
    window.matchMedia('(min-width: 1025px)').addEventListener('change', () => {
      const collapsed = document.querySelector('.app-container').classList.contains('sidebar-collapsed');
      $('sidebar').inert = collapsed && isDesktop();
      $('expandSidebarBtn').hidden = !(collapsed && isDesktop());
    });

    // Scroll-to-latest button + near-bottom tracking
    chatFeed().addEventListener('scroll', updateScrollBtn, { passive: true });
    $('scrollBottomBtn').addEventListener('click', () => scrollDown());
    new ResizeObserver(updateScrollBtn).observe(chatFeed());

    // Mobile sidebar toggle
    $('menuBtn').addEventListener('click', openSidebar);
    $('scrim').addEventListener('click', closeSidebar);

    // Global keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeSidebar();
        closePdfViewer();
        closeDeleteModal();
      }
    });

    // Initial load
    checkHealth().then(loadDocs);
  }

  init();
})();
