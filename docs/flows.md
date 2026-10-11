# How Watchtower works

Everything runs in one polling loop (default every 60 seconds) inside the same container
as the admin page. Each check re-reads the settings saved on the admin page, then runs
flows 1, 2 and 3 in order. Until the required credentials are saved, the loop waits.
Settings, encrypted credentials, the responder list, ticket state and routing history live in
SQLite (`/data/state.db`) in the `watchtower-data` volume.

## Flow 1: New Arctic Wolf ticket → SDP request, routed to the on-call responder

```mermaid
sequenceDiagram
    autonumber
    participant S as Watchtower
    participant AW as Arctic Wolf Ticket API
    participant PD as PagerDuty
    participant SDP as ServiceDesk Plus Cloud
    S->>AW: GET /tickets?status=NEW,OPEN,HOLD,PENDING&createdAfter=<baseline>
    AW-->>S: tickets
    loop each ticket not yet in state DB
        S->>PD: GET /schedules/{id} (final schedule, next 48h)
        PD-->>S: shifts
        Note over S: Pick the on-call responder (handoff rule below)<br/>PagerDuty ID → Responders page → SDP technician email
        S->>S: record AW id as "creating"
        S->>SDP: POST /requests  subject "[AW-id] title", technician, status = "Status after routing"
        SDP-->>S: request id
        S->>S: record mapping AW id ↔ SDP id ("open") and a "routed" history event
        S->>SDP: POST /requests/{id}/notes  "Watchtower routed this ticket to X… hasn't acknowledged it yet" (marks first response)
    end
```

## Assignment rule

```mermaid
flowchart TD
    A[New ticket] --> B{Someone on call now?}
    B -- No --> C[Next person on call]
    B -- Yes --> D{Shift ends within 30 min?}
    D -- No --> E[Person on call now]
    D -- Yes --> F{Next shift scheduled?}
    F -- Yes --> C
    F -- No --> E
    C --> G{Active responder in Watchtower?}
    E --> G
    G -- Yes --> H[Route in SDP + set status after routing + note]
    G -- No --> I{Fallback technician set?}
    I -- Yes --> J[Route to fallback + note why]
    I -- No --> K[Leave unassigned + note why]
```

Back-to-back PagerDuty entries for the same person are merged first, so the
30-minute window is measured from the real end of their shift.

## Flow 2: SDP Resolved/Closed → close the Arctic Wolf ticket

```mermaid
sequenceDiagram
    autonumber
    participant S as Watchtower
    participant SDP as ServiceDesk Plus Cloud
    participant AW as Arctic Wolf Ticket API
    loop each mapping still "open"
        S->>SDP: GET /requests/{id}
        SDP-->>S: status, technician, resolution
        S->>S: refresh current owner + SDP status; log ownership and status changes
        alt status in close statuses
            S->>AW: POST /tickets/{awId}/close  {"comment": "Resolved in our SDP… Resolution: …"}
            S->>S: mark "aw_closed" (closed_by = sdp), log "resolved"
        end
    end
```

If the close call fails but Arctic Wolf already shows the ticket CLOSED, it is
marked done. Otherwise the error is recorded and retried next cycle. If reading the
request from SDP fails, the ticket is flagged "Out of date" on the overview.

## Flow 3: Arctic Wolf closed it first → note on SDP

```mermaid
sequenceDiagram
    participant S as Watchtower
    participant AW as Arctic Wolf Ticket API
    participant SDP as ServiceDesk Plus Cloud
    S->>AW: GET /tickets?status=CLOSED&updatedAfter=<last check>
    loop each closed ticket still mapped "open"
        S->>SDP: POST /requests/{id}/notes "Arctic Wolf closed ticket…"
        S->>S: mark "aw_closed" (closed_by = arcticwolf)
    end
```

## Ticket states

What's stored, and what the overview shows for it (`watchtower/status.py`). Watchtower
never shows "Acknowledged": it can see that a ticket was routed, but not that the
responder accepted it.

| Stored state | Shown as | Meaning |
|---|---|---|
| `creating` | Needs check | SDP create was attempted but the outcome is unknown (e.g. timeout). Never retried automatically, to avoid duplicates. Use `resolve-stuck`. |
| `failed_create` | Routing failed | SDP rejected the create. Retried every check. |
| `open`, with an owner | Routed | Assigned in SDP; waiting for a close status. |
| `open`, no owner | Unassigned | No eligible on-call responder, or the owner was removed in SDP. |
| `open`, SDP status is a close status | Resolving | Arctic Wolf ticket closes on the next check. |
| `open`, close failed | Close failed | Closing the Arctic Wolf ticket failed; retried every check. |
| `aw_closed` (by SDP) | Resolved | Resolved in SDP; Arctic Wolf ticket closed. |
| `aw_closed` (by Arctic Wolf) | Closed in Arctic Wolf | Arctic Wolf closed it first; the SDP request may still be open. |

Any open ticket whose last read from SDP failed, or is older than three checks, also
shows **Out of date**.

## Routing history

Every routing decision, ownership change, SDP status change, resolution, close and
failure is written to the `events` table and shown on the ticket page and under
Activity. Repeated identical failures are recorded once.
