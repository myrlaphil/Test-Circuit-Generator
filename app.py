"""
Test Circuit Generator - type a circuit in plain "circuit lingo", get a worksheet-style
figure, the answers and a worked solution.  No AI needed (AI is an optional helper).

Run:  streamlit run app.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st

import exam_pdf
import lingo
import llm

APP_DIR = Path(__file__).resolve().parent
WORKER = APP_DIR / "render_worker.py"
IN_BROWSER = sys.platform == "emscripten"      # running under stlite / Pyodide (GitHub Pages build)
SETTINGS_FILE = Path.home() / ".test_circuit_generator.json"
DOCS = {
    "schemdraw": "https://schemdraw.readthedocs.io/",
    "schemdraw_elements": "https://schemdraw.readthedocs.io/en/stable/elements/electrical.html",
    "schemdraw_placement": "https://schemdraw.readthedocs.io/en/stable/usage/placement.html",
    "schemdraw_labels": "https://schemdraw.readthedocs.io/en/stable/usage/labels.html",
    "streamlit": "https://docs.streamlit.io/",
    "matplotlib": "https://matplotlib.org/stable/",
    "reportlab": "https://docs.reportlab.com/",
    "pillow": "https://pillow.readthedocs.io/",
    "python_re": "https://docs.python.org/3/library/re.html",
    "series_parallel": "https://openstax.org/books/college-physics-2e/pages/21-1-resistors-in-series-and-parallel",
    "youtube": "https://www.youtube.com/watch?v=kA69T-zXcMs",
}

st.set_page_config(page_title="Test Circuit Generator", page_icon="⚡", layout="wide")

EXAMPLES = {
    "Worksheet problem 1": "source: 12 V\ncircuit: (4 + 2) || 6 + 3\nask: current through R2, voltage across R2",
    "Worksheet problem 2": "source: 6 V\ncircuit: 6 || (2 + 3 || 6) + 1\nask: power in R3",
    "Simple series": "source: 9 V\ncircuit: 2 + 4 + 6\nask: total current",
    "Simple parallel": "source: 12 V\ncircuit: 3 || 6 || 9\nask: equivalent resistance, total current",
    "Unknown resistor": "source: 24 V\ncircuit: 4 + 12 || 6 + 4\nask: current through R3\nhide: R3\n"
                        "text: The battery supplies 2.00 A. Find the current through R3.",
}
ENGLISH_EXAMPLES = {
    "Worksheet problem 1": "12 V battery. A 4 ohm and a 2 ohm in series, that pair in parallel with a 6 ohm, then a "
                           "3 ohm. Find the current through and the voltage across the 2 ohm resistor.",
    "Worksheet problem 2": "6 V battery, a 3 ohm and a 6 ohm in parallel, then a 2 ohm in series with that pair, a 6 ohm "
                           "across that whole group, then a 1 ohm. Calculate the power dissipated in the 3 ohm resistor.",
    "Three in parallel": "A 9 volt battery with 2, 4 and 6 ohms in parallel. Find the total current and the equivalent "
                         "resistance.",
    "Unknown resistor": "24 V battery, a 4 ohm in series with a 12 ohm, then an unknown 6 ohm. What is the voltage "
                        "across each resistor?",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def load_settings() -> Dict[str, Any]:
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        return {}


def save_settings(d: Dict[str, Any]) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(d))
    except Exception:
        pass


def _render_subprocess(code: str, tmp: str) -> Dict[str, Any]:
    """Desktop: run render_worker.py in a separate process with a 60 s time limit."""
    cf = Path(tmp) / "code.py"
    cf.write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run([sys.executable, str(WORKER), str(cf), tmp], capture_output=True, text=True, timeout=60)
        return json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {
            "ok": False, "error": proc.stderr[-400:] or "no output"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _render_in_process(code: str, tmp: str) -> Dict[str, Any]:
    """Browser (stlite): no subprocesses exist, so call the worker's function directly."""
    import render_worker
    try:
        return render_worker.render_files(code, tmp)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def render(code: str) -> Dict[str, Any]:
    """Run the Schemdraw code (separate time-limited process on desktop, in-process in the browser)."""
    cache = st.session_state.setdefault("render_cache", {})
    key = hashlib.sha256(code.encode()).hexdigest()
    if key in cache:
        return cache[key]
    with tempfile.TemporaryDirectory() as tmp:
        info = _render_in_process(code, tmp) if IN_BROWSER else _render_subprocess(code, tmp)
        out = dict(info)
        if info.get("ok"):
            for ext in ("svg", "png", "pdf"):
                out[ext] = (Path(tmp) / f"diagram.{ext}").read_bytes()
            from PIL import Image
            im = Image.open(io.BytesIO(out["png"])).convert("RGB")
            b = io.BytesIO()
            im.save(b, "JPEG", quality=92)
            out["jpg"] = b.getvalue()
    if len(cache) > 40:
        cache.clear()
    cache[key] = out
    return out


