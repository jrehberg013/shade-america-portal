# Shade America Team Portal — Project Notes

## Recent Changes — May 2, 2026

Two batches of work shipped today. Everything below is deployed and live on shadeamerica.team.

### Batch 1 (commit `30eef36`): field_home + view_doc routes
In `app.py`:
- Login + change-password redirects: `url_for('field')` → `url_for('field_home')` for field users.
- New route `GET /field-home` → `field_home()` renders `field_home.html` (the menu page with My Projects / Forms / Logout buttons). Field users land here after login.
- New route `GET /docs/<int:doc_id>/view` → `view_doc(doc_id)` renders `doc_viewer.html` with a Back button (uses `request.referrer`, falls back to job detail).
- `field_preview` simplified to just `render_template('field_home.html')`.

The existing `field()` route at `/field` was kept — the My Projects button on field_home.html links to it.

### Batch 2: Rename "Jobs" → "Projects" + pipeline drag-and-drop

**Visible "Job/Jobs" → "Project/Projects" rename** across 10 templates: `base.html`, `dashboard.html`, `jobs.html`, `job_detail.html`, `new_job.html`, `field.html`, `field_home.html`, `report.html`, `estimator.html`, `estimate_result.html`. All visible labels, page titles, button text, headings, placeholders, and empty states.

**NOT renamed (intentionally — internal only):** URLs (`/jobs/...`), database table (`jobs`), Flask function names, form field names (`name="job_name"`), CSS classes (`.job-card`, `.jobs-table`), template variables (`{{ job.name }}`).

**Sidebar:** "Field Preview" → "Field View".

**Pipeline drag-and-drop on dashboard:**
- Cards in pipeline columns now have `draggable="true"` plus job-id + source-status data attributes.
- Drop handler distinguishes pipeline-source cards (move existing project — calls `/jobs/<id>/status` as JSON) from Trello-source cards (existing create-new-project flow, unchanged).
- `update_status` route in `app.py` now accepts both form-POST (existing job-detail page) and JSON (drag-and-drop). Returns `{ok: true, ...}` or `{error: ...}`.
- Cards move in any direction (forward or backward).
- Optimistic UI: card moves immediately on drop; if server rejects, snaps back with error alert.
- Silent move — no confirmation popup.

### Known limitation (deferred)
Dashboard stats (Pipeline Value, Contract Total, Balance Due, counts) don't auto-update when cards are dragged — they're rendered server-side at page load. **Workaround: F5 / Ctrl+R refreshes them.** User decided manual refresh is fine for now (May 2, 2026). To fix later: have `update_status` return updated stats in JSON, have JS update stat cards in place.

### Earlier today (before this work)
- Credentials rotated (GitHub, Namecheap, Render)
- Render env vars confirmed
- Email backup configured (daily 2 AM)
- 4 new template files added: `doc_viewer.html`, `field_home.html`, plus 2 others — these were used by the new routes in Batch 1.

---

## Overview
Flask web app deployed at shadeamerica.team. Built for the Shade America field and office team to manage projects, run estimates, and handle pricing. Hosted on Render.com (web service + PostgreSQL), code stored on GitHub.

## Tech Stack
- **Backend**: Python / Flask
- **Database**: SQLite (local dev) / PostgreSQL (Render production) via dual-driver `_DB` wrapper in app.py
- **Frontend**: Jinja2 templates, vanilla JS, custom CSS
- **Deployment**: GitHub push → Render manual deploy
- **Push script**: `push_update.bat` — finds GitHub Desktop's bundled git, removes index.lock, commits listed files, pushes to main

## Key Files
| File | Purpose |
|------|---------|
| `app.py` | All routes, pricing logic, DB access |
| `templates/base.html` | Sidebar nav, top bar, layout shell |
| `templates/estimator.html` | Full estimator UI + all JS pricing logic |
| `templates/dashboard.html` | Dashboard / job overview |
| `templates/job_detail.html` | Individual job view/edit |
| `static/style.css` | All styling |
| `static/app.js` | Sidebar toggle, mobile menu |
| `push_update.bat` | Git commit + push script |

## Roles
- **admin** — full access including Users, Settings, Field View
- **office / manager** — Dashboard, Projects, Estimator, Report, Pricing, Hip Calc
- **field** — My Projects (lands on /field-home menu) and Forms only

## Pricing Algorithm (v1.3.0+)
The estimator uses a **cut-optimization (bin-packing) algorithm** to find the cheapest combination of pipe sticks for each row.

### How it works
For each pole row: given a pole length and quantity needed, the algorithm tries every valid stick length as the "primary" stick, uses the shortest valid stick for any remainder, and picks the combination with the lowest total cost.

### Stick lengths by material
| Material | Stick Lengths |
|----------|--------------|
| SCH40 Galvanized | 21ft, 24ft |
| SCH40 Black Pipe | 21ft, 42ft |
| HSS (4x4, 4x6) | 20ft, 24ft, 40ft |
| OD Galv Tubing | 24ft only (ceil per pole) |

### Example
6" Black Pipe, 18ft poles, qty=2:
- 1×42ft stick = $780 (fits 2 poles, 6ft waste)
- 2×21ft sticks = $766 (3ft waste each)
- **Algorithm picks 2×21ft = $766**

HSS 4x4¼", 12ft poles, qty=2:
- 2×20ft sticks = $474 (8ft waste each)
- 1×24ft stick = $317 (fits exactly 2 poles, zero waste)
- **Algorithm picks 1×24ft = $317**

### Waste Rows
Each pipe section has a `+ Waste Row` button. Waste rows document leftover pipe material applied to a pole — they show $0 cost and are saved/printed with the estimate. Identified by a hidden `{prefix}_waste_{i}=1` field; server skips them in cost calculations.

### Waste Notes
Each regular pipe row shows a note under the cost (e.g., "2×42ft, 6ft waste ea") so the estimator can see which sticks are being used and how much is wasted.

## localStorage Key
Estimator state is saved under key `sa_estimator_v3`. If the estimator behaves oddly after an update, bump this key in estimator.html to clear stale saved state.

## Version History
| Version | Changes |
|---------|---------|
| v1.3.0 | Cut-optimization pipe pricing, waste rows, waste notes, HSS size fix, version badge |
| v1.2.x | Cantilever sections (HSS posts & beams) |
| v1.1.x | Hip pole section, OD Galv tubing |
| v1.0.x | Initial estimator, jobs, dashboard, field view |

## Deployment Checklist
1. Make all changes to files listed in `push_update.bat`
2. Update commit message in `push_update.bat`
3. Run `push_update.bat`
4. Log into render.com → shade-america-portal service → Manual Deploy
5. Watch deploy logs for errors

## Database Notes
- Render PostgreSQL free tier can expire after ~90 days of inactivity — check render.com dashboard periodically
- Pricing data is seeded from `PRICING_DEFAULTS` in app.py on first run / when keys are missing
- All pricing is editable via the Pricing page in the portal (admin/office roles)

## Known Gotchas for Future Development
- **Never edit large files (app.py, estimator.html) directly with Write tool** — it truncates. Always use Python patch scripts.
- **Shell `\!` corruption**: `/bin/sh` corrupts `\!` to `\\!` in heredocs. After any JS patch, run byte-level fix: `raw.replace(bytes([92,33]), bytes([33]))`
- **HSS size strings**: app.py receives full strings like `"4x4 HSS 1/4"` — use `startswith()` not `==` for matching
- **LS_KEY**: bump `sa_estimator_v3` → `sa_estimator_v4` etc. whenever localStorage schema changes
