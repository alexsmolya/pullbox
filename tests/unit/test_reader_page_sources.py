"""Contract tests for the bounded comic-reader page-source foundation."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import py7zr
import pytest
from PIL import Image

from pullbox.core.page_sources import (
    PageSourceError,
    PageSourceErrorCode,
    ReaderResourceLimits,
    canonical_page_names,
    detect_comic_format,
    open_page_source,
)
from pullbox.models.library import FileFormat


def _tiny_gif() -> bytes:
    output = io.BytesIO()
    with Image.new("P", (1, 1), color=0) as image:
        image.save(output, format="GIF")
    return output.getvalue()


_GIF = _tiny_gif()


def _write_cbz(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def _write_cb7(path: Path, members: dict[str, bytes]) -> None:
    payload_root = path.parent / f"{path.stem}-payload"
    payload_root.mkdir()
    with py7zr.SevenZipFile(path, "w") as archive:
        for name, payload in members.items():
            source = payload_root / Path(name)
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(payload)
            archive.write(source, name)


def _write_cbt(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_canonical_page_names_filter_and_naturally_order() -> None:
    names = [
        "pages/10.jpg",
        "pages/02.JPG",
        "pages/2.jpg",
        "pages/1.webp",
        "pages/.hidden.png",
        "__MACOSX/pages/3.jpg",
        "ComicInfo.xml",
        "../escape.jpg",
        "/absolute.jpg",
        "pages/readme.txt",
    ]

    assert canonical_page_names(names) == [
        "pages/1.webp",
        "pages/2.jpg",
        "pages/02.JPG",
        "pages/10.jpg",
    ]


@pytest.mark.parametrize(
    ("filename", "payload", "expected"),
    [
        ("book.cbz", b"PK\x03\x04payload", FileFormat.CBZ),
        ("book.cbr", b"Rar!\x1a\x07\x01\x00payload", FileFormat.CBR),
        ("book.cb7", b"7z\xbc\xaf\x27\x1cpayload", FileFormat.CB7),
        ("book.pdf", b"%PDF-1.7\npayload", FileFormat.PDF),
    ],
)
def test_detect_comic_format_uses_signature(
    tmp_path: Path,
    filename: str,
    payload: bytes,
    expected: FileFormat,
) -> None:
    source = tmp_path / filename
    source.write_bytes(payload)

    assert detect_comic_format(source) is expected


def test_detect_comic_format_recognizes_tar_as_cbt(tmp_path: Path) -> None:
    source = tmp_path / "book.cbt"
    _write_cbt(source, {"001.gif": _GIF})

    assert detect_comic_format(source) is FileFormat.CBT


def test_detect_comic_format_reads_only_the_signature(tmp_path: Path) -> None:
    source = tmp_path / "large.cbz"
    source.write_bytes(b"PK\x03\x04" + b"x" * 1024)

    with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read")):
        assert detect_comic_format(source) is FileFormat.CBZ


@pytest.mark.parametrize("format_name", ["cbz", "cb7", "cbt"])
def test_archive_page_sources_share_one_index_and_return_bounded_pages(
    tmp_path: Path,
    format_name: str,
) -> None:
    source = tmp_path / f"book.{format_name}"
    members = {
        "10.gif": _GIF + b"10",
        "2.gif": _GIF + b"2",
        "1.gif": _GIF + b"1",
        "ComicInfo.xml": b"<ComicInfo />",
    }
    writer = {"cbz": _write_cbz, "cb7": _write_cb7, "cbt": _write_cbt}[format_name]
    writer(source, members)

    page_source = open_page_source(source, declared_format=FileFormat(format_name))

    assert [page.name for page in page_source.pages] == ["1.gif", "2.gif", "10.gif"]
    page = page_source.read_page(1)
    assert page.index == 1
    assert page.media_type == "image/gif"
    assert page.data.endswith(b"2")


def test_cbr_page_source_uses_the_same_canonical_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rarfile

    from pullbox.core import archive as archive_module

    source = tmp_path / "book.cbr"
    source.write_bytes(b"Rar!\x1a\x07\x00payload")

    class _FakeRarFile:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def __enter__(self) -> _FakeRarFile:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def namelist(self) -> list[str]:
            return ["10.gif", "2.gif", "1.gif", "ComicInfo.xml"]

        def read(self, name: str) -> bytes:
            return _GIF + name.encode()

    monkeypatch.setattr(archive_module, "configure_rarfile_backend", lambda: None)
    monkeypatch.setattr(rarfile, "RarFile", _FakeRarFile)

    page_source = open_page_source(source, declared_format=FileFormat.CBR)

    assert [page.name for page in page_source.pages] == ["1.gif", "2.gif", "10.gif"]
    assert page_source.read_page(1).data.endswith(b"2.gif")


def test_page_source_rejects_mislabeled_content(tmp_path: Path) -> None:
    source = tmp_path / "pretend.cbz"
    source.write_bytes(b"%PDF-1.7\n")

    with pytest.raises(PageSourceError) as exc_info:
        open_page_source(source, declared_format=FileFormat.CBZ)

    assert exc_info.value.code is PageSourceErrorCode.FORMAT_MISMATCH


def test_page_source_rejects_out_of_range_page(tmp_path: Path) -> None:
    source = tmp_path / "book.cbz"
    _write_cbz(source, {"1.gif": _GIF})
    page_source = open_page_source(source, declared_format=FileFormat.CBZ)

    with pytest.raises(PageSourceError) as exc_info:
        page_source.read_page(1)

    assert exc_info.value.code is PageSourceErrorCode.PAGE_OUT_OF_RANGE


def test_page_source_enforces_entry_and_page_byte_budgets(tmp_path: Path) -> None:
    source = tmp_path / "book.cbz"
    _write_cbz(source, {"1.gif": _GIF, "2.gif": _GIF})

    with pytest.raises(PageSourceError) as entry_error:
        open_page_source(
            source,
            declared_format=FileFormat.CBZ,
            limits=ReaderResourceLimits(max_entries=1),
        )
    assert entry_error.value.code is PageSourceErrorCode.RESOURCE_LIMIT

    page_source = open_page_source(
        source,
        declared_format=FileFormat.CBZ,
        limits=ReaderResourceLimits(max_page_bytes=8),
    )
    with pytest.raises(PageSourceError) as page_error:
        page_source.read_page(0)
    assert page_error.value.code is PageSourceErrorCode.RESOURCE_LIMIT


@pytest.mark.parametrize(("suffix", "source_format"), [("bmp", "BMP"), ("tiff", "TIFF")])
def test_non_browser_baseline_images_are_normalized_to_jpeg(
    tmp_path: Path,
    suffix: str,
    source_format: str,
) -> None:
    image_bytes = io.BytesIO()
    with Image.new("RGB", (2, 3), color="purple") as image:
        image.save(image_bytes, format=source_format)
    source = tmp_path / "book.cbz"
    _write_cbz(source, {f"001.{suffix}": image_bytes.getvalue()})

    page_source = open_page_source(source, declared_format=FileFormat.CBZ)
    page = page_source.read_page(0)

    assert page_source.pages[0].media_type == "image/jpeg"
    assert page.media_type == "image/jpeg"
    assert page.data.startswith(b"\xff\xd8\xff")


def test_image_pixel_budget_is_enforced_before_full_decode(tmp_path: Path) -> None:
    image_bytes = io.BytesIO()
    with Image.new("RGB", (10, 10), color="black") as image:
        image.save(image_bytes, format="PNG")
    source = tmp_path / "book.cbz"
    _write_cbz(source, {"001.png": image_bytes.getvalue()})
    page_source = open_page_source(
        source,
        declared_format=FileFormat.CBZ,
        limits=ReaderResourceLimits(max_image_pixels=99),
    )

    with pytest.raises(PageSourceError) as exc_info:
        page_source.read_page(0)

    assert exc_info.value.code is PageSourceErrorCode.RESOURCE_LIMIT


def test_pdf_page_source_renders_only_requested_page(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    render_calls: list[tuple[int, int]] = []

    class _RenderedPage:
        size = (100, 200)

        def save(self, output: io.BytesIO, *, format: str, quality: int, optimize: bool) -> None:
            assert format == "JPEG"
            assert quality == 88
            assert optimize is True
            output.write(b"jpeg-page")

        def close(self) -> None:
            return None

    def _render(_path: str, **kwargs: object) -> list[_RenderedPage]:
        render_calls.append((int(kwargs["first_page"]), int(kwargs["last_page"])))
        return [_RenderedPage()]

    with (
        patch("pdf2image.pdfinfo_from_path", return_value={"Pages": 4}),
        patch("pdf2image.convert_from_path", side_effect=_render),
    ):
        page_source = open_page_source(source, declared_format=FileFormat.PDF)
        page = page_source.read_page(2)

    assert len(page_source.pages) == 4
    assert page.data == b"jpeg-page"
    assert page.media_type == "image/jpeg"
    assert render_calls == [(3, 3)]