_DL_CSS = """<style>
a.tcg-dl { display:inline-block; width:100%; box-sizing:border-box; text-align:center; padding:0.25rem 0.75rem;
  min-height:2.5rem; line-height:2rem; border-radius:0.5rem; border:1px solid rgba(49,51,63,0.2);
  color:inherit !important; text-decoration:none !important; font-weight:400; margin-bottom:0.5rem; }
a.tcg-dl:hover { border-color:#1f6feb; color:#1f6feb !important; }
</style>"""


def download(col, label: str, data, filename: str, mime: str) -> None:
    """A download control that also works in the browser build.

    st.download_button fetches from a server that does not exist under stlite, so there we
    emit a plain <a download> link carrying the bytes as a data: URL instead.
    """
    if not IN_BROWSER:
        col.download_button(label, data, filename, mime, width="stretch")
        return
    import base64
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    href = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    col.markdown(f'<a class="tcg-dl" href="{href}" download="{filename}">{label}</a>', unsafe_allow_html=True)


def build(text: str, style: str) -> Dict[str, Any]:
    """lingo text -> everything the screens need."""
    p = lingo.parse(text)
    res = lingo.solve(p)
    code = lingo.draw_code(p, style)
    return {"problem": p, "result": res, "code": code, "question": lingo.question_text(p),
            "answers": lingo.answers(p, res), "solution": lingo.solution_markdown(p, res), "render": render(code)}


def get_client() -> Optional[llm.LLMClient]:
    ss = st.session_state
    preset = llm.PRESETS[ss.ai_preset]
    if ("Ollama" not in ss.ai_preset and not ss.ai_key) or not ss.ai_model or not ss.ai_base:
        return None
    return llm.LLMClient(preset["provider"], ss.ai_key, ss.ai_model, ss.ai_base)


AI_SYSTEM = """You translate a physics teacher's description of a DC resistor circuit into "circuit lingo".
Reply with the lingo only, no commentary. Format:
source: <volts> V
circuit: <expression>   where + means series, || means parallel (|| binds tighter, like multiplication), parentheses group.
    Resistors are numbered R1, R2... in the order written. Write R3=6 to force a name.
ask: <one or more of: current through Rn, voltage across Rn, power in Rn, total current, equivalent resistance>
Optional lines:  hide: Rn   (prints "Rn = ?")     text: <the teacher's own wording of the question>
Example: "12 V battery; 4 and 2 in series, that pair in parallel with 6, then 3 in series; find the current in the 2 ohm"
->
source: 12 V
circuit: (4 + 2) || 6 + 3
ask: current through R2
Pick sensible values when the teacher gives none."""


def english_to_lingo(client: llm.LLMClient, text: str) -> str:
    reply = client.chat(AI_SYSTEM, [{"role": "user", "content": text}], max_tokens=400)
    reply = reply.replace("```", "").strip()
    lingo.parse(reply)          # raises a LingoError the teacher can read
    return reply


def set_text(t: str) -> None:
    st.session_state.lingo_text = t
    st.session_state.version += 1


