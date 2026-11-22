# Containerized build/run environment for the regex regression harness.
# Isolation properties:
#   - Non-root runtime user (regressor, UID 10001)
#   - No host mounts except an explicit results directory at `docker run` time
#   - No host credentials baked in or passed through the environment
#   - Pre-fetched Cargo crates in CARGO_HOME so runtime supports `--network none`
FROM rust:1.99-slim-bookworm

ENV CARGO_HOME=/usr/local/cargo \
    RUSTUP_HOME=/usr/local/rustup \
    PYTHONUNBUFFERED=1 \
    CARGO_NET_OFFLINE=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    ca-certificates \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Allow git operations when bind-mounting host directories owned by another UID,
# without baking any host credentials or .gitconfig files into the image.
RUN git config --system --add safe.directory /work/regressor \
    && git config --system --add safe.directory /work/regressor/regex

WORKDIR /work
COPY . /work/regressor

# noise-bench/Cargo.toml depends on regex = { path = "../regex" }, and RegexAdapter defaults
# to <repo>/regex, so the clone must live inside the regressor checkout (not /work/regex).
# Default REGEX_SHA tracks the Nov 2026 study window endpoint; full git history is retained
# so compare-interleaved, bisect, and continuous collection can check out any commit.
ARG REGEX_SHA=3d79fe92666a9f191d7677ebc123ac165eac200c
RUN git clone --quiet https://github.com/rust-lang/regex.git /work/regressor/regex \
    && git -C /work/regressor/regex checkout --quiet --detach "$REGEX_SHA"

# Editable install: the CLI resolves projects/, data/, noise-bench/ and ui/ relative to the checkout.
RUN pip3 install --no-cache-dir --break-system-packages -e /work/regressor

# Pre-fetch crates.io dependencies into CARGO_HOME so `--network none` + `CARGO_NET_OFFLINE=true`
# can compile historical commits offline, then build the release noise-bench binary.
WORKDIR /work/regressor/noise-bench
RUN cargo fetch && cargo build --release

RUN useradd -m -u 10001 -s /bin/bash regressor \
    && mkdir -p /work/regressor/noise-bench/results /work/regressor/.regressor-builds \
    && chmod +x /work/regressor/scripts/*.sh \
    && chown -R regressor:regressor /work "${CARGO_HOME:-/usr/local/cargo}"

USER regressor
WORKDIR /work/regressor

# Results should land in a bind-mounted volume, not baked into the image:
#   docker run -v $(pwd)/results:/work/regressor/noise-bench/results ...
VOLUME ["/work/regressor/noise-bench/results"]

ENTRYPOINT ["/work/regressor/scripts/container_entrypoint.sh"]
CMD ["/bin/bash"]
