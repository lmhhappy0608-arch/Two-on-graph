import streamlit as st
import networkx as nx
import matplotlib.pyplot as plt

from app.database import Database, default_db_path, source_stamp
from app.course_repository import CourseRepository
from app.graph_service import GraphService
from app.major_service import MajorService
from app.models import CourseNotFound
from app.prerequisite_service import PrerequisiteService

st.set_page_config(
    page_title="DKU Curriculum Navigator",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stApp { background: #f6f8fb; }
    .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1450px; }
    [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e5e7eb; }
    .hero-card, .section-card, .metric-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 1.1rem 1.2rem;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
        margin-bottom: 1rem;
    }
    .hero-title { font-size: 2.2rem; font-weight: 800; color: #111827; margin-bottom: 0.25rem; }
    .hero-subtitle, .small-note, .metric-label { color: #6b7280; }
    .panel-title { font-size: 1.12rem; font-weight: 700; color: #111827; margin-bottom: 0.75rem; }
    .metric-value { color: #111827; font-size: 1.5rem; font-weight: 800; }
    </style>
    """,
    unsafe_allow_html=True,
)

NOT_A_PLAN = "This is a structural graph path, not a course plan."
NOT_AN_AUDIT = "This is not an official degree audit."
RECORDED_ONLY = (
    "These are recorded sections from the available terms. "
    "They do not predict whether the course will be offered in a future term."
)


@st.cache_resource
def load_services(stamp: tuple[int, int]):
    database = Database()
    return (
        CourseRepository(database),
        GraphService(database),
        PrerequisiteService(database),
        MajorService(database),
    )


courses, graphs, prerequisites, majors = load_services(source_stamp(default_db_path()))
inventory = graphs.edge_inventory()
course_ids = courses.list_canonical_ids()
major_names = majors.list_majors()

st.markdown(
    """
    <div class="hero-card">
        <div class="hero-title">DKU Curriculum Navigator</div>
        <p class="hero-subtitle">Explore recorded course offerings, prerequisite structure, and major requirements from a read-only curriculum database.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown("## Dashboard")
selected_major = st.sidebar.selectbox("Major", major_names)
completed_courses = st.sidebar.multiselect("Completed courses", course_ids)
concurrent_courses = st.sidebar.multiselect("Concurrent this term", course_ids)
st.sidebar.caption(str(default_db_path().name))
st.sidebar.caption(NOT_AN_AUDIT)

metric_col1, metric_col2, metric_col3 = st.columns(3)
for column, label, value in (
    (metric_col1, "Canonical courses", inventory["nodes"]),
    (metric_col2, "Graph edges", inventory["edges"]),
    (metric_col3, "Major", selected_major),
):
    column.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value" style="font-size:1.05rem;">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

main_col, side_col = st.columns([2.45, 1.05], gap="large")


def show_value(value, empty_label="Not available"):
    return empty_label if value is None else value


def render_tree(node, level=0):
    indent = "&nbsp;" * 4 * level
    if node.kind == "group":
        label = {"or": "Complete one", "and": "Complete all", "single": "Required"}.get(node.logic or "", node.logic or "")
        st.markdown(f"{indent}<span style='color:#666;'>↳ {label}</span>", unsafe_allow_html=True)
    else:
        st.markdown(f"{indent}**{node.course_id}** · {node.state}", unsafe_allow_html=True)
    for child in node.children:
        render_tree(child, level + 1)


def draw_subgraph(subgraph, target):
    if subgraph.number_of_nodes() == 0:
        st.info("No prerequisite nodes to display.")
        return
    position = nx.spring_layout(subgraph, seed=4)
    figure, axis = plt.subplots(figsize=(12, 7))
    nx.draw(
        subgraph,
        position,
        with_labels=True,
        node_size=1800,
        node_color=["#dbeafe" if node == target else "#ffffff" for node in subgraph.nodes],
        edgecolors="#374151",
        font_size=8,
        arrows=True,
        ax=axis,
    )
    axis.set_title(f"Upstream prerequisites of {target}")
    axis.axis("off")
    st.pyplot(figure)
    plt.close(figure)
    st.caption("This view shows upstream prerequisites only. Antirequisites are not drawn as prerequisite edges.")


with main_col:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Search Course</div>', unsafe_allow_html=True)
    query = st.text_input("Search by code, alias, or name", "")
    alias_notes = {}
    if query.strip():
        matches = courses.search_courses(query, limit=20)
        options = [item.course_id for item in matches]
        alias_notes = {item.course_id: item.matched_alias for item in matches}
        if not options:
            st.info("No courses match this search.")
    else:
        options = course_ids
    selected_course = st.selectbox("Select a course", options) if options else None
    detail = courses.get_course(selected_course) if selected_course else None
    if detail is None:
        st.warning("Course not found.")
    else:
        left, right = st.columns(2)
        with left:
            st.subheader(detail.course_id)
            if alias_notes.get(detail.course_id):
                st.caption(f"Matched alias: {alias_notes[detail.course_id]}")
            st.write("**Aliases:**", ", ".join(detail.aliases) or "None listed")
            st.write("**Course Name:**", show_value(detail.course_name))
            st.write("**Department:**", show_value(detail.department))
            st.write("**Level:**", show_value(detail.level))
            st.write("**Units:**", show_value(detail.units))
            if detail.missing_fields:
                st.caption("Unavailable data: " + ", ".join(detail.missing_fields))
        with right:
            st.write("**Prerequisites:**", show_value(detail.prereq_text, "None listed"))
            st.write("**Antirequisites:**", show_value(detail.antireq_text, "None listed"))
            st.write("**Source:**", show_value(detail.source))
        try:
            sections = courses.get_recorded_sections(detail.course_id)
        except CourseNotFound:
            sections = []
        st.caption(RECORDED_ONLY)
        if sections:
            st.dataframe(
                [
                    {
                        "term_code": item.term_code,
                        "term_name": item.term_name,
                        "class_nbr": item.class_nbr,
                        "section": item.section,
                        "component": item.component,
                        "session": item.session_code,
                        "status": item.status,
                        "start": item.start_dt,
                        "end": item.end_dt,
                        "units": item.units if item.units is not None else item.units_text,
                    }
                    for item in sections
                ],
                hide_index=True,
            )
        else:
            st.info("No sections were found in the recorded terms.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Prerequisite check</div>', unsafe_allow_html=True)
    if detail is not None:
        rule = prerequisites.get_prerequisite_rule(detail.course_id)
        evaluation = prerequisites.evaluate_prerequisites(
            detail.course_id,
            completed_courses,
            concurrent_courses,
        )
        st.write("**Status:**", evaluation.status)
        st.write("**Strict groups:**", len(rule.strict_groups))
        st.write("**Prerequisite or corequisite groups:**", len(rule.corequisite_groups))
        if evaluation.satisfied_groups:
            st.write("**Satisfied groups:**", ", ".join(item.group_id for item in evaluation.satisfied_groups))
        if evaluation.unsatisfied_groups:
            st.write(
                "**Unsatisfied groups:**",
                "; ".join(
                    f"{item.group_id} ({item.logic}: {', '.join(item.courses)})"
                    for item in evaluation.unsatisfied_groups
                ),
            )
        if evaluation.options:
            st.write("**Options that satisfy the structured rule:**")
            for option in evaluation.options[:8]:
                st.write("- " + (", ".join(option) or "No additional courses"))
        if evaluation.hints:
            st.info("Advisory conditions do not block eligibility on their own: " + " | ".join(evaluation.hints[:4]))
        if evaluation.antirequisite_conflicts:
            st.warning("Antirequisite conflict: " + ", ".join(evaluation.antirequisite_conflicts))
        for note in evaluation.manual_review:
            st.warning(note)
        tree = prerequisites.get_recursive_requirements(detail.course_id, completed_courses, max_depth=4)
        st.markdown("**Requirement tree**")
        st.caption("A course may appear in more than one branch. Cycles are marked and expansion stops at the repeated node.")
        render_tree(tree)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Upstream dependency view</div>', unsafe_allow_html=True)
    if detail is not None and st.button("Show upstream prerequisites"):
        subgraph = graphs.get_prerequisite_subgraph(detail.course_id, max_depth=3)
        draw_subgraph(subgraph, detail.course_id)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Structural path explorer</div>', unsafe_allow_html=True)
    st.caption(NOT_A_PLAN)
    start_course = st.selectbox("Start course", course_ids, key="start")
    target_course = st.selectbox("Target course", course_ids, index=min(1, len(course_ids) - 1), key="target")
    if st.button("Generate path"):
        view = graphs.prerequisite_digraph()
        try:
            shortest = nx.shortest_path(view, start_course, target_course)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            shortest = None
        if not shortest:
            st.info("No structural prerequisite path connects these courses.")
        else:
            st.write("Shortest structural path: " + " → ".join(shortest))
            st.caption(NOT_A_PLAN)
            draw_subgraph(view.subgraph(shortest).copy(), target_course)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Major progress</div>', unsafe_allow_html=True)
    progress = majors.evaluate_major_progress(selected_major, completed_courses)
    st.caption(progress.automatic_judgment_note or NOT_AN_AUDIT)
    progress_left, progress_right = st.columns(2)
    ratio = "Not applicable" if progress.completion_ratio is None else f"{progress.completion_ratio:.0%}"
    progress_left.markdown(
        f"**Completion rules:** {progress.rule_count}  \n"
        f"**Satisfied:** {progress.satisfied_count}  \n"
        f"**Unsatisfied:** {progress.unsatisfied_count}"
    )
    progress_right.markdown(
        f"**Blocked:** {progress.blocked_count}  \n"
        f"**Advisory, not counted:** {progress.advisory_count}  \n"
        f"**Counted ratio:** {ratio}"
    )
    incomplete = [
        result
        for result in progress.results
        if result.counts_toward_completion and result.status == "unsatisfied"
    ]
    manual_review = [result for result in progress.results if result.status == "blocked"]
    advisory = [result for result in progress.results if result.operator == "ADVISORY"]
    satisfied = [
        result
        for result in progress.results
        if result.counts_toward_completion and result.status == "satisfied"
    ]

    if incomplete:
        st.write("**Requirements to complete**")
        for result in incomplete:
            page = "Source page unavailable" if result.source_page is None else f"Bulletin page {result.source_page}"
            label = result.group_label or result.category or result.operator
            st.write(f"**{label}** · {result.reason or 'Requirement not satisfied'}")
            if result.source_phrase:
                st.caption(f"{result.source_phrase} — {page}")
    else:
        st.success("All automatically evaluated completion requirements are satisfied.")

    if manual_review:
        with st.expander(f"Manual review required ({len(manual_review)})"):
            for result in manual_review:
                page = "Source page unavailable" if result.source_page is None else f"Bulletin page {result.source_page}"
                st.write(f"**{result.category or result.operator}** · {page}")
                st.caption("This requirement cannot be evaluated automatically.")

    if advisory:
        with st.expander(f"Advisory requirements ({len(advisory)})"):
            for result in advisory:
                page = "Source page unavailable" if result.source_page is None else f"Bulletin page {result.source_page}"
                st.write(f"**{result.category or result.operator}** · {page}")
                if result.source_phrase:
                    st.caption(result.source_phrase)

    if satisfied:
        with st.expander(f"Satisfied requirements ({len(satisfied)})"):
            for result in satisfied:
                page = "Source page unavailable" if result.source_page is None else f"Bulletin page {result.source_page}"
                st.write(f"**{result.group_label or result.category or result.operator}** · {page}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Full curriculum graph</div>', unsafe_allow_html=True)
    st.info("The full curriculum graph is not rendered at once. Use the upstream prerequisite view to inspect a focused subgraph.")
    st.markdown("</div>", unsafe_allow_html=True)

with side_col:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">How to use</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="small-note">
        Search by course code, cross-listing, or course name.<br><br>
        Completed and concurrent courses are evaluated by the prerequisite service.<br><br>
        Major progress includes verified completion requirements only. Advisory courses are shown separately.<br><br>
        {NOT_A_PLAN}<br><br>
        {NOT_AN_AUDIT}
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