# ---------------------------------------------------------------------------
# tour (first run only) and help
# ---------------------------------------------------------------------------

TOUR = [
    ("Welcome", "You type a circuit in a tiny language, the **circuit lingo**, and the app gives you a worksheet-style "
                "figure, the answers and a worked solution.\n\n```\nsource: 12 V\ncircuit: (4 + 2) || 6 + 3\n"
                "ask: current through R2, voltage across R2\n```\n`+` means series, `||` means parallel, parentheses "
                "group. That's most of it."),
    ("Where things are", "**Create** - type or dictate the lingo (or press *Random problem*), see the figure and "
                         "answers, then *Add to exam*.\n\n**Questions & Solutions** - the problems you've kept, "
                         "exported as a two-part PDF (questions, then solutions).\n\n**How to use** - the full lingo "
                         "guide, worked examples you can load with one click, and what code does what."),
    ("Placing resistors", "Order matters: the first parts go on the top rail, left to right; the last series part "
                          "goes on the bottom rail; parallel branches stack top to bottom in the order you write "
                          "them.\n\nSo `(4 + 2) || 6 + 3` draws 4 and 2 on the upper branch, 6 on the lower branch, "
                          "and 3 on the bottom rail - exactly like a textbook figure."),
    ("Or just say it in English", "Open **Or write it in plain English** under the lingo box and type a sentence:\n\n"
                                  "> 12 V battery. A 4 ohm and a 2 ohm in series, that pair in parallel with a 6 ohm, "
                                  "then a 3 ohm. Find the current through the 2 ohm.\n\n"
                                  "Press **Translate to lingo**. Fixed rules (no AI) turn it into lingo, show you the "
                                  "result and put it in the box, so you learn the lingo as you go. Words the rules "
                                  "know: *in series with*, *in parallel with*, *across*, *that pair*, *then*, "
                                  "*unknown*, *find the current through / voltage across / power in ...*. "
                                  "A word they don't know is named in the error message."),
    ("Done", "The full guide is in the **How to use** tab, with links to the Schemdraw documentation and the exact "
             "code behind each figure. Replay this tour any time from the sidebar."),
]


def _move(d: int) -> None:
    st.session_state.tour_step = max(0, min(len(TOUR) - 1, st.session_state.tour_step + d))


@st.dialog("Get started", width="large")
def tour_dialog() -> None:
    i = st.session_state.tour_step
    st.progress((i + 1) / len(TOUR), text=f"{i + 1} of {len(TOUR)}")
    st.markdown(f"### {TOUR[i][0]}")
    st.markdown(TOUR[i][1])
    a, b, c = st.columns(3)
    a.button("← Back", disabled=i == 0, on_click=_move, args=(-1,), width="stretch")
    if i < len(TOUR) - 1:
        b.button("Next →", type="primary", on_click=_move, args=(1,), width="stretch")
        if c.button("Skip", width="stretch"):
            st.rerun()
    elif b.button("Start", type="primary", width="stretch"):
        st.rerun()


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

ss = st.session_state
if "version" not in ss:
    ss.version = 0
    ss.lingo_text = EXAMPLES["Worksheet problem 1"]
    ss.exam = []                       # list of dicts: text, question, solution, png, answers
    ss.tour_step = 0
    settings = load_settings()
    ss.open_tour = not settings.get("tour_seen")
    if ss.open_tour:
        settings["tour_seen"] = True
        save_settings(settings)
    first = list(llm.PRESETS)[0]
    ss.ai_preset, ss.ai_model, ss.ai_base = first, llm.PRESETS[first]["model"], llm.PRESETS[first]["base_url"]
    ss.ai_key = os.environ.get(llm.PRESETS[first]["env"], "")
    ss.style = "US"


def _preset_changed() -> None:
    p = llm.PRESETS[ss.ai_preset]
    ss.ai_model, ss.ai_base = p["model"], p["base_url"]
    ss.ai_key = os.environ.get(p["env"], "") if p["env"] else ""


