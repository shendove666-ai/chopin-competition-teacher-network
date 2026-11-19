from __future__ import annotations

import csv
import hashlib
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch
from xml.etree import ElementTree

import analysis
import extract_wikidata


ROOT = Path(__file__).resolve().parents[1]


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def statement(student, teacher, student_label, statement_id, rank, reference="", teacher_label="Teacher"):
    binding = {
        "student": {"value": f"http://www.wikidata.org/entity/{student}"},
        "teacher": {"value": f"http://www.wikidata.org/entity/{teacher}"},
        "studentLabel": {"value": student_label},
        "teacherLabel": {"value": teacher_label},
        "statement": {"value": statement_id},
        "rank": {"value": f"http://wikiba.se/ontology#{rank}"},
    }
    if reference:
        binding["reference"] = {"value": reference}
    return binding


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


class SavedAnalysisTests(unittest.TestCase):
    def test_reproduces_the_three_checked_in_outputs(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(analysis, "OUT", output), redirect_stdout(io.StringIO()):
                analysis.main()
            for name in ("summary.csv", "teacher_degree.csv", "core_teachers.svg"):
                with self.subTest(name=name):
                    self.assertEqual(
                        (output / name).read_bytes(), (ROOT / "output" / name).read_bytes()
                    )

    def test_teacher_table_keeps_existing_display_label_counts(self):
        nodes = [
            {"qid": "Q1", "name": "Shared label", "role": "roster"},
            {"qid": "Q2", "name": "Shared label", "role": "roster"},
            {"qid": "Q3", "name": "Teacher", "role": "teacher"},
            {"qid": "Q4", "name": "Outside", "role": "teacher"},
        ]
        scenarios = [
            ([("Q1", "Shared label"), ("Q2", "Shared label")], 1, 2),
            ([("Q1", "Shared label"), ("Q1", "Alternative label")], 2, 1),
            ([("Q1", "Shared label"), ("Q4", "Outside")], 2, 1),
        ]
        for students, expected_labels, expected_coverage in scenarios:
            with self.subTest(students=students), TemporaryDirectory() as directory:
                output = Path(directory)
                edges = [
                    {"student_qid": qid, "student_name": label, "teacher_qid": "Q3"}
                    for qid, label in students
                ]
                with (
                    patch.object(analysis, "OUT", output),
                    patch.object(analysis, "load", return_value=(nodes, edges)),
                    redirect_stdout(io.StringIO()),
                ):
                    analysis.main()
                teacher, = read_rows(output / "teacher_degree.csv")
                summary = {row["metric"]: row["value"] for row in read_rows(output / "summary.csv")}
                self.assertEqual(int(teacher["n_students"]), expected_labels)
                self.assertEqual(int(summary["roster_with_teacher"]), expected_coverage)
                self.assertEqual(int(summary["teacher_links"]), len(edges))

    def test_component_summary_keeps_edge_case_behavior(self):
        self.assertEqual(analysis.components([{"qid": "Q1"}, {"qid": "Q1"}], []), (1, 1, 2))
        with self.assertRaisesRegex(IndexError, "list index out of range"):
            analysis.components([], [])
        with self.assertRaises(KeyError) as error:
            analysis.components([{"qid": "Q1"}], [{"student_qid": "Q1", "teacher_qid": "Q2"}])
        self.assertEqual(error.exception.args, ("Q2",))

    def test_loader_keeps_the_csv_reader_row_contract(self):
        with TemporaryDirectory() as directory:
            project = Path(directory)
            nodes, edges = project / "nodes.csv", project / "edges.csv"
            nodes.write_bytes(b"qid,name\nQ1,Student\n")
            edges.write_bytes(b"student_qid,teacher_qid,student_name\nQ1\n")
            with patch.multiple(analysis, NODES=nodes, EDGES=edges, OUT=project):
                node_rows, edge_rows = analysis.load()
                self.assertNotIn("role", node_rows[0])
                self.assertIsNone(edge_rows[0]["teacher_qid"])
                with self.assertRaises(KeyError) as error:
                    analysis.main()
            self.assertEqual(error.exception.args, ("role",))

    def test_svg_fixed_layout_and_text_boundaries(self):
        def teacher(label, students):
            return {"teacher_name": label, "n_students": 3, "student_names": students}

        teachers = [teacher(f"Teacher {index}", "One; Two; Three") for index in range(6)]
        svg = analysis.core_svg(teachers)
        self.assertIn('width="1180"', svg)
        self.assertIn('x="1436"', svg)
        dense_svg = analysis.core_svg([teacher("A & B < C", "; ".join(map(str, range(9))))])
        self.assertIn('y="376"', dense_svg)
        self.assertIn("A &amp; B &lt; C", dense_svg)
        ElementTree.fromstring(dense_svg)
        with self.assertRaises(ElementTree.ParseError):
            ElementTree.fromstring(analysis.core_svg([teacher("A ]]> B", "One; Two; Three")]))


class WikidataRefreshTests(unittest.TestCase):
    def test_entity_suffix_and_label_fallback_keep_their_current_meaning(self):
        cases = [
            ("http://www.wikidata.org/entity/Q123", "Q123"),
            ("http://www.wikidata.org/entity/", ""),
            ("unknown-value-token", "unknown-value-token"),
            ("http://example.test/entity/not-an-item", "not-an-item"),
        ]
        for uri, suffix in cases:
            with self.subTest(uri=uri):
                self.assertEqual(extract_wikidata.qid(uri), suffix)

        self.assertEqual(extract_wikidata.label({}, "name", "Q123"), "Q123")
        self.assertEqual(extract_wikidata.label({"name": {"value": "   "}}, "name", "Q123"), "Q123")
        self.assertEqual(
            extract_wikidata.label({"name": {"value": "  山田  "}}, "name", "Q123"),
            "山田",
        )

    def test_refresh_retains_current_pair_and_provenance_rules(self):
        roster_results = [{
            "person": {"value": "http://www.wikidata.org/entity/Q1"},
            "personLabel": {"value": "Roster label"},
        }]
        teaching_results = [
            statement("Q1", "Q2", "First student label", "S1", "NormalRank", "R1", "First teacher"),
            statement("Q1", "Q2", "Later student label", "S1", "NormalRank", "R2", "Later teacher"),
            statement("Q1", "Q2", "Later student label", "S2", "DeprecatedRank", "R1", "Later teacher"),
            statement("Q4", "Q2", "Added student", "S3", "DeprecatedRank"),
            statement("Q4", "Q4", "Added student", "S4", "NormalRank", teacher_label="Added student"),
            statement("Q4", "not-an-item", "Added student", "S5", "NormalRank"),
        ]
        with TemporaryDirectory() as directory:
            output = Path(directory)
            arguments = ["extract_wikidata.py", "--query-dir", str(ROOT / "queries"),
                         "--output-dir", str(output)]
            stdout = io.StringIO()
            with (
                patch("sys.argv", arguments),
                patch.object(extract_wikidata, "run_query", side_effect=[roster_results, teaching_results]) as query,
                patch.object(extract_wikidata, "datetime", FixedDateTime),
                redirect_stdout(stdout),
            ):
                extract_wikidata.main()
            node_by_qid = {node["qid"]: node for node in read_rows(output / "nodes.csv")}
            self.assertEqual(node_by_qid["Q1"]["name"], "Roster label")
            self.assertEqual(node_by_qid["Q2"]["name"], "Teacher")
            self.assertEqual(node_by_qid["Q4"]["role"], "both")
            self.assertIn("not-an-item", node_by_qid)
            edge_by_pair = {
                (edge["student_qid"], edge["teacher_qid"]): edge
                for edge in read_rows(output / "edges.csv")
            }
            pair = edge_by_pair["Q1", "Q2"]
            self.assertEqual(pair["student_name"], "First student label")
            self.assertEqual(pair["teacher_name"], "First teacher")
            self.assertEqual(pair["statement_urls"], "S1|S2")
            self.assertEqual(pair["statement_ranks"], "DeprecatedRank|NormalRank")
            self.assertEqual(pair["reference_count"], "2")
            self.assertEqual(edge_by_pair["Q4", "Q2"]["statement_ranks"], "DeprecatedRank")
            self.assertIn(("Q4", "Q4"), edge_by_pair)
            self.assertIn(("Q4", "not-an-item"), edge_by_pair)
            metadata = json.loads((output / "metadata.json").read_bytes())
            self.assertEqual(metadata, json.loads(stdout.getvalue()))
            self.assertEqual(metadata["roster_people"], 2)
            self.assertEqual(metadata["teacher_links"], 4)
            self.assertEqual(metadata["teacher_links_with_references"], 1)

        query_sources = [(ROOT / "queries" / name).read_text(encoding="utf-8")
                         for name in ("roster.rq", "teacher_links.rq")]
        self.assertEqual(query.call_args_list, [call(source) for source in query_sources])
        for field, source in zip(("roster_query_sha256", "teacher_query_sha256"), query_sources):
            self.assertEqual(metadata[field], hashlib.sha256(source.encode()).hexdigest())

    def test_refresh_second_write_failure_leaves_existing_partial_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            arguments = ["extract_wikidata.py", "--query-dir", str(ROOT / "queries"),
                         "--output-dir", str(output)]
            original_writer = extract_wikidata.write_csv

            def fail_on_edges(path, fields, rows):
                if path.name == "edges.csv":
                    raise OSError("fixture write failure")
                original_writer(path, fields, rows)

            with (
                patch("sys.argv", arguments),
                patch.object(extract_wikidata, "run_query", side_effect=[[], []]),
                patch.object(extract_wikidata, "write_csv", side_effect=fail_on_edges),
                self.assertRaisesRegex(OSError, "fixture write failure"),
            ):
                extract_wikidata.main()
            self.assertEqual([entry.name for entry in output.iterdir()], ["nodes.csv"])

    def test_query_retries_network_and_decoding_failures(self):
        result = [{"person": {"value": "Q1"}}]
        response = io.BytesIO(json.dumps({"results": {"bindings": result}}).encode())
        with (
            patch.object(extract_wikidata.urllib.request, "urlopen",
                         side_effect=[OSError("offline fixture"), io.BytesIO(b"{"), response]) as request,
            patch.object(extract_wikidata.time, "sleep") as sleep,
        ):
            self.assertEqual(extract_wikidata.run_query("SELECT * WHERE {}"), result)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(2)])

    def test_exhausted_and_zero_query_attempts_keep_the_error_contract(self):
        with (
            patch.object(extract_wikidata.urllib.request, "urlopen",
                         side_effect=[OSError("first"), OSError("last")]) as request,
            patch.object(extract_wikidata.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "failed after 2 attempts: last"):
                extract_wikidata.run_query("SELECT * WHERE {}", retries=2)
            self.assertEqual(request.call_count, 2)
            sleep.assert_called_once_with(1)
        with patch.object(extract_wikidata.urllib.request, "urlopen") as request:
            with self.assertRaisesRegex(RuntimeError, "failed after 0 attempts: None"):
                extract_wikidata.run_query("SELECT * WHERE {}", retries=0)
            request.assert_not_called()
