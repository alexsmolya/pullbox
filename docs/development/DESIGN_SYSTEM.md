# Pullbox Design System

**Author:** Adam Hernandez
**Version:** 1.0
**Last Modified:** 2026-05-15

## Purpose

This document is the working UI reference for Pullbox contributors. It captures
the visual language already used across the authenticated app, the standards new
UI code should follow, and the checks that keep the interface feeling like one
product instead of a pile of one-off screens.

The design system is meant to be practical. It covers color, typography, layout,
component contracts, accessibility expectations, and review habits. The details
are tactical, but the larger goal is simple: Pullbox should feel calm,
consistent, fast, and trustworthy for a self-hosted operator doing real work.

## Current Baseline Notes

- The authenticated app uses a fixed shell with a left sidebar, top utility
  header, and one primary content scroll region.
- Theme handling applies before first paint and must stay flicker-free.
- Pullbox uses a light-first design model, with dark mode treated as a full
  counterpart.
- Semantic `pb-*` tokens are the UI contract. Raw palette utilities should not
  be added to templates.
- The current font system is `Syne`, `DM Sans`, and `JetBrains Mono`.
- Settings, security, system, downloads, post-processing, interventions,
  library, series, and issue surfaces already share several standard page and
  component contracts.
- Tables, empty states, modals, action bars, footer docks, and settings rows
  should keep converging on shared macros and classes.
- UI copy should follow `docs/development/UI_COPY_STYLE_STANDARDS.md`.
- Accessibility expectations live in `docs/development/ACCESSIBILITY_STANDARDS.md` and
  apply to all UI work.

## Table of Contents

