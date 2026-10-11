# Watchtower — Brand & UI Design System

**Document type:** Product brand specification  
**Status:** Initial implementation baseline  
**Product:** Watchtower  
**Category:** On-call ticket routing and coordination  
**Primary tagline:** The right person. Right on time.

This document is the source of truth for Watchtower's brand identity and user-interface direction. Use it when implementing new screens, components, icons, copy, notifications, and visual assets. If an existing product requirement conflicts with this document, preserve required functionality and call out the conflict rather than silently inventing a new design direction.

---

## 1. Product definition

Watchtower routes tickets and issues to the appropriate on-call person. It helps teams coordinate handoffs, establish ownership, and follow an issue through routing, acknowledgment, escalation, and resolution.

**Watchtower is the coordination layer—not the monitoring or detection system.** Other tools may detect events and create tickets. Watchtower helps get those tickets to the correct responder.

### Product positioning

Watchtower is an on-call ticket-routing and coordination platform for IT and technical teams. It connects incoming issues to the right responder, clarifies ownership, and supports reliable handoffs so work reaches the people responsible for resolving it.

### Brand promise

Clearer handoffs. Faster routing. Accountable ownership.

### Primary tagline

**The right person. Right on time.**

### Supporting phrase

**From ticket to ownership.**

### Brand essence

**A reliable lookout for operational responsibility.**

### Product outcomes to emphasize

- Route a ticket to the appropriate person or team.
- Make current ownership and handoff status clear.
- Show who is on call and which routing rule or schedule was applied.
- Support acknowledgment and escalation workflows where implemented.
- Keep a useful history of routing decisions, notifications, and status changes.
- Reduce ambiguity and avoid tickets being stranded between people or teams.

Do not describe Watchtower as a SIEM, EDR, threat detector, security analytics platform, or monitoring agent unless the product scope explicitly changes.

---

## 2. Brand story and metaphor

The Watchtower name evokes a fire-watch tower or a lookout built into a castle wall: a dependable structure that maintains a view over a wider area and helps coordinate a response when something needs attention.

For this product, the metaphor is about **coordination, readiness, and continuity**—not surveillance or detecting threats.

- **Fire-watch tower:** a clear signal, readiness, dependable communication, and getting attention to the right place.
- **Castle wall / battlement:** protection, stability, boundaries, and a central point of coordination.
- **Connected paths:** tickets moving to teams and responders.
- **Beacon:** a notification or routing event that needs attention.
- **Gate / passage:** a controlled handoff from intake to ownership.

Use the metaphor subtly. The product should still look like modern premium software, not a medieval game, fantasy role-playing app, military command interface, or historical reenactment.

### Brand pillars

1. **Intelligent routing** — match issues to the appropriate responder using configured ownership, service, team, and on-call rules.
2. **Clear ownership** — make it obvious who is responsible, whether they have acknowledged the ticket, and what happens next.
3. **Reliable continuity** — support clear escalation, reassignment, and an auditable handoff history when those features are available.

### Brand personality

- **Reliable:** consistent, predictable, and accountable.
- **Intelligent:** understands routing context and makes decisions understandable.
- **Focused:** highlights what needs attention without unnecessary noise.
- **Calm:** professional under pressure; never alarmist.
- **Approachable:** a useful teammate for technical operators, not a bureaucratic gatekeeper.

### Brand is / is not

| Is | Is not |
|---|---|
| Operational coordination | Threat detection |
| Clear and accountable | Opaque or ambiguous |
| Calm and precise | Alarmist or fear-based |
| Modern and technical | Needlessly complex |
| Dependable and human-centered | Militaristic or intimidating |
| Helpful automation | An unexplained black box |

---

## 3. Logo and icon direction

### Preferred concept: The Watchtower Beacon

Create a simple geometric fire-watch tower or lookout-tower symbol. The shape should have a strong vertical structure, a recognizable elevated observation point, and a small roof or beacon detail. It should remain recognizable at favicon and app-icon sizes.

The symbol may also subtly reference a castle wall or battlement through a squared roofline or crenellated top. Keep this secondary; the tower should remain the dominant silhouette.

### Logo design characteristics

