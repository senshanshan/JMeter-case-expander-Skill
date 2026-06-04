#!/usr/bin/env python3
"""Inspect a JMeter .jmx file and summarize one or more thread groups."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
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
    if "headermanager" in text:
        return "header_manager"
    if "responseassertion" in text:
        return "assertion"
    if any(token in text for token in ("jsonpostprocessor", "regexextractor", "jsonextractor", "boundaryextractor")):
        return "extractor"
    if any(token in text for token in ("jsr223", "beanshell", "bshsampler")):
        return "script"
    if "jdbc" in text:
        return "jdbc_request"
    return "other"


def http_summary(element: ET.Element, path: List[str]) -> Dict[str, Any]:
    return {
        "name": attr_name(element),
        "path": " > ".join(path + [attr_name(element)]),
        "method": find_prop(element, "HTTPSampler.method"),
        "protocol": find_prop(element, "HTTPSampler.protocol"),
        "domain": find_prop(element, "HTTPSampler.domain"),
        "port": find_prop(element, "HTTPSampler.port"),
        "path_value": find_prop(element, "HTTPSampler.path"),
        "content_encoding": find_prop(element, "HTTPSampler.contentEncoding"),
        "post_body_raw": find_prop(element, "HTTPSampler.postBodyRaw"),
        "enabled": element.attrib.get("enabled", "true"),
    }


def generic_summary(element: ET.Element, path: List[str], sql: bool = False) -> Dict[str, Any]:
    item = {
        "name": attr_name(element),
        "path": " > ".join(path + [attr_name(element)]),
        "enabled": element.attrib.get("enabled", "true"),
    }
    if sql:
        item["query"] = find_prop(element, "query")
        item["query_type"] = find_prop(element, "queryType")
    return item


def summarize_thread_group(thread_group: ET.Element, subtree: ET.Element, parent_path: List[str]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "name": attr_name(thread_group),
        "path": " > ".join(parent_path + [attr_name(thread_group)]),
        "enabled": thread_group.attrib.get("enabled", "true"),
        "http_samplers": [],
        "headers": [],
        "assertions": [],
        "extractors": [],
        "scripts": [],
        "jdbc_requests": [],
    }

    def walk(hash_tree: ET.Element, path: List[str]) -> None:
        for element, child_tree in iter_pairs(hash_tree):
            kind = classify(element)
            name = attr_name(element)
            next_path = path + [name]
            if kind == "http_sampler":
                summary["http_samplers"].append(http_summary(element, path))
            elif kind == "header_manager":
                summary["headers"].append(generic_summary(element, path))
            elif kind == "assertion":
                summary["assertions"].append(generic_summary(element, path))
            elif kind == "extractor":
                summary["extractors"].append(generic_summary(element, path))
            elif kind == "script":
                summary["scripts"].append(generic_summary(element, path))
            elif kind == "jdbc_request":
                summary["jdbc_requests"].append(generic_summary(element, path, sql=True))
            walk(child_tree, next_path)

    walk(subtree, [attr_name(thread_group)])
    if summary["http_samplers"]:
        summary["suggested_base_sampler"] = summary["http_samplers"][0]["name"]
    return summary


def find_thread_groups(root: ET.Element) -> List[Tuple[ET.Element, ET.Element, List[str]]]:
    thread_groups: List[Tuple[ET.Element, ET.Element, List[str]]] = []

    def walk(hash_tree: ET.Element, path: List[str]) -> None:
        for element, child_tree in iter_pairs(hash_tree):
            name = attr_name(element)
            kind = classify(element)
            next_path = path + [name]
            if kind == "thread_group":
                thread_groups.append((element, child_tree, path))
            walk(child_tree, next_path)

    for candidate in root.iter():
        if is_hash_tree(candidate):
            walk(candidate, [])
            break
    return thread_groups


def format_text(report: Dict[str, Any]) -> str:
    lines: List[str] = [f"Input: {report['input']}"]
    for thread_group in report["thread_groups"]:
        lines.append(f"Thread group: {thread_group['name']}")
        lines.append(f"  Path: {thread_group['path']}")
        lines.append(f"  HTTP samplers: {len(thread_group['http_samplers'])}")
        for sampler in thread_group["http_samplers"]:
            lines.append(
                f"    - {sampler['name']} [{sampler['method']} {sampler['path_value']}] encoding={sampler['content_encoding'] or '(empty)'}"
            )
        lines.append(f"  JDBC requests: {len(thread_group['jdbc_requests'])}")
        for jdbc in thread_group["jdbc_requests"]:
            query = (jdbc.get("query") or "").replace("\n", " ").strip()
            lines.append(f"    - {jdbc['name']}: {query[:120]}")
        lines.append(f"  Assertions: {len(thread_group['assertions'])}")
        lines.append(f"  Extractors: {len(thread_group['extractors'])}")
        lines.append(f"  Scripts: {len(thread_group['scripts'])}")
        if thread_group.get("suggested_base_sampler"):
            lines.append(f"  Suggested base sampler: {thread_group['suggested_base_sampler']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a JMeter .jmx file.")
    parser.add_argument("--input", required=True, help="Path to the .jmx file.")
    parser.add_argument("--thread-group", help="Optional exact thread group name to filter.")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--output", help="Optional output file path.")
    args = parser.parse_args()

    input_path = Path(args.input)
    tree = ET.parse(input_path)
    root = tree.getroot()

    groups = []
    for thread_group, subtree, parent_path in find_thread_groups(root):
        if args.thread_group and attr_name(thread_group) != args.thread_group:
            continue
        groups.append(summarize_thread_group(thread_group, subtree, parent_path))

    if args.thread_group and not groups:
        raise SystemExit(f"Thread group not found: {args.thread_group}")

    report = {
        "input": str(input_path),
        "thread_group_count": len(groups),
        "thread_groups": groups,
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
