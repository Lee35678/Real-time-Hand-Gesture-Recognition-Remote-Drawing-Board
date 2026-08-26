FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY containers/0-web/app.py ./app.py
COPY containers/0-web/web ./web
# requirements.txt pulls the GUI build of opencv-python for local (non-Docker) dev;
# swap it for the headless build here since this container has no display and the
# GUI build's import fails without X11 libs (libxcb.so.1 not present in the image).
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir "opencv-python-headless>=4.10,<5"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
