# Belegscanner

*Scan a receipt, get a named, searchable PDF.* Belegscanner turns a network scanner and a Mac into a receipt inbox for your bookkeeping.

**English summary** · Deutsche Kurzanleitung unten

- Scans straight from a network scanner over AirScan (eSCL), the protocol most Wi-Fi printers speak. No vendor software, no driver.
- Crops the receipt out of the scan by itself. Several receipts on the glass at once are split into one PDF each; a crop dialog lets you draw the areas by hand when the automatic cut is wrong.
- Reads the text with the macOS Vision framework and writes it as an invisible layer into the PDF, so every receipt is searchable in Finder and Spotlight.
- The Claude Code CLI reads the page images and fills in date, merchant, kind of expense and gross amount, and for business meals the occasion and guests as written on the receipt, handwriting included. Without Claude, or if it fails, simple pattern matching fills in date, amount and merchant.
- Each PDF is renamed after its fields, e.g. `2026-10-14_Tankstelle-am-See_Tanken_79,32EUR.pdf`, filed in a folder per scan day, and listed in a CSV per day (`2026-10-27_Belegliste.csv`, semicolon-separated, opens in Excel or Numbers).
- Keyboard first: the space bar scans the next receipt and confirms the previous one. Fields can be corrected in place, pages added to a receipt, a receipt deleted (it goes to the Trash).
- Data stays local: the app is a small Python server on 127.0.0.1 with a page in the browser. Scans, PDFs and the list stay on the Mac. The only thing that leaves it is the AI step: the page images go to Claude through your own Claude Code login.
- Built with Claude Code.
- License: [AGPL-3.0](LICENSE), because the PDF library PyMuPDF is licensed under the AGPL.

## How the AI step is fenced in

The receipt is untrusted input: anyone can print text on a receipt. So `claude` runs headless (`claude -p`) with `Read` as the only allowed tool and `Bash`, `Edit`, `Write`, web and agent tools explicitly disallowed, in the app's work folder, with a 150-second timeout. The prompt says that image content and text are data and that instructions in them are not to be followed, and asks for a single JSON object. The app only takes the five expected fields from it, checks the date format, and every field stays editable before you confirm the receipt.

## Requirements

- macOS (the text recognition uses the Vision framework; built and used on macOS 27)
- Python 3.11 or newer
- A scanner reachable over AirScan/eSCL in the same network
- Optional: [Claude Code](https://claude.com/claude-code), logged in, for the AI step

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python belegscanner.py
```

The page opens at http://127.0.0.1:8737. Under **Einstellungen** enter the scanner's address, e.g. `drucker.local:8080` (shown in the printer's network settings or with `dns-sd -B _uscan._tcp`), and choose resolution, colour and whether Claude is used. **Ablage** sets the folder for the PDFs (default `~/Documents/Belege`). Settings are saved in `config.json` next to the code, which is not part of the repository.

`Belegscanner.command` starts the app with a double click. For a Dock icon, wrap the same two lines in an app (Automator → Application → Run Shell Script): start `belegscanner.py --no-browser` in the background if nothing answers on port 8737 yet, then `open http://127.0.0.1:8737`. The server quits by itself 15 minutes after the last browser window closed.

---

## Kurzanleitung (Deutsch)

1. Beleg mit der bedruckten Seite nach unten aufs Glas legen, **Scannen** drücken oder Leertaste.
2. Mehrere Belege nebeneinander? Oben **Mehrere auf dem Glas** wählen, jeder Beleg wird ein eigenes PDF.
3. Felder prüfen, bei Bedarf korrigieren, **Passt ✓** (oder einfach den nächsten Beleg scannen).
4. Falsch zugeschnitten: **Zuschneiden**, Bereiche ziehen, **Übernehmen**. Mehrseitige Rechnung: **+ Seite**.

Ablage: `<Ablage>/<Scandatum>/<Belegdatum>_<Händler>_<Art>_<Betrag>EUR.pdf` und daneben `<Scandatum>_Belegliste.csv`.
