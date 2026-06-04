#!/usr/bin/env python3
"""Patch a JMeter .jmx file by cloning a base sampler into conservative variants."""

from __future__ import annotations

import argparse
import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def indent_tree(element: ET.Element, level: int = 0) -> None:
    # Python 3.8 does not provide xml.etree.ElementTree.indent.
    indent_text = "\n" + level * "  "
    child_indent = "\n" + (level + 1) * "  "
    children = list(element)
    if children:
        if not element.text or not element.text.strip():
            element.text = child_indent
        for child in children:
            indent_tree(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = child_indent
        if not children[-1].tail or not children[-1].tail.strip():
            children[-1].tail = indent_text
    elif level and (not element.tail or not element.tail.strip()):
        element.tail = indent_text


def is_hash_tree(element: Optional[ET.Element]) -> bool:
    return element is not None and local_name(element.tag) == "hashTree"


def iter_pairs(hash_tree: ET.Element) -> Iterable[Tuple[int, ET.Element, ET.Element]]:
    children = list(hash_tree)
    index = 0
    while index < len(children):
        element = children[index]
        subtree = children[index + 1] if index + 1 < len(children) and is_hash_tree(children[index + 1]) else ET.Element("hashTree")
        yield index, element, subtree
        index += 2


def attr_name(element: ET.Element) -> str:
    return element.attrib.get("testname") or element.attrib.get("name") or local_name(element.tag)


def find_prop_node(element: ET.Element, prop_name: str) -> Optional[ET.Element]:
    for child in element.iter():
        if child.attrib.get("name") == prop_name:
            return child
    return None


def find_prop_text(element: ET.Element, prop_name: str) -> str:
    node = find_prop_node(element, prop_name)
    return node.text if node is not None and node.text is not None else ""


def classify(element: ET.Element) -> str:
    tag = local_name(element.tag)
    testclass = element.attrib.get("testclass", "")
    text = f"{tag} {testclass}".lower()
    if "threadgroup" in text:
        return "thread_group"
    if "httpsamplerproxy" in text:
        return "http_sampler"
    if "jdbc" in text:
        return "jdbc_request"
    return "other"


def find_thread_group(root: ET.Element, target_name: str) -> Tuple[ET.Element, ET.Element]:
    def walk(hash_tree: ET.Element) -> Optional[Tuple[ET.Element, ET.Element]]:
        for _, element, subtree in iter_pairs(hash_tree):
            if classify(element) == "thread_group" and attr_name(element) == target_name:
                return element, subtree
            found = walk(subtree)
            if found:
                return found
        return None

    for candidate in root.iter():
        if is_hash_tree(candidate):
            result = walk(candidate)
            if result:
                return result
            break
    raise ValueError(f"Thread group not found: {target_name}")


def find_base_sampler(thread_hash: ET.Element, sampler_name: Optional[str]) -> Tuple[int, ET.Element, ET.Element]:
    first_http: Optional[Tuple[int, ET.Element, ET.Element]] = None
    for index, element, subtree in iter_pairs(thread_hash):
        if classify(element) != "http_sampler":
            continue
        triple = (index, element, subtree)
        if first_http is None:
            first_http = triple
        if sampler_name and attr_name(element) == sampler_name:
            return triple
    if sampler_name:
        raise ValueError(f"Base sampler not found: {sampler_name}")
    if first_http:
        return first_http
    raise ValueError("No HTTP sampler found in target thread group")


def find_pair_index_by_element(thread_hash: ET.Element, target: ET.Element) -> int:
    for index, element, _ in iter_pairs(thread_hash):
        if element is target:
            return index
    raise ValueError(f"Sampler element not found: {attr_name(target)}")


def find_arguments_parent(sampler: ET.Element) -> Optional[ET.Element]:
    for element in sampler.iter():
        if element.attrib.get("name") == "HTTPsampler.Arguments":
            return element
    return None


def find_arguments_collection(sampler: ET.Element) -> Optional[ET.Element]:
    parent = find_arguments_parent(sampler)
    if parent is None:
        return None
    for child in list(parent):
        if local_name(child.tag) == "collectionProp" and child.attrib.get("name") == "Arguments.arguments":
            return child
    return None


def get_argument_elements(sampler: ET.Element) -> List[ET.Element]:
    collection = find_arguments_collection(sampler)
    if collection is None:
        return []
    return [child for child in list(collection) if local_name(child.tag) == "elementProp"]


def extract_request_model(sampler: ET.Element) -> Tuple[str, Dict[str, Any]]:
    post_body_raw = find_prop_text(sampler, "HTTPSampler.postBodyRaw").lower() == "true"
    argument_nodes = get_argument_elements(sampler)
    if post_body_raw:
        for node in argument_nodes:
            name = find_prop_text(node, "Argument.name")
            value = find_prop_text(node, "Argument.value")
            if not name.strip():
                return "json", json.loads(value or "{}")
        raise ValueError("Raw body sampler has no unnamed HTTPArgument payload")

    payload: Dict[str, Any] = {}
    for node in argument_nodes:
        name = find_prop_text(node, "Argument.name")
        if not name:
            continue
        payload[name] = find_prop_text(node, "Argument.value")
    if not payload:
        raise ValueError("Sampler does not contain editable HTTP arguments")
    return "params", payload


def set_argument_value(node: ET.Element, value: Any) -> None:
    target = find_prop_node(node, "Argument.value")
    if target is not None:
        target.text = "" if value is None else str(value)


def set_argument_name(node: ET.Element, value: str) -> None:
    target = find_prop_node(node, "Argument.name")
    if target is not None:
        target.text = value


def apply_payload_to_sampler(sampler: ET.Element, mode: str, payload: Dict[str, Any]) -> None:
    argument_nodes = get_argument_elements(sampler)
    if mode == "json":
        for node in argument_nodes:
            name = find_prop_text(node, "Argument.name")
            if not name.strip():
                set_argument_value(node, json.dumps(payload, ensure_ascii=False))
                return
        raise ValueError("Unable to find raw body argument to update")

    existing = {find_prop_text(node, "Argument.name"): node for node in argument_nodes}
    collection = find_arguments_collection(sampler)
    if collection is None:
        raise ValueError("Sampler is missing HTTP arguments container")

    for field_name in list(existing):
        if field_name not in payload:
            collection.remove(existing[field_name])

    template_node = argument_nodes[0] if argument_nodes else None
    for field_name, field_value in payload.items():
        if field_name in existing:
            set_argument_value(existing[field_name], field_value)
            continue
        if template_node is None:
            raise ValueError("Cannot add a new HTTP argument without a template element")
        new_node = copy.deepcopy(template_node)
        set_argument_name(new_node, field_name)
        set_argument_value(new_node, field_value)
        collection.append(new_node)


def mutate_missing(payload: Dict[str, Any], field_name: str) -> Dict[str, Any]:
    data = dict(payload)
    data.pop(field_name, None)
    return data


def mutate_set(payload: Dict[str, Any], field_name: str, value: Any) -> Dict[str, Any]:
    data = dict(payload)
    data[field_name] = value
    return data


def mismatch_value(field_type: str) -> Any:
    mapping = {
        "string": 12345,
        "integer": "not-an-integer",
        "int": "not-an-integer",
        "number": "not-a-number",
        "float": "not-a-number",
        "boolean": "not-a-boolean",
        "array": "not-an-array",
        "object": "not-an-object",
    }
    return mapping.get(field_type.lower(), "__TYPE_MISMATCH__")


def boundary_variants(base_payload: Dict[str, Any], field_name: str, boundary: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    cases: List[Tuple[str, Dict[str, Any]]] = []
    if "min" in boundary:
        try:
            cases.append((f"{field_name} below min", mutate_set(base_payload, field_name, boundary["min"] - 1)))
        except TypeError:
            pass
    if "max" in boundary:
        try:
            cases.append((f"{field_name} above max", mutate_set(base_payload, field_name, boundary["max"] + 1)))
        except TypeError:
            pass
    if "min_length" in boundary:
        target = max(int(boundary["min_length"]) - 1, 0)
        cases.append((f"{field_name} shorter than min length", mutate_set(base_payload, field_name, "x" * target)))
    if "max_length" in boundary:
        target = int(boundary["max_length"]) + 1
        cases.append((f"{field_name} longer than max length", mutate_set(base_payload, field_name, "x" * target)))
    return cases


def build_case_plan_variants(base_payload: Dict[str, Any], case_plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    variants: List[Dict[str, Any]] = []
    for case in case_plan:
        case_name = case.get("name")
        if not case_name:
            raise ValueError("Each case_plan item must include a name")
        payload = dict(base_payload)
        for field_name in case.get("remove_fields", []):
            payload.pop(field_name, None)
        for field_name, field_value in (case.get("set_fields") or {}).items():
            payload[field_name] = field_value
        variants.append({"name": str(case_name), "payload": payload})
    return variants


def generate_variants(base_payload: Dict[str, Any], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    case_plan = spec.get("case_plan")
    if case_plan:
        return build_case_plan_variants(base_payload, case_plan)

    variants: List[Dict[str, Any]] = []
    required_fields = spec.get("required_fields", [])
    optional_fields = spec.get("optional_fields", [])
    hidden_fields = spec.get("hidden_fields", [])
    field_types = spec.get("field_types", {})
    boundary_values = spec.get("boundary_values", {})
    extra_fields = spec.get("extra_fields") or {"__unexpectedField": "unexpected"}

    for field_name in optional_fields:
        variants.append({"name": f"optional missing {field_name}", "payload": mutate_missing(base_payload, field_name)})

    for field_name in required_fields:
        variants.append({"name": f"required missing {field_name}", "payload": mutate_missing(base_payload, field_name)})

    for field_name in required_fields + optional_fields:
        variants.append({"name": f"{field_name} is null", "payload": mutate_set(base_payload, field_name, None)})
        variants.append({"name": f"{field_name} is empty string", "payload": mutate_set(base_payload, field_name, "")})
        if field_name in required_fields:
            variants.append({"name": f"{field_name} is whitespace", "payload": mutate_set(base_payload, field_name, " ")})

    for field_name, field_type in field_types.items():
        if field_name in base_payload:
            variants.append({"name": f"{field_name} type mismatch", "payload": mutate_set(base_payload, field_name, mismatch_value(str(field_type)))})

    for field_name, boundary in boundary_values.items():
        if field_name in base_payload and isinstance(boundary, dict):
            for case_name, payload in boundary_variants(base_payload, field_name, boundary):
                variants.append({"name": case_name, "payload": payload})

    for field_name in hidden_fields:
        variants.append({"name": f"hidden field override {field_name}", "payload": mutate_set(base_payload, field_name, "__AUTO_HIDDEN__")})

    extra_payload = dict(base_payload)
    extra_payload.update(extra_fields)
    variants.append({"name": "extra undefined field", "payload": extra_payload})

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for variant in variants:
        key = (variant["name"], json.dumps(variant["payload"], ensure_ascii=False, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return deduped


def remove_named_http_samplers(
    thread_hash: ET.Element,
    names_to_remove: List[str],
    exclude_elements: Optional[List[ET.Element]] = None,
) -> int:
    excluded_ids = {id(element) for element in (exclude_elements or [])}
    positions: List[int] = []
    target_names = set(names_to_remove)
    for index, element, _ in iter_pairs(thread_hash):
        if id(element) in excluded_ids:
            continue
        if classify(element) != "http_sampler":
            continue
        if attr_name(element) in target_names:
            positions.append(index)

    for index in reversed(positions):
        del thread_hash[index : index + 2]
    return len(positions)


def locate_jdbc_samplers(thread_hash: ET.Element) -> List[ET.Element]:
    samplers: List[ET.Element] = []

    def walk(hash_tree: ET.Element) -> None:
        for _, element, subtree in iter_pairs(hash_tree):
            if classify(element) == "jdbc_request":
                samplers.append(element)
            walk(subtree)

    walk(thread_hash)
    return samplers


def apply_jdbc_cleanup(thread_hash: ET.Element, spec: Dict[str, Any]) -> List[Dict[str, str]]:
    jdbc_spec = spec.get("jdbc_cleanup") or {}
    if not jdbc_spec.get("allow_modify"):
        return []

    changes: List[Dict[str, str]] = []
    sampler_name = jdbc_spec.get("sampler_name")
    full_sql = jdbc_spec.get("full_sql")
    where_clause = jdbc_spec.get("where_clause")

    for sampler in locate_jdbc_samplers(thread_hash):
        if sampler_name and attr_name(sampler) != sampler_name:
            continue
        query_node = find_prop_node(sampler, "query")
        if query_node is None:
            continue
        original = query_node.text or ""
        updated = original
        if full_sql and original.strip() != full_sql.strip():
            updated = full_sql
        elif where_clause and " where " not in original.lower():
            updated = f"{original.rstrip().rstrip(';')} {where_clause}".strip()
        if updated != original:
            query_node.text = updated
            changes.append(
                {
                    "sampler": attr_name(sampler),
                    "original_sql": original,
                    "updated_sql": updated,
                }
            )
    return changes


def build_report(output_path: Path, thread_group: str, base_sampler: str, variants: List[Dict[str, Any]], jdbc_changes: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "output": str(output_path),
        "thread_group": thread_group,
        "base_sampler": base_sampler,
        "added_case_count": len(variants),
        "added_cases": [variant["name"] for variant in variants],
        "jdbc_changes": jdbc_changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch a JMeter .jmx file conservatively.")
    parser.add_argument("--input", required=True, help="Path to the source .jmx file.")
    parser.add_argument("--output", required=True, help="Path to the patched .jmx file.")
    parser.add_argument("--spec", required=True, help="Path to the JSON patch spec.")
    parser.add_argument("--thread-group", help="Optional thread group override.")
    parser.add_argument("--base-sampler", help="Optional base sampler override.")
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    thread_group_name = args.thread_group or spec.get("thread_group")
    if not thread_group_name:
        raise ValueError("thread_group is required in the spec or CLI")

    tree = ET.parse(args.input)
    root = tree.getroot()
    _, thread_hash = find_thread_group(root, thread_group_name)
    requested_base_sampler = args.base_sampler or spec.get("base_sampler")
    renamed_base_sampler = spec.get("rename_base_sampler_to")
    try:
        _, base_sampler, base_hash_tree = find_base_sampler(thread_hash, requested_base_sampler)
    except ValueError:
        if renamed_base_sampler and requested_base_sampler != renamed_base_sampler:
            _, base_sampler, base_hash_tree = find_base_sampler(thread_hash, renamed_base_sampler)
        else:
            raise

    mode, base_payload = extract_request_model(base_sampler)
    if renamed_base_sampler:
        base_sampler.attrib["testname"] = renamed_base_sampler
    variants = generate_variants(base_payload, spec)

    names_to_remove = list(spec.get("remove_samplers", []))
    names_to_remove.extend(variant["name"] for variant in variants)
    remove_named_http_samplers(thread_hash, names_to_remove, exclude_elements=[base_sampler])

    base_index = find_pair_index_by_element(thread_hash, base_sampler)
    insertion_index = base_index + 2
    for variant in variants:
        sampler_clone = copy.deepcopy(base_sampler)
        child_clone = copy.deepcopy(base_hash_tree)
        sampler_clone.attrib["testname"] = variant["name"]
        apply_payload_to_sampler(sampler_clone, mode, variant["payload"])
        thread_hash.insert(insertion_index, sampler_clone)
        thread_hash.insert(insertion_index + 1, child_clone)
        insertion_index += 2

    jdbc_changes = apply_jdbc_cleanup(thread_hash, spec)
    if hasattr(ET, "indent"):
        ET.indent(tree, space="  ")
    else:
        indent_tree(root)
    output_path = Path(args.output)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    report = build_report(output_path, thread_group_name, attr_name(base_sampler), variants, jdbc_changes)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
