# Embedded comic reader

Pullbox can open an owned issue directly from its issue-details page. The reader is a private,
full-viewport, single-page experience intended both for ordinary reading and for quickly checking
that a download is the correct comic.

## Supported files

The reader supports CBZ, CBR, CB7, CBT, and PDF. The production image includes the official UnRAR
backend for CBR, py7zr/7-Zip support for CB7, TAR support for CBT, and Poppler for PDF rendering.
The file signature must match the format recorded in Pullbox. EPUB is not supported.

Archive pages are naturally ordered, unsafe members are ignored or rejected, and extraction,
decoded pixels, rendering time, worker concurrency, and generated cache storage are bounded. Large
images are resized to the configured rendition ceiling before delivery to keep browser memory use
predictable. Source comic files are never rewritten by the reader.

## Controls

- Use the visible previous/next buttons, the one-based page field, the outer tap zones, or a
  horizontal touch swipe while the page is fitted.
- Fit page is the default. Fit width, fit height, actual size, and stepped zoom are available.
- LTR/RTL changes arrow, tap-zone, and swipe meaning without changing canonical page numbers.
- Close returns to the same issue URL, scroll position, page state, and Read button focus.
- `?` opens the complete keyboard shortcut reference. The main shortcuts are arrow keys,
  Page Up/Down, Space, Home/End, `G`, `W`, `H`, `0`, `+`/`-`, `R`, `F`, and Escape.

Pullbox saves only the last page that remained visible after decoding for the settle interval.
Progress is private to the signed-in user. Prefetching and opening directly on the final page do not
mark completion; deliberately navigating to and viewing the final page does.

## Errors and recovery

The reader keeps failures inside the full-viewport shell and never exposes library paths, archive
member names, renderer output, or stack traces. A page-level failure can be retried without closing
the reader, and the original Download action remains available. Missing, mismatched, corrupt, empty,
oversized, or temporarily busy sources return stable private errors.

If PDF or CBR support is unexpectedly unavailable, verify that the running image is the supported
Pullbox production image rather than a locally reduced Python environment. The authenticated
`GET /api/v1/reader/capabilities` diagnostic reports readiness for all five formats plus path-free
cache and worker limits.

## Cache and operations

Generated pages live under the Pullbox data directory in `reader-cache`; losing them affects only
latency because they are rebuilt from source comics. The authenticated, CSRF-protected
`DELETE /api/v1/reader/cache` operation clears only generated reader files and does not follow
symlinks or touch the comic library. Normal deployments use a 512 MiB quota, two expensive workers,
and a short bounded worker wait.

For an immediate feature rollback, set `PULLBOX_READER_ENABLED=false` in the Pullbox service
environment and recreate/restart that service. This hides Read and makes the private reader routes
return not found while preserving source comics, generated cache files, and private resume state.
Set the value back to `true` to restore the feature.

The `issue_reader_states` migration is reversible, but downgrading it deletes private resume and
completion records. Back up `/data` before any migration downgrade. Disabling the feature gate is
the preferred rollback because it is non-destructive.
