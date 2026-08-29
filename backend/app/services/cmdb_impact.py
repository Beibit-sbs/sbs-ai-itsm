from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import struct
import uuid
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.change_link import ChangeAssetLink
from app.models.change_request import ChangeRequest
from app.models.ci_relationship import (
    ConfigurationItemRelationship,
    ConfigurationItemRelationshipType,
)
from app.models.cmdb_impact import CMDBImpactCache
from app.models.problem import Problem
from app.models.problem_link import ProblemAssetLink
from app.models.ticket import Ticket
from app.services.cmdb_schema import canonical_json


FINAL_CHANGE_STATUSES = {
    "COMPLETED",
    "CANCELLED",
    "ROLLED_BACK",
    "FAILED",
}
SERVICE_CLASS_CODES = {"BUSINESS_SERVICE", "TECHNICAL_SERVICE"}
CRITICALITY_WEIGHT = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _json_dict(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def graph_revision_hash(db: Session, tenant_id: str) -> str:
    relationships = db.execute(
        select(
            ConfigurationItemRelationship.id,
            ConfigurationItemRelationship.version,
            ConfigurationItemRelationship.relationship_type_id,
            ConfigurationItemRelationship.source_ci_id,
            ConfigurationItemRelationship.target_ci_id,
        )
        .where(
            ConfigurationItemRelationship.tenant_id == tenant_id,
            ConfigurationItemRelationship.status == "ACTIVE",
        )
        .order_by(ConfigurationItemRelationship.id)
    ).all()
    relationship_types = db.execute(
        select(
            ConfigurationItemRelationshipType.id,
            ConfigurationItemRelationshipType.version,
        )
        .where(ConfigurationItemRelationshipType.tenant_id == tenant_id)
        .order_by(ConfigurationItemRelationshipType.id)
    ).all()
    assets = db.execute(
        select(
            Asset.id,
            Asset.ci_version,
            Asset.lifecycle_status,
            Asset.criticality,
            Asset.environment,
        )
        .where(Asset.tenant_id == tenant_id)
        .order_by(Asset.id)
    ).all()
    revision = {
        "relationships": [
            [
                item.id,
                item.version,
                item.relationship_type_id,
                item.source_ci_id,
                item.target_ci_id,
            ]
            for item in relationships
        ],
        "relationship_types": [
            [
                item.id,
                item.version,
            ]
            for item in relationship_types
        ],
        "assets": [
            [
                item.id,
                item.ci_version,
                item.lifecycle_status,
                item.criticality,
                item.environment,
            ]
            for item in assets
        ],
    }
    return hashlib.sha256(canonical_json(revision).encode()).hexdigest()


def _node(asset: Asset, depth: int, is_root: bool = False) -> dict[str, Any]:
    return {
        "id": asset.id,
        "asset_tag": asset.asset_tag,
        "name": asset.name,
        "ci_class_id": asset.ci_class_id,
        "ci_class_code": asset.ci_class_code,
        "ci_class_name": asset.ci_class_name,
        "lifecycle_status": asset.lifecycle_status,
        "criticality": asset.criticality,
        "environment": asset.environment,
        "support_group": asset.support_group,
        "depth": depth,
        "is_root": is_root,
    }


def _edge(
    relationship: ConfigurationItemRelationship,
    relationship_type: ConfigurationItemRelationshipType,
) -> dict[str, Any]:
    return {
        "id": relationship.id,
        "relationship_type_id": relationship_type.id,
        "relationship_type_code": relationship_type.code,
        "relationship_type_name": relationship_type.name,
        "forward_label": relationship_type.forward_label,
        "reverse_label": relationship_type.reverse_label,
        "source_ci_id": relationship.source_ci_id,
        "target_ci_id": relationship.target_ci_id,
    }


def _lock_cache_scope(
    db: Session,
    tenant_id: str,
    root_ci_id: str,
    direction: str,
    max_depth: int,
) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    digest = hashlib.sha256(
        f"{tenant_id}:{root_ci_id}:{direction}:{max_depth}".encode()
    ).digest()[:8]
    lock_key = struct.unpack(">q", digest)[0]
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": lock_key},
    )


