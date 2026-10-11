# Flows

Everything runs in one polling loop (default every 60 seconds). Each cycle runs
flows 1, 2 and 3 in order. State lives in SQLite (`/data/state.db`).

## Flow 1: New Arctic Wolf ticket → SDP request, assigned and acknowledged

```mermaid
sequenceDiagram
    autonumber
    participant S as Sync service
    participant AW as Arctic Wolf Ticket API
    participant PD as PagerDuty
    participant SDP as ServiceDesk Plus Cloud
    S->>AW: GET /tickets?status=NEW,OPEN,HOLD,PENDING&createdAfter=<baseline>
    AW-->>S: tickets
    loop each ticket not yet in state DB
        S->>PD: GET /schedules/{id} (final schedule, next 48h)
        PD-->>S: shifts
        Note over S: Pick on-shift person (handoff rule below)<br/>PagerDuty ID → identity_map.csv → SDP technician email
        S->>S: record AW id as "creating"
        S->>SDP: POST /requests  subject "[AW-id] title", technician, status = SDP_ACK_STATUS
        SDP-->>S: request id
        S->>S: record mapping AW id ↔ SDP id ("open")
        S->>SDP: POST /requests/{id}/notes  "Acknowledged… assigned to X" (marks first response)
    end
```

## Assignment rule

```mermaid
flowchart TD
    A[New ticket] --> B{Someone on shift now?}
    B -- No --> C[Next person coming on shift]
    B -- Yes --> D{Shift ends within 30 min?}
    D -- No --> E[Person on shift now]
    D -- Yes --> F{Next shift scheduled?}
    F -- Yes --> C
    F -- No --> E
    C --> G{In identity map and Active?}
    E --> G
    G -- Yes --> H[Assign in SDP + set ack status + note]
    G -- No --> I{Fallback technician set?}
    I -- Yes --> J[Assign fallback + note why]
    I -- No --> K[Leave unassigned + note why]
```

Back-to-back PagerDuty entries for the same person are merged first, so the
30-minute window is measured from the real end of their shift.

## Flow 2: SDP Resolved/Closed → close the Arctic Wolf ticket

```mermaid
sequenceDiagram
    autonumber
    participant S as Sync service
    participant SDP as ServiceDesk Plus Cloud
    participant AW as Arctic Wolf Ticket API
    loop each mapping still "open"
        S->>SDP: GET /requests/{id}
        SDP-->>S: status, technician, resolution
        alt status in SDP_CLOSE_STATUSES
            S->>AW: POST /tickets/{awId}/close  {"comment": "Resolved in our SDP… Resolution: …"}
            S->>S: mark "aw_closed" (closed_by = sdp)
        end
    end
```

If the close call fails but Arctic Wolf already shows the ticket CLOSED, it is
marked done. Otherwise the error is recorded and retried next cycle.

## Flow 3: Arctic Wolf closed it first → note on SDP

```mermaid
sequenceDiagram
    participant S as Sync service
    participant AW as Arctic Wolf Ticket API
    participant SDP as ServiceDesk Plus Cloud
    S->>AW: GET /tickets?status=CLOSED&updatedAfter=<last check>
    loop each closed ticket still mapped "open"
        S->>SDP: POST /requests/{id}/notes "Arctic Wolf closed AW ticket…"
        S->>S: mark "aw_closed" (closed_by = arcticwolf)
    end
```

## Ticket states in the DB

| State | Meaning |
|---|---|
| `creating` | SDP create was attempted but the outcome is unknown (e.g. timeout). Never retried automatically, to avoid duplicates. Use `resolve-stuck`. |
| `failed_create` | SDP rejected the create. Retried every cycle. |
| `open` | Mapped; waiting for SDP to reach a close status. |
| `aw_closed` | Arctic Wolf ticket is closed (by this service or by Arctic Wolf). |