with st.sidebar:
    st.markdown("## ⚡ Test Circuit Generator")
    st.caption("Series & parallel resistor problems for Physics 2.")
    st.radio("Resistor symbol", ["US", "IEC"], key="style", horizontal=True, captions=["zig-zag", "box"])
    with st.expander("🤖 Optional: AI translator"):
        st.caption("Backup for plain-English sentences the built-in rules cannot read. Everything else works without it.")
        st.selectbox("Service", list(llm.PRESETS), key="ai_preset", on_change=_preset_changed)
        st.text_input("API key", key="ai_key", type="password", placeholder="not needed for Ollama")
        st.text_input("Model", key="ai_model")
        st.text_input("Base URL", key="ai_base")
        st.success("AI ready") if get_client() else st.info("No AI connected")
    if st.button("🎓 Replay the get-started tour", width="stretch"):
        ss.tour_step, ss.open_tour = 0, True

if ss.open_tour:
    ss.open_tour = False
    tour_dialog()

st.title("⚡ Test Circuit Generator")
if IN_BROWSER:
    st.markdown(_DL_CSS, unsafe_allow_html=True)      # styles the data-URL download links (every rerun)
tab_create, tab_exam, tab_help = st.tabs(["✏️ Create", "📋 Questions & Solutions", "📖 How to use"])

# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------