def _traverse_root(
    db: Session,
    *,
    tenant_id: str,
    root: Asset,
    direction: str,
    max_depth: int,
    max_nodes: int,
) -> dict[str, Any]:
    visited = {root.id}
    depths = {root.id: 0}
    frontier = {root.id}
    edge_map: dict[str, ConfigurationItemRelationship] = {}
    truncated = False
    for current_depth in range(1, max_depth + 1):
        if not frontier:
            break
        filters = []
        if direction in {"DOWNSTREAM", "BOTH"}:
            filters.append(
                ConfigurationItemRelationship.source_ci_id.in_(frontier)
            )
        if direction in {"UPSTREAM", "BOTH"}:
            filters.append(
                ConfigurationItemRelationship.target_ci_id.in_(frontier)
            )
        relationships = db.scalars(
            select(ConfigurationItemRelationship).where(
                ConfigurationItemRelationship.tenant_id == tenant_id,
                ConfigurationItemRelationship.status == "ACTIVE",
                or_(*filters),
            )
        ).all()
        next_frontier: set[str] = set()
        for relationship in relationships:
            neighbors: list[str] = []
            if (
                direction in {"DOWNSTREAM", "BOTH"}
                and relationship.source_ci_id in frontier
            ):
                neighbors.append(relationship.target_ci_id)
            if (
                direction in {"UPSTREAM", "BOTH"}
                and relationship.target_ci_id in frontier
            ):
                neighbors.append(relationship.source_ci_id)
            for neighbor in neighbors:
                edge_map[relationship.id] = relationship
                if neighbor in visited:
                    continue
                if len(visited) >= max_nodes:
                    truncated = True
                    continue
                visited.add(neighbor)
                depths[neighbor] = current_depth
                next_frontier.add(neighbor)
        frontier = next_frontier

    assets = {
        item.id: item
        for item in db.scalars(
            select(Asset).where(
                Asset.tenant_id == tenant_id,
                Asset.id.in_(visited),
            )
        ).all()
    }
    type_ids = {
        relationship.relationship_type_id
        for relationship in edge_map.values()
    }
    relationship_types = {
        item.id: item
        for item in db.scalars(
            select(ConfigurationItemRelationshipType).where(
                ConfigurationItemRelationshipType.id.in_(type_ids),
                ConfigurationItemRelationshipType.tenant_id == tenant_id,
            )
        ).all()
    } if type_ids else {}
    nodes = [
        _node(
            assets[asset_id],
            depths[asset_id],
            is_root=asset_id == root.id,
        )
        for asset_id in sorted(
            assets,
            key=lambda item: (
                depths.get(item, max_depth + 1),
                assets[item].name.casefold(),
                item,
            ),
        )
    ]
    edges = [
        _edge(relationship, relationship_types[relationship.relationship_type_id])
        for relationship in sorted(
            edge_map.values(),
            key=lambda item: item.id,
        )
        if relationship.relationship_type_id in relationship_types
        and relationship.source_ci_id in assets
        and relationship.target_ci_id in assets
    ]
    return {
        "root_ci_id": root.id,
        "nodes": nodes,
        "edges": edges,
        "truncated": truncated,
    }


def _cached_root(
    db: Session,
    *,
    tenant_id: str,
    root: Asset,
    direction: str,
    max_depth: int,
    max_nodes: int,
    graph_hash: str,
) -> tuple[dict[str, Any], bool]:
    _lock_cache_scope(db, tenant_id, root.id, direction, max_depth)
    cache = db.scalar(
        select(CMDBImpactCache).where(
            CMDBImpactCache.tenant_id == tenant_id,
            CMDBImpactCache.root_ci_id == root.id,
            CMDBImpactCache.direction == direction,
            CMDBImpactCache.max_depth == max_depth,
        )
    )
    now = _now()
    if (
        cache is not None
        and cache.graph_hash == graph_hash
        and _aware(cache.expires_at) > now
    ):
        cached = _json_dict(cache.result_json)
        if cached:
            return cached, True
    result = _traverse_root(
        db,
        tenant_id=tenant_id,
        root=root,
        direction=direction,
        max_depth=max_depth,
        max_nodes=max_nodes,
    )
    if cache is None:
        cache = CMDBImpactCache(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            root_ci_id=root.id,
            direction=direction,
            max_depth=max_depth,
            graph_hash=graph_hash,
            result_json=canonical_json(result),
            node_count=len(result["nodes"]),
            edge_count=len(result["edges"]),
            expires_at=now + timedelta(minutes=15),
            created_at=now,
            updated_at=now,
        )
        db.add(cache)
    else:
        cache.graph_hash = graph_hash
        cache.result_json = canonical_json(result)
        cache.node_count = len(result["nodes"])
        cache.edge_count = len(result["edges"])
        cache.expires_at = now + timedelta(minutes=15)
        cache.updated_at = now
    db.flush()
    return result, False


