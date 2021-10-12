FROM python:3.10.0-slim-bullseye AS build
WORKDIR /app
RUN apt-get update && apt-get install -y git
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.10.0-slim-bullseye
WORKDIR /app/data
COPY --from=build /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY main.py /app
CMD ["python", "/app/main.py"]
