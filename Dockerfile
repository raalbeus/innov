# Production image. Put it behind HTTPS (Azure App Service, a reverse proxy, or similar) and set the
# variables from .env.example as platform secrets. Mount a persistent volume at /data.
FROM python:3.12-slim
WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY engine ./engine
COPY run.sh .
ENV DATA_DIR=/data HOST=0.0.0.0 PORT=8000
RUN useradd --create-home bidapp && mkdir -p /data && chown bidapp /data
USER bidapp
EXPOSE 8000
CMD ["./run.sh"]