- Minimal geometric vector artwork.
- Strong silhouette and clear negative space.
- One-color version must work as well as the color version.
- Flat shapes; no detailed illustration, photorealism, bevels, or heavy gradients.
- Designed to remain legible at 16–24 px.
- Wordmark uses a modern sans-serif with restrained letter spacing.
- The logo must not depend on a surrounding circle, shield, or complex background to be recognizable.

### Required variants

1. **Primary horizontal logo:** symbol plus WATCHTOWER wordmark.
2. **Standalone mark:** tower symbol only.
3. **Dark-background logo:** light wordmark with teal symbol.
4. **Light-background logo:** dark wordmark with teal or navy symbol.
5. **Monochrome logo:** one-color version for documentation and constrained environments.
6. **Small-size icon:** simplified silhouette optimized for favicon and app launcher use.

### Logo use rules

- Preserve aspect ratio and clear space.
- Do not redraw, distort, rotate, or add effects to the approved mark.
- Do not use the detailed wordmark at sizes where it becomes unreadable; use the standalone mark.
- Avoid using castle imagery as a repeated decorative background throughout the product.
- Treat the logo as a brand asset, not as a status icon.

**Implementation instruction:** If final logo files do not exist in the repository, create a clean, simple inline SVG or an SVG asset matching this description. Do not use emoji, a Unicode character, or an unrelated icon as the final logo. Keep the logo component replaceable so a designer can swap in approved artwork later. Name the component `WatchtowerLogo` and support at least `variant`, `size`, and `showWordmark` props if consistent with the project's framework.

---

## 4. Visual direction

**Style:** Modern, premium, minimalist technology.  
**Interface:** Dark-first.  
**Mood:** Calm, precise, dependable, operationally ready.  
**Density:** Information-efficient without feeling crowded.

The UI should feel like high-quality enterprise operations software. Use deep navy surfaces, restrained teal accents, clear type hierarchy, subtle dividers, and predictable interaction patterns.

Avoid:
- Neon cyberpunk styling.
- Glowing borders on every panel.
- Excessive gradients, glassmorphism, blur, and decorative animation.
- Large decorative tower illustrations inside routine workflow screens.
- Generic shield-and-lock clichés as the primary brand identity.
- Red or amber as decorative brand colors.
- Dense dashboards that imply Watchtower performs monitoring or threat detection.

---

## 5. Color tokens

Use these values as the initial design baseline. Centralize them in the project's theme or token system; do not scatter raw color literals through components. Validate contrast in the actual rendered UI before release.

### Core palette

| Token | Hex | Intended use |
|---|---|---|
| `wt-midnight` | `#0B1220` | Main dark application background |
| `wt-navy` | `#111C2E` | Sidebar, primary panels, navigation |
| `wt-elevated` | `#19283D` | Cards, menus, raised surfaces |
| `wt-blue` | `#1E4770` | Secondary accents, selected supporting elements |
| `wt-teal` | `#35D0BA` | Primary brand accent, focus and active states |
| `wt-cloud` | `#F1F5F9` | Primary text on dark surfaces; light theme surface |
| `wt-slate` | `#9AAABD` | Secondary text and subdued metadata |
| `wt-border` | `#2A3A50` | Dividers, borders, outlines |

### Semantic colors

These colors communicate ticket state, not brand personality. Always pair color with a visible label or other non-color cue.

| Token | Hex | Meaning |
|---|---|---|
| `wt-status-unassigned` | `#64748B` | Not yet assigned |
| `wt-status-routed` | `#60A5FA` | Routed / in progress |
| `wt-status-acknowledged` | `#35D0BA` | Responder acknowledged |
| `wt-status-escalated` | `#FBBF24` | Escalated / needs attention |
| `wt-status-resolved` | `#4ADE80` | Resolved |
| `wt-status-error` | `#FB7185` | Routing or workflow failure |
| `wt-status-info` | `#60A5FA` | Informational state |

**Status distinction is mandatory:**
- **Sent** means the notification attempt was made.
- **Delivered** means delivery was confirmed by the relevant integration, if that signal is available.
- **Acknowledged** means the intended responder acknowledged responsibility.
- **Resolved** means the ticket was resolved according to the connected workflow.
- Never label a ticket “acknowledged” just because a notification was sent.
- Never infer successful delivery or resolution when the source system does not provide that information.

