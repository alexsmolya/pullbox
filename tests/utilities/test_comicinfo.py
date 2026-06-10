"""Tests for UT-2.1 — ComicInfo.xml module.

Verifies XML generation, field handling, embedding into CBZ archives,
and edge cases (unicode, HTML entities, missing fields, case-insensitive
replacement).

Run:
    pytest tests/utilities/test_comicinfo.py -v
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path  # noqa: TC003

import pytest

from pullbox.utilities.comicinfo import embed_comicinfo_in_cbz, generate_comicinfo_xml

# ── XML Generation ─────────────────────────────────────────────


class TestGenerateXml:
    """Verify generate_comicinfo_xml produces well-formed XML."""

    def test_well_formed_xml(self) -> None:
        xml_str = generate_comicinfo_xml({"Series": "Batman", "Number": "1"})
        root = ET.fromstring(xml_str)
        assert root.tag == "ComicInfo"

    def test_all_fields_populated(self) -> None:
        data = {
            "Series": "Batman",
            "Number": "5",
            "Title": "The Court of Owls",
            "Year": 2016,
            "Month": 3,
            "Day": 15,
            "Writer": "Scott Snyder",
            "Penciller": "Greg Capullo",
            "Inker": "Jonathan Glapion",
            "Colorist": "FCO Plascencia",
            "Letterer": "Richard Starkings",
            "Publisher": "DC Comics",
            "Genre": "Superhero, Action",
            "Summary": "Batman investigates the Court of Owls.",
            "PageCount": 32,
            "Web": "https://comicvine.gamespot.com/batman-5/1234/",
        }
        xml_str = generate_comicinfo_xml(data)
        root = ET.fromstring(xml_str)
        assert root.findtext("Series") == "Batman"
        assert root.findtext("Number") == "5"
        assert root.findtext("Writer") == "Scott Snyder"
        assert root.findtext("Publisher") == "DC Comics"
        assert root.findtext("PageCount") == "32"

    def test_missing_fields_omitted(self) -> None:
        xml_str = generate_comicinfo_xml({"Series": "Saga"})
        root = ET.fromstring(xml_str)
        assert root.find("Writer") is None
        assert root.find("Publisher") is None
        assert root.findtext("Series") == "Saga"

    def test_empty_string_fields_omitted(self) -> None:
        xml_str = generate_comicinfo_xml({"Series": "Batman", "Writer": "", "Title": ""})
        root = ET.fromstring(xml_str)
        assert root.find("Writer") is None
        assert root.find("Title") is None
        assert root.findtext("Series") == "Batman"

    def test_unicode_characters(self) -> None:
        xml_str = generate_comicinfo_xml(
            {
                "Series": "\u9032\u6483\u306e\u5de8\u4eba",
                "Writer": "Jos\u00e9 Garc\u00eda",
            }
        )
        root = ET.fromstring(xml_str)
        assert root.findtext("Series") == "\u9032\u6483\u306e\u5de8\u4eba"
        assert root.findtext("Writer") == "Jos\u00e9 Garc\u00eda"

    def test_html_entities_escaped(self) -> None:
        xml_str = generate_comicinfo_xml(
            {
                "Series": "Tom & Jerry",
                "Summary": 'He said "hello" & <waved>',
            }
        )
        root = ET.fromstring(xml_str)
        assert root.findtext("Series") == "Tom & Jerry"
        assert root.findtext("Summary") == 'He said "hello" & <waved>'

    def test_very_long_summary(self) -> None:
        long_summary = "x" * 6000
        xml_str = generate_comicinfo_xml({"Series": "Test", "Summary": long_summary})
        root = ET.fromstring(xml_str)
        assert len(root.findtext("Summary") or "") == 6000

    def test_numeric_fields_converted(self) -> None:
        xml_str = generate_comicinfo_xml({"Series": "Test", "Year": 2016, "PageCount": 32})
        root = ET.fromstring(xml_str)
        assert root.findtext("Year") == "2016"
        assert root.findtext("PageCount") == "32"

    def test_invalid_month_omitted(self) -> None:
        xml_str = generate_comicinfo_xml({"Series": "Test", "Month": 13})
        root = ET.fromstring(xml_str)
        assert root.find("Month") is None

    def test_invalid_day_omitted(self) -> None:
        xml_str = generate_comicinfo_xml({"Series": "Test", "Day": 32})
        root = ET.fromstring(xml_str)
        assert root.find("Day") is None

    def test_xml_declaration_present(self) -> None:
        xml_str = generate_comicinfo_xml({"Series": "Batman"})
        assert xml_str.startswith("<?xml")

    def test_minimal_valid_xml(self) -> None:
        """No fields at all still produces valid XML."""
        xml_str = generate_comicinfo_xml({})
        root = ET.fromstring(xml_str)
        assert root.tag == "ComicInfo"

    def test_multiple_writers_comma_separated(self) -> None:
        """Multiple writers passed as comma-separated string produce single Writer element."""
        xml_str = generate_comicinfo_xml(
            {"Series": "Paper Girls", "Writer": "Brian K. Vaughan, Cliff Chiang"}
        )
        root = ET.fromstring(xml_str)
        assert root.findtext("Writer") == "Brian K. Vaughan, Cliff Chiang"
        # Only one Writer element, not split
        writer_elements = root.findall("Writer")
        assert len(writer_elements) == 1

    def test_genre_with_pipe_separator(self) -> None:
        """Pipe-separated genre string preserved as-is in Genre element."""
        xml_str = generate_comicinfo_xml({"Series": "Batman", "Genre": "Superhero|Action"})
        root = ET.fromstring(xml_str)
        # ComicInfo spec uses commas, but we pass through as-is
        assert root.findtext("Genre") == "Superhero|Action"

    def test_malformed_existing_comicinfo_replaced(self, tmp_path: Path) -> None:
        """Embed into CBZ with invalid XML in ComicInfo.xml replaces completely."""
        cbz = tmp_path / "malformed.cbz"
        with zipfile.ZipFile(cbz, "w") as zf:
            zf.writestr("page_000.jpg", "FAKE_JPEG")
            zf.writestr("ComicInfo.xml", "<ComicInfo><Series>Bad<Unclosed")

        embed_comicinfo_in_cbz(cbz, {"Series": "Fixed", "Number": "1"})

        with zipfile.ZipFile(cbz) as zf:
            content = zf.read("ComicInfo.xml").decode("utf-8")
            root = ET.fromstring(content)
            assert root.findtext("Series") == "Fixed"
            assert root.findtext("Number") == "1"

    def test_existing_comicinfo_entities_are_replaced(self, tmp_path: Path) -> None:
        """Entity-bearing existing ComicInfo.xml is treated as unsafe malformed input."""
        cbz = tmp_path / "entities.cbz"
        with zipfile.ZipFile(cbz, "w") as zf:
            zf.writestr("page_000.jpg", "FAKE_JPEG")
            zf.writestr(
                "ComicInfo.xml",
                """\
