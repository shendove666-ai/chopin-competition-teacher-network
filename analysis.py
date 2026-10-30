"""Metrics for the saved Wikidata teacher extract.

The CSV files are the source. This script does not download data and does
not add teacher links from memory.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NODES = ROOT / "data" / "nodes.csv"
EDGES = ROOT / "data" / "edges.csv"
OUT = ROOT / "output"


def load():
    nodes = list(csv.DictReader(NODES.open(encoding="utf-8", newline="")))
    edges = list(csv.DictReader(EDGES.open(encoding="utf-8", newline="")))
    return nodes, edges


def components(nodes, edges):
    parent = {row["qid"]: row["qid"] for row in nodes}

    def find(qid):
        while parent[qid] != qid:
            parent[qid] = parent[parent[qid]]
            qid = parent[qid]
        return qid

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    for edge in edges:
        union(edge["student_qid"], edge["teacher_qid"])
    groups = defaultdict(list)
    for row in nodes:
        groups[find(row["qid"])].append(row["qid"])
    sizes = sorted((len(group) for group in groups.values()), reverse=True)
    return len(sizes), sum(1 for size in sizes if size >= 2), sizes[0]


def core_svg(teacher_rows):
    chosen = [row for row in teacher_rows if int(row["n_students"]) >= 3]
    width, height = 1180, 360
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (width, height, width, height),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="32" y="34" font-family="Georgia, serif" font-size="21" fill="#1d1a16">Teachers linked to at least three people in this extract</text>',
        '<text x="32" y="56" font-family="Calibri, sans-serif" font-size="13" fill="#5c564e">Wikidata student-of statements only. Counts are not a ranking of historical importance.</text>',
    ]
    column_width = 280
    for index, row in enumerate(chosen):
        x = 36 + index * column_width
        parts.append('<text x="%d" y="100" font-family="Calibri, sans-serif" font-size="15" fill="#2c5f8a">%s</text>' % (x, escape(row["teacher_name"])))
        parts.append('<text x="%d" y="120" font-family="Calibri, sans-serif" font-size="12" fill="#5c564e">%s roster links</text>' % (x, row["n_students"]))
        for student_index, name in enumerate(row["student_names"].split("; ")):
            y = 152 + student_index * 28
            parts.append('<text x="%d" y="%d" font-family="Calibri, sans-serif" font-size="14" fill="#1d1a16">%s</text>' % (x, y, escape(name)))
    parts.append("</svg>")
    return "\n".join(parts)


def escape(value):
    return value.replace("&", "&amp;").replace("<", "&lt;")


def main():
    OUT.mkdir(exist_ok=True)
    nodes, edges = load()
    roster = [row for row in nodes if row["role"] in {"roster", "both"}]
    roster_ids = {row["qid"] for row in roster}
    students_with_teacher = {edge["student_qid"] for edge in edges}
    by_teacher = defaultdict(list)
    for edge in edges:
        by_teacher[edge["teacher_qid"]].append(edge["student_name"])
    names = {row["qid"]: row["name"] for row in nodes}
    teacher_rows = []
    for teacher_qid, student_names in by_teacher.items():
        ordered = sorted(set(student_names))
        teacher_rows.append({
            "teacher_qid": teacher_qid,
            "teacher_name": names[teacher_qid],
            "n_students": len(ordered),
            "student_names": "; ".join(ordered),
            "wikidata_url": "https://www.wikidata.org/wiki/" + teacher_qid,
        })
    teacher_rows.sort(key=lambda row: (-row["n_students"], row["teacher_name"]))
    component_count, nontrivial, largest = components(nodes, edges)
    summary = [
        ("retrieved", "2026-10-30"),
        ("source", "Wikidata Q857351"),
        ("roster_people", len(roster)),
        ("roster_with_teacher", len(students_with_teacher & roster_ids)),
        ("roster_without_teacher", len(roster_ids - students_with_teacher)),
        ("teacher_links", len(edges)),
        ("distinct_teachers", len(by_teacher)),
        ("teachers_with_2_or_more", sum(1 for row in teacher_rows if row["n_students"] >= 2)),
        ("teachers_with_3_or_more", sum(1 for row in teacher_rows if row["n_students"] >= 3)),
        ("components", component_count),
        ("components_of_at_least_2", nontrivial),
        ("largest_component", largest),
    ]
    with (OUT / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["metric", "value"])
        writer.writerows(summary)
    with (OUT / "teacher_degree.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["teacher_qid", "teacher_name", "n_students", "student_names", "wikidata_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(teacher_rows)
    (OUT / "core_teachers.svg").write_text(core_svg(teacher_rows), encoding="utf-8", newline="\n")
    for metric, value in summary:
        print(metric, value)


if __name__ == "__main__":
    main()
