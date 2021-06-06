FROM python:3.9.5-slim-buster AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.9.5-slim-buster
WORKDIR /app/data
COPY --from=build /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY main.py /app
CMD ["python", "/app/main.py"]
