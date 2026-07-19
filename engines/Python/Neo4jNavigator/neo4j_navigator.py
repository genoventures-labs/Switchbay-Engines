#!/usr/bin/env python3
"""Neo4j Navigator — read-only graph routing for RAG and agent workflows."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

DEFAULT_SEARCH_PROPERTIES = "name,title,description,summary,keywords,tags,text,content"
DEFAULT_IDENTITY_PROPERTIES = "id,key,slug,name,title"
DEFAULT_LOCATOR_PROPERTIES = "path,file,url,source,source_url,chunk_id,document_id,collection,index"


class Neo4jError(RuntimeError):
    """Safe, user-facing Neo4j request failure."""


def _noneish(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in {"", "none", "null"} else text


def _parse_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    text = _noneish(value)
    if text is None:
        return default
    try:
        return max(minimum, min(int(float(text)), maximum))
    except (TypeError, ValueError):
        return default


def _csv(value: Any, default: str = "") -> list[str]:
    raw = _noneish(value) or default
    result = []
    for item in raw.split(","):
        item = item.strip()
        if item and item not in result:
            result.append(item)
    return result[:50]


def _safe_label(value: Any) -> str:
    label = _noneish(value) or ""
    if label and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
        raise ValueError("label must contain only letters, numbers, and underscores")
    return label


def _query_text(value: Any, name: str = "query") -> str:
    text = _noneish(value)
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text[:1000]


@dataclass(frozen=True)
class Config:
    base_url: str
    database: str
    username: str
    password: str | None
    auth_mode: str
    timeout: int


def _config() -> Config:
    base_url = (os.environ.get("NEO4J_HTTP_URL") or "http://127.0.0.1:7474").rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("NEO4J_HTTP_URL must be an absolute http:// or https:// URL")
    database = os.environ.get("NEO4J_DATABASE", "neo4j").strip() or "neo4j"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", database):
        raise ValueError("NEO4J_DATABASE contains unsupported characters")
    auth_mode = os.environ.get("NEO4J_AUTH_MODE", "basic").strip().lower()
    if auth_mode not in {"basic", "none"}:
        raise ValueError("NEO4J_AUTH_MODE must be 'basic' or 'none'")
    return Config(
        base_url=base_url,
        database=database,
        username=os.environ.get("NEO4J_USERNAME", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD"),
        auth_mode=auth_mode,
        timeout=_parse_int(os.environ.get("NEO4J_TIMEOUT"), 15, 2, 120),
    )


def _request(statement: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    config = _config()
    if config.auth_mode == "basic" and not config.password:
        raise Neo4jError("NEO4J_PASSWORD is required when NEO4J_AUTH_MODE=basic")
    endpoint = f"{config.base_url}/db/{quote(config.database, safe='')}/query/v2"
    payload = json.dumps({
        "statement": " ".join(statement.split()),
        "parameters": parameters or {},
    }).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.auth_mode == "basic":
        token = base64.b64encode(f"{config.username}:{config.password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    request = Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=config.timeout) as response:
            raw = response.read(10_000_001)
            if len(raw) > 10_000_000:
                raise Neo4jError("Neo4j response exceeded 10 MB")
    except HTTPError as exc:
        if exc.code == 401:
            raise Neo4jError("Neo4j authentication failed") from exc
        detail = ""
        try:
            detail = exc.read(2000).decode("utf-8", errors="replace")
        except OSError:
            pass
        raise Neo4jError(f"Neo4j HTTP {exc.code}: {detail or exc.reason}") from exc
    except URLError as exc:
        raise Neo4jError(f"Neo4j connection failed: {exc.reason}") from exc
    try:
        result = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise Neo4jError("Neo4j returned invalid JSON") from exc
    errors = result.get("errors") or ([] if not result.get("error") else [result["error"]])
    if errors:
        first = errors[0]
        if isinstance(first, dict):
            raise Neo4jError(f"Neo4j query failed: {first.get('message') or first.get('code') or 'unknown error'}")
        raise Neo4jError(f"Neo4j query failed: {first}")
    return result


def _run_query(statement: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _request(statement, parameters)
    data = result.get("data") or {}
    fields = data.get("fields") or []
    values = data.get("values") or []
    rows = [dict(zip(fields, row)) for row in values]
    return {"rows": _compact(rows), "notifications": _compact(result.get("notifications") or [])}


def _compact(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[depth limited]"
    if isinstance(value, str):
        return value if len(value) <= 2000 else value[:2000] + "…"
    if isinstance(value, list):
        return [_compact(item, depth + 1) for item in value[:200]]
    if isinstance(value, dict):
        return {str(key): _compact(item, depth + 1) for key, item in list(value.items())[:100]}
    return value


def _common_parameters(search_properties: Any = None, identity_properties: Any = None,
                       locator_properties: Any = None, preview_chars: Any = 300) -> dict[str, Any]:
    return {
        "search_properties": _csv(search_properties, DEFAULT_SEARCH_PROPERTIES),
        "identity_properties": _csv(identity_properties, DEFAULT_IDENTITY_PROPERTIES),
        "locator_properties": _csv(locator_properties, DEFAULT_LOCATOR_PROPERTIES),
        "preview_chars": _parse_int(preview_chars, 300, 40, 2000),
    }


def _node_projection(variable: str) -> str:
    return (
        "{element_id: elementId(" + variable + "), labels: labels(" + variable + "), "
        "identity: [k IN $identity_properties WHERE " + variable + "[k] IS NOT NULL | "
        "{property: k, value: left(toString(" + variable + "[k]), $preview_chars)}], "
        "locators: [k IN $locator_properties WHERE " + variable + "[k] IS NOT NULL | "
        "{property: k, value: left(toString(" + variable + "[k]), $preview_chars)}]}"
    )


def status() -> dict[str, Any]:
    try:
        config = _config()
        if config.auth_mode == "basic" and not config.password:
            return {"ok": False, "engine": "neo4j-navigator", "configured": False,
                    "base_url": config.base_url, "database": config.database,
                    "error": "NEO4J_PASSWORD is not set"}
        result = _run_query("RETURN 1 AS ready")
        return {"ok": True, "engine": "neo4j-navigator", "configured": True,
                "connected": True, "base_url": config.base_url, "database": config.database,
                "auth_mode": config.auth_mode, "query_api": "v2", "result": result["rows"]}
    except (ValueError, Neo4jError) as exc:
        try:
            config = _config()
            target = {"base_url": config.base_url, "database": config.database}
        except ValueError:
            target = {}
        return {"ok": False, "engine": "neo4j-navigator", "connected": False,
                **target, "error": str(exc)}


def graph_overview(limit: Any = 25) -> dict[str, Any]:
    size = _parse_int(limit, 25, 1, 100)
    queries = {
        "labels": "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY count DESC LIMIT $limit",
        "relationships": "MATCH ()-[r]->() RETURN type(r) AS relationship, count(*) AS count ORDER BY count DESC LIMIT $limit",
        "properties": "MATCH (n) UNWIND keys(n) AS property RETURN property, count(*) AS occurrences ORDER BY occurrences DESC LIMIT $limit",
    }
    output: dict[str, Any] = {"ok": True, "limit": size, "warnings": []}
    for name, statement in queries.items():
        try:
            output[name] = _run_query(statement, {"limit": size})["rows"]
        except Neo4jError as exc:
            output[name] = []
            output["warnings"].append(f"{name}: {exc}")
    try:
        output["indexes"] = _run_query(
            "SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties, state "
            "RETURN name, type, entityType, labelsOrTypes, properties, state LIMIT $limit",
            {"limit": size},
        )["rows"]
    except Neo4jError as exc:
        output["indexes"] = []
        output["warnings"].append(f"indexes: {exc}")
    return output


def search_nodes(query: Any, label: Any = None, search_properties: Any = None,
                 identity_properties: Any = None, locator_properties: Any = None,
                 limit: Any = 12, preview_chars: Any = 300) -> dict[str, Any]:
    text = _query_text(query)
    params = _common_parameters(search_properties, identity_properties, locator_properties, preview_chars)
    params.update({"query": text.lower(), "label": _safe_label(label), "limit": _parse_int(limit, 12, 1, 50)})
    projection = _node_projection("n")
    statement = (
        "MATCH (n) WHERE ($label = '' OR $label IN labels(n)) "
        "AND any(k IN $search_properties WHERE n[k] IS NOT NULL "
        "AND toLower(toString(n[k])) CONTAINS $query) "
        f"RETURN {projection} AS node LIMIT $limit"
    )
    result = _run_query(statement, params)
    return {"ok": True, "query": text, "label": params["label"] or None,
            "match_count": len(result["rows"]), "matches": result["rows"],
            "notifications": result["notifications"]}


def fulltext_search(index_name: Any, query: Any, identity_properties: Any = None,
                    locator_properties: Any = None, limit: Any = 12,
                    preview_chars: Any = 300) -> dict[str, Any]:
    name = _query_text(index_name, "index_name")
    text = _query_text(query)
    params = _common_parameters(None, identity_properties, locator_properties, preview_chars)
    params.update({"index_name": name, "query": text, "limit": _parse_int(limit, 12, 1, 50)})
    projection = _node_projection("node")
    statement = (
        "CALL db.index.fulltext.queryNodes($index_name, $query, {limit: $limit}) "
        f"YIELD node, score RETURN score, {projection} AS node ORDER BY score DESC LIMIT $limit"
    )
    result = _run_query(statement, params)
    return {"ok": True, "index_name": name, "query": text,
            "match_count": len(result["rows"]), "matches": result["rows"],
            "notifications": result["notifications"]}


def node_neighborhood(anchor_property: Any, anchor_value: Any, label: Any = None,
                      depth: Any = 2, relationship_types: Any = None,
                      identity_properties: Any = None, locator_properties: Any = None,
                      limit: Any = 40, preview_chars: Any = 300) -> dict[str, Any]:
    property_name = _query_text(anchor_property, "anchor_property")
    value = _query_text(anchor_value, "anchor_value")
    hops = _parse_int(depth, 2, 1, 4)
    params = _common_parameters(None, identity_properties, locator_properties, preview_chars)
    params.update({"anchor_property": property_name, "anchor_value": value,
                   "label": _safe_label(label), "relationship_types": _csv(relationship_types),
                   "limit": _parse_int(limit, 40, 1, 100)})
    nodes = f"[x IN nodes(p) | {_node_projection('x')}]"
    rels = "[r IN relationships(p) | {type: type(r), properties: properties(r)}]"
    statement = (
        "MATCH (center) WHERE ($label = '' OR $label IN labels(center)) "
        "AND toString(center[$anchor_property]) = $anchor_value "
        f"MATCH p=(center)-[*1..{hops}]-(other) "
        "WHERE size($relationship_types) = 0 OR all(r IN relationships(p) WHERE type(r) IN $relationship_types) "
        f"RETURN length(p) AS hops, {nodes} AS nodes, {rels} AS relationships "
        "ORDER BY hops LIMIT $limit"
    )
    result = _run_query(statement, params)
    return {"ok": True, "anchor": {"property": property_name, "value": value,
            "label": params["label"] or None}, "depth": hops,
            "branch_count": len(result["rows"]), "branches": result["rows"],
            "notifications": result["notifications"]}


def explore_branches(query: Any, label: Any = None, depth: Any = 3,
                     search_properties: Any = None, identity_properties: Any = None,
                     locator_properties: Any = None, relationship_types: Any = None,
                     seed_limit: Any = 5, limit: Any = 50, preview_chars: Any = 300) -> dict[str, Any]:
    text = _query_text(query)
    hops = _parse_int(depth, 3, 1, 4)
    params = _common_parameters(search_properties, identity_properties, locator_properties, preview_chars)
    params.update({"query": text.lower(), "label": _safe_label(label),
                   "relationship_types": _csv(relationship_types),
                   "seed_limit": _parse_int(seed_limit, 5, 1, 10),
                   "limit": _parse_int(limit, 50, 1, 100)})
    nodes = f"[x IN nodes(p) | {_node_projection('x')}]"
    rels = "[r IN relationships(p) | {type: type(r), properties: properties(r)}]"
    statement = (
        "MATCH (seed) WHERE ($label = '' OR $label IN labels(seed)) "
        "AND any(k IN $search_properties WHERE seed[k] IS NOT NULL "
        "AND toLower(toString(seed[k])) CONTAINS $query) "
        "WITH seed LIMIT $seed_limit "
        f"MATCH p=(seed)-[*1..{hops}]-(target) "
        "WHERE size($relationship_types) = 0 OR all(r IN relationships(p) WHERE type(r) IN $relationship_types) "
        f"RETURN {_node_projection('seed')} AS seed, length(p) AS hops, "
        f"{nodes} AS nodes, {rels} AS relationships ORDER BY hops LIMIT $limit"
    )
    result = _run_query(statement, params)
    return {"ok": True, "query": text, "depth": hops,
            "branch_count": len(result["rows"]), "branches": result["rows"],
            "notifications": result["notifications"]}


def route_sources(query: Any, label: Any = None, depth: Any = 3,
                  search_properties: Any = None, identity_properties: Any = None,
                  locator_properties: Any = None, relationship_types: Any = None,
                  seed_limit: Any = 5, limit: Any = 40, preview_chars: Any = 300) -> dict[str, Any]:
    text = _query_text(query)
    hops = _parse_int(depth, 3, 0, 4)
    params = _common_parameters(search_properties, identity_properties, locator_properties, preview_chars)
    if not params["locator_properties"]:
        raise ValueError("locator_properties must contain at least one property")
    params.update({"query": text.lower(), "label": _safe_label(label),
                   "relationship_types": _csv(relationship_types),
                   "seed_limit": _parse_int(seed_limit, 5, 1, 10),
                   "limit": _parse_int(limit, 40, 1, 100)})
    statement = (
        "MATCH (seed) WHERE ($label = '' OR $label IN labels(seed)) "
        "AND any(k IN $search_properties WHERE seed[k] IS NOT NULL "
        "AND toLower(toString(seed[k])) CONTAINS $query) "
        "WITH seed LIMIT $seed_limit "
        f"MATCH p=(seed)-[*0..{hops}]-(target) "
        "WHERE any(k IN $locator_properties WHERE target[k] IS NOT NULL) "
        "AND (size($relationship_types) = 0 OR all(r IN relationships(p) WHERE type(r) IN $relationship_types)) "
        f"RETURN {_node_projection('seed')} AS seed, length(p) AS hops, "
        "[r IN relationships(p) | type(r)] AS branch, "
        f"{_node_projection('target')} AS target ORDER BY hops LIMIT $limit"
    )
    result = _run_query(statement, params)
    return {"ok": True, "query": text, "depth": hops,
            "route_count": len(result["rows"]), "routes": result["rows"],
            "next_step": "Use each target locator with RAG Navigator, File Helper, Web Ingest, or the named source system.",
            "notifications": result["notifications"]}


def find_paths(from_query: Any, to_query: Any, depth: Any = 4,
               search_properties: Any = None, identity_properties: Any = None,
               locator_properties: Any = None, relationship_types: Any = None,
               limit: Any = 10, preview_chars: Any = 300) -> dict[str, Any]:
    start = _query_text(from_query, "from_query")
    end = _query_text(to_query, "to_query")
    hops = _parse_int(depth, 4, 1, 6)
    params = _common_parameters(search_properties, identity_properties, locator_properties, preview_chars)
    params.update({"from_query": start.lower(), "to_query": end.lower(),
                   "relationship_types": _csv(relationship_types),
                   "limit": _parse_int(limit, 10, 1, 25)})
    nodes = f"[x IN nodes(p) | {_node_projection('x')}]"
    rels = "[r IN relationships(p) | {type: type(r), properties: properties(r)}]"
    statement = (
        "MATCH (a) WHERE any(k IN $search_properties WHERE a[k] IS NOT NULL "
        "AND toLower(toString(a[k])) CONTAINS $from_query) WITH a LIMIT 5 "
        "MATCH (b) WHERE any(k IN $search_properties WHERE b[k] IS NOT NULL "
        "AND toLower(toString(b[k])) CONTAINS $to_query) WITH a, b LIMIT 25 "
        f"MATCH p=shortestPath((a)-[*1..{hops}]-(b)) "
        "WHERE size($relationship_types) = 0 OR all(r IN relationships(p) WHERE type(r) IN $relationship_types) "
        f"RETURN length(p) AS hops, {nodes} AS nodes, {rels} AS relationships "
        "ORDER BY hops LIMIT $limit"
    )
    result = _run_query(statement, params)
    return {"ok": True, "from_query": start, "to_query": end, "max_depth": hops,
            "path_count": len(result["rows"]), "paths": result["rows"],
            "notifications": result["notifications"]}


TOOLS = {
    "status": status,
    "graph_overview": graph_overview,
    "search_nodes": search_nodes,
    "fulltext_search": fulltext_search,
    "node_neighborhood": node_neighborhood,
    "explore_branches": explore_branches,
    "route_sources": route_sources,
    "find_paths": find_paths,
}


def _common_args(parser: argparse.ArgumentParser, include_search: bool = False) -> None:
    if include_search:
        parser.add_argument("--search_properties", default=None)
    parser.add_argument("--identity_properties", default=None)
    parser.add_argument("--locator_properties", default=None)
    parser.add_argument("--preview_chars", default="300")


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="tool", required=True)
    sub.add_parser("status")
    p = sub.add_parser("graph_overview"); p.add_argument("--limit", default="25")
    p = sub.add_parser("search_nodes")
    p.add_argument("--query", required=True); p.add_argument("--label", default=None); p.add_argument("--limit", default="12"); _common_args(p, True)
    p = sub.add_parser("fulltext_search")
    p.add_argument("--index_name", required=True); p.add_argument("--query", required=True); p.add_argument("--limit", default="12"); _common_args(p)
    p = sub.add_parser("node_neighborhood")
    p.add_argument("--anchor_property", required=True); p.add_argument("--anchor_value", required=True); p.add_argument("--label", default=None)
    p.add_argument("--depth", default="2"); p.add_argument("--relationship_types", default=None); p.add_argument("--limit", default="40"); _common_args(p)
    for tool in ("explore_branches", "route_sources"):
        p = sub.add_parser(tool); p.add_argument("--query", required=True); p.add_argument("--label", default=None)
        p.add_argument("--depth", default="3"); p.add_argument("--relationship_types", default=None); p.add_argument("--seed_limit", default="5"); p.add_argument("--limit", default="50" if tool == "explore_branches" else "40"); _common_args(p, True)
    p = sub.add_parser("find_paths")
    p.add_argument("--from_query", required=True); p.add_argument("--to_query", required=True); p.add_argument("--depth", default="4")
    p.add_argument("--relationship_types", default=None); p.add_argument("--limit", default="10"); _common_args(p, True)
    args = parser.parse_args()
    try:
        kwargs = {key: value for key, value in vars(args).items() if key != "tool"}
        print(json.dumps(TOOLS[args.tool](**kwargs), indent=2, ensure_ascii=False))
    except (ValueError, Neo4jError, OSError) as exc:
        print(json.dumps({"ok": False, "tool": args.tool, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    _cli()
