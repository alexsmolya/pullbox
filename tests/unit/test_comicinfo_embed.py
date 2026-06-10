"""Tests for ComicInfo.xml merge behavior."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from typing import TYPE_CHECKING

from pullbox.utilities.comicinfo import embed_comicinfo_in_cbz, materialize_cbz_with_comicinfo

if TYPE_CHECKING:
    from pathlib import Path


def _write_cbz(path: Path, comicinfo_xml: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("page001.jpg", b"image")
        archive.writestr("ComicInfo.xml", comicinfo_xml)


def _read_comicinfo(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path, "r") as archive:
        xml_content = archive.read("ComicInfo.xml").decode("utf-8")
    root = ET.fromstring(xml_content)
    return {child.tag: child.text or "" for child in root}


def test_embed_comicinfo_overwrites_expanded_authoritative_fields(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "issue.cbz"
    _write_cbz(
        archive_path,
        """
        <ComicInfo>
          <Series>Old Series</Series>
          <Summary>Old summary</Summary>
          <Writer>Old Writer</Writer>
          <Penciller>Old Penciller</Penciller>
          <Inker>Old Inker</Inker>
          <Colorist>Old Colorist</Colorist>
          <Letterer>Old Letterer</Letterer>
          <CoverArtist>Old Cover Artist</CoverArtist>
          <Editor>Old Editor</Editor>
          <PageCount>12</PageCount>
          <Count>6</Count>
          <Genre>Existing Genre</Genre>
          <Tags>Existing Tags</Tags>
          <CustomField>Keep Me</CustomField>
        </ComicInfo>
        """,
    )

    embed_comicinfo_in_cbz(
        archive_path,
        {
            "Series": "New Series",
            "Summary": "New summary",
            "Writer": "New Writer",
            "Penciller": "New Penciller",
            "Inker": "New Inker",
            "Colorist": "New Colorist",
            "Letterer": "New Letterer",
            "CoverArtist": "New Cover Artist",
            "Editor": "New Editor",
            "PageCount": 24,
            "Count": 10,
            "Genre": "New Genre",
            "Tags": "New Tags",
        },
    )

    fields = _read_comicinfo(archive_path)

    assert fields["Series"] == "New Series"
    assert fields["Summary"] == "New summary"
    assert fields["Writer"] == "New Writer"
    assert fields["Penciller"] == "New Penciller"
    assert fields["Inker"] == "New Inker"
    assert fields["Colorist"] == "New Colorist"
    assert fields["Letterer"] == "New Letterer"
    assert fields["CoverArtist"] == "New Cover Artist"
    assert fields["Editor"] == "New Editor"
    assert fields["PageCount"] == "24"
    assert fields["Count"] == "10"
    assert fields["Genre"] == "Existing Genre"
    assert fields["Tags"] == "Existing Tags"
    assert fields["CustomField"] == "Keep Me"


def test_embed_comicinfo_preserves_authoritative_fields_when_pullbox_has_no_value(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "issue.cbz"
    _write_cbz(
        archive_path,
        """
        <ComicInfo>
          <Summary>Existing summary</Summary>
          <Writer>Existing Writer</Writer>
          <PageCount>22</PageCount>
          <Count>4</Count>
        </ComicInfo>
        """,
    )

    embed_comicinfo_in_cbz(
        archive_path,
        {
            "Summary": None,
            "Writer": None,
            "PageCount": None,
            "Count": None,
        },
    )

    fields = _read_comicinfo(archive_path)

    assert fields["Summary"] == "Existing summary"
    assert fields["Writer"] == "Existing Writer"
    assert fields["PageCount"] == "22"
    assert fields["Count"] == "4"


def test_embed_comicinfo_drops_stale_retailer_web_and_notes_without_replacements(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "issue.cbz"
    _write_cbz(
        archive_path,
        """
        <ComicInfo>
          <Series>Old Series</Series>
          <Web>https://www.amazon.com/dp/B09DEADLINK</Web>
          <Notes>Imported from Comixology [cvid:12345]</Notes>
          <Genre>Existing Genre</Genre>
        </ComicInfo>
        """,
    )

    embed_comicinfo_in_cbz(
        archive_path,
        {
            "Series": "New Series",
            "Web": None,
            "Notes": None,
        },
    )

    fields = _read_comicinfo(archive_path)

    assert fields["Series"] == "New Series"
    assert "Web" not in fields
    assert "Notes" not in fields
    assert fields["Genre"] == "Existing Genre"


def test_embed_comicinfo_replaces_stale_retailer_fields_with_pullbox_values(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "issue.cbz"
    _write_cbz(
        archive_path,
        """
        <ComicInfo>
          <Web>https://www.comixology.com/Old-Dead-Link/digital-comic/1</Web>
          <Notes>Amazon metadata</Notes>
        </ComicInfo>
        """,
    )

    embed_comicinfo_in_cbz(
        archive_path,
        {
            "Web": "https://comicvine.gamespot.com/batman-1/4000-123456/",
            "Notes": "[cv_vol_id:97508] [cv_issue_id:123456]",
        },
    )

    fields = _read_comicinfo(archive_path)

    assert fields["Web"] == "https://comicvine.gamespot.com/batman-1/4000-123456/"
    assert fields["Notes"] == "[cv_vol_id:97508] [cv_issue_id:123456]"


def test_materialize_cbz_with_comicinfo_writes_target_in_one_pass(tmp_path: Path) -> None:
    source = tmp_path / "source.cbz"
    target = tmp_path / "library" / "target.cbz"
    _write_cbz(
        source,
        """
        <ComicInfo>
          <Series>Old Series</Series>
          <Number>9</Number>
          <Pages>
            <Page Image="0" />
          </Pages>
        </ComicInfo>
        """,
    )

    changed = materialize_cbz_with_comicinfo(
        source,
        target,
        {
            "Series": "New Series",
            "Number": "1",
            "Notes": "[cv_vol_id:100] [cv_issue_id:200]",
        },
        transfer_method="copy",
    )

    assert changed is True
    assert source.exists()
    assert target.exists()
    with zipfile.ZipFile(target, "r") as archive:
        names = archive.namelist()
        xml_content = archive.read("ComicInfo.xml").decode("utf-8")
    root = ET.fromstring(xml_content)
    assert names.count("ComicInfo.xml") == 1
    assert "page001.jpg" in names
    assert root.findtext("Series") == "New Series"
    assert root.findtext("Number") == "1"
    assert root.find("Pages") is not None


def test_materialize_cbz_with_comicinfo_move_deletes_source_after_success(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.cbz"
    target = tmp_path / "target.cbz"
    _write_cbz(source, "<ComicInfo><Series>Old Series</Series></ComicInfo>")

    materialize_cbz_with_comicinfo(
        source,
        target,
        {"Series": "Moved Series"},
        transfer_method="move",
    )

    assert not source.exists()
    assert target.exists()
    assert _read_comicinfo(target)["Series"] == "Moved Series"
