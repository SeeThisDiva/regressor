# Containerized build/run environment for the regex regression harness.
# Isolation properties (matches the original safety brief):
#   - No host mounts except a results directory you choose at `docker run` time
#   - No credentials baked in or passed through the environment
#   - Network only reaches what's needed to fetch the repo + crates.io deps
#     (enforce the crates.io-only restriction at your firewall/DNS if you
#     want a hard guarantee beyond this container's own scope)
FROM rust:1.82-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential ca-certificates python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY . /work/regressor

# noise-bench/Cargo.toml depends on regex = { path = "../regex" }, and RegexAdapter defaults
# to <repo>/regex, so the clone must live inside the regressor checkout (not /work/regex).
# Pinned to the last commit of the 27-commit study so the image builds reproducibly; the full
# history is kept so compare-interleaved / bisect can still check out other commits.
ARG REGEX_SHA=4733e28ba4f281f643ce93e4089eccbb9a9d5a5a
RUN git clone --quiet https://github.com/rust-lang/regex.git /work/regressor/regex \
    && git -C /work/regressor/regex checkout --quiet --detach "$REGEX_SHA"

# Editable install: the CLI resolves projects/, data/, noise-bench/ and ui/ relative to the checkout.
RUN pip3 install --no-cache-dir --break-system-packages -e /work/regressor

WORKDIR /work/regressor/noise-bench
RUN cargo build --release

RUN useradd -m -u 10001 regressor && chown -R regressor:regressor /work
USER regressor
WORKDIR /work/regressor

# Results should land in a bind-mounted volume, not baked into the image:
#   docker run -v $(pwd)/results:/work/regressor/noise-bench/results ...
VOLUME ["/work/regressor/noise-bench/results"]

ENTRYPOINT ["/bin/bash"]
