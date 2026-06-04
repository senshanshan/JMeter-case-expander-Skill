# JDBC Safety Rules

## Hard rules

- Never widen delete scope to "make cleanup work".
- Prefer exact cleanup using a stable unique key, such as code, username, or ID.
- If the original SQL is already narrower than the proposed change, keep the narrower version.
- Do not infer child-table cascade deletes automatically.
- If cleanup intent is unclear, warn and leave the SQL unchanged.

## Safe modification patterns

Safe changes are limited to:

- replacing a broad delete with an explicitly provided `full_sql`
- appending an explicitly provided `where_clause`
- normalizing whitespace while preserving SQL meaning

Do not invent table names, joins, or predicates from context clues alone.

## Risk indicators

Treat these as review findings:

- `DELETE` or `UPDATE` without `WHERE`
- `TRUNCATE`
- `WHERE 1=1`
- wildcard cleanup that could affect historical data
- cleanup based on non-unique display names when unique IDs exist

## Reporting

Always report:

- whether any JDBC sampler changed
- original and new sampler name
- a short explanation of why the change is safer
- any unresolved risk that still needs human review
