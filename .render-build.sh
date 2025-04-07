#!/usr/bin/env bash
set -o errexit

# Configura mirror de PyPI para China (opcional, pero más rápido)
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# Instala solo dependencias del sistema CRÍTICAS (evita apt-get si no es necesario)
# Render no permite modificar el sistema con apt-get en entornos efímeros
echo "Saltando instalación de paquetes del sistema (no permitido en Render)"
