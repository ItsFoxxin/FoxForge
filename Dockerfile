FROM python:3.13-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS builder
WORKDIR /build
COPY deployment/requirements-build.txt /build/requirements-build.txt
RUN python -m pip install --no-cache-dir -r requirements-build.txt
COPY pyproject.toml MANIFEST.in README.md AGENTS.md ./
COPY foxforge ./foxforge
COPY templates ./templates
COPY scripts ./scripts
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir /wheels .

FROM python:3.13-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962
# Debian's security-updated OS packages are resolved at build time. Record the
# resulting image digest; Python application dependencies are pinned below.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 foxforge \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin foxforge
COPY deployment/requirements-runtime.txt /tmp/requirements-runtime.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-runtime.txt
COPY --from=builder /wheels /tmp/wheels
RUN python -m pip install --no-cache-dir --no-deps /tmp/wheels/*.whl && rm -rf /tmp/wheels
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FOXFORGE_DATA_DIR=/var/lib/foxforge/control-plane \
    FOXFORGE_REPOS_DIR=/var/lib/foxforge/repos FOXFORGE_CONFIG_DIR=/etc/foxforge
WORKDIR /app
USER 10001:10001
# CLI exits on completion. No fake liveness process or periodic inference.
ENTRYPOINT ["python", "-m", "foxforge.container_cli"]
CMD ["doctor", "--require-mounts"]
