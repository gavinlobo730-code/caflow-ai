FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer cache), from the LOCK and nothing else.
#
# requirements.txt is pip-compile's output: every package, transitive ones included, pinned to one
# version with the sha256 of each distribution file. `--require-hashes` makes pip REFUSE anything that is
# not exactly that, so a build next month installs the versions the test suite passed on, and a tampered
# or substituted file fails the build instead of reaching production (engineering-04). The test runner is
# not here: it is requirements-dev.txt, installed by CI only, and neither that file nor tests/ is copied
# below (.dockerignore). tests/test_the_backend_installs_from_a_lock.py holds all of it, and the
# `docker image` workflow builds this file and inspects what came out.
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# Copy source (what .dockerignore leaves: no tests/, no .env, no dev requirements)
COPY . .

# Non-root user
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# 1 worker fits within Render free tier's 512 MB RAM limit.
#
# NO `--access-logfile`. gunicorn's access line is the raw request line, path and query string
# included, and a token can be in either (the engagement-signing token is a path segment); it also
# answers nothing about how long the request took. middleware/request_context.py writes ONE JSON line per
# request instead, carrying the matched route TEMPLATE, the status, the duration and the request id, and
# skips the health probes that would otherwise be most of the log (ops-11).
CMD ["gunicorn", "main:app", "--workers", "1", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120", "--error-logfile", "-"]
