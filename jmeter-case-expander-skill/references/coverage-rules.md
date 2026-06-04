# Coverage Rules

## Default order

Expand in this order and stop when the input data no longer supports a case with high confidence:

1. Positive baseline confirmation
2. Optional field missing
3. Required field missing
4. `null`
5. Empty string
6. Single-space string
7. Type mismatch
8. Boundary overflow or underflow
9. Hidden field override attempt
10. Extra undefined field

## Required fields

For each required field, prefer one-field-at-a-time variants:

- field removed entirely
- field present with `null`
- field present with `""`
- field present with `" "`

Only add type mismatch or boundary cases when the field type or limit is explicitly provided.

## Optional fields

For each optional field, prefer:

- field removed entirely
- field present with `null`
- field present with `""`

Only add a single-space variant when the business context suggests whitespace is meaningful.

## Hidden fields

Do not brute-force hidden fields. Add at most one or two focused checks:

- hidden field injected when absent from the baseline
- hidden field overwritten when present in the baseline

Use obvious marker values such as `__AUTO_HIDDEN__` so reviewers can spot the case quickly.

## Extra undefined fields

Add at most one extra-field case unless the user asks for more depth. Use a stable field name such as `__unexpectedField`.

## Boundaries

Only generate boundary cases when the user provides concrete limits. Prefer:

- numeric `min - 1` and `max + 1`
- string lengths `min_length - 1` and `max_length + 1`

If the value cannot be transformed safely, skip the case and report the gap.

## Uniqueness

Do not auto-generate uniqueness collision cases unless the user provides a known duplicate strategy or fixture data. Mention the gap instead of guessing.
