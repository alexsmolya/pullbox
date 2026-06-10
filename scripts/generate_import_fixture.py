"""Generate a test import fixture ZIP for testing the collection import feature.

Creates a ZIP archive containing a simulated comic collection with various
matching scenarios:

1. Series folders with ComicInfo CV IDs (direct match)
2. Loose files with ComicInfo CV IDs (create series + match)
3. Series folders with good names, no CV ID (name-based match)
4. Loose files with good names, no CV ID (name-based match)
5. Duplicate/conflict files (series already in DB)
6. Mixed folder (good name, mix of parseable + junk files)
7. Year mismatch (folder year vs file year)
8. Variant types (annuals, TPBs)
9. Bad folder names with bad files (fail to match)
10. Loose bad files (fail to match)
11. Non-comic files mixed in (should be ignored)

Usage:
    python scripts/generate_import_fixture.py
    # Output: data/test-import-collection.zip
    # Extract to: data/test-import/
"""

import io
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_ZIP = _PROJECT_ROOT / "tests" / "fixtures" / "test-import-collection.zip"
_OUTPUT_DIR = _PROJECT_ROOT / "data" / "test-import"


def _make_minimal_png() -> bytes:
    """1x1 dark gray PNG."""
    sig = b"\x89PNG\r\n\x1a\n"
    def _chunk(t: bytes, d: bytes) -> bytes:
        raw = t + d
        crc = struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)
        return struct.pack(">I", len(d)) + raw + crc
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = _chunk(b"IDAT", zlib.compress(b"\x00\x33\x33\x33"))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _make_comicinfo_xml(
    series: str | None = None,
    number: str | None = None,
    volume: int | None = None,
    publisher: str | None = None,
    cvid: int | None = None,
) -> bytes:
    """Generate a ComicInfo.xml with optional fields."""
    root = Element("ComicInfo")
    if series:
        SubElement(root, "Series").text = series
    if number:
        SubElement(root, "Number").text = number
    if volume:
        SubElement(root, "Volume").text = str(volume)
    if publisher:
        SubElement(root, "Publisher").text = publisher
    if cvid:
        SubElement(root, "Notes").text = f"Scraped metadata [cvid:{cvid}]"
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + tostring(root)


def _make_cbz(
    page_count: int = 3,
    comicinfo: bytes | None = None,
) -> bytes:
    """Create a valid CBZ (ZIP) with placeholder pages and optional ComicInfo.xml."""
    page_png = _make_minimal_png()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if comicinfo:
            zf.writestr("ComicInfo.xml", comicinfo)
        for i in range(page_count):
            zf.writestr(f"page_{i + 1:03d}.png", page_png)
    return buf.getvalue()


