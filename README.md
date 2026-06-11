# Pullbox

Modern comic book management and acquisition for self-hosted libraries.

Pullbox helps discover, download, organize, and catalog digital comic
collections. It follows the familiar self-hosted media-app model: connect
metadata, indexers, download clients, and a library path, then let the app keep
wanted issues moving through search, download, post-processing, and library
organization.

Pullbox is under active development. The app is usable for testing and early
feedback, but deployments should be backed up and treated as pre-1.0 software.

## Quick Start With Docker

Pullbox listens on port `8585` and uses four main container paths:

| Path | Purpose |
| --- | --- |
| `/data` | Pullbox state: database, config, logs, backups, temp files |
| `/comics` | Comic library |
| `/downloads` | Completed downloads shared with download clients |
| `/imports` | Manual import/drop-folder sources, including Mylar3 databases |

Keep `/data` durable and backed up. On first startup, Pullbox creates
`/data/config.xml` and writes a strong `<SecretKey>` used for browser sessions
and encrypted integration secrets. You do not need to generate this manually
for normal Docker installs.

If you intentionally manage the application secret outside `config.xml`, set
`PULLBOX_SECRET_KEY` to a stable, deployment-specific value and never change it
after saving credentials:

```bash
export PULLBOX_SECRET_KEY="$(openssl rand -hex 64)"
```

When `PULLBOX_SECRET_KEY` is set, it overrides the value in `config.xml` at
runtime. Changing it later prevents Pullbox from decrypting saved integration
secrets.

### Docker Run

```bash
docker volume create pullbox-data

docker run -d \
  --name pullbox \
  --restart unless-stopped \
  -p 8585:8585 \
  -e TZ=America/New_York \
  -e PULLBOX_DB_URL=sqlite+aiosqlite:////data/pullbox.db \
  -e PULLBOX_SQLITE_JOURNAL_MODE=WAL \
  -e PULLBOX_LIBRARY_ROOT=/comics \
  -e PULLBOX_COVERS_DIR=/comics/.covers \
  -v pullbox-data:/data \
  -v /path/to/comics:/comics \
  -v /path/to/shared-downloads:/downloads \
  -v /path/to/imports:/imports \
  ghcr.io/pullboxapp/pullbox:latest
```

Open `http://localhost:8585` and complete first-run setup.

### Admin Password Reset

If you are locked out of the web UI, reset a user's password through the
installed management CLI inside the container:

```bash
printf '%s\n' 'NewPass1!' | docker exec -i pullbox \
  python -m pullbox.cli reset-password --user admin --password-stdin
```

Replace `pullbox` with your container name if you changed it. The new password
must meet the normal password policy, and the reset invalidates existing
browser sessions for that user.

### Native HTTPS

Pullbox can serve HTTPS directly on the normal Pullbox port. Enable it from
Settings > General or with `PULLBOX_HTTPS_ENABLED=true`, then point
`PULLBOX_HTTPS_CERT_PATH` and `PULLBOX_HTTPS_KEY_PATH` at files mounted inside
the container. The default cert root is `/config/certs`, so a typical Docker
mount is:

```yaml
volumes:
  - /path/to/certs:/config/certs:ro
```

Certificate files must be readable by the container runtime user `65532`.

### Docker Compose

Create a `.env` file next to `compose.yml`:

```env
TZ=America/New_York
COMICS_PATH=/path/to/comics
DOWNLOADS_PATH=/path/to/shared-downloads
IMPORTS_PATH=/path/to/imports
```

Use this compose file:

```yaml
services:
  pullbox:
    image: ghcr.io/pullboxapp/pullbox:latest
    container_name: pullbox
    restart: unless-stopped
    ports:
      - "8585:8585"
    environment:
      TZ: ${TZ}
      PULLBOX_DB_URL: sqlite+aiosqlite:////data/pullbox.db
      PULLBOX_SQLITE_JOURNAL_MODE: WAL
      PULLBOX_LIBRARY_ROOT: /comics
      PULLBOX_COVERS_DIR: /comics/.covers
    volumes:
      - pullbox-data:/data
      - ${COMICS_PATH}:/comics
      - ${DOWNLOADS_PATH}:/downloads
      - ${IMPORTS_PATH}:/imports

volumes:
  pullbox-data:
    name: pullbox-data
```

Start Pullbox:

```bash
docker compose up -d
```

Open `http://localhost:8585` and complete first-run setup.

### Storage Permissions

The production container runs as a non-root user. Make sure the host or network
paths mounted at `/comics`, `/downloads`, and `/imports` are readable by the
container runtime identity. `/comics` and `/downloads` also need write access
for normal library and post-processing work. `/imports` only needs write access
if the deployment expects Pullbox to move, rewrite, or clean up source files.

Pullbox can normalize file and folder modes with its library permission tools,
but it does not take ownership of host storage. Ownership, group membership, NAS
ACLs, and mount options should be fixed in the deployment environment.

## Import Source Path Model

Docker containers can only scan paths that are mounted into the container. For
manual folder imports, mount the host drop folder at `/imports` and scan that
container path from the Import page.

For Mylar3 imports, the Mylar3 database and any referenced comic paths must be
visible inside the Pullbox container. The simplest setup is to place or mount
the Mylar3 database under `/imports` and mount the library path with the same
container path Mylar3 stores, such as `/comics`.

Avoid mounting broad host paths like `/` just to make browsing easier. It works
against the hardened-container model and gives the app access to far more host
storage than it needs.

## Download Client Path Model

Pullbox works best when all completed downloads are visible inside the
container under `/downloads`. Each download client can keep its own remote path,
but the Pullbox download directory should usually point at `/downloads`.

| Client | Example remote path | Pullbox download directory |
| --- | --- | --- |
| SABnzbd | `/data/download` | `/downloads` |
| qBittorrent | `/data/download` | `/downloads` |
| NZBGet | `/downloads/completed` | `/downloads` |
| Transmission | `/volume1/downloads` | `/downloads` |

The important rule: completed files must physically exist in storage mounted
into Pullbox at `/downloads`.

## Features

- Comic series and issue management.
- ComicVine metadata integration.
- Newznab, Torznab, and Prowlarr-backed indexer support.
- SABnzbd, NZBGet, qBittorrent, Transmission, and Deluge download clients.
- Manual and automated wanted-issue search.
- Search history, rejected results, and blocklist support.
- Post-processing for completed downloads.
- Library scanning, matching, renaming, conversion, and integrity utilities.
- Intervention queue for ambiguous matches.
- Health checks, diagnostics, logs, backups, and audit trail.
- Server-rendered UI with HTMX, Alpine.js, and Tailwind CSS.

## Development

Contributor setup, validation commands, coding standards, and workflow details
live in the repo docs:

- `CONTRIBUTING.md`
- `docs/development/ARCHITECTURE_OVERVIEW.md`
- `docs/development/CODE_STANDARDS.md`
- `docs/development/DATABASE_STANDARDS.md`
- `docs/development/SECURITY_STANDARDS.md`
- `docs/development/INFRASTRUCTURE.md`
- `docs/development/DESIGN_SYSTEM.md`

## Security

Private vulnerability reporting and deployment security guidance are covered in
`SECURITY.md`.

## License

Pullbox is licensed under GPL-3.0-or-later. See `LICENSE` for details.
