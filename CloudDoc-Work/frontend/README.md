# CloudDoc AI frontend

A dependency-free page for asking questions about PDF files. Plain HTML, CSS and vanilla JavaScript. No build step, no framework, no external fonts, no analytics, no API keys. The page makes network requests only to the backend address you configure.

## Files

| File | Purpose |
|---|---|
| `index.html` | Main page: left panel (status, upload, documents), conversation, input |
| `app.js` | API calls, upload progress, rendering, error handling |
| `styles.css` | Styles for the main page. Flat colors, system fonts, rectangular controls |
| `privacy.html`, `terms.html`, `legal.css` | Legal pages. Contain placeholders you must fill (see Before launch) |
| `favicon.svg`, `favicon.ico`, `apple-touch-icon.png` | Site icons |
| `check_launch.py` | Pre-launch check. Fails if anything on the list below is unfinished |

## Run locally

```bash
python -m http.server 5173
# open http://localhost:5173
```

The backend address defaults to `http://127.0.0.1:8000`. Change it under Backend settings in the left panel. It is saved in the browser's local storage. The backend must allow CORS from the origin that serves this page.

## Backend calls used

| Call | Use |
|---|---|
| `GET /api/health` | Any 2xx response means the backend is connected |
| `GET /api/provider/status` | Model name and OCR status shown in the left panel |
| `GET /api/documents` | List documents (array, or `{ "documents": [...] }`) |
| `POST /api/documents` | Upload, `multipart/form-data`, key `file` |
| `DELETE /api/documents/{id}` | Delete a document |
| `GET /api/documents/{id}/file` | PDF shown in the viewer |
| `POST /api/chat` | `{ "question": string, "document_id": string or null }` |
| `POST /api/operations` | Quick Analysis buttons (`summarize`, `key_points`, `deadlines`, `costs`, `people`, `compare`) |

Chat response fields used: `answer`, `sources` (`document_id`, `filename`, `page`, `text`, `score`), `mode`, `model`. `document_id` is `null` when All Uploaded Documents is selected.

## How the interface behaves

- Answers show a Thoughts checklist (what was searched, how many passages were found, how the answer was produced), the answer text, numbered citations, and a collapsible Sources list. The checklist text comes from the real response. The step-by-step ticking is a short staged reveal after the response arrives, not live progress. Change `gap` in `playSteps()` in `app.js` to adjust or remove it.
- Selecting a citation number opens that page in the PDF viewer and highlights the matching source.
- The left panel collapses on desktop (remembered) and slides in on narrow screens. The upload area shrinks to a slim button once a document exists.
- Upload progress is the real browser upload progress. After the bytes are sent it shows a processing message until the backend replies.
- Filenames, questions, answers and source text are inserted with `textContent`, never as HTML.
- Stored in the browser: `clouddoc.baseUrl`, `clouddoc.sidebarCollapsed`, `clouddoc.toolsCollapsed`. No cookies. The conversation lives in memory only.

## Before launch

Run `python check_launch.py`. It must print "All checks passed." It checks for: unfilled placeholders, em and en dashes, emoji and symbol characters, gradients, pill-shaped radii, requests to outside addresses, "Made with" or "Powered by" wording, cursor, scroll or counter effects, missing favicon files, and missing links to the privacy and terms pages.

Things the script cannot do for you:

1. **Fill every placeholder** in `privacy.html` and `terms.html`. They are marked in yellow and wrapped in double square brackets. The text is a plain starting draft built from what this page does. Have a lawyer review it for your jurisdiction before it goes live. The backend sections (where documents are stored, retention, who has access, which model runs where) must describe your real setup.
2. **Decide the deployment model first.** If the backend runs on each user's own computer, a public website cannot reach it from other machines, and browsers may block an `https` page from calling a plain `http` backend. If you host one backend for everyone, documents are stored on your server, and the privacy policy must say so. Pick one before you write the policy.
3. **Connect the custom domain** at your host: add the domain in the host's dashboard, create the DNS records it shows (usually a CNAME for `www` and an A or ALIAS record for the root), wait for DNS to update, and confirm HTTPS works. Then set the backend's CORS allow-list to the final domain and use the backend's `https` address in Backend settings.
4. **Check the host's own badge or footer.** Some hosting platforms add a banner to free plans. It is not in these files and has to be turned off in the host's settings.
5. **Look at the real site once** on a phone and a desktop: favicon in the tab, both legal pages open from the footer, no console errors.

## Manual test checklist

1. **Backend down.** The status shows "Backend unavailable" and the document list shows an error. Start the backend and press Sync.
2. **Empty state.** With no documents the page shows the heading, three steps and example questions.
3. **Upload.** Click the upload area or drag a PDF onto it. Progress shows, then a processing message, then the document appears in the list.
4. **Upload error.** Upload an unsupported or oversized file. The row turns red with the server's message and can be dismissed. A 0-byte file is rejected before upload.
5. **Ask.** Type a question and press Enter. The checklist ticks, then the answer appears with numbered citations and Sources.
6. **Scope.** Select one document and check the request body contains its `document_id`. Select All Uploaded Documents and check it sends `null`.
7. **Citations.** Select a number. The PDF opens at that page and the source card is highlighted.
8. **Long conversation.** Ask six or more questions. The conversation scrolls inside its own area and the input stays at the bottom. The Latest button appears when you scroll up.
9. **Left panel.** Collapse and expand it. Reload and check the state is remembered. Below 1025px wide it slides in and closes with the button, the dark overlay or Esc.
10. **Injection check.** Upload a file named `<img src=x onerror=alert(1)>.pdf`. It displays as text and nothing runs.
11. **Keyboard.** Tab through everything. Focus outlines are visible and "Skip to question box" appears on the first Tab.
12. **Legal pages.** Open Privacy policy and Terms from the footer. Check there is no yellow placeholder text left.
