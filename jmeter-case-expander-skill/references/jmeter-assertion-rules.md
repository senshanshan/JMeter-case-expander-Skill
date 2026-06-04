# JMeter Assertion Rules

## Review focus

Check these items before delivery:

- success assertions still match the positive case semantics
- negative cases are not incorrectly reusing strict success-only assertions
- response encoding remains consistent for Chinese text and other non-ASCII payloads
- request path, method, and content encoding remain aligned across generated samplers
- child extractors and scripts remain attached to cloned samplers only when that behavior is still correct

## Assertion heuristics

- If a sampler has no response assertion at all, flag it for review.
- If failure detection depends on raw database exception text, mark it as brittle.
- If success relies only on HTTP 200 without body checks, mark it as weak rather than wrong.
- If cloned negative cases still assert the original success message, call that out explicitly.

## Encoding heuristics

- Prefer a single `HTTPSampler.contentEncoding` convention within one thread group.
- If some generated samplers have empty encoding while peers use UTF-8, flag the drift.
- Invalid JSON bodies should be reported as high-priority review findings.
