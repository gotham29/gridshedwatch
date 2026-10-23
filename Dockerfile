FROM python:3.11-slim
WORKDIR /gsw
COPY . .
RUN pip install --no-cache-dir -e ".[test]"
CMD ["python", "-m", "pytest", "-q"]