def generate() -> None:
    """Build the fixture ZIP and also extract it to a directory."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    files: dict[str, bytes] = {}
    page_png = _make_minimal_png()

    # ────────────────────────────────────────────────────────────
    # Case 1: Series folders with ComicInfo CV IDs (direct match)
    # ────────────────────────────────────────────────────────────
    # Use real ComicVine volume IDs that exist in the API
    cv_series = [
        ("Green Lantern (2005)", 2005, "DC Comics", 18216, [
            ("Green Lantern (2005) #001.cbz", "1", 140812),
            ("Green Lantern (2005) #002.cbz", "2", 140813),
            ("Green Lantern (2005) #003.cbz", "3", 140814),
            ("Green Lantern (2005) #004.cbz", "4", 140815),
        ]),
        ("Daredevil (2011)", 2011, "Marvel", 41388, [
            ("Daredevil (2011) #001.cbz", "1", 310432),
            ("Daredevil (2011) #002.cbz", "2", 313567),
            ("Daredevil (2011) #003.cbz", "3", 316789),
        ]),
        ("East of West (2013)", 2013, "Image Comics", 55227, [
            ("East of West (2013) #001.cbz", "1", 387654),
            ("East of West (2013) #002.cbz", "2", 392100),
            ("East of West (2013) #003.cbz", "3", 396500),
            ("East of West (2013) #004.cbz", "4", 401200),
            ("East of West (2013) #005.cbz", "5", 405800),
        ]),
    ]
    for folder, year, pub, vol_cvid, issues in cv_series:
        for fname, num, issue_cvid in issues:
            ci = _make_comicinfo_xml(
                series=folder.split(" (")[0],
                number=num,
                volume=year,
                publisher=pub,
                cvid=issue_cvid,
            )
            files[f"{folder}/{fname}"] = _make_cbz(comicinfo=ci)

    # ────────────────────────────────────────────────────────────
    # Case 2: Loose files with ComicInfo CV IDs (no folder)
    # ────────────────────────────────────────────────────────────
    loose_cv = [
        ("Chew 001 (2009).cbz", "Chew", "1", 2009, "Image Comics", 450001),
        ("Chew 002 (2009).cbz", "Chew", "2", 2009, "Image Comics", 450002),
        ("Chew 003 (2009).cbz", "Chew", "3", 2009, "Image Comics", 450003),
        ("Locke and Key 001 (2008).cbz", "Locke & Key", "1", 2008, "IDW Publishing", 460001),
        ("Locke and Key 002 (2008).cbz", "Locke & Key", "2", 2008, "IDW Publishing", 460002),
    ]
    for fname, series, num, year, pub, cvid in loose_cv:
        ci = _make_comicinfo_xml(series=series, number=num, volume=year, publisher=pub, cvid=cvid)
        files[fname] = _make_cbz(comicinfo=ci)

    # ────────────────────────────────────────────────────────────
    # Case 3: Series folders with good names, no CV ID
    # ────────────────────────────────────────────────────────────
    name_match_series = [
        ("Planetary (1998)", 1998, "Wildstorm", [
            ("Planetary (1998) #001.cbz", "1"),
            ("Planetary (1998) #002.cbz", "2"),
            ("Planetary (1998) #003.cbz", "3"),
            ("Planetary (1998) #004.cbz", "4"),
        ]),
        ("Preacher (1995)", 1995, "Vertigo", [
            ("Preacher (1995) #001.cbz", "1"),
            ("Preacher (1995) #002.cbz", "2"),
            ("Preacher (1995) #003.cbz", "3"),
        ]),
        ("Fables (2002)", 2002, "Vertigo", [
            ("Fables (2002) #001.cbz", "1"),
            ("Fables (2002) #002.cbz", "2"),
            ("Fables (2002) #003.cbz", "3"),
            ("Fables (2002) #004.cbz", "4"),
            ("Fables (2002) #005.cbz", "5"),
        ]),
    ]
    for folder, year, pub, issues in name_match_series:
        for fname, num in issues:
            ci = _make_comicinfo_xml(
                series=folder.split(" (")[0],
                number=num,
                volume=year,
                publisher=pub,
            )
            files[f"{folder}/{fname}"] = _make_cbz(comicinfo=ci)

    # ────────────────────────────────────────────────────────────
    # Case 4: Loose files with good names, no CV ID
    # ────────────────────────────────────────────────────────────
    loose_names = [
        ("Y The Last Man 001 (2002).cbz", "Y: The Last Man", "1", 2002, "Vertigo"),
        ("Y The Last Man 002 (2002).cbz", "Y: The Last Man", "2", 2002, "Vertigo"),
        ("Y The Last Man 003 (2002).cbz", "Y: The Last Man", "3", 2002, "Vertigo"),
        ("100 Bullets 001 (1999).cbz", "100 Bullets", "1", 1999, "Vertigo"),
        ("100 Bullets 002 (1999).cbz", "100 Bullets", "2", 1999, "Vertigo"),
    ]
    for fname, series, num, year, pub in loose_names:
        ci = _make_comicinfo_xml(series=series, number=num, volume=year, publisher=pub)
        files[fname] = _make_cbz(comicinfo=ci)

    # ────────────────────────────────────────────────────────────
    # Case 5: Duplicate/conflict — series already in DB
    # ────────────────────────────────────────────────────────────
    # Batman and Saga are in the seed data. These should trigger dedup detection.
    conflict_series = [
        ("Batman (2016)", 2016, "DC Comics", [
            ("Batman (2016) #001.cbz", "1"),
            ("Batman (2016) #002.cbz", "2"),
            ("Batman (2016) #010.cbz", "10"),
        ]),
        ("Saga (2012)", 2012, "Image Comics", [
            ("Saga (2012) #001.cbz", "1"),
            ("Saga (2012) #005.cbz", "5"),
        ]),
    ]
    for folder, year, pub, issues in conflict_series:
        for fname, num in issues:
            ci = _make_comicinfo_xml(
                series=folder.split(" (")[0],
                number=num,
                volume=year,
                publisher=pub,
            )
            files[f"{folder}/{fname}"] = _make_cbz(comicinfo=ci)

    # ────────────────────────────────────────────────────────────
    # Case 6: Mixed folder — good name, parseable + junk files
    # ────────────────────────────────────────────────────────────
    files["Hellboy (1993)/Hellboy (1993) #001.cbz"] = _make_cbz(
        comicinfo=_make_comicinfo_xml(series="Hellboy", number="1", volume=1993, publisher="Dark Horse")
    )
    files["Hellboy (1993)/Hellboy (1993) #002.cbz"] = _make_cbz(
        comicinfo=_make_comicinfo_xml(series="Hellboy", number="2", volume=1993, publisher="Dark Horse")
    )
    files["Hellboy (1993)/extras/cover_scan.cbz"] = _make_cbz(page_count=1)
    files["Hellboy (1993)/extras/promo_art.cbz"] = _make_cbz(page_count=1)
    files["Hellboy (1993)/desktop.ini"] = b"[.ShellClassInfo]\nIconResource=folder.ico,0"

    # ────────────────────────────────────────────────────────────
    # Case 7: Year mismatch — folder says 2018, files say 2023
    # ────────────────────────────────────────────────────────────
    for i in range(1, 4):
        ci = _make_comicinfo_xml(
            series="Superman", number=str(i), volume=2023, publisher="DC Comics"
        )
        files[f"Superman (2018)/Superman (2023) #{i:03d}.cbz"] = _make_cbz(comicinfo=ci)

    # ────────────────────────────────────────────────────────────
    # Case 8: Variant types — annuals, TPBs
    # ────────────────────────────────────────────────────────────
    # Annual folder
    for i in range(1, 4):
        ci = _make_comicinfo_xml(
            series="Batman Annual", number=str(i), volume=2016, publisher="DC Comics"
        )
        files[f"Batman Annual (2016)/Batman Annual (2016) #{i:03d}.cbz"] = _make_cbz(comicinfo=ci)

    # TPB files (loose)
    files["Saga Vol 01 TPB (2012).cbz"] = _make_cbz(
        comicinfo=_make_comicinfo_xml(series="Saga", number="1", volume=2012, publisher="Image Comics")
    )
    files["Saga Vol 02 TPB (2012).cbz"] = _make_cbz(
        comicinfo=_make_comicinfo_xml(series="Saga", number="2", volume=2012, publisher="Image Comics")
    )

    # Graphic novel
    files["Batman - The Long Halloween (1996).cbz"] = _make_cbz(
        comicinfo=_make_comicinfo_xml(
            series="Batman: The Long Halloween", number="1", volume=1996, publisher="DC Comics"
        )
    )

    # ────────────────────────────────────────────────────────────
    # Case 9: Bad folder names with bad files
    # ────────────────────────────────────────────────────────────
    bad_folders = {
        "Comics Misc": ["file001.cbz", "file002.cbz", "file003.cbz"],
        "Scan_Batch_2024": ["IMG_4521.cbz", "IMG_4522.cbz", "scan_final.cbz"],
        "New Folder (2)": ["doc1.cbz", "doc2.cbz"],
        "unsorted": ["comic_a.cbz", "comic_b.cbz", "comic_c.cbz", "comic_d.cbz"],
    }
    for folder, filenames in bad_folders.items():
        for fname in filenames:
            files[f"{folder}/{fname}"] = _make_cbz(page_count=2)

    # ────────────────────────────────────────────────────────────
    # Case 10: Loose bad files
    # ────────────────────────────────────────────────────────────
    loose_bad = [
        "download (3).cbz",
        "untitled.cbz",
        "New Document.cbz",
        "test.cbz",
        "comic.cbz",
    ]
    for fname in loose_bad:
        files[fname] = _make_cbz(page_count=1)

    # ────────────────────────────────────────────────────────────
    # Case 11: Non-comic files (should be ignored by scanner)
    # ────────────────────────────────────────────────────────────
    files["README.txt"] = b"This is my comic collection. Do not delete!"
    files["collection_notes.nfo"] = b"Organized by publisher and year."
    files["folder_icon.jpg"] = page_png  # PNG data but .jpg extension
    files["Green Lantern (2005)/Thumbs.db"] = b"\x00" * 100
    files["Planetary (1998)/desktop.ini"] = b"[.ShellClassInfo]"
    files["covers/batman_cover.jpg"] = page_png
    files["covers/saga_cover.png"] = page_png

    # ── Write ZIP ───────────────────────────────────────────────
    _OUTPUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(_OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in sorted(files.items()):
            zf.writestr(path, data)

    total_cbz = sum(1 for p in files if p.endswith(".cbz"))
    total_non = sum(1 for p in files if not p.endswith(".cbz"))
    folders = set(p.rsplit("/", 1)[0] for p in files if "/" in p)

    print(f"Generated: {_OUTPUT_ZIP}")
    print(f"  {len(files)} total files ({total_cbz} CBZ, {total_non} non-comic)")
    print(f"  {len(folders)} folders")
    print()

    # ── Also extract to directory for direct import ─────────────
    if _OUTPUT_DIR.exists():
        import shutil
        shutil.rmtree(_OUTPUT_DIR)
    _OUTPUT_DIR.mkdir(parents=True)
    with zipfile.ZipFile(_OUTPUT_ZIP, "r") as zf:
        zf.extractall(_OUTPUT_DIR)

    print(f"Extracted to: {_OUTPUT_DIR}")
    print()
    print("Test scenarios:")
    print("  1. Direct CV match:   Green Lantern, Daredevil, East of West (folder + ComicInfo CV IDs)")
    print("  2. Loose + CV:        Chew, Locke & Key (loose files with ComicInfo CV IDs)")
    print("  3. Name match:        Planetary, Preacher, Fables (folder + good names, no CV ID)")
    print("  4. Loose name match:  Y The Last Man, 100 Bullets (loose files, good names)")
    print("  5. Duplicate/conflict: Batman, Saga (already in DB)")
    print("  6. Mixed folder:      Hellboy (parseable + junk files + non-comics)")
    print("  7. Year mismatch:     Superman folder=2018, files=2023")
    print("  8. Variants:          Batman Annual folder, Saga TPBs, Long Halloween GN")
    print("  9. Bad folders:       Comics Misc, Scan_Batch_2024, New Folder (2), unsorted")
    print(" 10. Loose bad files:   download (3).cbz, untitled.cbz, etc.")
    print(" 11. Non-comics:        README.txt, .nfo, .jpg, Thumbs.db, desktop.ini")


if __name__ == "__main__":
    generate()
