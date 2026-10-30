# Integration Checklist

Complete in order. Tick only what you personally verified.

## Before merging anyone's branch
- [ ] Only the owner's paths from `TASKS.md` were changed (`git diff --stat`)
- [ ] `API_CONTRACT.md` unchanged, or the change was agreed by backend and frontend owners
- [ ] No files from `data/`, `.venv/`, or `.env` staged

## Backend
- [ ] Fresh venv: `pip install -r requirements.txt` succeeds
- [ ] Server starts with `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`
- [ ] Function signatures match `ARCHITECTURE.md` (A↔C, B↔C)
- [ ] Status codes 201/400/404/413/422 match `API_CONTRACT.md`
- [ ] `answer` prefix and empty/no-match strings match the contract exactly

## Frontend
- [ ] Required DOM ids present; only relative `/api/...` URLs
- [ ] No CDN/external URLs (`grep -nE "https?://" frontend/` shows none except harmless comments/links)
- [ ] Source text rendered via `textContent` (`grep -n innerHTML frontend/app.js` is empty)
- [ ] Results labelled "Retrieved passages", no "AI answer" wording

## End to end
- [ ] Acceptance tests 1–12 in `TASKS.md` all pass
- [ ] Server bound to 127.0.0.1 only
- [ ] Documents survive a server restart
- [ ] Demo PDFs contain no personal or confidential data
- [ ] README setup steps work on a teammate's machine from a clean clone
