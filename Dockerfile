FROM node:22-alpine AS css-builder

WORKDIR /build
COPY package.json package-lock.json tailwind.config.js ./
COPY frontend ./frontend
COPY crates ./crates
COPY server/static ./server/static
RUN npm ci && npm run build

FROM rust:1.88-bookworm AS rust-builder

WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
RUN cargo build --release

FROM debian:bookworm-slim

ENV PHENIKAA_SERVER_HOST=0.0.0.0 \
    PHENIKAA_SERVER_STATE=/data

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=rust-builder /build/target/release/phenikaa-server /usr/local/bin/phenikaa-calendar-server
COPY --from=rust-builder /build/target/release/phenikaa-cli /usr/local/bin/phenikaa-calendar
COPY --from=css-builder /build/server/static/styles.css /app/server/static/styles.css

RUN useradd --create-home --uid 1000 phenikaa \
    && mkdir -p /data \
    && chown -R phenikaa:phenikaa /data /app
USER phenikaa

VOLUME /data
EXPOSE 8416

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://127.0.0.1:${PHENIKAA_SERVER_PORT:-8416}/api/v1/health || exit 1

ENTRYPOINT ["phenikaa-calendar-server"]
