FROM python:3.12-slim

WORKDIR /app

# Copy entire project first
COPY pyproject.toml /app/
COPY janus /app/janus

# Upgrade pip and install project (installs dependencies from pyproject.toml)
RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

# Check that the janus process is still running inside the container
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c "import os,sys;sys.exit(0 if any('janus' in open(f'/proc/{p}/cmdline','rb').read().decode(errors='ignore') for p in os.listdir('/proc') if p.isdigit()) else 1)"

ENTRYPOINT ["janus"]