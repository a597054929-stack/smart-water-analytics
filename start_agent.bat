@echo off
echo === Smart Water AI Agent ===
echo.

cd /d "%~dp0\agent"

:: ===== LLM Config =====
:: Change these to use a different provider:
::   Option 1: MiMo (free)
::   Option 2: DeepSeek
::   Option 3: NVIDIA (GLM/Qwen/DeepSeek)
::   Option 4: Any OpenAI-compatible API

set LLM_PROVIDER=mimo
set LLM_MODEL=mimo-v2.5-pro

:: =======================

echo Provider: %LLM_PROVIDER%
echo Model: %LLM_MODEL%
echo.

echo Checking Python dependencies...
pip install -r ../requirements.txt -q

echo.
echo Starting AI Agent server at http://localhost:8000
echo.

python server.py
