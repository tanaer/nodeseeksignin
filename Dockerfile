FROM python:3.11-slim

# 安装系统依赖和 Playwright 需要的支持库
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm1 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 初始化 camoufox (基于 playwright 的免检测浏览器)
RUN camoufox fetch

# 复制代码
COPY . .

# 通过 xvfb 运行守护进程（如果是无头模式可以直跑，但xvfb更稳妥）
CMD ["xvfb-run", "python", "-u", "daemon.py"]