### Color usage rules

- Dark backgrounds should dominate the dark theme.
- Use teal sparingly for primary actions, focus, active navigation, and confirmed acknowledgment.
- Use amber for escalation or time-sensitive attention.
- Use red/pink for errors and genuinely critical workflow failures—not ordinary routing.
- Avoid using teal as the sole indication that a ticket is healthy or resolved.
- Keep text and interactive controls readable against their surfaces.
- Target WCAG 2.2 AA contrast: at least 4.5:1 for normal text and 3:1 for large text and applicable UI components. Test every actual foreground/background pairing, including hover and disabled states.
- Provide light-theme equivalents if the app supports a light theme; dark-first does not mean hard-coding dark colors into every component.

---

## 6. Typography

### Recommended typefaces

- **Space Grotesk:** brand headlines and major page titles.
- **Inter:** interface, forms, navigation, buttons, tables, and body text.
- **IBM Plex Mono:** optional technical identifiers, ticket IDs, timestamps, or system references.

Use fonts already approved or bundled by the project where possible. If adding fonts, include a sensible system fallback and avoid introducing an external runtime dependency unnecessarily.

### Type scale

| Role | Size / line height | Weight |
|---|---|---|
| Marketing display | 40 / 48 px | 600 |
| Page title | 32 / 40 px | 600 |
| Section title | 24 / 32 px | 600 |
| Card title | 18–20 / 26–28 px | 600 |
| Body | 14–16 / 22–24 px | 400 |
| Secondary body | 13 / 20 px | 400 |
| Label | 12 / 16 px | 500 |
| Technical identifier | 12–14 / 18–20 px | 400–500 |

Use sentence case for most labels and headings. Reserve uppercase for short eyebrow labels and compact metadata. Avoid using tiny text to fit more content into a screen. Use tabular numerals where available for aligned counts and times.

---

## 7. Layout and component principles

### Spacing and geometry

Use a 4 px spacing base. Preferred intervals: 4, 8, 12, 16, 24, 32, and 40 px. Use 6 px corner radius for controls and 8 px for cards as the default starting point. Use shadows sparingly; surface contrast and borders should do most of the work.

### Interface principles

1. **Clarity first:** show the most important ticket, owner, and state information at the right level of detail.
2. **Ownership is visible:** every ticket view should clearly show current owner or team, and whether the ticket is unassigned.
3. **Routing is explainable:** where possible, show why a person was selected, such as service ownership, team assignment, or on-call schedule.
4. **Continuity over spectacle:** emphasize routing history, notification outcome, acknowledgment, escalation, and next steps.
5. **Progressive disclosure:** keep summaries concise and allow users to inspect routing rules, event history, and detailed ticket metadata when needed.
6. **Trust through transparency:** clearly distinguish actual state from unknown state or unavailable integration data.
7. **Safe actions:** confirm potentially disruptive actions and describe their consequences.
8. **Accessible by default:** support keyboard navigation, visible focus, screen readers, responsive layouts, reduced motion, and meaningful labels.

### Recommended product information architecture

Adapt to the existing application rather than creating routes that the product does not support. Likely navigation areas include:

- **Overview:** routing health, unassigned tickets, awaiting acknowledgment, and recent handoffs.
- **Tickets / Queue:** incoming, assigned, escalated, and resolved work.
- **On-call:** current responder, team/service schedules, and relevant coverage.
- **Routing rules:** service/team mappings, assignment rules, and fallbacks.
- **Activity / Audit:** routing decisions, notification attempts, acknowledgments, reassignment, and status changes.
- **Settings / Integrations:** connected ticket sources, notification channels, and configuration.

Do not fabricate metrics or statuses. Use data from the actual application and connected services. If a feature is not implemented, do not present it as functional.

### Suggested ticket lifecycle

Use the connected ticket system's real lifecycle where available. A conceptual routing flow is:

`Received → Routed → Notified → Acknowledged → Resolved`

Escalation and reassignment may occur when configured conditions are met. “Notified” is not equivalent to “Acknowledged.” A ticket may be routed but still awaiting acknowledgment. Show failures and unknown states explicitly.

### Component conventions

