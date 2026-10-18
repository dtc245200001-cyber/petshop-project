FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Tạo user không có quyền root (UID 10001)
RUN groupadd -r appuser --gid 10001 && \
    useradd  -r -g appuser --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates ./templates
# CSS, JavaScript, icon và ảnh dịch vụ (service_<id>.jpg). Lưu ý: Dockerfile KHÔNG cho phép
# chú thích cuối dòng lệnh, nên chú thích phải nằm trên dòng riêng như thế này.
COPY static ./static

USER appuser
EXPOSE 5000

# 1 worker + nhiều thread để metrics Prometheus nhất quán; log ra stdout cho Loki
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", \
     "--access-logfile", "-", "--error-logfile", "-", "app:app"]
