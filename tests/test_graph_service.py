import networkx as nx
import pytest

from app.graph_service import GraphService
from app.models import CourseNotFound


@pytest.fixture(scope="module")
def service():
    return GraphService()


@pytest.fixture(scope="module")
def graph(service):
    return service.build_curriculum_graph()


def test_node_count_matches_canonical_courses(service, graph):
    assert graph.number_of_nodes() == 824
    assert graph.number_of_nodes() == len(service.courses.list_canonical_ids())


def test_edges_keep_direction_and_strictness(graph):
    assert graph.number_of_edges() == 532
    assert graph.has_edge("MATH101", "MATH206")
    matched = [
        data
        for _source, _target, data in graph.edges("MATH101", data=True)
        if _target == "MATH206" and data["relation_type"] == "prerequisite"
    ]
    assert matched[0]["strict"] == 1
    assert matched[0]["issue"] == "ok"
    strict = sum(1 for _s, _t, data in graph.edges(data=True) if data["strict"] == 1)
    nonstrict = sum(1 for _s, _t, data in graph.edges(data=True) if data["strict"] == 0)
    assert (strict, nonstrict) == (495, 37)


def test_isolated_nodes_remain(graph):
    isolated = [node for node in graph.nodes if graph.degree(node) == 0]
    assert isolated
    assert "DKU101" in isolated


def test_endpoints_exist_and_parallel_edges_are_kept(graph):
    for source, target in graph.edges():
        assert source in graph
        assert target in graph
    assert isinstance(graph, nx.MultiDiGraph)
    assert graph.has_edge("MATH205", "MATH206")


def test_subgraph_excludes_unrelated_and_antirequisite_nodes(service, graph):
    subgraph = service.get_prerequisite_subgraph("MATH206", max_depth=1, graph=graph)
    assert set(subgraph.nodes) == {"MATH206", "MATH101", "MATH105"}
    assert "STATS303" not in subgraph
    assert "MATH205" not in subgraph
    data = subgraph.get_edge_data("MATH101", "MATH206")
    assert any(item["relation_type"] == "prerequisite" for item in data.values())


def test_unknown_subgraph_course(service):
    with pytest.raises(CourseNotFound):
        service.get_prerequisite_subgraph("ZZZ999")