- **Primary button:** teal background, dark readable text, clear verb-based label.
- **Secondary button:** neutral surface or transparent background with a visible border.
- **Cards:** consistent padding, restrained borders, no decorative glow.
- **Tables:** clear headers, useful sorting/filtering, keyboard access, and informative empty states.
- **Ticket row:** ticket title/ID, priority if provided, source/service, current owner, state, and relevant age/time.
- **Status badge:** semantic color plus explicit text; never color alone.
- **Timeline:** ordered, timestamped events with actor/source and outcome.
- **Notifications:** concise title, ticket reference, routing result, and next action when applicable.
- **Forms:** visible labels, inline validation, helpful error messages, and confirmation for consequential changes.
- **Empty states:** explain why no items appear and offer a relevant next step.
- **Loading states:** show genuine progress or a neutral loading indicator; do not imply a routing outcome before it exists.

Target approximately 44 × 44 CSS px for primary touch targets where practical. Ensure dialogs, menus, tables, and ticket actions remain usable with a keyboard.

---

## 8. Iconography and illustration

Use a consistent outline icon set, such as Lucide, with a consistent stroke weight. Use icons for routing, users/responders, tickets, schedules, notifications, acknowledgment, escalation, and resolution.

The brand mark should be a custom tower silhouette. Supporting UI icons should remain conventional and easy to recognize.

Recommended semantic concepts:
- Tower / beacon: Watchtower brand.
- User / user-check: responder and ownership.
- Git branch / route: routing path.
- Clock: schedule, elapsed time, or SLA where applicable.
- Bell: notification attempt or notification settings.
- Check circle: acknowledgment or completion, only when that state is verified.
- Arrow-up-right / escalation icon: escalation.
- History / list: activity log.

Do not use the tower icon to mean “monitoring active” unless that is an explicit, accurate product state. Avoid emojis in production UI.

---

## 9. Voice, tone, and terminology

Watchtower speaks like a capable operations teammate: direct, calm, precise, and helpful.

### Voice principles

- **Clear:** short sentences and concrete verbs.
- **Specific:** name the ticket, team, person, time, and result when known.
- **Calm:** no alarmist language or excessive exclamation marks.
- **Honest:** distinguish attempted, delivered, acknowledged, escalated, and resolved.
- **Actionable:** tell the user what happened and what can happen next.

### Preferred terminology

Use consistently:
- Ticket
- Responder
- On-call person / on-call team
- Current owner
- Routing rule
- Notification
- Acknowledgment
- Escalation
- Reassignment
- Resolved
- Routing history

Do not use “detected threat,” “threat intelligence,” “security posture,” or “monitoring coverage” to describe Watchtower's own functions unless those capabilities genuinely exist.

### Example UI copy

| Situation | Recommended copy |
|---|---|
| Successful routing | “Ticket routed to the Infrastructure on-call team.” |
| Awaiting acknowledgment | “Notification sent. Waiting for the responder to acknowledge.” |
| No responder found | “No eligible on-call responder was found. Review the schedule or routing rule.” |
| Notification failure | “We couldn't confirm notification delivery. Check the channel and retry if appropriate.” |
| Escalation | “No acknowledgment received within the configured window. Escalation started.” |
| Reassignment | “Ownership changed from [person/team] to [person/team].” |
| Resolved | “Ticket marked as resolved in [source system].” |
| Empty queue | “No tickets match these filters.” |
| Schedule gap | “No on-call coverage is configured for this period.” |
| Integration unavailable | “Ticket status could not be refreshed. The displayed state may be out of date.” |

Avoid unsupported guarantees such as “No ticket will ever be missed” or “Every issue is instantly routed.” Use “helps route,” “supports reliable handoffs,” and other accurate claims.

---

## 10. Messaging

### Primary tagline

**The right person. Right on time.**

### Supporting messages

- **Intelligent routing:** Get each issue to the appropriate responder.
- **Clear ownership:** Know who has the ticket and what happens next.
- **Reliable continuity:** Keep handoffs visible from routing through acknowledgment and resolution.

### Short product description

Watchtower helps IT teams route tickets to the right on-call responder, clarify ownership, and coordinate reliable handoffs.

### Longer product description

