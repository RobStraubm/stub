#!/bin/zsh
# Doppelklick startet den Belegscanner und öffnet ihn im Browser.
cd "$(dirname "$0")"
exec .venv/bin/python belegscanner.py
