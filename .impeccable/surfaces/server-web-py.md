---
version: 1
slug: "server-web-py"
primary_target: "server/web.py"
related_targets: ["frontend/input.css","server/static/styles.css","tailwind.config.js"]
---

# Surface brief — full-site redesign (landing, quick export, dashboard, about, status, legal)

## Scope and visitor mode

All web surfaces of Phenikaa Calendar Exporter, server-rendered in `server/web.py` with Tailwind (`frontend/input.css` → `server/static/styles.css`). Mode: **Persuade** on the landing/first-viewport level (a student decides to export in one visit), **Operate** on dashboard/export/status surfaces. Bilingual EN/VI copy is preserved; information architecture may change.

## Audience, job, action, proof, constraints

- Audience: Phenikaa students with a QLDT portal session; no other audience.
- Job: get their timetable into their calendar tool. Success = unaided export in under 2 minutes, zero support requests.
- Action: quick export (no account) as the primary action; sign-in for sessions/Google sync as secondary.
- Proof: no-password/no-storage trust posture; dedicated Google calendar only; verified live API workflow.
- Constraints: server-rendered f-string HTML, single Tailwind build, bilingual strings, no invented adoption claims.

## Direction contract

THESIS: the category standard — the friendly-utility tool site (Google Calendar / Notion Calendar craft bar) — executed at full commitment; light, unambiguous, convention embraced without irony or smuggled quirk. The refusal: no themed costume (notebook, ticket, poster) and no hero-metric template; the ordinary arrangement done impeccably.

OWN-WORLD: white/near-white ground, one blue accent doing all interactive work, gray-600 secondary text, 8px-radius panels on `#f9fafb`, system-ui type with tight-tracked 800-weight display, form-first hero. Recognizable with content removed by its proportions: split 1.1fr/.9fr hero with the working form right, quiet footer facts.

STORY: visitor sees headline + working export form in one viewport, understands "no password, nothing stored" without hunting, exports unaided, optionally signs in for sync.

FIRST VIEWPORT: the chosen sketch `.impeccable/mocks/decision/canon.html` — top bar (brand left, nav center: Xuất nhanh / Dashboard / Giới thiệu, Đăng nhập CTA right), split hero: h1 52px "Lịch học Phenikaa, trong mọi ứng dụng lịch" with blue second line, 18px muted lede, primary "Xuất nhanh" + ghost "Xem cách dùng" buttons left; right panel `#f9fafb` 16px-radius with the quick-export fields (dates, file/token) and full-width submit. Primary action sits in the working form.

FORM: canon (category standard), position 1 of the safer lineup. seed:da6adf2e1a11bb56

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.
