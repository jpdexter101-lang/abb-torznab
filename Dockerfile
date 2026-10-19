FROM python:3.12-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY abb_torznab ./abb_torznab
USER nobody
EXPOSE 9117
HEALTHCHECK CMD wget -qO- http://127.0.0.1:9117/health || exit 1
CMD ["python", "-m", "abb_torznab"]
