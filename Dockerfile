FROM python:3.11-slim

WORKDIR /app

# 1. 安装系统级依赖
# 选用 debian 官方源可能慢，如果有问题可以换阿里源
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 2. 复制依赖清单
COPY requirements.txt .

# 3. 安装依赖 (集成加速方案)
# Step 0: 预先安装 CPU版 PyTorch (避免下载巨大的 CUDA 版本，适合 NAS/无显卡环境)
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Step A: 优先走阿里云镜像安装通用包
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# Step B: 单独安装 Google AI SDK (强制走宿主机代理，防止连接超时)
# 注意：假设宿主机代理端口为 7899，如果不同请修改此处
RUN pip install --no-cache-dir \
    --proxy http://host.docker.internal:7899 \
    google-generativeai

# 4. 复制源码
COPY src/ ./src/
COPY web /app/web
COPY scripts/ ./scripts/

# 5. 环境配置
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 6. 启动命令 (V3.0 API Mode)
# [Fix] 端口改为 5000
# [Fix] 添加 --no-access-log 减少日志噪音，使用 --log-level warning 降低 uvicorn 自己的输出
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "5000", "--reload", "--no-access-log"]