with tab_create:
    left, right = st.columns([0.42, 0.58], gap="large")
    with left:
        st.subheader("1. Describe the circuit")
        c1, c2, c3 = st.columns(3)
        if c1.button("🎲 Random problem", width="stretch"):
            set_text(lingo.random_lingo())
            st.rerun()
        example = c2.selectbox("Example", list(EXAMPLES), label_visibility="collapsed")
        if c3.button("Load example", width="stretch"):
            set_text(EXAMPLES[example])
            st.rerun()
        text = st.text_area("Circuit lingo", ss.lingo_text, key=f"lingo_{ss.version}", height=150,
                            help="+ = series, || = parallel, ( ) = grouping. See the How to use tab.")
        ss.lingo_text = text
        with st.expander("Or write it in plain English", expanded=bool(ss.get("last_translation"))):
            english = st.text_area("Plain English", height=80, key="english",
                                   placeholder="12 V battery, a 4 ohm and a 2 ohm in series, that pair in parallel "
                                               "with a 6 ohm, then a 3 ohm. Find the current through the 2 ohm.")
            client = get_client()
            if st.button("Translate to lingo", type="primary", disabled=not english.strip()):
                try:
                    result, how = lingo.translate(english), "rules"
                except lingo.LingoError as rule_error:
                    if client is None:
                        st.error(str(rule_error))
                        result = None
                    else:
                        try:
                            result, how = english_to_lingo(client, english), "AI"
                        except (llm.LLMError, lingo.LingoError) as e:
                            st.error(f"{rule_error}\n\nThe AI translator could not help either: {e}")
                            result = None
                if result:
                    ss.last_translation = {"english": english, "lingo": result, "how": how}
                    set_text(result)
                    st.rerun()
            if ss.get("last_translation"):
                lt = ss.last_translation
                st.markdown("**Translated to lingo** " + ("(by the rules, no AI)" if lt["how"] == "rules"
                                                          else "(by the AI helper - check it)"))
                st.markdown(f"> {lt['english']}")
                st.code(lt["lingo"], language="text")
                st.caption("This is what the lingo box now holds. Same words next time give the same lingo. "
                           "Phrases the rules know: *in series (with)*, *in parallel (with)*, *across*, *that pair*, "
                           "*then*, *unknown*, *find the current through / voltage across / power in ...*")
            else:
                st.caption("Plain sentences are turned into lingo by fixed rules (no AI). The lingo is shown here "
                           "and put in the box above, so you can check it and learn it. The optional AI translator "
                           "in the sidebar only steps in for sentences the rules cannot read.")

        try:
            built = build(text, ss.style)
            error = None
        except lingo.LingoError as e:
            built, error = None, str(e)

        if error:
            st.error(error)
        else:
            p = built["problem"]
            st.subheader("2. Question")
            st.markdown(f"> {built['question']}")
            st.subheader("3. Answers")
            if built["answers"]:
                st.success("\n".join(f"- {a}" for a in built["answers"]))
            else:
                st.info("Add an `ask:` line to pick what students must find.")
            with st.expander("Worked solution"):
                st.markdown(built["solution"])
            if st.button("➕ Add to exam", type="primary", disabled=not built["render"].get("ok")):
                ss.exam.append({"text": text, "question": built["question"], "solution": built["solution"],
                                "png": built["render"]["png"], "answers": built["answers"]})
                st.toast(f"Added as problem {len(ss.exam)}.", icon="✅")

    with right:
        st.subheader("Figure")
        if built and built["render"].get("ok"):
            r = built["render"]
            st.image(r["png"], width="stretch")
            name = "circuit"
            d1, d2, d3, d4, d5 = st.columns(5)
            download(d1, "PNG", r["png"], f"{name}.png", "image/png")
            download(d2, "JPEG", r["jpg"], f"{name}.jpg", "image/jpeg")
            download(d3, "PDF", r["pdf"], f"{name}.pdf", "application/pdf")
            download(d4, "SVG", r["svg"], f"{name}.svg", "image/svg+xml")
            download(d5, "Lingo", text, f"{name}.txt", "text/plain")
            with st.expander("🔍 What code made this? (transparency)"):
                st.markdown(
                    f"1. **Parser** (`lingo.parse`, plain Python with [regular expressions]({DOCS['python_re']})) "
                    f"read your text into a tree: series and parallel groups of resistors.\n"
                    f"2. **Layout** (`lingo.draw_code`) walked that tree and wrote the "
                    f"[Schemdraw]({DOCS['schemdraw']}) script below: every part is placed with "
                    f"[`.endpoints()`]({DOCS['schemdraw_placement']}) at exact coordinates, so loops always close.\n"
                    f"3. **Renderer** (`render_worker.py`) ran that script in a separate process and saved SVG, and "
                    f"PNG/PDF through [Matplotlib]({DOCS['matplotlib']}).\n"
                    f"4. **Solver** (`lingo.solve`) reduced the same tree step by step (series add, parallel "
                    f"reciprocals) - that is the worked solution on the left.")
                st.code(built["code"], language="python")
                st.caption(f"Element gallery: [{DOCS['schemdraw_elements']}]({DOCS['schemdraw_elements']}) · "
                           f"Labels: [{DOCS['schemdraw_labels']}]({DOCS['schemdraw_labels']})")
        elif built:
            st.error("The figure could not be drawn: " + str(built["render"].get("error")))

# ---------------------------------------------------------------------------
# QUESTIONS & SOLUTIONS
# ---------------------------------------------------------------------------

with tab_exam:
    if not ss.exam:
        st.info("No problems yet. Make one in the Create tab and press **Add to exam**.")
    else:
        title = st.text_input("Exam title", "Resistors in series and parallel")
        e1, e2, e3 = st.columns(3)
        items = [(x["question"], x["solution"], x["png"], "; ".join(x["answers"])) for x in ss.exam]
        download(e1, "⬇️ Questions + solutions PDF", exam_pdf.build(items, title, True),
                 "exam_with_solutions.pdf", "application/pdf")
        download(e2, "⬇️ Questions only PDF", exam_pdf.build(items, title, False),
                 "exam_questions.pdf", "application/pdf")
        download(e3, "⬇️ All lingo (.txt, reload later)", "\n\n---\n\n".join(x["text"] for x in ss.exam),
                 "exam_lingo.txt", "text/plain")
        st.divider()
        for i, x in enumerate(ss.exam):
            a, b = st.columns([0.55, 0.45], gap="large")
            with a:
                st.markdown(f"**{i + 1}.** {x['question']}")
                st.image(x["png"], width=420)
            with b:
                st.markdown("**Answer:** " + "; ".join(x["answers"]) if x["answers"] else "_no ask line_")
                with st.expander("Solution"):
                    st.markdown(x["solution"])
                k1, k2 = st.columns(2)
                if k1.button("Edit in Create", key=f"edit{i}"):
                    set_text(x["text"])
                    st.rerun()
                if k2.button("Remove", key=f"rm{i}"):
                    ss.exam.pop(i)
                    st.rerun()
            st.divider()

