# Pullbox UI Copy Style Standards

**Author:** Adam Hernandez
**Version:** 1.0
**Last Modified:** 2026-05-15

## Purpose

This document is the working user-facing copy reference for Pullbox
contributors. It explains how Pullbox should sound in headings, helper text,
empty states, alerts, buttons, links, onboarding, sign-in, and settings flows.

If a string is shown to a user, it should sound like Pullbox: clear, calm,
technically fluent, and human without getting cute at the wrong time.

## Current Baseline Notes

- Pullbox is written for self-hosters.
- The audience is usually technical, independent, and comfortable with paths,
  logs, APIs, queues, and automation.
- Copy should be direct and useful without sounding like enterprise marketing.
- User-facing language should avoid product-design terms such as workspace,
  surface, and shell unless the user is actually debugging that behavior.
- Destructive actions, security settings, credentials, imports, and file
  operations need extra clarity.
- The design system owns visual presentation. This document owns wording and
  voice.

## Table of Contents

1. [Audience](#1-audience)
2. [Voice And Tone](#2-voice-and-tone)
3. [Core Rules](#3-core-rules)
4. [Vocabulary](#4-vocabulary)
5. [Pattern Guidance](#5-pattern-guidance)
6. [Banned Patterns](#6-banned-patterns)
7. [Examples](#7-examples)
8. [Copy Audit Checklist](#8-copy-audit-checklist)

## 1. Audience

### 1.1 Current Pullbox implementation

Pullbox copy is aimed at self-hosters who are:

- technical
- independent
- comfortable with paths, logs, APIs, and automation
- skeptical of corporate fluff
- impatient with vague or robotic copy

### 1.2 Required standard

- Do not over-explain basic technical concepts.
- Do explain consequences, defaults, and next steps.
- Keep copy helpful without sounding patronizing.
- Treat the user as capable.

### 1.3 Current repo nuances

- Some users will be comfortable with advanced settings, but still need clear
  warnings around destructive actions and security-sensitive changes.
- Dense admin pages need short, scannable copy more than personality.

### 1.4 Audit checks

- [ ] Copy assumes a capable technical reader.
- [ ] Consequences are clear where stakes are high.
- [ ] Helper text does not lecture.
- [ ] Dense pages stay scannable.

## 2. Voice And Tone

### 2.1 Current Pullbox implementation

Pullbox voice is:

- technically fluent
- calm and competent
- clean and casual
- slightly nerdy in a natural way
- on the user's side

### 2.2 Required standard

- Use subtle personality.
- Prefer plain verbs.
- Use contractions when they sound natural.
- Keep confidence quiet.
- Keep jokes rare and never use them in security, failure, or destructive
  confirmations.

### 2.3 Current repo nuances

Pullbox should not sound like:

- release notes
- a product manager
- legal copy
- enterprise marketing
- a stiff chatbot

### 2.4 Audit checks

- [ ] Copy sounds like a technically fluent peer.
- [ ] Tone fits the risk of the moment.
- [ ] Serious flows stay clear and restrained.
- [ ] Personality does not bury the instruction.

## 3. Core Rules

### 3.1 Lead with the outcome

**Current Pullbox implementation**

Many headings and helper strings work best when they start with what the user
gets, fixes, checks, or moves forward.

**Required standard**

Good:

- `Keep downloads moving.`
- `Check what failed and retry the right thing.`
- `Pick a better match before bad metadata spreads through the library.`

Avoid:

- `This interface provides...`
- `This workflow is designed to...`
- `This surface organizes...`

**Audit checks**

- [ ] Heading starts with the user outcome.
- [ ] Helper text explains why or what happens next.
- [ ] Copy avoids generic feature-description language.

### 3.2 Say what and why, not how the UI was built

**Required standard**

Never explain layout, rendering, shell behavior, or design choices in
user-facing copy unless the user is directly debugging that behavior.

Avoid:

- `without leaving the workspace`
- `before the shell paints`
- `reloading the surrounding shell`
- `this page is organized around`
- `this was designed to`

Prefer:

- `keep this page current`
- `open the logs you need`
- `pick up where you left off`
- `check the latest state`

**Current repo nuances**

- Developer docs can use UI architecture words. Product copy should not.
- The user does not need to know whether a screen is a partial, shell, modal
  fragment, or HTMX swap unless that is part of troubleshooting.

**Audit checks**

- [ ] Visible copy avoids implementation terms.
- [ ] UI mechanics are only mentioned when they help the user.
- [ ] Product copy does not read like a design review.

### 3.3 Write like a person

**Required standard**

Prefer:

- `you're`
- `it's`
- `doesn't`
- `check`
- `fix`
- `grab`
- `save`
- `clean up`
- `pick up where you left off`

Avoid needlessly formal alternatives:

- `administrator` when `admin account` or `account` is enough
- `utilize`
- `commence`
- `facilitate`
- `perform an action`

**Audit checks**

- [ ] Plain verbs are used.
- [ ] Formal wording is replaced where it adds no precision.
- [ ] Copy sounds natural when read aloud.

### 3.4 Keep it short unless the stakes are high

**Required standard**

- Headings should carry one idea.
- Helper text should usually be one or two sentences.
- Checklist items should be direct and concrete.
- Destructive confirmations should slow down and be explicit.
- Security and credential copy should be short, but not vague.

**Audit checks**

- [ ] Headings are short and specific.
- [ ] Helper text is scannable.
- [ ] Destructive or security-sensitive flows explain consequences.

### 3.5 Respect the reader

**Required standard**

- Do not lecture.
- Do not oversell.
- Do not use fake enthusiasm.
- Do not explain obvious UI mechanics unless they matter.
- Do not hide risk behind friendly wording.

**Audit checks**

- [ ] Copy respects user competence.
- [ ] Risk is stated plainly.
- [ ] Empty cheerleading is removed.

## 4. Vocabulary

### 4.1 Preferred words

Use these freely when they fit:

- library
- collection
- queue
- jobs
- sign in
- set up
- review
- clean up
- retry
- path
- key
- source
- logs
- health
- keep moving
- keep an eye on
- pick up where you left off

### 4.2 Use carefully

These words are fine when precise, but easy to overuse:

- settings
- automation
- refresh
- monitor
- import
- match

### 4.3 Avoid in user-facing copy unless technically required

- workspace
- surface
- shell
- experience
- journey
- streamline
- optimize
- enterprise
- robust
- powerful
- administrator

### 4.4 Audit checks

- [ ] Preferred product words are used where natural.
- [ ] Banned product-design words do not leak into visible copy.
- [ ] Technical words are used only when they add precision.

## 5. Pattern Guidance

### 5.1 Headings

**Required standard**

Headings should tell the user what the area helps them do.

Good:

- `Keep API access tight.`
- `Bring an existing library into Pullbox.`
- `Check what failed before you retry it.`

Avoid:

- `Authentication workspace`
- `Metadata control center`
- `Import experience`

### 5.2 Helper text

**Required standard**

Helper text should answer one of these:

- why this matters
- what happens next
- what a good default is
- when to use this option

### 5.3 Buttons and links

**Required standard**

Use direct verbs.

Good:

- `Refresh now`
- `Check logs`
- `Save display settings`
- `Open import history`

Avoid:

- `Proceed`
- `Execute`
- `Launch workflow`

### 5.4 Empty states

**Required standard**

Say what is missing and what to do next.

Good:

- `No active utility jobs right now.`
- `Start a new run when you need conversion, export, or cleanup work.`

### 5.5 Errors and warnings

**Required standard**

Be plain, specific, and useful.

Good:

- `Passwords don't match.`
- `This key didn't validate. Check it and try again.`
- `This job finished with warnings. Open the details before assuming it's done.`

Avoid:

- `An error occurred.`
- `The operation was unsuccessful.`

### 5.6 Audit checks

- [ ] Headings describe outcomes.
- [ ] Helper text answers why, what next, default, or when to use.
- [ ] Buttons and links use direct verbs.
- [ ] Empty states say what is missing and what to do.
- [ ] Errors are specific and useful.

## 6. Banned Patterns

### 6.1 Required standard

Do not write copy that:

- explains UI or UX choices to the user
- reads like a changelog
- sounds like generic SaaS marketing
- uses `workspace`, `surface`, or `shell` as visible product language
- sounds more formal than the problem requires
- uses jokes where trust, safety, or data loss is involved

### 6.2 Current repo nuances

- Some old copy may still use design-system language. Update it when that area
  is touched.
- A word can be banned for visible product copy and still be valid in developer
  docs.

### 6.3 Audit checks

- [ ] Product copy avoids implementation language.
- [ ] Product copy does not sound like marketing.
- [ ] Product copy does not read like release notes.

## 7. Examples

Instead of:

- `Move between authentication, API access, file screening, and audit visibility without losing your place in the security workspace.`

Write:

- `Jump between sign-in, API keys, file screening, and audit logs without losing your spot.`

Instead of:

- `Theme preference is applied before the shell paints.`

Write:

- `Theme changes should feel instant and stick the next time you open Pullbox.`

Instead of:

- `Review matches, revisit import history, and follow up on health issues from one place.`

Write:

- `Check matches, revisit old imports, and catch anything that needs a second look.`

## 8. Copy Audit Checklist

Use this checklist for new or revised user-facing copy:

- [ ] Copy leads with the user outcome.
- [ ] Copy is short unless the stakes are high.
- [ ] Helper text explains why, what happens next, a good default, or when to
  use the option.
- [ ] Buttons and links use direct verbs.
- [ ] Errors explain what happened and what to try next.
- [ ] Destructive actions explain consequences plainly.
- [ ] Copy avoids implementation terms like workspace, surface, and shell.
- [ ] Copy avoids generic marketing language.
- [ ] Tone matches the seriousness of the flow.
- [ ] The string sounds like Pullbox when read aloud.
