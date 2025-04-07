#!/usr/bin/env bash
set -o errexit

# Instalar dependencias del sistema necesarias para face-recognition/dlib/opencv
apt-get update && apt-get install -y \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libavcodec-dev

# Opcional: Configurar mirror de PyPI para descargas más rápidas
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
