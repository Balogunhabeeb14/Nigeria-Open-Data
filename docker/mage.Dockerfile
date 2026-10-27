FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_HTTP_TIMEOUT=120
ENV UV_CONCURRENT_DOWNLOADS=4

# Build from a clean base rather than the damaged prebuilt Mage image.
RUN python -c "import ssl; print(ssl.OPENSSL_VERSION)" \
    && pip install --no-cache-dir "uv==0.8.22"

# Constrain dependencies whose newer releases conflict with Mage's typing pin.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system "mage-ai==0.9.79" "psycopg2-binary==2.9.10" \
      "pydantic==2.9.2" "alembic==1.14.1" "anyio==4.8.0" "notebook==7.2.2"

# Mage's validation stack pins NumPy 1.x; newer Arrow wheels require NumPy 2.
# The compatibility Polars wheel also supports Docker CPUs without AVX2.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system "numpy==1.26.4" "pandas==2.2.0" "pyarrow==17.0.0" \
    && uv pip uninstall --system polars \
    && uv pip install --system "polars-lts-cpu==1.30.0"

RUN python -c "import ssl; import mage_ai.server.server"

WORKDIR /home/src
ENV USER_CODE_PATH=/home/src/datapipeline
EXPOSE 6789
CMD ["mage", "start", "/home/src/datapipeline"]
