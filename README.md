# Test Circuit Generator

Type a resistor circuit in a tiny "circuit lingo", get a worksheet-style figure, the answers and a worked
solution. Built for Physics 2 instructors writing series/parallel exam questions. No AI is needed; the same
text always gives the same figure and the same numbers.

```
source: 12 V
circuit: (4 + 2) || 6 + 3
ask: current through R2, voltage across R2
```

`+` = series, `||` = parallel (binds tighter, like ×), parentheses group. Parts are numbered in the
order written; the first parts go on the top rail, the last series part on the bottom rail, parallel branches
stack top to bottom. `4uF` is a capacitor, `S1=closed` a switch, `A1` an ammeter, `6 || V1` a voltmeter across
the 6 Ω; `6?` hides a value on the figure. Plain English works too ("a 4 ohm and a 2 ohm in series, that pair
in parallel with a 6 ohm, then a 3 ohm; find the current through the 2 ohm") - fixed rules turn it into lingo,
no AI. Full guide in the app's **How to use** tab.

## Use it in a browser (no install)

**https://myrlaphil.github.io/Test-Circuit-Generator/** - the whole app runs inside your browser
([stlite](https://github.com/whitphx/stlite): Streamlit on Pyodide/WebAssembly). The first visit downloads
about 30 MB of Python and packages, so give it half a minute; nothing you type leaves your computer.
The optional AI translator is the one feature meant for the desktop version.

## Run it on your computer

1. Install Python 3.10+ from https://www.python.org/downloads/ (Windows: tick "Add to PATH").
2. Windows: double-click `run_windows.bat`. Mac/Linux: `bash run_mac_linux.sh`.
   (or: `pip install -r requirements.txt` then `streamlit run app.py`)
3. The browser opens at http://localhost:8501. A short get-started tour shows the first time only.

## What's inside

| File | Job |
|---|---|
| `app.py` | the screens: Create, Questions & Solutions, How to use, references (Streamlit) |
| `lingo.py` | parser, worksheet-style layout → Schemdraw code, reduction solver with worked steps, random problems |
| `render_worker.py` | runs the Schemdraw code in a separate, time-limited process; saves SVG/PNG/PDF |
| `exam_pdf.py` | questions-then-solutions PDF (ReportLab) |
| `llm.py`, `circuit_core.py` | optional AI translator (English → lingo) and the earlier JSON-spec engine it borrows from |
| `test_lingo.py` | checks against hand-worked answers: `python -m pytest` |
| `site/index.html`, `build_site.sh` | the GitHub Pages build (stlite); deployed by `.github/workflows/pages.yml` on every push to `main` |

## Features
- Resistors, capacitors, switches (open/closed) and ideal meters, solved in DC steady state by series/parallel
  reduction with the worked steps a student would write (Q = CV, U = ½CV², meter readings, open/shorted branches)
- Plain-English sentences translated to lingo by fixed rules; the generated lingo is always shown
- Random problem button (ten arrangements, nice values)
- Figure export as PNG, JPEG, PDF, SVG; lingo export to reload later
- Questions & Solutions tab → two-part exam PDF
- "What code made this?" expander showing the exact Schemdraw script, with documentation links
- Optional AI translator (Claude, OpenAI, Gemini, or free local Ollama) whose output is always shown for checking

## Roadmap
- RC time constants, multi-battery loops and bridges (the JSON-spec engine in `circuit_core.py` already solves loops)
- Upload a photo of an existing figure and generate a variation

## Built with
[Schemdraw](https://schemdraw.readthedocs.io/) · [Streamlit](https://docs.streamlit.io/) ·
[Matplotlib](https://matplotlib.org/) · [Pillow](https://pillow.readthedocs.io/) · [ReportLab](https://docs.reportlab.com/)

MIT licensed.
