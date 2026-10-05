FROM python:3.13-alpine@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt && \
    mkdir -p /var/log/apps && chown 1000:1000 /var/log/apps
COPY app.py ./
USER 1000:1000
EXPOSE 8000
CMD ["python", "-u", "app.py"]
