# Shade America Team Portal — Project Notes

## Overview
Flask web app deployed at shadeamerica.team. Built for the Shade America field and office team to manage jobs, run estimates, and handle pricing. Hosted on Render.com (web service + PostgreSQL), code stored on GitHub.

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
- **admin** — full access including Users, Settings, Field Preview
- **office** — Dashboard, Jobs, Estimator, Report, Pricing, Hip Calc
- **field** — My Jobs and Forms only

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
