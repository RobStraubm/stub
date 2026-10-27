#!/bin/zsh
# Doppelklick startet Stub und öffnet die Oberfläche im Browser.
cd "$(dirname "$0")"
exec .venv/bin/python -m stub
