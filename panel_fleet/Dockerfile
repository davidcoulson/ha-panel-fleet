ARG BUILD_FROM
FROM ${BUILD_FROM}

COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

COPY app /app
WORKDIR /app
CMD ["python3", "-u", "/app/main.py"]