<!DOCTYPE ComicInfo [
  <!ENTITY injected "Injected Series">
]>
<ComicInfo><Series>&injected;</Series></ComicInfo>
""",
            )

        embed_comicinfo_in_cbz(cbz, {"Series": "Fixed", "Number": "1"})

        with zipfile.ZipFile(cbz) as zf:
            content = zf.read("ComicInfo.xml").decode("utf-8")
            root = ET.fromstring(content)
            assert root.findtext("Series") == "Fixed"
            assert "Injected Series" not in content


# ── Embed in CBZ ───────────────────────────────────────────────


def _create_test_cbz(path: Path, pages: int = 3, comicinfo: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(pages):
            zf.writestr(f"page_{i:03d}.jpg", f"FAKE_JPEG_{i}")
        if comicinfo:
            zf.writestr("ComicInfo.xml", comicinfo)
    return path


class TestEmbedInCbz:
    """Verify embedding ComicInfo.xml into CBZ archives."""

    def test_embed_new_comicinfo(self, tmp_path: Path) -> None:
        cbz = _create_test_cbz(tmp_path / "test.cbz")
        embed_comicinfo_in_cbz(cbz, {"Series": "Batman", "Number": "5"})

        with zipfile.ZipFile(cbz) as zf:
            assert "ComicInfo.xml" in zf.namelist()
            content = zf.read("ComicInfo.xml").decode("utf-8")
            root = ET.fromstring(content)
            assert root.findtext("Series") == "Batman"

    def test_merge_existing_comicinfo_preserves_secondary_fields(self, tmp_path: Path) -> None:
        old_xml = (
            '<?xml version="1.0"?>'
            "<ComicInfo>"
            "<Series>Old Series</Series>"
            "<Number>9</Number>"
            "<Writer>Alan Moore</Writer>"
            "<Summary>Existing summary</Summary>"
            "<PageCount>28</PageCount>"
            "</ComicInfo>"
        )
        cbz = _create_test_cbz(tmp_path / "test.cbz", comicinfo=old_xml)
        embed_comicinfo_in_cbz(
            cbz,
            {
                "Series": "New Series",
                "Number": "1",
                "Publisher": "DC Comics",
                "Summary": "Pullbox summary",
                "PageCount": 24,
            },
        )

        with zipfile.ZipFile(cbz) as zf:
            ci_entries = [n for n in zf.namelist() if n.lower() == "comicinfo.xml"]
            assert len(ci_entries) == 1
            content = zf.read(ci_entries[0]).decode("utf-8")
            root = ET.fromstring(content)
            assert root.findtext("Series") == "New Series"
            assert root.findtext("Number") == "1"
            assert root.findtext("Publisher") == "DC Comics"
            assert root.findtext("Writer") == "Alan Moore"
            assert root.findtext("Summary") == "Pullbox summary"
            assert root.findtext("PageCount") == "24"

    def test_merge_existing_comicinfo_fills_missing_secondary_fields(self, tmp_path: Path) -> None:
        old_xml = (
            '<?xml version="1.0"?>'
            "<ComicInfo>"
            "<Series>Existing Series</Series>"
            "<Writer>Gail Simone</Writer>"
            "</ComicInfo>"
        )
        cbz = _create_test_cbz(tmp_path / "test.cbz", comicinfo=old_xml)
        embed_comicinfo_in_cbz(
            cbz,
            {
                "Series": "Pullbox Series",
                "Summary": "Pulled from Pullbox",
                "PageCount": 22,
            },
        )

        with zipfile.ZipFile(cbz) as zf:
            content = zf.read("ComicInfo.xml").decode("utf-8")
            root = ET.fromstring(content)
            assert root.findtext("Series") == "Pullbox Series"
            assert root.findtext("Writer") == "Gail Simone"
            assert root.findtext("Summary") == "Pulled from Pullbox"
            assert root.findtext("PageCount") == "22"

    def test_case_insensitive_replacement(self, tmp_path: Path) -> None:
        cbz_path = tmp_path / "test.cbz"
        with zipfile.ZipFile(cbz_path, "w") as zf:
            zf.writestr("page_000.jpg", "FAKE")
            zf.writestr("COMICINFO.XML", "<ComicInfo><Series>Old</Series></ComicInfo>")

        embed_comicinfo_in_cbz(cbz_path, {"Series": "Fixed"})

        with zipfile.ZipFile(cbz_path) as zf:
            ci_entries = [n for n in zf.namelist() if n.lower() == "comicinfo.xml"]
            assert len(ci_entries) == 1
            content = zf.read(ci_entries[0]).decode("utf-8")
            assert "Fixed" in content

    def test_archive_integrity_preserved(self, tmp_path: Path) -> None:
        cbz = _create_test_cbz(tmp_path / "test.cbz", pages=5)
        embed_comicinfo_in_cbz(cbz, {"Series": "Batman"})

        with zipfile.ZipFile(cbz) as zf:
            pages = [n for n in zf.namelist() if n.endswith(".jpg")]
            assert len(pages) == 5
            assert "ComicInfo.xml" in zf.namelist()

    def test_noop_merge_skips_archive_rewrite(self, tmp_path: Path) -> None:
        existing_xml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<ComicInfo>"
            "<Series>Batman</Series>"
            "<Number>5</Number>"
            "<Publisher>DC Comics</Publisher>"
            "<Writer>Grant Morrison</Writer>"
            "</ComicInfo>"
        )
        cbz = _create_test_cbz(tmp_path / "noop.cbz", comicinfo=existing_xml)
        original_bytes = cbz.read_bytes()

        changed = embed_comicinfo_in_cbz(
            cbz,
            {
                "Series": "Batman",
                "Number": "5",
                "Publisher": "DC Comics",
            },
        )

        assert changed is False
        assert cbz.read_bytes() == original_bytes

    def test_noop_merge_still_reports_completed_progress(self, tmp_path: Path) -> None:
        existing_xml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<ComicInfo>"
            "<Series>Batman</Series>"
            "<Number>5</Number>"
            "<Publisher>DC Comics</Publisher>"
            "</ComicInfo>"
        )
        cbz = _create_test_cbz(tmp_path / "noop-progress.cbz", comicinfo=existing_xml)
        progress_events: list[tuple[str, int, int, str]] = []

        changed = embed_comicinfo_in_cbz(
            cbz,
            {
                "Series": "Batman",
                "Number": "5",
                "Publisher": "DC Comics",
            },
            progress_callback=lambda stage, current, total, unit: progress_events.append(
                (stage, current, total, unit)
            ),
        )

        assert changed is False
        assert progress_events == [("rewriting", 1, 1, "entries")]

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            embed_comicinfo_in_cbz(tmp_path / "ghost.cbz", {"Series": "X"})

    def test_unicode_in_embedded_xml(self, tmp_path: Path) -> None:
        cbz = _create_test_cbz(tmp_path / "test.cbz")
        embed_comicinfo_in_cbz(
            cbz,
            {
                "Series": "\u9032\u6483\u306e\u5de8\u4eba",
                "Writer": "Jos\u00e9 Garc\u00eda",
            },
        )

        with zipfile.ZipFile(cbz) as zf:
            content = zf.read("ComicInfo.xml").decode("utf-8")
            assert "\u9032\u6483\u306e\u5de8\u4eba" in content

    def test_embed_in_readonly_cbz_raises(self, tmp_path: Path) -> None:
        """Read-only CBZ file raises OSError/PermissionError on embed."""
        import os
        import sys

        if sys.platform == "win32":
            pytest.skip("chmod not effective on Windows")

        cbz = _create_test_cbz(tmp_path / "readonly.cbz")
        # Make the parent directory read-only so tempfile creation fails
        os.chmod(tmp_path, 0o555)

        try:
            with pytest.raises((OSError, PermissionError)):
                embed_comicinfo_in_cbz(cbz, {"Series": "Should Fail"})
        finally:
            os.chmod(tmp_path, 0o755)
