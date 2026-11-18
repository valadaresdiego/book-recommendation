@echo off
rem Abre o Recomendador de Livros. Da para criar um atalho deste arquivo na Area de Trabalho.
title Recomendador de Livros
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar.ps1"