Watchtower is an on-call ticket-routing and coordination platform for technical teams. It connects incoming tickets with configured ownership and on-call schedules, makes routing outcomes visible, and supports acknowledgment and escalation workflows so issues reach the people responsible for resolving them.

### Sample landing-page hero

**Headline:** The right person. Right on time.  
**Subheading:** Route tickets to the right on-call responder, make ownership clear, and keep every handoff accountable.  
**Primary action:** View routing queue  
**Secondary action:** Configure routing

Use these action labels only if those destinations and workflows exist in the app.

---

## 11. Motion and interaction

Motion should clarify state changes rather than decorate the product.

- Use short, subtle transitions for navigation, menus, and panel changes.
- Make newly routed tickets noticeable without flashing or pulsing continuously.
- Provide clear feedback after routing, acknowledgment, reassignment, and escalation actions.
- Never display success feedback before the operation has actually succeeded.
- Respect `prefers-reduced-motion`.
- Avoid animated radar sweeps, scanning effects, and other visual treatments that imply Watchtower itself detects or monitors threats.

---

## 12. Accessibility, trust, and operational correctness

Brand credibility depends on truthful state representation.

- Pair semantic colors with text or icons.
- Provide visible keyboard focus and logical tab order.
- Use accessible names for icon-only controls.
- Validate WCAG 2.2 AA contrast on real component states.
- Make status, ownership, and routing history available to assistive technology.
- Use consistent time zones and label them clearly.
- Indicate stale data or disconnected integrations.
- Do not expose sensitive ticket details in notification previews unless permitted by product policy.
- Log consequential routing changes when supported.
- Do not claim delivery, acknowledgment, escalation, or resolution without supporting evidence from the application or integration.
- Ensure retry actions do not unintentionally create duplicate notifications or duplicate ticket operations.

---

## 13. Engineering implementation guidance for Claude Code

When applying this guide to the repository:

1. Inspect the existing framework, routes, component system, theme setup, and current functionality before editing.
2. Reuse existing architecture and conventions. Do not replace working features merely to match a mockup.
3. Create centralized design tokens using the project's native styling approach (CSS variables, theme configuration, or equivalent).
4. Implement reusable components for the logo, buttons, ticket status badges, ticket rows/cards, and event timeline as appropriate.
5. Keep the Watchtower logo as a replaceable vector asset/component.
6. Apply the visual system consistently to the existing screens and flows; do not invent backend capabilities or mock operational success.
7. Use real product data where available. Clearly label any fixture or sample data used in development.
8. Verify loading, empty, error, disabled, success, and permission-denied states.
9. Check responsive behavior, keyboard navigation, reduced motion, and contrast.
10. Run the repository's existing lint, test, and build commands where available. Report any failures rather than claiming success without verification.

### Definition of done

- The product's actual purpose is clear: ticket routing and on-call coordination.
- The tower/beacon brand is consistent and usable at small sizes.
- Colors and typography come from centralized tokens.
- Ticket ownership and routing states are easy to distinguish.
- Notifications sent are not confused with acknowledgments.
- UI copy follows the voice and terminology in this document.
- No unsupported monitoring or threat-detection capabilities are implied.
- Existing product behavior remains intact.
- Build and test results are reported accurately.

---

## 14. Quick reference

| Item | Standard |
|---|---|
| Product | Watchtower |
| Category | On-call ticket routing and coordination |
| Tagline | The right person. Right on time. |
| Brand essence | A reliable lookout for operational responsibility |
| Brand pillars | Intelligent routing, clear ownership, reliable continuity |
| Logo metaphor | Fire-watch tower / castle-wall lookout, simplified to a geometric beacon |
| Visual style | Modern, premium, minimalist technology |
| Theme | Dark-first |
| Primary background | `#0B1220` |
| Main surface | `#111C2E` |
| Raised surface | `#19283D` |
| Brand accent | `#35D0BA` |
| Primary text | `#F1F5F9` |
| Secondary text | `#9AAABD` |
| Display font | Space Grotesk |
| UI font | Inter |
| Optional data font | IBM Plex Mono |
| Voice | Clear, calm, precise, actionable |
| Core test | Does this make routing, ownership, and the next step clearer? |

**Final brand test:** Every design and copy decision should help a technical team understand where a ticket is going, who owns it, whether the handoff succeeded, and what happens next.
