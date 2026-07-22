FROM python:3.13-slim

# 国内构建加速：可用 build arg 覆盖为官方源（海外环境）：
#   APT_MIRROR=https://deb.debian.org/debian  PIP_INDEX_URL=https://pypi.org/simple
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=$PIP_INDEX_URL

WORKDIR /app

RUN sed -i -E "s#https?://deb\.debian\.org/debian#${APT_MIRROR}#g" /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY backend/app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
