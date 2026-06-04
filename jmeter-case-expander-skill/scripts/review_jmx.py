#!/usr/bin/env python3
"""Review a JMeter .jmx file for common safety and quality issues."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_hash_tree(element: Optional[ET.Element]) -> bool:
    return element is not None and local_name(element.tag) == "hashTree"


def iter_pairs(hash_tree: ET.Element) -> Iterable[Tuple[ET.Element, ET.Element]]:
    children = list(hash_tree)
    index = 0
    while index < len(children):
        element = children[index]
        subtree = children[index + 1] if index + 1 < len(children) and is_hash_tree(children[index + 1]) else ET.Element("hashTree")
        yield element, subtree
        index += 2


def attr_name(element: ET.Element) -> str:
    return element.attrib.get("testname") or element.attrib.get("name") or local_name(element.tag)


def find_prop(element: ET.Element, prop_name: str) -> str:
    for child in element.iter():
        if child.attrib.get("name") == prop_name and child.text is not None:
            return child.text
    return ""


def classify(element: ET.Element) -> str:
    tag = local_name(element.tag)
    testclass = element.attrib.get("testclass", "")
    text = f"{tag} {testclass}".lower()
    if "threadgroup" in text:
        return "thread_group"
    if "httpsamplerproxy" in text:
        return "http_sampler"
    if "responseassertion" in text:
        return "assertion"
    if "jdbc" in text:
        return "jdbc_request"
    return "other"


def find_thread_group(root: ET.Element, target_name: str) -> Tuple[ET.Element, ET.Element]:
    def walk(hash_tree: ET.Element) -> Optional[Tuple[ET.Element, ET.Element]]:
        for element, subtree in iter_pairs(hash_tree):
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


def get_argument_nodes(sampler: ET.Element) -> List[ET.Element]:
    for element in sampler.iter():
        if element.attrib.get("name") == "HTTPsampler.Arguments":
            return [child for child in list(element) if local_name(child.tag) == "elementProp"]
    return []


def review_http_sampler(sampler: ET.Element, child_tree: ET.Element, findings: List[Dict[str, str]]) -> Dict[str, Any]:
    sampler_name = attr_name(sampler)
    method = find_prop(sampler, "HTTPSampler.method")
    path_value = find_prop(sampler, "HTTPSampler.path")
    content_encoding = find_prop(sampler, "HTTPSampler.contentEncoding")
    post_body_raw = find_prop(sampler, "HTTPSampler.postBodyRaw").lower() == "true"
    assertion_count = sum(1 for child, _ in iter_pairs(child_tree) if classify(child) == "assertion")

    if not sampler_name.strip():
        findings.append({"severity": "high", "item": "blank sampler name", "location": "(unnamed sampler)"})
    if not path_value.strip():
        findings.append({"severity": "high", "item": "missing request path", "location": sampler_name})
    if assertion_count == 0:
        findings.append({"severity": "medium", "item": "missing response assertion", "location": sampler_name})

    if post_body_raw:
        for node in get_argument_nodes(sampler):
            argument_name = find_prop(node, "Argument.name")
            if argument_name.strip():
                continue
            body = find_prop(node, "Argument.value")
            try:
                json.loads(body or "{}")
            except json.JSONDecodeError as exc:
                findings.append(
                    {
                        "severity": "high",
                        "item": f"invalid JSON request body: {exc.msg}",
                        "location": sampler_name,
                    }
                )
            break

    return {
        "name": sampler_name,
        "method": method,
        "path": path_value,
        "content_encoding": content_encoding,
        "assertion_count": assertion_count,
    }


def review_jdbc_sampler(sampler: ET.Element, findings: List[Dict[str, str]]) -> Dict[str, Any]:
    sampler_name = attr_name(sampler)
    sql = (find_prop(sampler, "query") or "").strip()
    lower_sql = sql.lower()

    if lower_sql.startswith("truncate"):
        findings.append({"severity": "high", "item": "TRUNCATE cleanup is high risk", "location": sampler_name})
    if lower_sql.startswith(("delete", "update")) and " where " not in lower_sql:
        findings.append({"severity": "high", "item": "cleanup SQL has no WHERE clause", "location": sampler_name})
    if "where 1=1" in lower_sql or "or 1=1" in lower_sql:
        findings.append({"severity": "high", "item": "cleanup SQL contains always-true predicate", "location": sampler_name})

    return {"name": sampler_name, "query": sql}


def review_thread_group(thread_hash: ET.Element) -> Dict[str, Any]:
    findings: List[Dict[str, str]] = []
    http_samplers: List[Dict[str, Any]] = []
    jdbc_samplers: List[Dict[str, Any]] = []

    for element, child_tree in iter_pairs(thread_hash):
        kind = classify(element)
        if kind == "http_sampler":
            http_samplers.append(review_http_sampler(element, child_tree, findings))
        elif kind == "jdbc_request":
            jdbc_samplers.append(review_jdbc_sampler(element, findings))

    name_counts = Counter(item["name"] for item in http_samplers if item["name"])
    for name, count in name_counts.items():
        if count > 1:
            findings.append({"severity": "medium", "item": f"duplicate sampler name appears {count} times", "location": name})

    encodings = [item["content_encoding"] for item in http_samplers if item["content_encoding"]]
    distinct_encodings = sorted(set(encodings))
    if len(distinct_encodings) > 1:
        findings.append(
            {
                "severity": "medium",
                "item": f"inconsistent content encoding: {', '.join(distinct_encodings)}",
                "location": "thread group",
            }
        )
    if encodings and any(not item["content_encoding"] for item in http_samplers):
        findings.append(
            {
                "severity": "medium",
                "item": "some samplers have empty content encoding while peers are explicit",
                "location": "thread group",
            }
        )

    return {"findings": findings, "http_samplers": http_samplers, "jdbc_samplers": jdbc_samplers}


def format_text(report: Dict[str, Any]) -> str:
    lines = [f"Input: {report['input']}", f"Thread group: {report['thread_group']}"]
    lines.append("Findings:")
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"  - [{finding['severity']}] {finding['location']}: {finding['item']}")
    else:
        lines.append("  - none")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Review a JMeter .jmx file.")
    parser.add_argument("--input", required=True, help="Path to the .jmx file.")
    parser.add_argument("--thread-group", required=True, help="Exact target thread group name.")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--output", help="Optional output file path.")
    args = parser.parse_args()

    tree = ET.parse(args.input)
    root = tree.getroot()
    _, thread_hash = find_thread_group(root, args.thread_group)
    result = review_thread_group(thread_hash)

    report = {
        "input": str(Path(args.input)),
        "thread_group": args.thread_group,
        "findings": result["findings"],
        "http_sampler_count": len(result["http_samplers"]),
        "jdbc_sampler_count": len(result["jdbc_samplers"]),
        "http_samplers": result["http_samplers"],
        "jdbc_samplers": result["jdbc_samplers"],
    }

    output = json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else format_text(report)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
