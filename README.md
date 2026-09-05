# 🛰️ ip-scout

[![Tests](https://github.com/wmhunter96/ip-scout/actions/workflows/tests.yml/badge.svg)](https://github.com/wmhunter96/ip-scout/actions/workflows/tests.yml)
[![Build and publish Docker image](https://github.com/wmhunter96/ip-scout/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/wmhunter96/ip-scout/actions/workflows/docker-publish.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![ghcr.io](https://img.shields.io/badge/ghcr.io-wmhunter96%2Fip--scout-blue?logo=docker)](https://github.com/wmhunter96/ip-scout/pkgs/container/ip-scout)

A self-hosted network utility that answers one question: **which IPs are already taken on this subnet, and what's the next one free?**

It cross-references two sources — Docker containers (via the Docker SDK, no shelling out to the CLI) and a live scan of the wire (nmap, falling back to a parallel ping sweep) — and reports both the full picture and the single next free address. Runs once and prints a table/JSON, or sits in the background as a tiny HTTP server for a dashboard widget to poll.

---

## Table of Contents

- [What Ip Scout Is](#what-ip-scout-is)
- [Features](#features)
- [Docker Installation](#docker-installation)
- [Unraid Installation](#unraid-installation)
- [Network Access](#network-access)
- [Updating](#updating)
- [Development](#development)
- [Architecture](#architecture)
- [License](#license)

---

## What Ip Scout Is

Every home network eventually needs a static IP assigned to something new — a container, a Pi, a switch — and answering "what's actually free?" usually means either guessing, or SSHing in to run `docker ps` and `nmap` by hand. ip-scout automates exactly that check:

1. **Ask Docker** which containers are running and what IPs it assigned them (via the `docker` Python SDK against `/var/run/docker.sock` — never `docker inspect` shelled out).
2. **Scan the wire** for anything else answering in a configurable range (`nmap -sn`, or a parallelized ping sweep if nmap isn't available).
3. **Cross-reference** the two into one used-IP set, and report every free address in range plus the single next one.

No database, no setup wizard, no state — it re-scans fresh every time it's asked. Point it at env vars and go.

## Features

- 🐳 **Docker container inventory** — every running container's name and assigned IP(s), read via the Docker SDK
- 📡 **Live subnet scan** — `nmap -sn` when available, automatic fallback to a parallel ping sweep when it isn't
- 🔀 **Cross-referenced report** — containers + live hosts deduplicated into one used-IP list, full free-IP list, and the single next free address
- 🖥️ **CLI mode** — run once, get a table (or `--json` for scripting) and exit
- 🌐 **Serve mode** — a single `GET /api/status` endpoint (stdlib `http.server`, no framework) that re-scans on a timer and serves the cached result, so a dashboard widget (e.g. [Homarr](https://homarr.dev/)'s Custom API widget) can poll it without needing SSH access every time
- ⚙️ **Env var config with CLI overrides** — `SUBNET_PREFIX` / `RANGE_START` / `RANGE_END` / `SCAN_INTERVAL`, or the matching `--subnet-prefix` / `--range-start` / `--range-end` / `--interval` flags
- 🪶 **Stateless** — no database, no volumes required; re-scans fresh every request/interval

## Docker Installation

```bash
docker run -d \
  --name ip-scout \
  --cap-add=NET_ADMIN \
  -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e SUBNET_PREFIX=192.168.4 \
  -e RANGE_START=1 \
  -e RANGE_END=254 \
  -e SCAN_INTERVAL=300 \
  ghcr.io/wmhunter96/ip-scout:latest
```

Then poll it:

```bash
curl http://localhost:8000/api/status
```

Or with Compose (see [docker-compose.yml](docker-compose.yml)):

```bash
docker compose up -d
```

| Setting | Value |
| --- | --- |
| Image | `ghcr.io/wmhunter96/ip-scout:latest` |
| Port | `8000` (HTTP, serve mode) |
| Volume | `/var/run/docker.sock` (read-only) — lets ip-scout list containers |
| Capability | `NET_ADMIN` (or `--network host`) — see [Network Access](#network-access) |
| Env `SUBNET_PREFIX` | First three octets, e.g. `192.168.4` |
| Env `RANGE_START` / `RANGE_END` | Host-octet range to scan (default `1`–`254`) |
| Env `SCAN_INTERVAL` | Seconds between background scans in serve mode (default `300`) |

To run a single scan and exit instead of the long-running server, override the container's default command:

```bash
docker run --rm \
  --cap-add=NET_ADMIN \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e SUBNET_PREFIX=192.168.4 \
  ghcr.io/wmhunter96/ip-scout:latest \
  python -m ipscout --json
```

## Unraid Installation

**Option A — Template repository (recommended):**

1. **Docker** tab → **Template Repositories** → add `https://github.com/wmhunter96/ip-scout` → **Save**.
2. Go to **Apps** (or **Docker** → **Add Container** → template dropdown) and select **ip-scout**.
3. Confirm the fields below, then **Apply**.

**Option B — Add manually:**

**Docker** → **Add Container**, and set:

| Field | Value |
| --- | --- |
| Repository | `ghcr.io/wmhunter96/ip-scout:latest` |
| Icon URL | `https://raw.githubusercontent.com/wmhunter96/ip-scout/main/unraid/icon.png?v=1` |
| WebUI Port | `8000` |
| Path: Container | `/var/run/docker.sock` |
| Path: Host | `/var/run/docker.sock` (read-only) |
| Extra Parameters | `--cap-add=NET_ADMIN` |
| Variable: `SUBNET_PREFIX` | your LAN's first three octets, e.g. `192.168.4` |
| Variable: `RANGE_START` / `RANGE_END` | scan range, default `1` / `254` |
| Variable: `SCAN_INTERVAL` | seconds between scans, default `300` |

One-time setup for a private GHCR image: on GitHub, go to the repo's **Packages** tab → `ip-scout` package → **Package settings** → set visibility to **Public** (GHCR packages default to private, and a private image needs a login secret on the Unraid side to pull).

The Unraid template XML is included at [`unraid/ip-scout.xml`](unraid/ip-scout.xml).

Once running, add a **Custom API** widget in Homarr (or similar) pointed at `http://<unraid-ip>:8000/api/status` to see the report on your dashboard.

## Network Access

nmap's `-sn` host discovery and a raw ICMP ping both need `CAP_NET_RAW`, which Docker's default capability set drops. Without it, ip-scout still runs, but every scan silently fails to see anything (nmap errors out and ip-scout falls back to a ping sweep that also can't send ICMP, so it reports every host as free).

Two ways to fix that, in order of how much access they grant:

| Option | What it gives up | When to use it |
| --- | --- | --- |
| `--cap-add=NET_ADMIN` (used in the examples above) | Just the raw-socket capability nmap/ping need — the container still gets its own network namespace | Default recommendation; simplest fix with the smallest blast radius |
| `--network host` | The container shares the host's network stack entirely — no namespace isolation at all | If `NET_ADMIN` alone doesn't get a clean scan on your setup (some Docker network drivers still restrict raw sockets even with the capability granted) |

The image runs as root by default specifically so `--cap-add=NET_ADMIN` is a one-flag fix with no follow-up permission wrangling — the tradeoff most Unraid network-utility containers make, and the simplest default for this project too. If that tradeoff doesn't work for your setup, `--network host` is the fallback with no such caveat.

## Updating

**Unraid:** the Docker tab (or Community Applications' "Check for Updates") detects new `latest` images automatically — click **Update**.

**Docker CLI:**

```bash
docker pull ghcr.io/wmhunter96/ip-scout:latest
docker stop ip-scout && docker rm ip-scout
docker run -d --name ip-scout --cap-add=NET_ADMIN -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e SUBNET_PREFIX=192.168.4 \
  ghcr.io/wmhunter96/ip-scout:latest
```

**Docker Compose:**

```bash
docker compose pull && docker compose up -d
```

ip-scout is stateless — there's no data to preserve across an update.

## Development

```bash
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
```

### Run it locally

```bash
SUBNET_PREFIX=192.168.4 PYTHONPATH=src python -m ipscout          # one-shot table
SUBNET_PREFIX=192.168.4 PYTHONPATH=src python -m ipscout --json   # one-shot JSON
SUBNET_PREFIX=192.168.4 PYTHONPATH=src python -m ipscout serve    # long-running server on :8000
```

Running outside a container needs a reachable Docker daemon (the SDK talks to whatever `DOCKER_HOST` / the default socket points at) and, for a real scan, the same raw-socket access described in [Network Access](#network-access) — on most desktop OSes that means running with elevated privileges, since there's no container capability to add.

### Tests

```bash
pytest -v
```

Every test mocks the Docker SDK and any subprocess/network call — the suite needs no Docker daemon, no nmap/ping binary, and no real network access to run. Covers, among other things:

- Free-IP computation and numeric IP sorting (`ipmath.py`)
- Container → IP extraction, including host-networked containers with no IP (`docker_inspect.py`)
- nmap output parsing, the ping-sweep fallback, and the nmap → ping fallback path itself (`scanner.py`)
- Cross-referencing containers and scan results into one report, with dedup (`report.py`)
- Env var config parsing and CLI flag overrides (`config.py`, `cli.py`)

### Lint

```bash
ruff check src tests
```

### Full container build

```bash
docker build -f docker/Dockerfile -t ip-scout:dev .
docker run --rm --cap-add=NET_ADMIN -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  ip-scout:dev
```

## Architecture

```
src/ipscout/
├── config.py          Config dataclass -- env vars, with CLI flag overrides layered on top
├── ipmath.py           Pure range math: generate a range, compute free IPs, sort/dedupe
├── docker_inspect.py   Docker SDK -> list of ContainerInfo(name, short_id, networks, ips)
├── scanner.py          nmap -sn, parsed; parallel ping-sweep fallback; picks whichever works
├── report.py           Cross-references docker_inspect + scanner into one report dict
├── cli.py              argparse: one-shot table/JSON, or dispatch to serve mode
└── server.py           stdlib http.server; background scan timer + cached GET /api/status
```

`report.build_report()` is the single function both entry points call — `cli.py` for a one-shot scan, `server.py` on a background timer — so the CLI and the HTTP endpoint can never drift into reporting different things for the same config. Nothing below it does I/O it doesn't need to: `ipmath.py` has no dependency on Docker, subprocess, or the network at all, which is what keeps the free-IP arithmetic testable without mocking anything.

## License

[MIT](LICENSE)
