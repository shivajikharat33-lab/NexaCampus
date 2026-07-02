FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc g++ libffi-dev libssl-dev libxcb1 libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir fastapi "uvicorn[standard]" pymongo python-dotenv "python-jose[cryptography]" passlib "bcrypt==4.0.1" python-multipart Pillow piexif requests openpyxl reportlab "qrcode[pil]" twilio ultralytics opencv-python-headless

COPY . .

RUN mkdir -p uploads logs

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
