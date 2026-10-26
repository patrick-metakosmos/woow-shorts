@echo off
rem Rodada diaria do WooW_Shorts: gera o video da edicao do dia e publica nas redes.
rem Agendado no Agendador de Tarefas ("WooW Shorts diario", 09:15). Para desligar:
rem   Disable-ScheduledTask -TaskName "WooW Shorts diario"
rem A voz vai explicita: sem isso o programa cai na voz padrao do Google (Puck).
setlocal
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
echo ---------- %date% %time% >> "output\diario.log"
python woow_shorts.py --publicar --motor elevenlabs --voz 0YziWIrqiRTHCxeg1lyc >> "output\diario.log" 2>&1
echo FIM codigo=%errorlevel% >> "output\diario.log"
