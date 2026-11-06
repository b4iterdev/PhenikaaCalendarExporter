---
name: Phenikaa Calendar Exporter
description: Category-standard academic timetable exporter executed at full craft
colors:
  primary: "#2563eb"
  primary-hover: "#1d4ed8"
  foreground: "#21262d"
  background: "#ffffff"
  card: "#ffffff"
  panel: "#f8fafc"
  muted: "#f1f5f9"
  muted-foreground: "#64748b"
  border: "#e2e8f0"
  destructive: "#dc2626"
  success: "#16a34a"
  success-bg: "#f0fdf4"
  warning: "#ca8a04"
  warning-bg: "#fefce8"
typography:
  display:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "3.75rem"
    fontWeight: 800
    lineHeight: 1.06
    letterSpacing: "-0.028em"
  headline:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.022em"
  body:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "0em"
  label:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.02em"
rounded:
  sm: "6px"
  md: "8px"
  lg: "16px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.background}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-quiet:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  card:
    backgroundColor: "{colors.card}"
    rounded: "{rounded.lg}"
    padding: "24px"
---

# Design System: Phenikaa Calendar Exporter

## Overview

**Creative North Star: "The Friendly Utility"**

A category-standard academic timetable tool executed with precision and restraint, inspired by Google Calendar and Notion Calendar. Crisp white surfaces, one committed blue accent doing all primary interactive work, and clean typographic hierarchy.

No decorative costume, no faux textures, no zero-blur offset drop shadows, and no decorative eyebrow kickers above headings. Every surface delivers the 2-minute unaided export workflow without friction.

**Key Characteristics:**
- White and slate-50 panel surfaces with subtle 1px border definition
- Single committed Royal Blue accent (`#2563eb`) driving all calls to action
- Split hero with real working inputs in the first viewport
- Clean system-ui typography with tight-tracked bold display headings

## Colors

A restrained palette where pure white and cool slate neutrals carry the structure, and single-hue Royal Blue signals all interactivity.

### Primary
- **Royal Blue** (`#2563eb`): Used exclusively for primary buttons, active state indicators, link text, and the brand mark accent.
- **Deep Royal Blue** (`#1d4ed8`): Primary button hover state.

### Neutral
- **Pure White** (`#ffffff`): Page background and card container surfaces.
- **Cool Slate Panel** (`#f8fafc`): Hero working panel and subtle callout regions.
- **Slate Ink** (`#21262d`): Primary text color for body, labels, and headlines (minimum 9:1 contrast against white).
- **Muted Slate** (`#64748b`): Secondary descriptions, helper text, and inactive navigation links (minimum 4.5:1 contrast against white).
- **Subtle Slate Border** (`#e2e8f0`): 1px structural dividing lines and input boundaries.

### Semantic
- **Emerald** (`#16a34a` / `#f0fdf4`): Connected session badges and operational server health status.
- **Amber** (`#ca8a04` / `#fefce8`): Pending login and degraded server status indicators.
- **Crimson** (`#dc2626`): Error notices, destructive actions, and disconnected status badges.

**The One Voice Rule.** The royal blue accent is used strictly for interactive affordances and active state. It never appears as a decorative background, border accent, or graphic filler.

## Typography

**Display Font:** `ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
**Body Font:** `ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
**Mono Font:** `ui-monospace, SFMono-Regular, Menlo, monospace`

A clean, legible native platform font stack that renders instantly without external network requests or font flash.

### Hierarchy
- **Display** (800 weight, clamp(2.5rem, 5vw, 3.75rem), line-height 1.06, tracking -0.028em): Primary page statement in the hero.
- **Headline** (700 weight, 1.875rem to 2.25rem, line-height 1.2, tracking -0.022em): Major section titles.
- **Title** (600 weight, 1.25rem to 1.5rem, line-height 1.3): Card headings and sub-features.
- **Body** (400 weight, 1rem, line-height 1.6, tracking normal, max-width 65ch): Reading copy, lede statements, and instructions.
- **Label** (600 weight, 0.75rem to 0.875rem, tracking 0.02em): Form field labels, button copy, and status indicators.

**The No-Eyebrow Rule.** Section headings carry their own weight. Never place an uppercase tracking-spaced kicker or eyebrow label above a heading.

## Layout

- Max container width of 72rem (1152px) centered horizontally with 1rem to 1.5rem padding.
- Split-screen hero layout on desktop: 1.1fr copy column on the left, 0.9fr working interactive panel on the right.
- Single-column linear flow on mobile viewports (<640px) with full-width interactive targets.
- 16px to 24px vertical rhythm between sibling sections.

## Elevation & Depth

Surfaces are flat by default with subtle 1px border definition (`#e2e8f0`). Elevation is reserved exclusively for interactive feedback:
- Buttons carry subtle resting shadow (`box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05)`).
- Dropdowns and modals carry diffused elevation (`box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1)`).

**The Flat Surface Rule.** Cards and panels never use wide fuzzy ambient shadows or neobrutalist block shadows at rest. Depth comes from tonal contrast between pure white (`#ffffff`) and panel tint (`#f8fafc`) over a 1px border.

## Shapes

- Small controls (buttons, text inputs, badges): 8px radius (`rounded-lg`).
- Cards and panels: 16px radius (`rounded-2xl`).
- Status pills and language toggles: fully rounded pill (`rounded-full`).
- Borders are consistently 1px solid (`#e2e8f0`), expanding to 2px dashed for upload dropzones.

## Components

### Buttons
- **Primary:** Solid royal blue (`#2563eb`) with white text, 8px radius, 10px 16px padding. Subtle hover darkening to `#1d4ed8`.
- **Quiet / Secondary:** White card background with 1px border, dark slate text, subtle background hover to `#f1f5f9`.
- **Danger:** Subtle red border and crimson text, hovering to tinted background.

### Inputs & Dropzones
- Text inputs and date pickers: 44px min-height, 1px border, 8px radius, `#21262d` text, 2px blue ring on focus.
- File dropzone: 2px dashed border, light hover tint, centered upload icon with prominent call-to-action copy.

### Navigation
- Sticky top header with subtle backdrop blur (`backdrop-blur-sm`).
- Brand mark: 32px rounded square in royal blue with bold white "P".
- Active route highlighted by subtle muted gray pill background (`#f1f5f9`).
- Compact language toggle switch (VI / EN).

## Do's and Don'ts

### Do:
- **Do** place the primary export workflow in the first viewport above the fold.
- **Do** keep button radii at 8px and panel radii at 16px.
- **Do** maintain a strict 4.5:1 minimum contrast ratio for all secondary and helper text.
- **Do** keep error states clear, prominent, and accompanied by recovery instructions.

### Don't:
- **Don't** add decorative eyebrow labels or numbers above section titles.
- **Don't** use decorative gradients, glassmorphism blur layers, or hard offset drop shadows.
- **Don't** hide or relocate the primary quick-export form behind an unnecessary sign-in wall.
- **Don't** introduce external font dependencies that cause layout shift or delay rendering.
