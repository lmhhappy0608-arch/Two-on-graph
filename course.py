import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt

file_path = "/Users/mohan/Desktop/curriculum_subset_math_cs_ds.xlsx"

courses = pd.read_excel(file_path, sheet_name="courses")
relations = pd.read_excel(file_path, sheet_name="relations")

courses["course_id"] = courses["course_id"].astype(str).str.strip().str.upper()
relations["source_course"] = relations["source_course"].astype(str).str.strip().str.upper()
relations["target_course"] = relations["target_course"].astype(str).str.strip().str.upper()
relations["relation_type"] = relations["relation_type"].astype(str).str.strip().str.lower()

G = nx.DiGraph()

for _, row in courses.iterrows():
    G.add_node(row["course_id"])

for _, row in relations.iterrows():
    if row["relation_type"] != "prerequisite":
        continue
    source = row["source_course"]
    target = row["target_course"]
    if source == target:
        continue
    G.add_edge(source, target)

start = "MATH101"
end = "MATH308"

path_edges = []
path_nodes = []

try:
    path = nx.shortest_path(G, source=start, target=end)
    path_nodes = path
    path_edges = list(zip(path[:-1], path[1:]))
    print("Shortest path:", " -> ".join(path))
except nx.NetworkXNoPath:
    print(f"No path from {start} to {end}")

plt.figure(figsize=(18, 12))
pos = nx.spring_layout(G, seed=42, k=0.9)

# normal nodes
normal_nodes = [n for n in G.nodes if n not in path_nodes]
nx.draw_networkx_nodes(G, pos, nodelist=normal_nodes, node_size=900)

# highlighted path nodes
nx.draw_networkx_nodes(G, pos, nodelist=path_nodes, node_size=1100)

# normal edges
normal_edges = [e for e in G.edges if e not in path_edges]
nx.draw_networkx_edges(G, pos, edgelist=normal_edges, arrows=True, arrowsize=16, width=1.0)

# highlighted path edges
nx.draw_networkx_edges(G, pos, edgelist=path_edges, arrows=True, arrowsize=20, width=2.5)

nx.draw_networkx_labels(G, pos, font_size=8)

plt.title(f"Highlighted Path: {start} to {end}", fontsize=16)
plt.axis("off")
plt.tight_layout()

output_path = "/Users/mohan/Desktop/curriculum_graph_highlighted.png"
plt.savefig(output_path, dpi=300, bbox_inches="tight")
plt.show()

print(f"Highlighted graph saved to: {output_path}")