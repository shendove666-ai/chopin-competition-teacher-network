#!/usr/bin/env python3
"""Rebuild a dated Chopin Competition teacher-link snapshot from Wikidata.

The script writes to a separate output directory by default and never silently
overwrites the saved application snapshot in ``data/``.  Wikidata is live, so
new runs may differ from the 30 October 2026 extract.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List


ROOT = Path(__file__).resolve().parent
ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "WenMao-ChopinTeacherNetwork/1.0 (educational research project)"


def run_query(query: str, retries: int = 3) -> List[Dict[str, Dict[str, str]]]:
    search_params = urllib.parse.urlencode({"query": query, "format": "json"})
    request = urllib.request.Request(
        f"{ENDPOINT}?{search_params}",
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
    )
    last_query_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                sparql_response = json.load(response)
            return sparql_response["results"]["bindings"]
        except Exception as exc:
            last_query_error = exc
            if attempt + 1 < retries:
                # Space retries to avoid bursts against the query service.
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Wikidata query failed after {retries} attempts: {last_query_error}")


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def label(binding: Dict[str, Dict[str, str]], field: str, identifier: str) -> str:
    display_label = binding.get(field, {}).get("value", "").strip()
    return display_label if display_label and display_label != identifier else identifier


def write_csv(path: Path, fieldnames: List[str], rows: Iterable[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="data/refresh")
    parser.add_argument("--query-dir", default="queries")
    args = parser.parse_args()

    query_dir = Path(args.query_dir)
    roster_query = (query_dir / "roster.rq").read_text(encoding="utf-8")
    teacher_query = (query_dir / "teacher_links.rq").read_text(encoding="utf-8")

    roster_bindings = run_query(roster_query)
    teacher_bindings = run_query(teacher_query)

    roster_labels_by_qid: Dict[str, str] = {}
    for roster_binding in roster_bindings:
        person_qid = qid(roster_binding["person"]["value"])
        roster_labels_by_qid[person_qid] = label(roster_binding, "personLabel", person_qid)

    evidence_by_pair: Dict[tuple[str, str], Dict[str, object]] = {}
    teacher_labels_by_qid: Dict[str, str] = {}
    for teacher_statement_binding in teacher_bindings:
        student_qid = qid(teacher_statement_binding["student"]["value"])
        teacher_qid = qid(teacher_statement_binding["teacher"]["value"])
        student_name = label(teacher_statement_binding, "studentLabel", student_qid)
        teacher_name = label(teacher_statement_binding, "teacherLabel", teacher_qid)
        roster_labels_by_qid.setdefault(student_qid, student_name)
        teacher_labels_by_qid[teacher_qid] = teacher_name
        student_teacher_key = (student_qid, teacher_qid)
        pair_evidence = evidence_by_pair.setdefault(
            student_teacher_key,
            {
                "student_qid": student_qid,
                "student_name": student_name,
                "teacher_qid": teacher_qid,
                "teacher_name": teacher_name,
                "statement_urls": set(),
                "statement_ranks": set(),
                "reference_urls": set(),
            },
        )
        statement_url = teacher_statement_binding.get("statement", {}).get("value", "")
        rank_uri = teacher_statement_binding.get("rank", {}).get("value", "")
        reference_node_uri = teacher_statement_binding.get("reference", {}).get("value", "")
        if statement_url:
            pair_evidence["statement_urls"].add(statement_url)
        if rank_uri:
            pair_evidence["statement_ranks"].add(rank_uri.rsplit("#", 1)[-1])
        if reference_node_uri:
            pair_evidence["reference_urls"].add(reference_node_uri)

    all_qids = sorted(set(roster_labels_by_qid) | set(teacher_labels_by_qid))
    node_rows = []
    for person_qid in all_qids:
        in_roster = person_qid in roster_labels_by_qid
        is_teacher = person_qid in teacher_labels_by_qid
        role = "both" if in_roster and is_teacher else "roster" if in_roster else "teacher"
        person_name = roster_labels_by_qid.get(person_qid, teacher_labels_by_qid.get(person_qid, person_qid))
        node_rows.append(
            {
                "qid": person_qid,
                "name": person_name,
                "role": role,
                "wikidata_url": f"https://www.wikidata.org/wiki/{person_qid}",
            }
        )

    edge_rows = []
    for student_teacher_key in sorted(evidence_by_pair):
        pair_evidence = evidence_by_pair[student_teacher_key]
        edge_rows.append(
            {
                "student_qid": pair_evidence["student_qid"],
                "student_name": pair_evidence["student_name"],
                "teacher_qid": pair_evidence["teacher_qid"],
                "teacher_name": pair_evidence["teacher_name"],
                "statement_urls": "|".join(sorted(pair_evidence["statement_urls"])),
                "statement_ranks": "|".join(sorted(pair_evidence["statement_ranks"])),
                "reference_count": len(pair_evidence["reference_urls"]),
            }
        )
    output_dir = Path(args.output_dir)
    write_csv(output_dir / "nodes.csv", ["qid", "name", "role", "wikidata_url"], node_rows)
    write_csv(
        output_dir / "edges.csv",
        [
            "student_qid",
            "student_name",
            "teacher_qid",
            "teacher_name",
            "statement_urls",
            "statement_ranks",
            "reference_count",
        ],
        edge_rows,
    )

    retrieved_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "retrieved_at_utc": retrieved_at,
        "endpoint": ENDPOINT,
        "competition_qid": "Q857351",
        "roster_people": len(roster_labels_by_qid),
        "teacher_links": len(edge_rows),
        "distinct_teachers": len(teacher_labels_by_qid),
        "teacher_links_with_references": sum(
            int(row["reference_count"]) > 0 for row in edge_rows
        ),
        "roster_query_sha256": hashlib.sha256(roster_query.encode()).hexdigest(),
        "teacher_query_sha256": hashlib.sha256(teacher_query.encode()).hexdigest(),
        "note": "Wikidata is live; refreshed results may differ from the saved 2026-10-30 snapshot.",
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
