#!/bin/bash
cd /run/media/teo-derizzo/HDD/Chloe/fish-speech
source .fishvenv/bin/activate
python -m tools.api_server --listen 0.0.0.0:8080 \
    --llama-checkpoint-path checkpoints/fish-speech-1.5 \
    --decoder-checkpoint-path checkpoints/fish-speech-1.5/firefly-gan-vq-fsq-8x1024-21hz-generator.pth \
    --device cuda --half &
FISH_PID=$!

cd /run/media/teo-derizzo/HDD/Chloe/Chloe-master
.venv/bin/python voice_app.py

kill $FISH_PID 2>/dev/null
