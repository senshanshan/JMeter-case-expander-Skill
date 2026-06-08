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
9. Hidden value matrix: allowed correct values, type-invalid values, business-invalid values, tamper values, unauthorized values
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

Hidden values must be covered as their own ordered matrix. For every hidden field with enough rule data, generate cases in this order:

1. Business-allowed correct values
2. Type-invalid values
3. Business-invalid values
4. Tampering and unauthorized-access values

Keep each case one-field-at-a-time. Do not combine hidden-field mutations with required-field,
optional-field, boundary, or extra-field mutations.

Use these spec keys when available:

- `allowed_values`: values the business allows, including the baseline value when it is valid
- `type_invalid_values`: values with the wrong JSON or parameter type
- `business_invalid_values`: values with the right type but rejected by business rules
- `tamper_values`: altered hidden values that should fail integrity or anti-tamper checks
- `unauthorized_values`: values belonging to another user, tenant, role, org, store, or data scope

If only `hidden_fields` is provided, still add focused tamper and unauthorized marker cases so reviewers
can see the risk area. Use obvious marker values such as `__AUTO_HIDDEN_TAMPER__` and
`__AUTO_HIDDEN_UNAUTHORIZED__`.

Do not brute-force hidden fields. Skip speculative values when neither the baseline nor the spec gives
enough context to produce a meaningful case, and report the gap.

Prefer naming that exposes the coverage layer, for example `hidden allowed orderId`,
`hidden type invalid orderId`, `hidden business invalid orderId`, `hidden tamper orderId`, and
`hidden unauthorized orderId`.

## Extra undefined fields

Add at most one extra-field case unless the user asks for more depth. Use a stable field name such as `__unexpectedField`.

## Boundaries

Only generate boundary cases when the user provides concrete limits. Prefer:

- numeric `min - 1` and `max + 1`
- string lengths `min_length - 1` and `max_length + 1`

If the value cannot be transformed safely, skip the case and report the gap.

## Uniqueness

Do not auto-generate uniqueness collision cases unless the user provides a known duplicate strategy or fixture data. Mention the gap instead of guessing.