def traverse_impact(
    db: Session,
    *,
    tenant_id: str,
    root_ci_ids: list[str],
    direction: str = "UPSTREAM",
    max_depth: int = 5,
    max_nodes: int = 1_000,
) -> dict[str, Any]:
    root_ids = list(
        dict.fromkeys(item.strip() for item in root_ci_ids if item.strip())
    )
    if not root_ids or len(root_ids) > 100:
        raise ValueError("impact analysis requires 1-100 root CIs")
    if direction not in {"UPSTREAM", "DOWNSTREAM", "BOTH"}:
        raise ValueError("unsupported impact direction")
    if max_depth < 1 or max_depth > 12:
        raise ValueError("max_depth must be between 1 and 12")
    roots = db.scalars(
        select(Asset).where(
            Asset.id.in_(root_ids),
            Asset.tenant_id == tenant_id,
        )
    ).all()
    if len(roots) != len(root_ids):
        raise ValueError("one or more impact root CIs are unavailable")
    root_map = {item.id: item for item in roots}
    revision = graph_revision_hash(db, tenant_id)
    combined_nodes: dict[str, dict[str, Any]] = {}
    combined_edges: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    truncated = False
    for root_id in root_ids:
        result, cache_hit = _cached_root(
            db,
            tenant_id=tenant_id,
            root=root_map[root_id],
            direction=direction,
            max_depth=max_depth,
            max_nodes=max_nodes,
            graph_hash=revision,
        )
        cache_hits += int(cache_hit)
        truncated = truncated or bool(result.get("truncated"))
        for node in result.get("nodes", []):
            if not isinstance(node, dict) or "id" not in node:
                continue
            existing = combined_nodes.get(str(node["id"]))
            if existing is None or int(node["depth"]) < int(existing["depth"]):
                combined_nodes[str(node["id"])] = dict(node)
        for edge in result.get("edges", []):
            if isinstance(edge, dict) and edge.get("id"):
                combined_edges[str(edge["id"])] = dict(edge)
    root_set = set(root_ids)
    nodes = sorted(
        combined_nodes.values(),
        key=lambda item: (
            int(item["depth"]),
            str(item["name"]).casefold(),
            str(item["id"]),
        ),
    )
    if len(nodes) > max_nodes:
        allowed_ids = {str(item["id"]) for item in nodes[:max_nodes]}
        nodes = nodes[:max_nodes]
        combined_edges = {
            edge_id: edge
            for edge_id, edge in combined_edges.items()
            if str(edge["source_ci_id"]) in allowed_ids
            and str(edge["target_ci_id"]) in allowed_ids
        }
        truncated = True
    for node in nodes:
        node["is_root"] = str(node["id"]) in root_set
    return {
        "tenant_id": tenant_id,
        "root_ci_ids": root_ids,
        "direction": direction,
        "max_depth": max_depth,
        "graph_hash": revision,
        "nodes": nodes,
        "edges": sorted(
            combined_edges.values(),
            key=lambda item: str(item["id"]),
        ),
        "truncated": truncated,
        "cache_hits": cache_hits,
        "computed_at": _now().isoformat(),
    }


def resolve_entity_roots(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    lock: bool = False,
) -> tuple[str, list[str], int | None]:
    entity_type = entity_type.upper()
    if entity_type == "TICKET":
        statement = select(Ticket).where(Ticket.id == entity_id)
        if lock and db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        ticket = db.scalar(statement)
        if ticket is None or not ticket.tenant_id:
            raise ValueError("ticket not found")
        return (
            ticket.tenant_id,
            [ticket.asset_id] if ticket.asset_id else [],
            None,
        )
    if entity_type == "PROBLEM":
        statement = select(Problem).where(Problem.id == entity_id)
        if lock and db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        problem = db.scalar(statement)
        if problem is None:
            raise ValueError("problem not found")
        roots = db.scalars(
            select(ProblemAssetLink.asset_id).where(
                ProblemAssetLink.problem_id == problem.id
            )
        ).all()
        return problem.tenant_id, list(roots), problem.version
    if entity_type == "CHANGE":
        statement = select(ChangeRequest).where(ChangeRequest.id == entity_id)
        if lock and db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        change = db.scalar(statement)
        if change is None:
            raise ValueError("change not found")
        roots = db.scalars(
            select(ChangeAssetLink.asset_id).where(
                ChangeAssetLink.change_id == change.id
            )
        ).all()
        return change.tenant_id, list(roots), change.version
    raise ValueError("release impact requires explicit roots")


