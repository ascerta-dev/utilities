# ascerta-n8n-toolkit — minimal container for running audit/migrate CLIs
#
# Usage:
#   docker build -t ascerta-n8n-toolkit .
#   docker run --rm \
#     -e N8N_BASE_URL -e N8N_API_KEY \
#     -e ASCERTA_BASE_URL -e ASCERTA_API_KEY \
#     -v $(pwd)/reports:/reports \
#     ascerta-n8n-toolkit \
#     python audit-configure-ascerta-proxy.py --out /reports/audit.json
#
# The toolkit is stdlib-only, so the image stays small.

FROM python:3.12-slim

LABEL org.opencontainers.image.title="ascerta-n8n-toolkit"
LABEL org.opencontainers.image.description="Audit and migrate n8n AI workflows to route through Ascerta"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY audit-configure-ascerta-proxy.py \
     migrate-workflows-to-ascerta.py \
     migrate-to-ascerta.sh \
     migrate-openai-to-ascerta.sh \
     ./

# Make the shell scripts executable; Python files are run via the python entrypoint.
RUN chmod +x migrate-to-ascerta.sh migrate-openai-to-ascerta.sh

# Run as a non-root user so the container doesn't have root privileges
# at runtime. The user owns /app so volume mounts under /reports remain
# writable when the host directory permits.
RUN useradd --create-home --uid 1000 --shell /bin/bash toolkit && \
    chown -R toolkit:toolkit /app
USER toolkit

# Default to the audit script with --help so `docker run ascerta-n8n-toolkit`
# does something useful instead of hanging on stdin.
ENTRYPOINT ["python"]
CMD ["audit-configure-ascerta-proxy.py", "--help"]
