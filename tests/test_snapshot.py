from __future__ import annotations

import csv
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class SnapshotIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.nodes = read_csv(ROOT / "data" / "nodes.csv")
        cls.edges = read_csv(ROOT / "data" / "edges.csv")

    def test_expected_snapshot_counts(self) -> None:
        roster = [row for row in self.nodes if row["role"] in {"roster", "both"}]
        teachers = {row["teacher_qid"] for row in self.edges}
        self.assertEqual(len(roster), 144)
        self.assertEqual(len(self.edges), 129)
        self.assertEqual(len(teachers), 98)

    def test_unique_nodes_and_edges(self) -> None:
        node_ids = [row["qid"] for row in self.nodes]
        edge_ids = [(row["student_qid"], row["teacher_qid"]) for row in self.edges]
        self.assertEqual(len(node_ids), len(set(node_ids)))
        self.assertEqual(len(edge_ids), len(set(edge_ids)))

    def test_every_edge_references_saved_nodes(self) -> None:
        node_ids = {row["qid"] for row in self.nodes}
        for edge in self.edges:
            self.assertIn(edge["student_qid"], node_ids)
            self.assertIn(edge["teacher_qid"], node_ids)

    def test_qids_and_urls_are_well_formed(self) -> None:
        for node in self.nodes:
            self.assertRegex(node["qid"], r"^Q\d+$")
            self.assertEqual(
                node["wikidata_url"],
                f"https://www.wikidata.org/wiki/{node['qid']}",
            )


if __name__ == "__main__":
    unittest.main()