1. [Scope & Authority](#1-scope--authority)
2. [Design Principles](#2-design-principles)
3. [Immutable Platform Constraints](#3-immutable-platform-constraints)
4. [Theme Model & Token Taxonomy](#4-theme-model--token-taxonomy)
5. [Typography & Iconography](#5-typography--iconography)
6. [Visual Primitives](#6-visual-primitives)
7. [Standard Page Blueprints](#7-standard-page-blueprints)
8. [Standard Component Catalog](#8-standard-component-catalog)
9. [UX Contracts](#9-ux-contracts)
10. [Anti-Patterns & Banned Patterns](#10-anti-patterns--banned-patterns)
11. [Adoption Rules](#11-adoption-rules)
12. [Contributor Review Checklist](#12-contributor-review-checklist)

---

## 1. Scope & Authority

### 1.1 Current Pullbox implementation

- The authenticated app uses this document as its UI source of truth.
- The approved palette direction is **Palette A**.
- The strongest reference surfaces are the settings, security, system, queue,
  library, series, and issue pages.
- The visual priorities are simplicity, consistency, readability, and calm
  density.
- The theme strategy is light-first, with dark mode treated as a first-class
  counterpart.

### 1.2 Required standard

- New UI work should follow this document.
- Existing divergence should be cleaned up when the surrounding code is touched.
- Do not invent a third pattern when a shared shell, component, or token already
  exists.
- If implementation and design guidance disagree, either update the code toward
  the standard or update this document deliberately when the implementation is
  the better pattern.

### 1.3 Scope

This specification applies to:

- authenticated app shell
- page layouts
- templates
- component macros
- CSS tokens and utility aliases
- empty, loading, success, warning, and error states
- modal workflows

Marketing and landing-page work can borrow from this system, but the authenticated app is the priority.

### 1.4 Current repo nuances

- Some older templates still contain raw Tailwind palette utilities or bespoke
  markup.
- Some settings and admin rows still have repeated structure that should move
  toward shared macros when touched.
- Some status-heavy pages may still use one-off color treatments.
- These are cleanup targets, not permission to add more drift.

### 1.5 Audit checks

- [ ] New UI work follows an existing page blueprint or documents the exception.
- [ ] New UI work uses semantic tokens instead of raw palette utilities.
- [ ] Repeated structures use shared components or macros where practical.
- [ ] Touched areas move closer to the design system instead of further away.

---

## 2. Design Principles

### 2.1 Simplicity

Use fewer visual decisions per page.

- fewer shell variants
- fewer special-case layouts
- fewer custom state treatments
- fewer one-off color decisions

### 2.2 Consistency

Shared problems must share shared solutions.

- one semantic token model
- one type scale
- one settings row anatomy
- one alert banner contract
- one modal shell contract
- one action hierarchy model

### 2.3 Readability

Readable UI beats decorative UI.

- light mode must be comfortable and high-contrast
- metadata must remain readable
- helper text must stay supportive, not dominant
- layout hierarchy should do more work than color

### 2.4 Calm Density

Pullbox is a dense product UI, not a sparse marketing site.

- keep information density where it helps
- reduce noise, not content
- rely on spacing, border rhythm, and typography before adding more color

### 2.5 Durable Theming

The token is the API. The palette is not.

- templates use semantic tokens, not raw palette names
- component markup should remain stable when the palette changes
- a future palette update should mostly be a token change, not a template rewrite

### 2.6 Copy Voice

User-facing copy should follow `docs/development/UI_COPY_STYLE_STANDARDS.md`.

- write for self-hosters in clean casual language
- focus on outcomes and next steps
- avoid UI, rendering, or design-meta language in visible copy
- avoid corporate and overly formal product wording

---

## 3. Immutable Platform Constraints

### 3.1 No-Flash Rule

The no-flash rule is non-negotiable.

The app must continue to:

- apply theme before first paint
- suppress boot transitions during initial hydration
- reveal the shell only after Alpine is initialized and fonts are ready
- preload collapsed sidebar width before hydration
- avoid instant theme-switch regressions and layout jump
- preserve existing content during boosted shell navigation instead of fading it out

The behavior currently implemented in `src/pullbox/ui/templates/base.html` is correct and must be preserved through redesign work.

### 3.2 Shell Architecture

The authenticated app remains a fixed-shell application.

Required shell behavior:

- fixed left sidebar
- fixed top header
- one primary vertical scroll region
- stable main-area layout
- persistent shell chrome

Shell chrome rules:

- the header is a slim utility bar, not the owner of visible page titles
- visible page titles belong inside page content, not in the shell header
- the header keeps global utility controls only
- the left navigation rail uses a 240px expanded width and a 72px collapsed width on desktop
- the expanded rail shows the Pullbox mark, uppercase wordmark, and compact mono version label
- the collapsed rail keeps only the mark, icon links, collapsed badges, and footer LED
- navigation groups use compact Syne uppercase section labels with extending divider lines
- active navigation uses a tinted background plus a 3px left accent bar; do not replace it with large icon pills or heavy card chrome
- sidebar badges use compact mono counters and reposition into the top-right corner of icon buttons when collapsed
- the sidebar footer owns shell-level status text only; when collapsed it reduces to the LED only
- the footer dock is opt-in by page; if a page does not provide dock content, no dock should appear
- when present, header and footer dock use the same shell-toned background for visual bookending
- content should never visually collide with the footer dock; every scrollable
  page needs a small, consistent end-of-content buffer before the dock

Do not redesign Pullbox into a body-scrolling marketing-style app.

### 3.3 Scroll Rules

These are hard rules:

- `html` and `body` do not become the primary app scroll containers
- `#content` remains the main scroll region
- dropdowns, tooltips, and overlays should assume stable shell boundaries
- workspace tabs and filters should swap content regions, not the whole shell
- the bottom buffer belongs to the shared content/page contract, not one-off
  margins on individual tables

### 3.4 Theme Behavior

Theme switching must be:

- instant
- flicker-free
- layout-stable
- consistent in both directions

Design changes are not allowed to reintroduce:

- theme flash
- shell flash
- sidebar jump
- transition burst on first paint

---

## 4. Theme Model & Token Taxonomy

### 4.1 Approved Theme Strategy

Pullbox is authored light-first.

That means:

- light mode is the primary review and design surface
- dark mode is required and equal in quality
- contrast must pass in both themes
- a component is not complete until it works in both themes

### 4.2 Token Families

The `pb-*` namespace is retained, but token names are semantic only.

Canonical token families:

- `pb-surface-*`
- `pb-text-*`
- `pb-border-*`
- `pb-interactive-*`
- `pb-brand-*`
- `pb-status-*`
- `pb-shadow-*`
- `pb-focus-*`

Required semantic roles:

| Family | Required roles |
|---|---|
| Surface | `app`, `shell`, `card`, `raised`, `input`, `overlay`, `selected` |
| Text | `primary`, `secondary`, `tertiary`, `inverse` |
| Border | `subtle`, `default`, `strong`, `focus` |
| Interactive | `default`, `hover`, `active`, `selected`, `disabled` |
| Brand | `default`, `muted` |
| Status | `success`, `warning`, `danger`, `info` plus muted/background companions |
| Shadow | `0`, `1`, `2`, `overlay` |
| Focus | `ring`, `outline`, `selection` |

### 4.3 Approved Palette: Palette A

Palette A is the canonical color direction.

#### Light theme

```css
--pb-surface-app:        #F6F1E8;
--pb-surface-shell:      #FBF6EE;
--pb-surface-card:       #FFFCF7;
--pb-surface-raised:     #FFFFFF;
--pb-surface-input:      #FFFDFA;
--pb-surface-overlay:    rgba(26, 22, 19, 0.42);
--pb-surface-selected:   rgba(47, 94, 140, 0.12);

--pb-text-primary:       #1E1A17;
--pb-text-secondary:     #51473D;
--pb-text-tertiary:      #7B6F63;
--pb-text-inverse:       #F7F1E8;

--pb-border-subtle:      rgba(81, 71, 61, 0.14);
--pb-border-default:     rgba(81, 71, 61, 0.20);
--pb-border-strong:      rgba(81, 71, 61, 0.34);

--pb-interactive:        #2F5E8C;
--pb-interactive-hover:  #274F76;
--pb-interactive-active: #21435F;
--pb-interactive-selected: rgba(47, 94, 140, 0.14);

--pb-brand:              #8C6847;
--pb-brand-muted:        rgba(140, 104, 71, 0.12);

--pb-status-success:     #2E6A4F;
--pb-status-warning:     #8A5A1F;
--pb-status-danger:      #B24432;
--pb-status-info:        #2F5E8C;

--pb-focus-ring:         rgba(47, 94, 140, 0.26);
--pb-focus-outline:      rgba(47, 94, 140, 0.50);
--pb-selection:          rgba(47, 94, 140, 0.20);
```

#### Dark theme

```css
--pb-surface-app:        #171311;
--pb-surface-shell:      #1D1815;
--pb-surface-card:       #26201B;
--pb-surface-raised:     #2D2620;
--pb-surface-input:      #201A16;
--pb-surface-overlay:    rgba(10, 8, 7, 0.68);
--pb-surface-selected:   rgba(140, 180, 224, 0.16);

--pb-text-primary:       #F7F1E8;
--pb-text-secondary:     #D0C2B2;
--pb-text-tertiary:      #A99886;
--pb-text-inverse:       #171311;

--pb-border-subtle:      rgba(208, 194, 178, 0.12);
--pb-border-default:     rgba(208, 194, 178, 0.20);
--pb-border-strong:      rgba(208, 194, 178, 0.32);

--pb-interactive:        #8CB4E0;
--pb-interactive-hover:  #79A4D3;
--pb-interactive-active: #648AB4;
--pb-interactive-selected: rgba(140, 180, 224, 0.18);

--pb-brand:              #C6A17B;
--pb-brand-muted:        rgba(198, 161, 123, 0.16);

--pb-status-success:     #63B089;
--pb-status-warning:     #D49B57;
--pb-status-danger:      #E37A69;
--pb-status-info:        #8CB4E0;

--pb-focus-ring:         rgba(140, 180, 224, 0.28);
--pb-focus-outline:      rgba(140, 180, 224, 0.52);
--pb-selection:          rgba(140, 180, 224, 0.22);
```

### 4.4 Approved Template Utility Aliases

Templates may continue to use short `pb-*` utility aliases, but those aliases must map one-to-one to semantic roles.

Approved alias examples:

| Template utility | Semantic role |
|---|---|
| `bg-pb-base` | `pb-surface-app` |
| `bg-pb-surface` | `pb-surface-shell` |
| `bg-pb-card` | `pb-surface-card` |
| `bg-pb-input` | `pb-surface-input` |
| `bg-pb-overlay` | `pb-surface-overlay` |
| `bg-pb-card-hover` | surface selected/hover tone |
| `text-pb-text` | `pb-text-primary` |
| `text-pb-text-sec` | `pb-text-secondary` |
| `text-pb-text-dim` | `pb-text-tertiary` |
| `border-pb-border` | `pb-border-default` |
| `border-pb-border-hover` | `pb-border-strong` |
| `text-pb-interactive` | `pb-interactive` |

The utility name may be short. The meaning may not be vague.

### 4.5 Contrast Rules

All normal text and actionable controls must meet WCAG AA contrast in both themes.

Approved contrast intent:

- primary text: comfortably above AA
- secondary text: data-safe, not decorative
- tertiary text: helper-only unless contrast remains safe
- metadata, values, dates, file sizes, table headers, and status labels must not drop into unreadable tertiary styling

### 4.6 Hard Color Rules

The following are banned in app templates:

- raw Tailwind palette utilities such as `text-red-300`, `bg-green-500`, `divide-slate-700/60`
- arbitrary hex utilities such as `bg-[#0D0F16]`
- inline color styles
- direct `rgba(...)` styling in templates

Exceptions are limited to documented logo or illustration cases.

---

## 5. Typography & Iconography

### 5.1 Approved Fonts

Pullbox now uses a restrained three-font system:

- **Display:** `Syne`
- **UI / Body:** `DM Sans`
- **Monospace:** `JetBrains Mono`

Legacy note:

- `Bricolage Grotesque` is legacy display typography and should not be used for new work.
- New series-domain work uses `Syne` for its hero, section, and telemetry language.

### 5.2 Usage Rules

- Display font is reserved for page H1, app-level branded headings, and high-signal library/detail headings.
- UI/body font is used for section titles, card titles, tabs, tables, forms, settings rows, and body text.
- Monospace is used only for paths, technical values, tokens, IDs, and machine-oriented metadata.

### 5.3 Type Scale

| Role | Font | Weight | Typical size | Usage |
|---|---|---|---|---|
| Page title | Display | 800 | 1.6rem to 2.5rem | Page-level H1 and series-domain hero titles |
| Section title | UI | 700 | 1.25rem to 1.5rem | Section heads, workspace subheads |
| Card title | UI | 700 | 1rem to 1.125rem | Card, panel, modal titles |
| Eyebrow / label | UI | 700 | 0.72rem to 0.78rem | Sparse, uppercase, high-signal labels |
| Body | UI | 400-500 | 0.95rem to 1rem | Primary reading text |
| Metadata | UI | 400-500 | 0.875rem to 0.94rem | Secondary but readable data |
| Helper | UI | 400 | 0.82rem to 0.88rem | Instructional copy only |
| Table header | UI | 600-700 | 0.75rem to 0.82rem | Dense tables only |
| Mono meta | Mono | 400-500 | 0.82rem to 0.88rem | Paths, timestamps, technical values |

### 5.4 Typography Rules

- Do not build new pages out of ad hoc `text-[10px]` and `text-[11px]` utilities.
- Uppercase eyebrow text should be rare and structural, not the default label treatment.
- Use secondary tone for real metadata.
- Use tertiary tone for helper/instructional copy only.
- `Syne` is the approved structural accent for series list, series detail, and issue detail surfaces.
- `JetBrains Mono` is the default mono face for telemetry strips, gauges, file paths, IDs, and dense technical values.

### 5.5 Iconography Rules

- Use line icons with consistent stroke weight.
- Icons support labels; they do not replace labels by default.
- Icon-only buttons must have accessible labels.
- Destructive icon actions should not be the visually strongest action in a zone.

---

## 6. Visual Primitives

### 6.1 Spacing

Approved spacing scale:

- `4px`
- `8px`
- `12px`
- `16px`
- `20px`
- `24px`
- `32px`
- `40px`
- `48px`

Use repeated spacing steps consistently across cards, toolbars, rows, and modals.

### 6.2 Radius

Approved radius tokens:

- small: `8px`
- medium: `12px`
- large: `16px`
- extra large: `20px`
- pill: `999px`

### 6.3 Borders

Border hierarchy:

- `subtle` for internal row separators
- `default` for component shells
- `strong` for hovered or more emphasized boundaries
- `focus` only for active keyboard focus

Do not substitute saturated color for border hierarchy when a border token is sufficient.

### 6.4 Elevation

Approved elevation levels:

- `shadow-0` for flat surfaces
- `shadow-1` for cards and grouped controls
- `shadow-2` for sticky footers and emphasized grouped regions
- `shadow-overlay` for modal shells only

Shadows should remain soft and structural. Pullbox is not a glossy card UI.

### 6.5 Hover, Active, Selected, Disabled

- Hover should tighten hierarchy, not repaint the whole screen
- Selected states should be visible but calm
- Disabled controls should look unavailable without disappearing
- Destructive states should remain semantic, not become the default emphasis color

### 6.6 Motion

Approved motion timings:

- fast: `140ms`
- base: `180ms`
- shell/layout: `200ms`

Rules:

- no entrance animation on first paint
- no theme-switch flash
- respect reduced motion
- use motion for clarity, not decoration

---

## 7. Standard Page Blueprints

### 7.1 Workspace Page

Required anatomy:

1. page header
2. workspace tabs
3. toolbar / action bar
4. primary content region
5. optional footer dock

Rules:

- filters belong in the toolbar region
- the toolbar owns search, filter chips, summary chips, and the zone primary action
- one primary action per workspace zone
- empty and loading states use shared shells
- the page title lives in the content header, not the shell header
- use the series page header as the default page-header contract: same title rail, subtitle rhythm, gauge sizing, and right-side action alignment unless a page has a documented exception
- top-level workspace tabs belong on the page-header action rail, aligned with the same right-side action slot used by the series header
- the optional footer dock is reserved for pagination, status strips, or page-level save state
- pages with a footer dock keep a consistent visual buffer between the final
  table/card row and the dock
- shared pagination uses a five-token rail: either all pages when `<= 5`, or two visible page numbers, one ellipsis, and two more visible page numbers; the visible two-page cluster may shift so the current page remains visible without growing the rail
- shared pagination controls are button-driven HTMX actions, not native links, so they do not trigger browser hover URL chrome and should always expose `data-page-url` for contract tests
- series list and intervention queue share the same mission-control workspace shell: the same header/tool/results structure, sticky toolbar boundary, and mission-control table wrapper
- downloads uses a queue-first workspace variant: plain page header, compact queue gauges, small tab rail, table-first content, footer summary strip
- post-processing uses the same queue-first workspace variant as downloads: same header rail, same tabs placement, same static-toolbar/dynamic-results split for history, and the same footer-dock responsibility
- intervention is split by tab: queue uses the same series-shell contract as the series list page (same header spacing, sticky toolbar boundary, select-mode toolbar, and results shell), while history uses the same downloads-history contract as downloads
- queue and history workspace tabs should swap only the content region, not the full shell

### 7.2 Dashboard / Mission Control Page

Required anatomy:

1. in-content dashboard title block
2. compact gauge cluster
3. horizontal scoreboard strip
4. alerts / exceptions table
5. active-downloads table when work is in flight
6. recent activity feed
7. shell footer dock with status values

Rules:

- the dashboard exists to surface actionable intelligence, not generic status copy
- use one compact plain page header with freshness, not a card-wrapped hero
- alerts and active work render as tables, not marketing-style cards
- recent activity stays short and factual
- summary values live in the shell footer dock, not in a duplicated card inside the page body
- when the system is quiet, show a single quiet-note state instead of filler sections

### 7.3 Health Monitoring Page

Required anatomy:

1. in-content page header
2. compact health gauge cluster
3. search-telemetry scoreboard strip
4. component registry card grid
5. inline drill-in detail state for the selected component
6. shell footer dock with monitor summary values

Rules:

- the health page surfaces monitored dependencies, not general product analytics
- use the same plain page-header rail as the series and dashboard pages
- component cards must stay scannable first and detailed second
- multi-endpoint monitors may switch to a table in the drill-in state; single monitors use check rows
- monitor summary values live in the shell footer dock, not in a bottom card
- when no recent results exist, render known monitors in an honest waiting state instead of hiding them

### 7.4 Settings / Admin Page

This is the primary reference blueprint for the system.

Required anatomy:

1. page header
2. left-rail `admin_workspace` navigation shell
3. constrained main content column
4. stacked `settings_section` cards
5. repeated `settings_row` anatomy
6. optional alert banners above or inside sections
7. sticky footer dock when the page is dirty

Rules:

- the outer workspace shell is shared by security, settings, system, and future admin pages
- the workspace header stays lighter than the inner cards; it sets context but does not become a second hero
- the left rail owns section switching and remains sticky on desktop
- main content width stays constrained so row-based admin forms remain readable
- settings rows share one label/help/control/action order
- row actions stay secondary
- page save behavior is handled at page level, not repeated per row
- security, settings, and system now consume this shell directly

### 7.5 Utilities Launcher / Queue / History Page

Required anatomy:

1. plain in-content page header
2. compact running / queued gauge cluster
3. segmented `Tools / Queue / History` tab rail
4. launcher grid, queue work region, or job-history table
5. shell footer dock with queue or history summary values

Rules:

- the utilities page uses the same plain page-header rail as series, dashboard, and health
- gauges stay compact and factual; they are quick state counters, not decorative charts
- the overview tab groups tools by purpose and uses launch cards only
- the queue tab keeps live work, controls, and logs in the content region; summary values belong in the shell footer dock
- the history tab is a first-class paginated history table, not a secondary
  panel inside the queue tab
- tool launch cards use the utilities launcher contract: icon, uppercase title, short outcome-first copy, mono tag

### 7.6 Utilities Tool Page

Required anatomy:

1. back link to Utilities
2. compact tool header with icon, title, subtitle, and mono tag
3. tool-specific work cards
4. shell footer dock with compact tool context

Rules:

- utility subpages do not use oversized hero cards
- the header stays compact and operational
- header icon tones must stay aligned with the launcher card for the same tool
- launcher cards and tool-page outer cards share the same utilities card contract: `surface-card`, `border-subtle`, `shadow-1`
- nested option panels inside utility workflows step down to the quieter inset contract: `surface-app`, `border-subtle`, no elevated shadow
- preview-first tools such as mass rename split setup into distinct target, scope, and preview cards instead of collapsing everything into one admin form stack
- tool work remains server-rendered and queue-backed
- footer dock values summarize the current tool context instead of duplicating a bottom card
- scope-driven tools such as mass convert keep the preview, trash path, and action footer inside the same working card; the footer dock only carries compact context values such as tool, scope, files, and enabled steps
- scan-driven tools such as integrity keep mode, scope, browse, and actions inside one compact working card; the footer dock only carries tool, mode, and scope

### 7.7 Detail Page

Required anatomy:

1. summary hero
2. primary action cluster
3. supporting fact panels
4. recent activity / audit / detail sections
5. optional side rail

Rules:

- the summary hero tells the story first
- status color supports meaning, not layout
- supporting panels should not compete with the hero

### 7.8 Series-Domain Detail Page

The series and issue domain is allowed a more editorial, collector-focused detail language.

Required anatomy:

1. breadcrumb row
2. hero card with cover, linked title, status row, key stats, and a compact
   manage-action stack
3. compact supporting sections
4. recent activity, files, audit, or detail sections when useful
5. telemetry strip footer

Rules:

- use `Syne` for hero and section titling
- use `JetBrains Mono` for gauges, telemetry, identifiers, and file paths
- keep manage actions route-first and integrated into the hero card so series
  and issue controls feel owned by the entity
- link series and issue hero titles to their ComicVine pages when a ComicVine
  URL is available
- do not reintroduce generic admin-card copy into these pages

### 7.9 Setup / Auth Page

Required anatomy:

1. centered flow
2. clear title and short supporting copy
3. one primary action
4. minimal secondary actions
5. progressive disclosure only when necessary

Rules:

- lower density than authenticated admin pages
- no noisy dashboard chrome
- same token and type system as the main app

### 7.10 Modal Workflow

Required anatomy:

1. modal header
2. modal body
3. modal footer

Rules:

- one standard modal shell
- use small, medium, and large width tiers only
- critical consequences belong in a standard alert/banner treatment
- footer keeps primary action to the right and secondary/destructive actions subordinate unless the workflow is explicitly destructive

---

## 8. Standard Component Catalog

### 8.1 Componentization Rules

- Multi-node repeated structures become reusable Jinja macros/components.
- Single-node styling primitives stay as shared classes/tokens.
- Components accept a small approved option set only.
- Do not add arbitrary per-call style overrides.

Shared option vocabulary:

- `variant`
- `tone`
- `size`
- `density`
- `state`
- `icon`
- `align`
- `actions`

### 8.2 Existing Canonical Components

| Component | Contract |
|---|---|
| Buttons | `primary`, `secondary`, `quiet`, `danger`; `sm` and default sizes |
| Pills / status badges | semantic tones: `neutral`, `info`, `success`, `warning`, `danger` |
| Toggle switch | shared binary control; off knob uses `brand`, on rail uses `interactive`, on knob uses `surface-shell` in both light and dark themes |
| Workspace tabs | peer workspace surfaces only |
| Filter chip bar | selected state visible, multi-filter safe |
| Search field | consistent input shell and clear/reset behavior |
| Dropdown select | shared field shell and option treatment |
| Confirm modal | reusable confirmation flow, not page-specific markup |
| File browser | shared picker shell with consistent toolbar and empty state |
| Table shell | shared toolbar, header, body, empty/loading shell |

### 8.3 New Required Components

| Component | Purpose | Required anatomy |
|---|---|---|
| `page_header` | Standard page intro and actions | kicker, title, subtitle, actions |
| `admin_workspace` | Shared admin/config page shell | light header, sticky left rail, constrained main column |
| `action_bar` | Shared toolbar zone | search, filters, summary chips, primary action |
| `section_card` | General content shell | shell, header, body |
| `section_header` | Shared section head | title, supporting copy, actions |
| `settings_section` | Settings/admin section shell | section header + rows |
| `settings_row` | Settings row contract | label, help, control, optional row actions |
| `alert_banner` | Shared inline status messaging | tone, icon, title, copy, optional action |
| `empty_state` | Shared no-data shell | icon, title, copy, optional actions |
| `stat_card` | Shared summary metric card | label, value, supporting copy |
| `modal_shell` | Standard modal wrapper | header, body, footer |
| `telemetry_strip` | Dense collector/ops summary line | mono values, compact labels, semantic pills |
| `gauge_cluster` | Circular summary metrics for library progress | ring, value, label |
| `acquisition_bar` | Horizontal collection completion indicator | track, fill, mono value |
| `collector_card` | Cover-first library card | cover, monitor state, progress ring, actions |
| `page_dock` | Shared footer bookend for pagination and page status | optional pagination, mono status strip |

### 8.4 Component Rules

- If a standard component exists, use it.
- If a page needs a repeated structure not covered here, add or refine a component instead of copying markup.
- Component variants must stay semantic. Do not create palette-specific component APIs.

### 8.5 Cursor Affordance Contract

Every enabled semantic interactive control must display the pointer cursor so
clickability is consistent across the application. The global contract covers
links with destinations, buttons, button-like inputs, selects, disclosure
summaries, toggle/file labels, and elements with `role="button"` or
`role="link"`.

Rules:

- disabled native controls and controls with `aria-disabled="true"` use the
  `not-allowed` cursor
- active request states may override the pointer with a wait/progress cursor
- custom clickable surfaces must use the correct semantic element whenever
  possible; otherwise they require the appropriate role, keyboard behavior,
  focus treatment, and accessible name
- background HTMX polling, Alpine outside-click listeners, and modal backdrops
  are not interactive controls and must not receive a pointer automatically
- page-specific cursor classes are allowed only for a meaningful state
  override, not to repair a missing shared affordance

---

## 9. UX Contracts

### 9.1 Forms

Required form structure:

- label
- control
- helper or validation message

Rules:

- labels are concise and specific
- helper text is tertiary and optional
- validation errors are explicit and semantic
- save actions belong in a consistent zone, not scattered through the page

### 9.2 Settings Row Contract

Required row anatomy:

1. label
2. supporting help text
3. primary control
4. optional secondary row actions

Rules:

- the label/help column is consistent
- controls align vertically and use consistent spacing
- row-level actions remain secondary to the page save action

### 9.3 Tables

Required table contract:

- toolbar above table
- secondary-tone table headers
- clear row hover behavior
- trailing row action cluster
- shared empty state
- shared loading state

Rules:

- row actions should not visually dominate the row
- status cells use semantic pills/badges, not raw colored text when a badge is clearer
- dense metadata should use secondary tone, not helper tone by default

### 9.4 Filters

- Filters live in the toolbar region.
- Active filters should be visible as chips or selected controls.
- Do not scatter filters above, below, and inside the content region at the same time.

### 9.5 Empty, Loading, Success, Warning, Error States

Each state must use a standard structure:

- short title
- supporting copy
- semantic tone
- optional action

Rules:

- state messaging should explain what happened and what the user can do next
- do not invent page-specific loading shells when the standard one fits

### 9.6 Action Hierarchy

Hard rules:

- one primary action per zone
- secondary actions grouped consistently
- destructive actions do not compete visually with the primary action
- icon-only actions are reserved for compact secondary actions

### 9.7 Status Color Usage

Status colors are semantic only:

- success for successful outcomes
- warning for caution / partial attention
- danger for destructive / failed / blocked states
- info for neutral informational emphasis

Brand color is not the default CTA color.

---

## 10. Anti-Patterns & Banned Patterns

The following are banned in new UI work:

- raw Tailwind palette utilities in templates
- arbitrary hex color utilities in templates
- inline color styles
- multiple competing primary buttons in one zone
- page-specific settings row markup when `settings_row` applies
- using tertiary/helper tone for important metadata
- modal shells built from scratch when `modal_shell` applies
- body-scrolling authenticated layouts
- theme flash, shell flash, or sidebar jump regressions

Avoid these even if the current codebase still contains them.

---

## 11. Adoption Rules

### 11.1 Current Pullbox implementation

- The UI already uses the fixed-shell app model, semantic token direction,
  shared admin workspace shell, table contracts, queue-first workspace variants,
  modal patterns, and common empty-state structure in many places.
- Some older surfaces still contain direct palette utilities, repeated shell
  markup, and bespoke component structure.
- `src/pullbox/ui/static/css/input.css` remains the main home for global token,
  utility, and component-layer CSS.

### 11.2 Required standard

- No new page or component should increase divergence from this system.
- If full cleanup is out of scope for a task, the touched area should still move
  in the right direction.
- Use the approved token model where code is touched.
- Prefer extracting a reusable shell or macro over copying markup.
- Component drift should be fixed near the source, not patched with one-off
  template styling.
- Visual verification should happen in light and dark mode for UI-affecting
  changes.

### 11.3 Current repo nuances

- Some screens may keep local layout code because the shared component does not
  exist yet. When the same pattern appears more than once, it is probably time
  to extract it.
- Design cleanup should not break the no-flash rule, shell scroll model, HTMX
  behavior, accessibility, or existing test contracts.
- The most valuable cleanup is usually boring: fewer raw colors, fewer copied
  rows, fewer custom empty states, fewer one-off action bars.

### 11.4 Audit checks

- [ ] New code uses semantic tokens where styling is added or changed.
- [ ] Repeated markup is moved toward shared components when practical.
- [ ] Existing shell, scroll, and no-flash behavior is preserved.
- [ ] Light and dark themes are both checked.
- [ ] Accessibility checks stay part of UI review.

---

## 12. Contributor Review Checklist

Use this checklist for every UI-affecting change:

- [ ] The page follows the correct blueprint for its type
- [ ] Palette A semantic tokens are used instead of raw palette utilities
- [ ] The component uses an approved shared component where one exists
- [ ] The action hierarchy has one clear primary action per zone
- [ ] Forms, tables, and state shells follow standard contracts
- [ ] Contrast passes in both light and dark themes
- [ ] Light mode was reviewed first, not treated as an afterthought
- [ ] The change does not regress the no-flash rule
- [ ] Sidebar behavior and shell reveal remain stable
- [ ] Empty, loading, and error states were verified
- [ ] Manual visual verification was completed in both themes

Visual polish is not optional garnish in Pullbox. It is part of whether the app
feels safe, understandable, and worth trusting.
