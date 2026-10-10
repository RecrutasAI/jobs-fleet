# One image for every worker, wherever it runs (GitHub Actions, a home machine, Kubernetes).
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY fleet ./fleet
COPY registry ./registry
RUN pip install --no-cache-dir .
ENTRYPOINT ["python", "-m", "fleet.cli"]
