"""Reproduce the saved Wikidata snapshot's coverage and teacher-link summaries."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NODES = ROOT / "data" / "nodes.csv"
EDGES = ROOT / "data" / "edges.csv"
OUT = ROOT / "output"


def load():
    """Read the node and student-of tables from the saved snapshot."""
    with NODES.open(encoding="utf-8", newline="") as node_file:
        node_rows = list(csv.DictReader(node_file))
    with EDGES.open(encoding="utf-8", newline="") as edge_file:
        edge_rows = list(csv.DictReader(edge_file))
    return node_rows, edge_rows


def components(nodes, edges):
    """Count weak components across all saved nodes, including isolates."""
    parent_by_qid = {node_row["qid"]: node_row["qid"] for node_row in nodes}

    def find(qid):
        while parent_by_qid[qid] != qid:
            parent_by_qid[qid] = parent_by_qid[parent_by_qid[qid]]
            qid = parent_by_qid[qid]
        return qid

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent_by_qid[right] = left

    for edge in edges:
        union(edge["student_qid"], edge["teacher_qid"])
    component_sizes = defaultdict(int)
    for node_row in nodes:
        component_sizes[find(node_row["qid"])] += 1

    if not component_sizes:
        raise IndexError("list index out of range")
    nontrivial_count = sum(1 for size in component_sizes.values() if size >= 2)
    return len(component_sizes), nontrivial_count, max(component_sizes.values())


def core_svg(teacher_rows):
    """Render teachers with at least three student labels in the fixed view box."""
    displayed_teachers = [teacher_row for teacher_row in teacher_rows if int(teacher_row["n_students"]) >= 3]
    width, height = 1180, 360
    svg_fragments = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (width, height, width, height),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="32" y="34" font-family="Georgia, serif" font-size="21" fill="#1d1a16">Teachers linked to at least three people in this extract</text>',
        '<text x="32" y="56" font-family="Calibri, sans-serif" font-size="13" fill="#5c564e">Wikidata student-of statements only. Counts are not a ranking of historical importance.</text>',
    ]
    column_width = 280
    for column_index, teacher_row in enumerate(displayed_teachers):
        x = 36 + column_index * column_width
        svg_fragments.append('<text x="%d" y="100" font-family="Calibri, sans-serif" font-size="15" fill="#2c5f8a">%s</text>' % (x, escape(teacher_row["teacher_name"])))
        svg_fragments.append('<text x="%d" y="120" font-family="Calibri, sans-serif" font-size="12" fill="#5c564e">%s roster links</text>' % (x, teacher_row["n_students"]))
        for student_index, student_label in enumerate(teacher_row["student_names"].split("; ")):
            y = 152 + student_index * 28
            svg_fragments.append('<text x="%d" y="%d" font-family="Calibri, sans-serif" font-size="14" fill="#1d1a16">%s</text>' % (x, y, escape(student_label)))
    svg_fragments.append("</svg>")
    return "\n".join(svg_fragments)


def escape(value):
    return value.replace("&", "&amp;").replace("<", "&lt;")


def main():
    OUT.mkdir(exist_ok=True)
    nodes, edges = load()
    roster_rows = [row for row in nodes if row["role"] in {"roster", "both"}]
    roster_qids = {row["qid"] for row in roster_rows}
    student_qids_with_teacher = {edge["student_qid"] for edge in edges}
    student_labels_by_teacher = defaultdict(list)
    for edge in edges:
        student_labels_by_teacher[edge["teacher_qid"]].append(edge["student_name"])
    node_labels = {row["qid"]: row["name"] for row in nodes}
    teacher_rows = []
    # The archived degree table counts unique student labels for each teacher.
    for teacher_qid, student_names in student_labels_by_teacher.items():
        sorted_student_labels = sorted(set(student_names))
        teacher_rows.append({
            "teacher_qid": teacher_qid,
            "teacher_name": node_labels[teacher_qid],
            "n_students": len(sorted_student_labels),
            "student_names": "; ".join(sorted_student_labels),
            "wikidata_url": "https://www.wikidata.org/wiki/" + teacher_qid,
        })
    teacher_rows.sort(key=lambda row: (-row["n_students"], row["teacher_name"]))
    component_count, nontrivial_components, largest_component_size = components(nodes, edges)
    summary_rows = [
        ("retrieved", "2026-10-30"),
        ("source", "Wikidata Q857351"),
        ("roster_people", len(roster_rows)),
        ("roster_with_teacher", len(student_qids_with_teacher & roster_qids)),
        ("roster_without_teacher", len(roster_qids - student_qids_with_teacher)),
        ("teacher_links", len(edges)),
        ("distinct_teachers", len(student_labels_by_teacher)),
        ("teachers_with_2_or_more", sum(1 for row in teacher_rows if row["n_students"] >= 2)),
        ("teachers_with_3_or_more", sum(1 for row in teacher_rows if row["n_students"] >= 3)),
        ("components", component_count),
        ("components_of_at_least_2", nontrivial_components),
        ("largest_component", largest_component_size),
    ]
    with (OUT / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["metric", "value"])
        writer.writerows(summary_rows)
    with (OUT / "teacher_degree.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["teacher_qid", "teacher_name", "n_students", "student_names", "wikidata_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(teacher_rows)
    (OUT / "core_teachers.svg").write_text(core_svg(teacher_rows), encoding="utf-8", newline="\n")
    for metric, value in summary_rows:
        print(metric, value)


if __name__ == "__main__":
    main()
