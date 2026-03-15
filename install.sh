#!/bin/bash
echo "=== Instalando Nutribot en Oracle Cloud ==="

# Actualizar sistema
sudo apt-get update -y
sudo apt-get upgrade -y

# Instalar Python 3.11 y dependencias del sistema
sudo apt-get install -y python3.11 python3.11-venv python3-pip git screen

# Crear entorno virtual
python3.11 -m venv venv
source venv/bin/activate

# Instalar dependencias Python
pip install --upgrade pip
pip install -r requirements.txt

# Crear carpetas necesarias
mkdir -p data
mkdir -p media/stickers/Advertencia
mkdir -p media/stickers/Celebracion
mkdir -p media/stickers/Falta_de_Respeto
mkdir -p media/stickers/Felicitaciones
mkdir -p media/stickers/Nathalie
mkdir -p media/stickers/Reproche

echo "=== Instalación completa ==="
echo "Siguiente paso: edita el .env con tus credenciales"
