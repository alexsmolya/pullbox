"""Standalone archive integrity checks for utility jobs and post-processing."""

from __future__ import annotations

import asyncio
import hashlib
import io
import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from pullbox.core.file_safety import has_archive_member_path_traversal
from pullbox.core.rar_backend import configure_rarfile_backend

IMAGE_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".webp",
        ".tiff",
        ".tif",
    }
)
SCAN_EXTENSIONS = frozenset({".cbz", ".cbr", ".cb7", ".cbt", ".pdf"})


@dataclass
class IntegrityResult:
    """Result of checking a single file's integrity."""

    status: str  # "healthy", "corrupt", "warning"
    page_count: int = 0
    file_hash: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def check_file_integrity(
    path: Path,
    deep: bool = False,
) -> IntegrityResult:
    """Check a single file's integrity. Usable outside the job queue."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _check_sync, path, deep)


def _unsafe_archive_member_error(name: str) -> str:
    return f"Unsafe archive member path: {name}"


def _find_unsafe_archive_member(names: list[str]) -> str | None:
    for name in names:
        if has_archive_member_path_traversal(name):
            return name
    return None


def _reject_unsafe_archive_members(
    names: list[str],
    errors: list[str],
    warnings: list[str],
    page_count: int,
) -> IntegrityResult | None:
    unsafe = _find_unsafe_archive_member(names)
    if unsafe is None:
        return None
    errors.append(_unsafe_archive_member_error(unsafe))
    return IntegrityResult(
        status="corrupt",
        page_count=page_count,
        errors=errors,
        warnings=warnings,
    )


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def _compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _check_sync(path: Path, deep: bool) -> IntegrityResult:
    """Synchronous integrity check — runs in a worker thread/process."""
    warnings: list[str] = []
    errors: list[str] = []

    if not path.exists():
        return IntegrityResult(status="corrupt", errors=[f"File not found: {path}"])

    if path.stat().st_size == 0:
        return IntegrityResult(status="corrupt", errors=["Empty file (0 bytes)"])

    suffix = path.suffix.lower()

    try:
        if suffix in {".cbz", ".zip"}:
            result = _check_zip(path, deep, warnings, errors)
        elif suffix == ".cb7":
            result = _check_7z(path, deep, warnings, errors)
        elif suffix == ".cbr":
            result = _check_rar(path, deep, warnings, errors)
        elif suffix == ".cbt":
            result = _check_tar(path, deep, warnings, errors)
        elif suffix == ".pdf":
            result = _check_pdf(path, deep, warnings, errors)
        else:
            result = _check_zip(path, deep, warnings, errors)

        if result.status != "corrupt":
            result.file_hash = _compute_file_hash(path)
        return result
    except Exception as exc:
        errors.append(f"Integrity check failed: {exc}")
        return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)


def _check_zip(
    path: Path,
    deep: bool,
    warnings: list[str],
    errors: list[str],
) -> IntegrityResult:
    """Check a ZIP/CBZ archive."""
    try:
        with zipfile.ZipFile(path, "r") as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                errors.append(f"Corrupt entry: {bad_entry}")
                return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)

            image_names = [
                name for name in archive.namelist() if Path(name).suffix.lower() in IMAGE_EXTENSIONS
            ]
            if not image_names:
                errors.append("No valid images found in archive")
                return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)

            page_count = len(image_names)
            if deep:
                deep_errors = _deep_verify_zip_images(archive, image_names, warnings)
                if deep_errors:
                    errors.extend(deep_errors)
                    return IntegrityResult(
                        status="corrupt",
                        page_count=page_count,
                        warnings=warnings,
                        errors=errors,
                    )

            return IntegrityResult(
                status="warning" if warnings else "healthy",
                page_count=page_count,
                warnings=warnings,
                errors=errors,
            )
    except zipfile.BadZipFile as exc:
        errors.append(f"Invalid ZIP archive: {exc}")
        return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)


def _check_7z(
    path: Path,
    deep: bool,
    warnings: list[str],
    errors: list[str],
) -> IntegrityResult:
    """Check a 7z/CB7 archive."""
    import py7zr

    try:
        with py7zr.SevenZipFile(path, "r") as archive:
            image_names = [
                name for name in archive.getnames() if Path(name).suffix.lower() in IMAGE_EXTENSIONS
            ]
            if not image_names:
                errors.append("No valid images found in archive")
                return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)

            page_count = len(image_names)
            unsafe_result = _reject_unsafe_archive_members(
                image_names,
                errors,
                warnings,
                page_count,
            )
            if unsafe_result is not None:
                return unsafe_result

            if deep:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    archive.extract(path=tmp_dir, targets=image_names)
                    deep_errors = _deep_verify_extracted_images(
                        Path(tmp_dir),
                        image_names,
                        warnings,
                    )
                    if deep_errors:
                        errors.extend(deep_errors)
                        return IntegrityResult(
                            status="corrupt",
                            page_count=page_count,
                            warnings=warnings,
                            errors=errors,
                        )

            return IntegrityResult(
                status="warning" if warnings else "healthy",
                page_count=page_count,
                warnings=warnings,
                errors=errors,
            )
    except Exception as exc:
        errors.append(f"Cannot open 7z archive: {exc}")
        return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)


def _check_rar(
    path: Path,
    deep: bool,
    warnings: list[str],
    errors: list[str],
) -> IntegrityResult:
    """Check a RAR/CBR archive."""
    try:
        import rarfile  # type: ignore[import-untyped]

        configure_rarfile_backend()

        with rarfile.RarFile(path) as archive:
            image_names = [
                name for name in archive.namelist() if Path(name).suffix.lower() in IMAGE_EXTENSIONS
            ]
            if not image_names:
                errors.append("No valid images found in archive")
                return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)

            page_count = len(image_names)
            unsafe_result = _reject_unsafe_archive_members(
                image_names,
                errors,
                warnings,
                page_count,
            )
            if unsafe_result is not None:
                return unsafe_result

            if deep:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    for image_name in image_names:
                        archive.extract(image_name, path=tmp_dir)
                    deep_errors = _deep_verify_extracted_images(
                        Path(tmp_dir),
                        image_names,
                        warnings,
                    )
                    if deep_errors:
                        errors.extend(deep_errors)
                        return IntegrityResult(
                            status="corrupt",
                            page_count=page_count,
                            warnings=warnings,
                            errors=errors,
                        )

            return IntegrityResult(
                status="warning" if warnings else "healthy",
                page_count=page_count,
                warnings=warnings,
                errors=errors,
            )
    except Exception as exc:
        errors.append(f"Cannot open RAR archive: {exc}")
        return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)


def _check_tar(
    path: Path,
    deep: bool,
    warnings: list[str],
    errors: list[str],
) -> IntegrityResult:
    """Check a TAR/CBT archive."""
    try:
        with tarfile.open(path, "r") as archive:
            image_members = [
                member
                for member in archive.getmembers()
                if member.isfile() and Path(member.name).suffix.lower() in IMAGE_EXTENSIONS
            ]
            image_names = [member.name for member in image_members]
            if not image_names:
                errors.append("No valid images found in archive")
                return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)

            page_count = len(image_names)
            unsafe_result = _reject_unsafe_archive_members(
                image_names,
                errors,
                warnings,
                page_count,
            )
            if unsafe_result is not None:
                return unsafe_result

            if deep:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    _safe_extract_tar_members(archive, image_members, Path(tmp_dir))
                    deep_errors = _deep_verify_extracted_images(
                        Path(tmp_dir),
                        image_names,
                        warnings,
                    )
                    if deep_errors:
                        errors.extend(deep_errors)
                        return IntegrityResult(
                            status="corrupt",
                            page_count=page_count,
                            warnings=warnings,
                            errors=errors,
                        )

            return IntegrityResult(
                status="warning" if warnings else "healthy",
                page_count=page_count,
                warnings=warnings,
                errors=errors,
            )
    except tarfile.TarError as exc:
        errors.append(f"Cannot open TAR archive: {exc}")
        return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)


def _safe_extract_tar_members(
    archive: tarfile.TarFile,
    members: list[tarfile.TarInfo],
    destination: Path,
) -> None:
    """Extract regular TAR files without allowing paths to escape destination."""
    destination.mkdir(parents=True, exist_ok=True)
    resolved_destination = destination.resolve()

    for member in members:
        if has_archive_member_path_traversal(member.name):
            raise tarfile.TarError(_unsafe_archive_member_error(member.name))

        target_path = destination / member.name
        resolved_parent = target_path.parent.resolve()
        if not _is_relative_to(resolved_parent, resolved_destination):
            raise tarfile.TarError(_unsafe_archive_member_error(member.name))

        source = archive.extractfile(member)
        if source is None:
            raise tarfile.TarError(f"Cannot extract archive member: {member.name}")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with source, target_path.open("wb") as target:
            shutil.copyfileobj(source, target)


def _check_pdf(
    path: Path,
    deep: bool,
    warnings: list[str],
    errors: list[str],
) -> IntegrityResult:
    """Check a PDF file's integrity."""
    try:
        from pdf2image import convert_from_path, pdfinfo_from_path
    except ImportError:
        errors.append("pdf2image not available for PDF verification")
        return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)

    try:
        info = pdfinfo_from_path(str(path))
        page_count = info.get("Pages", 0)
        if page_count == 0:
            errors.append("PDF has no pages")
            return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)

        if deep:
            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    images = convert_from_path(str(path), dpi=72, output_folder=tmp_dir)
                    rendered_count = len(images)
                    if rendered_count != page_count:
                        warnings.append(
                            f"Expected {page_count} pages but rendered {rendered_count}"
                        )
            except Exception as exc:
                errors.append(f"PDF page rendering failed: {exc}")
                return IntegrityResult(
                    status="corrupt",
                    page_count=page_count,
                    warnings=warnings,
                    errors=errors,
                )

        return IntegrityResult(
            status="warning" if warnings else "healthy",
            page_count=page_count,
            warnings=warnings,
            errors=errors,
        )
    except Exception as exc:
        errors.append(f"Cannot read PDF: {exc}")
        return IntegrityResult(status="corrupt", errors=errors, warnings=warnings)


def _deep_verify_zip_images(
    archive: zipfile.ZipFile,
    image_names: list[str],
    warnings: list[str],
) -> list[str]:
    """Decode each image from a ZIP to detect truncation or corruption."""
    errors: list[str] = []
    try:
        from PIL import Image
    except ImportError:
        warnings.append("Pillow not available for deep image verification")
        return errors

    for name in image_names:
        try:
            data = archive.read(name)
            image = Image.open(io.BytesIO(data))
            image.verify()
        except Exception as exc:
            errors.append(f"{name}: image verification failed ({exc})")
    return errors


def _deep_verify_extracted_images(
    extract_dir: Path,
    image_names: list[str],
    warnings: list[str],
) -> list[str]:
    """Decode each extracted image file to detect truncation or corruption."""
    errors: list[str] = []
    try:
        from PIL import Image
    except ImportError:
        warnings.append("Pillow not available for deep image verification")
        return errors

    for name in image_names:
        image_path = extract_dir / name
        if not image_path.exists():
            errors.append(f"{name}: extracted file not found")
            continue
        try:
            image = Image.open(image_path)
            image.verify()
        except Exception as exc:
            errors.append(f"{name}: image verification failed ({exc})")
    return errors
