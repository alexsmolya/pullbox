# Pullbox Accessibility Standards

**Author:** Adam Hernandez
**Version:** 1.0
**Last Modified:** 2026-05-15

## Purpose

This document is the working accessibility reference for Pullbox contributors.
It explains the accessibility target, the checks that protect it, and the
product rules that keep the app usable for keyboard, zoom, reduced-motion, and
assistive-technology users.

Accessibility is not a final polish pass. It is part of the product contract.
Pullbox should stay usable when someone cannot use a mouse, has motion reduced,
zooms the interface heavily, or relies on clear semantic structure.

## Current Baseline Notes

- Pullbox targets WCAG 2.2 AA for the authenticated app, login flow, and setup
  flow.
- Token-level contrast checks run through `scripts/check_ui_contrast.py`.
- Browser accessibility checks run through `make test-a11y`.
- Functional E2E coverage still runs separately in Chromium and Firefox.
- The app has a global live-updates control in the header.
- Theme handling, shell reveal, and page transitions are expected to respect
  reduced-motion preferences.
- The design system owns color, focus, typography, spacing, and component
  contracts. This document owns how those decisions are verified for
  accessibility.

## Table of Contents

1. [Target Standard](#1-target-standard)
2. [Defensible Compliance](#2-defensible-compliance)
3. [Automated Checks](#3-automated-checks)
4. [Product Rules](#4-product-rules)
5. [Manual Verification](#5-manual-verification)
6. [CI Policy](#6-ci-policy)
7. [Contributor Audit Checklist](#7-contributor-audit-checklist)

## 1. Target Standard

### 1.1 Current Pullbox implementation

- Pullbox targets WCAG 2.2 AA for supported app flows.
- The target applies to:
  - authenticated app shell
  - login flow
  - setup flow
  - common modal, dropdown, table, form, and navigation patterns
- Pullbox does not claim third-party accessibility certification unless an
  external audit has happened.

### 1.2 Required standard

- Normal text and actionable controls meet AA contrast.
- Keyboard access works in supported flows.
- Dialogs, dropdowns, and forms expose correct semantics.
- Reduced-motion preferences are respected.
- Live-updating regions can be paused.
- Public wording should be accurate and modest.

Approved wording:

- `Pullbox targets WCAG 2.2 AA`
- `Pullbox is tested against WCAG 2.2 AA in supported flows and browsers`

Avoid:

- `certified accessible`
- `fully certified WCAG compliant`

### 1.3 Current repo nuances

- Automated checks are strong guardrails, but they do not replace manual
  keyboard, zoom, and screen reader spot checks.
- Dense self-hosted admin screens are allowed. Density still has to be usable.

### 1.4 Audit checks

- [ ] Accessibility claims say "targets" or "tested against," not "certified."
- [ ] New UI surfaces keep WCAG 2.2 AA as the target.
- [ ] Dense UI remains keyboard-usable and readable.

## 2. Defensible Compliance

### 2.1 Current Pullbox implementation

- Contrast, accessibility browser scans, and functional browser tests are
  separate validation lanes.
- Manual checks are still expected for UI-affecting release work.

### 2.2 Required standard

Accessibility work is release-ready only when all of these are true:

1. Semantic token contrast checks pass.
2. The dedicated browser accessibility suite passes.
3. Normal functional E2E still passes in Chromium and Firefox.
4. Reduced-motion behavior is verified for affected flows.
5. Manual keyboard and zoom checks are completed for affected flows.

### 2.3 Current repo nuances

- A passing axe scan does not prove the UI is good. It proves a useful set of
  known issues was not detected.
- Manual checks should focus on flows touched by the change plus one or two
  representative shared components when those components are involved.

### 2.4 Audit checks

- [ ] Automated contrast checks pass.
- [ ] Browser accessibility checks pass.
- [ ] Functional E2E remains green.
- [ ] Manual checks cover the changed flow.

## 3. Automated Checks

### 3.1 Contrast Gate

**Current Pullbox implementation**

The repo includes a token-level contrast audit:

```bash
python scripts/check_ui_contrast.py
```

The script checks:

- semantic text tones on app, shell, card, and input surfaces
- inverse text on interactive and status controls
- focus-outline contrast on core surfaces
- light-theme fallback parity for the prepaint system-theme path

**Required standard**

- Semantic tokens must preserve AA contrast in both themes.
- Token changes should run the contrast gate before browser review.
- Do not lower important metadata into unreadable helper-tone styling.

**Current repo nuances**

- This check catches palette regressions before browser tests run.
- It does not catch every rendered composition issue, especially when layout,
  opacity, or layering changes.

**Audit checks**

- [ ] `python scripts/check_ui_contrast.py` passes after token changes.
- [ ] Focus outline contrast remains visible in both themes.
- [ ] Important data stays readable, not merely decorative.

### 3.2 Browser Accessibility Suite

**Current Pullbox implementation**

The browser accessibility lane runs in Chromium:

```bash
make test-a11y
```

Representative coverage includes:

- `/login`
- dashboard
- settings
- security
- system
- health
- downloads
- post-processing
- import
- library
- series detail
- issue detail
- confirm modal
- shared dropdown panel

**Required standard**

- Accessibility scans should cover representative app states, not only static
  happy paths.
- New shared components should get accessibility coverage when they introduce
  meaningful semantics or interaction.
- Reports or screenshots should be uploaded when violations are found in CI.

**Current repo nuances**

- Accessibility scans run separately from functional browser tests so failures
  stay easier to reason about.

**Audit checks**

- [ ] `make test-a11y` passes.
- [ ] New shared interactive components have representative coverage.
- [ ] Failures include enough artifacts to fix the issue without guessing.

### 3.3 Functional Browser Matrix

**Current Pullbox implementation**

- Chromium E2E covers primary functional behavior.
- Firefox E2E covers cross-browser functional behavior.
- Accessibility scans do not replace either lane.

**Required standard**

- Accessibility validation must not remove functional browser coverage.
- Browser-specific focus, dialog, and form behavior should be watched when UI
  interaction patterns change.

**Current repo nuances**

- Some accessibility regressions show up as functional failures first,
  especially around focus traps, modals, and keyboard navigation.

**Audit checks**

- [ ] Chromium E2E remains green after UI changes.
- [ ] Firefox E2E remains green after UI changes.
- [ ] Keyboard/focus behavior is checked when interaction code changes.

## 4. Product Rules

### 4.1 Live Updates

**Current Pullbox implementation**

- The app header provides a global live-updates control.
- Polling triggers respect the paused state.
- Manual refresh actions can still run when live updates are paused.
- The paused state persists on the device.

**Required standard**

- Any auto-refreshing page or panel must respect the live-updates pause state.
- Live updates should not steal focus.
- Live updates should not make keyboard operation unpredictable.
- Manual refresh remains available where it helps.

**Current repo nuances**

- The issue is not just motion. Constant DOM changes can make keyboard and
  assistive-technology use miserable.

**Audit checks**

- [ ] Auto-refreshing regions respect the global pause control.
- [ ] Live updates do not steal focus.
- [ ] Manual refresh remains available where useful.

### 4.2 Reduced Motion

**Current Pullbox implementation**

- Pullbox respects `prefers-reduced-motion` in app-level transition behavior.
- Theme and shell behavior are expected to stay flicker-free without relying on
  motion.

**Required standard**

- Non-essential animation is suppressed or shortened when reduced motion is
  enabled.
- Motion is never required to understand state.
- Theme changes stay instant and do not reintroduce flash.
- Loading indicators remain understandable without motion.

**Current repo nuances**

- The no-flash rule and reduced-motion behavior overlap, but they are not the
  same thing. Both need to stay true.

**Audit checks**

- [ ] Reduced motion suppresses non-essential animation.
- [ ] State remains understandable without animation.
- [ ] Theme and shell transitions do not flash or jump.

### 4.3 Focus Visibility

**Current Pullbox implementation**

- Focus token contrast is checked at the token layer.
- Shared controls are expected to show visible focus in both themes.

**Required standard**

- Keyboard focus must remain easy to see in both themes.
- No control may remove visible focus without a replacement.
- Focus styles must remain distinct from hover styles.
- Dialogs must move focus somewhere safe when they open.
- Closing a dialog should return focus to a sensible trigger or fallback target.

**Current repo nuances**

- Icon-only table actions and compact toolbar controls are high-risk. They need
  visible focus and accessible labels.

**Audit checks**

- [ ] Focus is visible on every interactive control.
- [ ] Focus order is logical.
- [ ] Dialog open and close behavior manages focus safely.
- [ ] Icon-only controls have accessible names.

## 5. Manual Verification

### 5.1 Keyboard

**Current Pullbox implementation**

- Keyboard verification is expected for release candidates and meaningful UI
  changes.

**Required standard**

Verify affected flows with keyboard only. For broad release checks, include:

- login
- setup
- dashboard
- settings
- security
- system
- downloads
- import
- at least one confirm modal
- at least one shared dropdown

Check:

- focus order is logical
- focus is always visible
- dropdowns and dialogs open and close without a mouse
- no keyboard trap prevents escape

**Current repo nuances**

- Table row actions, modals, dropdowns, and select-mode toolbars are the common
  places to look closely.

**Audit checks**

- [ ] Affected flows work with keyboard only.
- [ ] Focus order is logical.
- [ ] Dropdowns and dialogs are keyboard-operable.
- [ ] No keyboard trap blocks escape.

### 5.2 Zoom And Reflow

**Required standard**

Verify affected UI at:

- 200% browser zoom
- 400% browser zoom or equivalent narrow viewport

Check:

- critical actions stay reachable
- text does not overlap or clip
- dialogs remain usable
- tables and dense panels remain navigable

**Current repo nuances**

- Dense tables do not have to become beautiful at extreme zoom. They do have to
  remain usable and not hide critical actions.

**Audit checks**

- [ ] 200% zoom remains usable.
- [ ] 400% zoom or equivalent narrow viewport remains usable.
- [ ] Dialogs remain reachable and operable.
- [ ] Critical actions do not disappear.

### 5.3 Screen Reader Spot Check

**Required standard**

For broad release checks, run at least one spot check on a supported combo and
cover:

- login
- dashboard
- settings
- one modal flow

Check:

- page title and landmarks make sense
- form fields announce labels and errors
- status or toast messages are announced appropriately

**Current repo nuances**

- A spot check is not a full audit, but it catches issues automated checks often
  miss.

**Audit checks**

- [ ] Landmarks and headings make sense.
- [ ] Forms announce labels and errors.
- [ ] Modal flows announce useful context.
- [ ] Toasts or status messages are announced appropriately when relevant.

## 6. CI Policy

### 6.1 Current Pullbox implementation

- UI quality checks are split into separate lanes:
  - token/contrast gate
  - accessibility browser scans in Chromium
  - functional E2E in Chromium
  - functional E2E in Firefox

### 6.2 Required standard

- CI keeps accessibility checks separate from functional browser checks.
- Accessibility failures should produce enough artifacts to make fixes
  straightforward.
- UI-affecting changes should not skip accessibility checks unless the reason is
  explicit and low-risk.

### 6.3 Current repo nuances

- Keeping lanes separate makes failures easier to triage. A contrast failure,
  an axe failure, and a Firefox behavior failure should not look like the same
  problem.

### 6.4 Audit checks

- [ ] Contrast checks are part of validation.
- [ ] Browser accessibility scans are part of validation.
- [ ] Chromium and Firefox functional E2E remain separate.
- [ ] Accessibility failure artifacts are available in CI.

## 7. Contributor Audit Checklist

Use this checklist when touching UI:

- [ ] Semantic tokens are used for color.
- [ ] Contrast remains safe in both themes.
- [ ] Focus styles remain visible.
- [ ] Icon-only controls have accessible names.
- [ ] Forms have labels and useful validation messages.
- [ ] Dialogs manage focus when opening and closing.
- [ ] Dropdowns are keyboard-operable.
- [ ] Live-updating regions respect pause behavior.
- [ ] New animation respects reduced motion.
- [ ] Manual keyboard verification was done for affected flows.
- [ ] Zoom/reflow was checked when layout changed.
- [ ] Accessibility coverage was added or updated when behavior changed
  materially.

Accessibility bugs are product bugs, not polish work.
