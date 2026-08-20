# Governance

LumenPlot is a pre-alpha project with an unstable public API. Human maintainers
are accountable for the project, including its legal terms, security response,
architecture, merges, releases, and repository visibility.

## Decision ownership

- Cross-cutting architecture decisions are recorded in an ADR before
  implementation. The ADR states context, decision, alternatives, rationale,
  consequences, affected interfaces, and verification.
- Maintainers decide whether an ADR is accepted, superseded, historical, or not
  suitable for the public tree.
- A document or partial implementation does not become a compatibility promise
  merely because it exists in a working tree.
- Performance and compatibility statements require reproducible evidence and
  maintainer review.

## Human authority and tools

Agents, bots, and automation are tools. They may inspect, propose, implement,
test, and report work, but they are not legal authority, security-response
authority, merge authority, or release authority. A human maintainer must
approve legal notices, public visibility changes, security disclosures,
architecture decisions, and release claims.

## Public communication

Issues and pull requests should describe supported behavior and explicit
limitations without overstating unfinished work. Security and sensitive conduct
reports must use the private routes in [SECURITY.md](SECURITY.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) rather than public discussion.
