"""Build the curriculum graph from graph_edges without changing the database."""

from __future__ import annotations

import networkx as nx

from app.course_repository import CourseRepository, _number, _text
from app.database import Database
from app.models import GraphIntegrityError

PREREQUISITE_RELATIONS = ("prerequisite", "prerequisite_or_corequisite")
_EDGE_FIELDS = (
    "relation_type",
    "group_id",
    "logic_within_group",
    "group_relation",
    "strict",
    "issue",
    "raw_clause",
)


class GraphService:
    def __init__(self, database: Database | None = None):
        self.database = database or Database()
        self.courses = CourseRepository(self.database)

    def build_curriculum_graph(self) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph()
        for row in self.database.query(
            """
            SELECT c.course_id, c.course_name, c.department, c.level, c.units
            FROM course_aliases AS a
            JOIN courses AS c ON c.course_id = a.course_id
            WHERE a.alias_code = a.course_id
            ORDER BY c.course_id
            """
        ):
            graph.add_node(
                row["course_id"],
                course_name=_text(row["course_name"]),
                department=_text(row["department"]),
                level=row["level"],
                units=_number(row["units"]),
            )
        seen = set()
        for row in self.database.query(
            """
            SELECT source_course, target_course, relation_type, group_id,
                   logic_within_group, group_relation, strict, issue, raw_clause
            FROM graph_edges
            ORDER BY id
            """
        ):
            key = (
                row["source_course"],
                row["target_course"],
                row["relation_type"],
                row["group_id"],
                row["raw_clause"],
            )
            if key in seen:
                raise GraphIntegrityError(f"Duplicate edge would overwrite graph semantics: {key}")
            seen.add(key)
            graph.add_edge(
                row["source_course"],
                row["target_course"],
                **{field: row[field] for field in _EDGE_FIELDS},
            )
        self.validate(graph)
        return graph

    def validate(self, graph: nx.MultiDiGraph) -> None:
        if not graph.is_directed() or not graph.is_multigraph():
            raise GraphIntegrityError("The curriculum graph must be a directed multigraph.")
        canonical = set(self.courses.list_canonical_ids())
        if set(graph.nodes) != canonical:
            missing = sorted(canonical - set(graph.nodes))[:5]
            extra = sorted(set(graph.nodes) - canonical)[:5]
            raise GraphIntegrityError(f"Graph nodes do not match canonical courses; missing {missing}, extra {extra}")
        for source, target in graph.edges():
            if source not in graph or target not in graph:
                raise GraphIntegrityError(f"Edge endpoint is missing from the graph: {source} -> {target}")
        db_strict = {
            row["strict"]: row["n"]
            for row in self.database.query(
                "SELECT strict, COUNT(*) AS n FROM graph_edges GROUP BY strict"
            )
        }
        graph_strict = {0: 0, 1: 0}
        for _source, _target, data in graph.edges(data=True):
            graph_strict[int(data["strict"])] = graph_strict.get(int(data["strict"]), 0) + 1
        if graph_strict.get(1, 0) != db_strict.get(1, 0) or graph_strict.get(0, 0) != db_strict.get(0, 0):
            raise GraphIntegrityError(f"Strict-edge counts differ: graph {graph_strict}, database {db_strict}")
        db_isolated = self.database.query(
            """
            SELECT COUNT(*) AS n
            FROM course_aliases AS a
            WHERE a.alias_code = a.course_id
              AND a.course_id NOT IN (SELECT source_course FROM graph_edges)
              AND a.course_id NOT IN (SELECT target_course FROM graph_edges)
            """
        )[0]["n"]
        isolated = sum(1 for node in graph.nodes if graph.degree(node) == 0)
        if isolated != db_isolated:
            raise GraphIntegrityError(f"Isolate counts differ: graph {isolated}, database {db_isolated}")

    def edge_inventory(self) -> dict[str, int]:
        rows = self.database.query(
            """
            SELECT
                COUNT(*) AS edges,
                SUM(strict = 1) AS strict_edges,
                SUM(strict = 0) AS nonstrict_edges
            FROM graph_edges
            """
        )[0]
        return {
            "nodes": len(self.courses.list_canonical_ids()),
            "edges": rows["edges"],
            "strict_edges": rows["strict_edges"] or 0,
            "nonstrict_edges": rows["nonstrict_edges"] or 0,
        }

    def get_prerequisite_subgraph(
        self,
        course_id: str,
        max_depth: int | None = None,
        graph: nx.MultiDiGraph | None = None,
    ) -> nx.MultiDiGraph:
        canonical = self.courses.resolve_course_code(course_id)
        if canonical is None:
            from app.models import CourseNotFound

            raise CourseNotFound(course_id)
        full = graph if graph is not None else self.build_curriculum_graph()
        if canonical not in full:
            from app.models import CourseNotFound

            raise CourseNotFound(canonical)
        selected = {canonical}
        frontier = {canonical}
        depth = 0
        incoming = _incoming_prerequisite_edges(full)
        while frontier and (max_depth is None or depth < max_depth):
            nxt = set()
            for node in frontier:
                for source, _key, _data in incoming.get(node, ()):
                    if source not in selected:
                        selected.add(source)
                        nxt.add(source)
            frontier = nxt
            depth += 1
        subgraph = nx.MultiDiGraph()
        for node in selected:
            subgraph.add_node(node, **full.nodes[node])
        for node in selected:
            for source, key, data in incoming.get(node, ()):
                if source in selected:
                    subgraph.add_edge(source, node, key=key, **data)
        return subgraph

    def prerequisite_digraph(self, graph: nx.MultiDiGraph | None = None) -> nx.DiGraph:
        """Prerequisite edges only, for structural exploration. Not a term plan."""
        full = graph if graph is not None else self.build_curriculum_graph()
        view = nx.DiGraph()
        view.add_nodes_from(full.nodes(data=True))
        for source, target, data in full.edges(data=True):
            if data.get("relation_type") not in PREREQUISITE_RELATIONS:
                continue
            if view.has_edge(source, target):
                raise GraphIntegrityError(f"Multiple prerequisite edges share the same course pair: {source} -> {target}")
            view.add_edge(source, target, **data)
        return view


def _incoming_prerequisite_edges(graph: nx.MultiDiGraph) -> dict[str, list[tuple]]:
    incoming: dict[str, list[tuple]] = {}
    for source, target, key, data in graph.edges(keys=True, data=True):
        if data.get("relation_type") not in PREREQUISITE_RELATIONS:
            continue
        incoming.setdefault(target, []).append((source, key, data))
    return incoming
