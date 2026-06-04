# Input Contract

## Required inputs

- `input`: path to one `.jmx` file
- `thread_group`: exact target thread group name, unless the caller already resolved it from inspection
- `base_sampler`: one positive HTTP sampler to clone, or enough context to let the script choose the first HTTP sampler safely
- `required_fields`: top-level fields that must exist
- `optional_fields`: top-level fields that may be omitted

## Recommended inputs

- `hidden_fields`
- `field_types`
- `boundary_values`
- `unique_fields`
- `extra_fields`
- `jdbc_cleanup`
- `rename_base_sampler_to`
- `remove_samplers`
- `case_plan`

## Supported patch spec

Use a JSON file shaped like this:

```json
{
  "thread_group": "Create User Thread Group",
  "base_sampler": "Create User - positive",
  "required_fields": ["username", "password"],
  "optional_fields": ["nickname"],
  "hidden_fields": ["id"],
  "rename_base_sampler_to": "1.全必填正常情况",
  "remove_samplers": ["2.旧的自动生成用例"],
  "field_types": {
    "username": "string",
    "age": "integer",
    "enabled": "boolean"
  },
  "boundary_values": {
    "age": { "min": 1, "max": 120 },
    "username": { "min_length": 2, "max_length": 20 }
  },
  "extra_fields": {
    "__unexpectedField": "unexpected"
  },
  "case_plan": [
    {
      "name": "2.必填用户名缺失",
      "remove_fields": ["username"]
    },
    {
      "name": "3.可选昵称为空串",
      "set_fields": {
        "nickname": ""
      }
    }
  ],
  "jdbc_cleanup": {
    "allow_modify": true,
    "sampler_name": "cleanup user data",
    "full_sql": "DELETE FROM user_info WHERE username = '${username}'"
  }
}
```

## Assumptions

- Field mutation currently supports top-level JSON body fields or standard HTTP argument fields.
- Nested JSON paths are intentionally out of scope for v1.
- If `base_sampler` is omitted, the first HTTP sampler in the target thread group is used.
- If `jdbc_cleanup.allow_modify` is false or missing, cleanup SQL is reviewed but not changed.
- If `case_plan` is provided, it overrides the default auto-generated English mutation list and preserves the given order exactly.
- Prefer Chinese sampler names with explicit numbering such as `1.全必填正常情况`, `2.必填编号缺失`.
