FROM python:3.12-slim

WORKDIR /app
COPY containers/pattern-command/requirements.txt ./requirements.txt
COPY containers/pattern-command ./
COPY config/pattern-command*.yaml ./config/
RUN pip install --no-cache-dir -r requirements.txt

ENV APP_ENV=prod

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8761"]
