#!/bin/bash
# Instala ffmpeg (necesario para convertir a MP3)
apt-get update && apt-get install -y ffmpeg
pip install -r requirements.txt
