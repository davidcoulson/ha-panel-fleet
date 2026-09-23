ARG BUILD_FROM
FROM ${BUILD_FROM}

# Supervisor passes the add-on version in at build time; the page shows
# it, so a stale tab can be told from a failed update at a glance.
ARG BUILD_VERSION
ENV ADDON_VERSION=${BUILD_VERSION}

COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

COPY app /app
WORKDIR /app
# No s6 init: it would reset the environment, taking SUPERVISOR_TOKEN
# with it, and one process needs no supervision tree.
ENTRYPOINT []
CMD ["python3", "-u", "/app/main.py"]
