import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generate import (
    PdfEntry,
    build_site,
    display_name,
    pdf_sort_key,
    topic_sort_key,
    url_path,
)


class GeneratorTests(unittest.TestCase):
    def test_display_name_cleans_file_names(self):
        self.assertEqual(display_name("cauchy_sequences"), "Cauchy Sequences")

    def test_url_path_encodes_components_and_preserves_slashes(self):
        self.assertEqual(
            url_path("/math", "assets/pdfs/real analysis/note 1.pdf"),
            "/math/assets/pdfs/real%20analysis/note%201.pdf",
        )

    def test_topic_order_prioritizes_configured_topics(self):
        order = ["number_theory", "complex_analysis"]
        topics = ["topology", "complex_analysis", "algebra", "number_theory"]

        self.assertEqual(
            sorted(topics, key=lambda topic: topic_sort_key(topic, order)),
            ["number_theory", "complex_analysis", "algebra", "topology"],
        )

    def test_pdf_order_prioritizes_configured_entries(self):
        def entry(title, source):
            return PdfEntry(
                title=title,
                description="",
                section_key="topology",
                section="Topology",
                source=Path(source),
                asset_url="",
                viewer_url="",
                size="",
            )

        entries = [
            entry("Zeta", "topology/zeta.pdf"),
            entry("Alpha", "topology/alpha.pdf"),
            entry("Middle", "topology/middle.pdf"),
        ]

        ordered = sorted(
            entries,
            key=lambda item: pdf_sort_key(item, ["topology/middle.pdf"]),
        )

        self.assertEqual(
            [item.source.as_posix() for item in ordered],
            [
                "topology/middle.pdf",
                "topology/alpha.pdf",
                "topology/zeta.pdf",
            ],
        )

    def test_build_discovers_nested_pdfs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            output = root / "output"
            pdf = source / "number_theory" / "new_note.pdf"
            metadata_path = root / "pdf_metadata.json"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"%PDF-1.4\n")
            metadata_path.write_text(
                json.dumps(
                    {
                        "number_theory/new_note.pdf": {
                            "title": "A Custom Title",
                            "description": "A custom description for this document.",
                        }
                    }
                )
            )

            count = build_site(
                source,
                output,
                "/math",
                "G-TEST123",
                metadata_path=metadata_path,
            )

            self.assertEqual(count, 1)
            self.assertTrue((output / "assets/pdfs/number_theory/new_note.pdf").exists())
            index = (output / "index.html").read_text()
            self.assertIn("A Custom Title", index)
            self.assertIn("A custom description for this document.", index)
            self.assertIn("G-TEST123", index)
            self.assertEqual(len(list((output / "view").glob("*.html"))), 1)

    def test_missing_override_uses_filename_title(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            output = root / "output"
            pdf = source / "new_note.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"%PDF-1.4\n")

            build_site(
                source,
                output,
                "",
                "",
                metadata_path=root / "missing.json",
            )

            self.assertIn("New Note", (output / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
