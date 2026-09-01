FROM python:3.11-slim

WORKDIR /app

# 先装依赖再拷代码，利用镜像层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
