FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY containers/canvas/app.py containers/canvas/drawing_canvas.py containers/canvas/canvas_config.py containers/canvas/canvas_config_loader.py containers/canvas/canvas_config_schema.py ./
COPY containers/pattern-command ./pattern-command
COPY config/canvas*.yaml ./config/
# requirements.txt pulls the GUI build of opencv-python for local (non-Docker) dev;
# swap it for the headless build here since this container has no display and the
# GUI build's import fails without X11 libs (libxcb.so.1 not present in the image).
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir "opencv-python-headless>=4.10,<5"

ENV APP_ENV=prod

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8762"]
