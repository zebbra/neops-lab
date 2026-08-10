FROM python:3.12-slim

RUN pip install --no-cache-dir pyyaml==6.0.2 requests==2.32.3

COPY register.py /usr/local/bin/register.py

ENTRYPOINT ["python", "/usr/local/bin/register.py"]
