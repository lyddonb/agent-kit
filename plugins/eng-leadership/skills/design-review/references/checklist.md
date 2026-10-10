# Design review checklist

Use what applies. Each item is a prompt for a finding, not a box to tick.

## Problem and scope
- Is the problem stated in terms of user or business impact, with evidence?
- Are goals and explicit non-goals listed? Is success measurable?
- Were simpler alternatives (including "do nothing" or "buy") considered and fairly rejected?

## Approach
- Can you explain the design from the doc alone? Are diagrams consistent with the text?
- What are the one-way doors: data model, public API, storage engine, vendor, protocol?
- Does it fit existing systems and conventions, or introduce a new pattern? If new, is it justified?

## Data
- Schema, ownership, and source of truth are clear.
- Migration and backfill plan, including rollback and dual-write/read periods.
- Retention, deletion, privacy, and tenant isolation (especially multi-tenant SaaS).

## Reliability and scale
- Expected load now and in 12-24 months; where it breaks first.
- Failure modes: dependency outage, partial failure, retries, idempotency, back-pressure, timeouts.
- What happens during deploys and rollbacks?

## Security
- AuthN/AuthZ for every new surface; least privilege for services and credentials.
- Input validation, secrets handling, auditability, and abuse cases.

## Operability
- Metrics, logs, traces, alerts, and dashboards defined up front.
- Runbooks and on-call impact. Who owns it after launch?

## Delivery
- Milestones that ship value incrementally; feature flags; how it is tested (unit, integration, load).
- Dependencies on other teams and their commitment.
- Estimated effort vs. team capacity; the riskiest part is done first.

## Cost
- Infrastructure and vendor cost at expected scale; cost of being wrong.
