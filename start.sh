#!/bin/bash
cd /home/ubuntu/nutribot
source venv/bin/activate
screen -dmS nutribot python main.py
echo "Nutribot corriendo en background (screen -r nutribot para ver logs)"
