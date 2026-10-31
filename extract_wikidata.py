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
    params = urllib.parse.urlencode({"query": query, "format": "json"})
    request = urllib.request.Request(
        f"{ENDPOINT}?{params}",
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.load(response)
            return payload["results"]["bindings"]
        except Exception as exc:  # network services can fail transiently
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Wikidata query failed after {retries} attempts: {last_error}")


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def label(binding: Dict[str, Dict[str, str]], field: str, identifier: str) -> str:
    value = binding.get(field, {}).get("value", "").strip()
    return value if value and value != identifier else identifier


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

    roster: Dict[str, str] = {}
    for row in roster_bindings:
        person_qid = qid(row["person"]["value"])
        roster[person_qid] = label(row, "personLabel", person_qid)

    edge_map: Dict[tuple[str, str], Dict[str, str]] = {}
    teachers: Dict[str, str] = {}
    for row in teacher_bindings:
        student_qid = qid(row["student"]["value"])
        teacher_qid = qid(row["teacher"]["value"])
        student_name = label(row, "studentLabel", student_qid)
        teacher_name = label(row, "teacherLabel", teacher_qid)
        roster.setdefault(student_qid, student_name)
        teachers[teacher_qid] = teacher_name
        edge_map[(student_qid, teacher_qid)] = {
            "student_qid": student_qid,
            "student_name": student_name,
            "teacher_qid": teacher_qid,
            "teacher_name": teacher_name,
        }

    all_qids = sorted(set(roster) | set(teachers))
    node_rows = []
    for person_qid in all_qids:
        in_roster = person_qid in roster
        is_teacher = person_qid in teachers
        role = "both" if in_roster and is_teacher else "roster" if in_roster else "teacher"
        person_name = roster.get(person_qid, teachers.get(person_qid, person_qid))
        node_rows.append(
            {
                "qid": person_qid,
                "name": person_name,
                "role": role,
                "wikidata_url": f"https://www.wikidata.org/wiki/{person_qid}",
            }
        )

    edge_rows = [edge_map[key] for key in sorted(edge_map)]
    output_dir = Path(args.output_dir)
    write_csv(output_dir / "nodes.csv", ["qid", "name", "role", "wikidata_url"], node_rows)
    write_csv(
        output_dir / "edges.csv",
        ["student_qid", "student_name", "teacher_qid", "teacher_name"],
        edge_rows,
    )

    retrieved_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "retrieved_at_utc": retrieved_at,
        "endpoint": ENDPOINT,
        "competition_qid": "Q857351",
        "roster_people": len(roster),
        "teacher_links": len(edge_rows),
        "distinct_teachers": len(teachers),
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
