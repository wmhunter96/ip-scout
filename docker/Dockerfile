# syntax=docker/dockerfile:1

# Just the `docker` CLI binary (statically linked, so it drops straight
# into a glibc image with no library dependencies of its own) -- copied in
# below instead of adding Docker's apt repo just for one file. ip-scout
# shells out to it against the mounted socket rather than using the Docker
# Python SDK, so there's no separate Engine API version to keep in sync.
FROM docker:27-cli AS docker-cli

FROM python:3.12-slim AS runtime

# Baked in at build time (see .github/workflows/docker-publish.yml) purely
# for /api/status to report which commit a running container was actually
# built from.
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GIT_SHA=${GIT_SHA} \
    BUILD_DATE=${BUILD_DATE}

# nmap: preferred scan method for the subnet sweep (fast host discovery via
# raw ICMP/ARP sockets). iputils-ping: the fallback ip-scout uses
# automatically when nmap isn't on PATH, or when it can't get the
# raw-socket access it needs. curl: container HEALTHCHECK only.
#
# Both nmap's -sn scan and a raw ICMP ping need CAP_NET_RAW, which Docker's
# default capability set drops -- see "Network access" in the README. This
# image runs as root by default so the simplest fix (`--cap-add=NET_ADMIN`
# or `--network host` on `docker run`) is enough on its own, with no extra
# user/permission flags required -- the common pattern for Unraid
# network-utility containers, and the tradeoff this project takes on
# purpose to keep the default docker run/compose example in the README
# working with one added flag instead of several.
RUN apt-get update && apt-get install -y --no-install-recommends \
        nmap \
        iputils-ping \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ipscout ./ipscout

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/status || exit 1

ENTRYPOINT ["python", "-m", "ipscout"]
CMD ["serve"]