# ---------------------------------------------------------------------------
# HOW TO USE
# ---------------------------------------------------------------------------

with tab_help:
    st.markdown(f"""
### The circuit lingo

| You write | Meaning |
|---|---|
| `source: 12 V` | the battery (drawn on the left, + at the top) |
| `circuit: 4 + 2` | **`+` = series** |
| `circuit: 4 \\|\\| 6` | **`\\|\\|` = parallel** (binds tighter than `+`, like × vs +) |
| `circuit: (4 + 2) \\|\\| 6 + 3` | parentheses group: 4 and 2 in series, that pair in parallel with 6, then 3 in series |
| `circuit: R3=6 + 2` | give a resistor your own name |
| `circuit: 2 kohm + 470` | values may carry k / kΩ; bare numbers are ohms |
| `circuit: 4 + 6? + 3` | `?` after a value (or the word **unknown** before it) prints "R2 = ?" on the figure; the answer key still knows it is 6 Ω |
| `ask: current through R2` | also `voltage across R2`, `power in R2`, `total current`, `equivalent resistance`, or `the 2 ohm resistor` |
| `hide: R3` | the other way to print "R3 = ?" on the figure |
| `text: ...` | your own wording of the question instead of the automatic one |
| `title: Quiz 3` | a title kept with the problem |

Dictation-friendly words work on the circuit line too: **plus**, **in series with**, **then**, **followed by** for `+`;
**parallel**, **in parallel with**, **across**, **with** for `||`; **unknown** for `?`; **ohm(s)**, **kohm**, **volt(s)**.
So `4 in series with 2 in parallel with 6 then 3` is read as `4 + 2 || 6 + 3` (the usual `||`-first precedence applies).

### Plain English (no AI needed)

Under the lingo box, open **Or write it in plain English**, type a sentence and press **Translate to lingo**.
Fixed rules read it, show the lingo they produced, and put it in the lingo box. The same sentence always gives the same lingo.

| You say | The rules produce |
|---|---|
| 12 V battery *(or: a 6 volt source)* | `source: 12 V` |
| a 4 ohm and a 2 ohm **in series** *(or: a 4 ohm **in series with** a 2 ohm)* | `4 + 2` |
| a 3 ohm and a 6 ohm **in parallel** · 2, 4 and 6 ohms **in parallel** | `3 \\|\\| 6` · `2 \\|\\| 4 \\|\\| 6` |
| ..., **that pair** in parallel with a 6 ohm *(also: that group, the combination, them)* | `(4 + 2) \\|\\| 6` |
| ..., a 6 ohm **across** that pair | `6 \\|\\| (4 + 2)` - the 6 comes first because you said it first |
| ..., **then** a 3 ohm *(also: followed by, next, finally)* | `+ 3` on the end |
| **two 4 ohm resistors** · **3 resistors of 6 ohms** · **twelve volt** | `4 + 4` · `6 \\|\\| 6 \\|\\| 6` · `12 V` |
| 4.7 **kilo-ohm** · 2.2**k** | `4700` · `2200` |
| an **unknown** 6 ohm · the 3 ohm **is unknown** | `hide: R3` |
| **Find** the current through **and** the voltage across the 2 ohm resistor | `ask: current through R2, voltage across R2` |
| **What is** the power in R3 · **Calculate** the total current · the equivalent resistance | `ask: power in R3` · `ask: total current` · `ask: equivalent resistance` |
| the voltage across **each** resistor | one `voltage across` ask per resistor |

One connection per phrase: write "a 4 ohm and a 2 ohm in series, that pair in parallel with a 6 ohm" rather than
"4 and 2 in series with 6 in parallel". A word the rules do not know stops the translation with a message naming that word,
so nothing is guessed. The optional AI translator in the sidebar is only tried when the rules give up.

### Where the resistors go
Reading order decides the picture. Parts before the last `+` go on the **top rail** left to right;
the **last** series part goes on the **bottom rail**; parallel branches **stack top to bottom** in the order written.
To move a resistor, move it in the text: `3 + (4 + 2) || 6` puts the 3 Ω on the top-left instead of the bottom.

### Try these
""")
    for name, t in EXAMPLES.items():
        h1, h2 = st.columns([0.7, 0.3])
        h1.code(t, language="text")
        if h2.button(f"Load: {name}", key=f"help_{name}", width="stretch"):
            set_text(t)
            st.toast("Loaded - see the Create tab.", icon="✏️")
            st.rerun()
    st.markdown("### Try these sentences")
    for name, en in ENGLISH_EXAMPLES.items():
        h1, h2 = st.columns([0.7, 0.3])
        h1.markdown(f"> {en}")
        if h2.button(f"Translate: {name}", key=f"help_en_{name}", width="stretch"):
            result = lingo.translate(en)
            ss.last_translation = {"english": en, "lingo": result, "how": "rules"}
            set_text(result)
            st.toast("Translated and loaded - see the Create tab.", icon="✏️")
            st.rerun()
    st.markdown(f"""
### What code does what (and where to read more)
| Step | Code | Documentation |
|---|---|---|
| Read your text | `lingo.parse` - a small hand-written parser (recursive descent) | [Python `re`]({DOCS['python_re']}) |
| Plain English → lingo | `lingo.translate` - fixed phrase rules, clause by clause; unknown words stop it with a message | [Python `re`]({DOCS['python_re']}) |
| Draw the figure | `lingo.draw_code` writes a Schemdraw script; `render_worker.py` runs it in a separate process | [Schemdraw docs]({DOCS['schemdraw']}), [placement with `.endpoints()`]({DOCS['schemdraw_placement']}), [labels]({DOCS['schemdraw_labels']}), [video tutorial]({DOCS['youtube']}) |
| PNG / JPEG / PDF | Schemdraw's Matplotlib backend, JPEG via Pillow | [Matplotlib]({DOCS['matplotlib']}), [Pillow]({DOCS['pillow']}) |
| Solve | `lingo.solve` - series/parallel reduction, then back-substitution | [OpenStax: resistors in series and parallel]({DOCS['series_parallel']}) |
| Exam PDF | `exam_pdf.py` | [ReportLab]({DOCS['reportlab']}) |
| This screen | `app.py` | [Streamlit]({DOCS['streamlit']}) |
| Random problems | `lingo.random_lingo` - six Physics-2 arrangements, values from a fixed pool | - |
| Optional AI | `llm.py` translates English → lingo; the result is always shown for checking | - |

**Limits (for now):** DC circuits with one battery and resistors only. Capacitors, switches, meters and
multi-battery loops are next on the list. Uploading a photo of an existing figure and getting a variation is planned.
""")

# ---------------------------------------------------------------------------
# REFERENCES (bottom of every page)
# ---------------------------------------------------------------------------

st.divider()
st.markdown(f"""
**References - software used by this tool**
[Schemdraw]({DOCS['schemdraw']}) (circuit drawing) ·
[Streamlit]({DOCS['streamlit']}) (interface) ·
[Matplotlib]({DOCS['matplotlib']}) (PNG/PDF rendering) ·
[Pillow]({DOCS['pillow']}) (JPEG) ·
[ReportLab]({DOCS['reportlab']}) (exam PDF) ·
[Python]({'https://www.python.org/'}) ·
[OpenStax College Physics, ch. 21]({DOCS['series_parallel']}) (physics background) ·
[Schemdraw video tutorial]({DOCS['youtube']}) ·
[Source code on GitHub](https://github.com/) (this project)
""")
