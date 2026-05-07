FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN wget -q -O /app/yolov8n-face.pt \
    https://huggingface.co/arnabdhar/YOLOv8-Face-Detection/resolve/main/model.pt

COPY main.py .

CMD ["python", "main.py"]
