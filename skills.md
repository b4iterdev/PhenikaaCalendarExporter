# Frontend Design & Development Rules

## Design Constraints

- Primitives: Use exclusively `shadcn/ui` components and Tailwind CSS utility classes.
- NEVER invent arbitrary hex colors (e.g., `#1e293b`) or random inline CSS styles.
- Semantic tokens only: `bg-background`, `text-foreground`, `bg-card`, `text-muted-foreground`, `border-border`.
- Responsive layout: Mobile-first styling (`w-full`, `sm:`, `md:`, `lg:`).
- Visual polish: Always specify subtle borders (`border border-border/40`), clean radii (`rounded-xl`), and proper negative space (`p-6`, `gap-4`).

## Quality Standards

- Strict TypeScript: No `any`. Props must have explicit interface definitions.
- Handling Edge Cases: Always implement `loading`, `empty`, and `error` states for dynamic UI.
- Self-Correction: After editing any component, run `npm run typecheck` or `npm run build` using the bash tool. Fix any compiler errors before completing the turn.

## Hero Design Specification

### Platform
Phenikaa Calendar Exporter — developer observability dashboard for calendar data export and sync.

### Style Direction: Academic Navy & White
A clean, academic editorial look built on navy blue and white:
- Primary palette: navy/slate-900 backgrounds with white and slate-100 text
- Accent: blue-600 for interactive elements and highlights
- Cards and surfaces: white/bg-card with subtle borders
- Typography: Clean sans-serif hierarchy — bold headers in navy, body in light slate
- Avoid generic AI aesthetics (purple gradients, glassmorphism, abstract blobs)
- Restrained, institutional feel — not corporate-tech
- Data-as-visual-element: calendar grids, timelines, sync statuses as design content
- Monospace accents for technical details (event IDs, timestamps, format badges)

### Landing Page Hero Requirements
- Split or asymmetric layout: bold headline + technical visual (calendar grid/timeline)
- Export format badges (`.xlsx`, `.ics`, `.json`) as prominent visual anchors
- Status indicators (sync status, session count) as dashboard-style metrics
- Use `shadcn/ui` primitives: `Card`, `Badge`, `Button`, `Separator`, `Metric` patterns
- Tailwind tokens only throughout
- Mobile-first responsive with `sm:`/`md:`/`lg:` breakpoints
- Every dynamic element must have `loading`, `empty`, and `error` states
- Strict TypeScript with named interfaces, no `any`

### Self-Correction Rule
After editing any hero component, run `npm run typecheck` or `npm run build`. Fix compiler errors before considering the task complete.