def change_collisions(
    db: Session,
    *,
    change_id: str,
    tenant_id: str,
    impacted_ci_ids: set[str],
) -> list[dict[str, Any]]:
    change = db.get(ChangeRequest, change_id)
    if change is None or change.tenant_id != tenant_id:
        raise ValueError("change not found")
    if not impacted_ci_ids:
        return []
    rows = db.execute(
        select(ChangeRequest, ChangeAssetLink.asset_id)
        .join(ChangeAssetLink, ChangeAssetLink.change_id == ChangeRequest.id)
        .where(
            ChangeRequest.id != change.id,
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequest.status.notin_(FINAL_CHANGE_STATUSES),
            ChangeAssetLink.asset_id.in_(impacted_ci_ids),
        )
        .order_by(ChangeRequest.change_number, ChangeAssetLink.asset_id)
    ).all()
    grouped: dict[str, tuple[ChangeRequest, set[str]]] = {}
    for other, asset_id in rows:
        grouped.setdefault(other.id, (other, set()))[1].add(asset_id)
    asset_tags = {
        item.id: item.asset_tag
        for item in db.scalars(
            select(Asset).where(
                Asset.id.in_(impacted_ci_ids),
                Asset.tenant_id == tenant_id,
            )
        ).all()
    }
    collisions: list[dict[str, Any]] = []
    for other, shared_ids in grouped.values():
        change_start = change.planned_start_at
        change_end = change.planned_end_at
        other_start = other.planned_start_at
        other_end = other.planned_end_at
        both_scheduled = (
            change_start is not None
            and change_end is not None
            and other_start is not None
            and other_end is not None
        )
        window_overlap = False
        if both_scheduled:
            window_overlap = bool(
                _aware(other_start) < _aware(change_end)
                and _aware(other_end) > _aware(change_start)
            )
            if not window_overlap:
                continue
        collisions.append(
            {
                "change_id": other.id,
                "change_number": other.change_number,
                "title": other.title,
                "status": other.status,
                "risk_level": other.risk_level,
                "planned_start_at": (
                    other.planned_start_at.isoformat()
                    if other.planned_start_at
                    else None
                ),
                "planned_end_at": (
                    other.planned_end_at.isoformat()
                    if other.planned_end_at
                    else None
                ),
                "window_overlap": window_overlap,
                "collision_type": (
                    "WINDOW_OVERLAP" if window_overlap else "SHARED_SCOPE"
                ),
                "shared_ci_ids": sorted(shared_ids),
                "shared_asset_tags": sorted(
                    asset_tags[item]
                    for item in shared_ids
                    if item in asset_tags
                ),
            }
        )
    return collisions


def build_impact_result(
    db: Session,
    *,
    tenant_id: str,
    root_ci_ids: list[str],
    direction: str,
    max_depth: int,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    graph = traverse_impact(
        db,
        tenant_id=tenant_id,
        root_ci_ids=root_ci_ids,
        direction=direction,
        max_depth=max_depth,
    )
    nodes = graph["nodes"]
    services = [
        node
        for node in nodes
        if node.get("ci_class_code") in SERVICE_CLASS_CODES
    ]
    business_services = [
        node
        for node in services
        if node.get("ci_class_code") == "BUSINESS_SERVICE"
    ]
    critical_nodes = [
        node
        for node in nodes
        if node.get("criticality") == "CRITICAL"
    ]
    production_nodes = [
        node
        for node in nodes
        if node.get("environment") == "PRODUCTION"
    ]
    collisions = (
        change_collisions(
            db,
            change_id=entity_id,
            tenant_id=tenant_id,
            impacted_ci_ids={str(node["id"]) for node in nodes},
        )
        if entity_type == "CHANGE" and entity_id
        else []
    )
    max_criticality = max(
        (
            CRITICALITY_WEIGHT.get(str(node.get("criticality")), 1)
            for node in nodes
        ),
        default=1,
    )
    severity_weight = max_criticality
    reasons: list[str] = []
    if business_services:
        severity_weight = max(severity_weight, 3)
        reasons.append("business_service_impact")
    if critical_nodes:
        severity_weight = max(severity_weight, 3)
        reasons.append("critical_ci_impact")
    if len(critical_nodes) >= 2:
        severity_weight = 4
        reasons.append("multiple_critical_cis")
    if len(production_nodes) >= 5 or len(nodes) >= 25:
        severity_weight = max(severity_weight, 3)
        reasons.append("large_production_blast_radius")
    if any(item["window_overlap"] for item in collisions):
        severity_weight = 4
        reasons.append("change_window_collision")
    severity = {
        1: "LOW",
        2: "MEDIUM",
        3: "HIGH",
        4: "CRITICAL",
    }[severity_weight]
    return {
        **graph,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "severity": severity,
        "severity_reasons": reasons or ["limited_ci_scope"],
        "customer_impact": bool(business_services),
        "impacted_ci_count": len(nodes),
        "impacted_service_count": len(services),
        "critical_ci_count": len(critical_nodes),
        "production_ci_count": len(production_nodes),
        "services": services,
        "critical_cis": critical_nodes,
        "collisions": collisions,
        "collision_count": len(collisions),
    }
