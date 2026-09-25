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

DEFAULT_TYPE = "Mixed series-parallel"
ENGLISH_EXAMPLES = {
    "Textbook series-parallel": "12 V battery. A 4 ohm and a 2 ohm in series, that pair in parallel with a 6 ohm, "
                                "then a 3 ohm. Find the current through and the voltage across the 2 ohm resistor.",
    "Nested groups": "6 V battery, a 3 ohm and a 6 ohm in parallel, then a 2 ohm in series with that pair, a 6 ohm "
                     "across that whole group, then a 1 ohm. Calculate the power dissipated in the 3 ohm resistor.",
    "Three in parallel": "A 9 volt battery with 2, 4 and 6 ohms in parallel. Find the total current and the equivalent "
                         "resistance.",
    "Unknown resistor": "24 V battery, a 4 ohm in series with a 12 ohm, then a 6 ohm. The 6 ohm is unknown. Find the "
                        "resistance of R3 and the current through R3.",
    "Capacitors": "12 V battery, a 4 microfarad and a 2 microfarad capacitor in series, that pair in parallel with a "
                  "6 uF. Find the charge on the 4 uF capacitor and the equivalent capacitance.",
    "Switch and meters": "12 V battery, an ammeter, then a 4 ohm in series with a closed switch, that pair in parallel "
                         "with a 6 ohm, then a 3 ohm, a voltmeter across the 3 ohm. What does the ammeter read, and "
                         "what does the voltmeter read?",
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


AI_SYSTEM = """You translate a physics teacher's description of a DC circuit into "circuit lingo".
Reply with the lingo only: no commentary, no code fences. Format:
source: <volts> V
circuit: <expression>
ask: <comma-separated questions>
Optional lines:  hide: <names>  (prints "R3 = ?" on the figure)     text: <the teacher's own wording>

Expression: + means series, || means parallel (|| binds tighter, like multiplication), parentheses group.
Parts are numbered by kind in reading order (R1, R2 ... C1 ... S1 ... A1 ... V1):
  4        a 4 ohm resistor          4.7k   a 4.7 kilo-ohm resistor
  4uF      a capacitor (units F, mF, uF, nF, pF)
  S1=open or S1=closed               a switch
  A1       an ideal ammeter, in series with what it measures
  V1       an ideal voltmeter, in parallel with what it measures, e.g. 3 || V1
Questions: current through R2, voltage across R2, power in R2, resistance of R2, charge on C1, energy in C1,
  reading of A1, reading of V1, total current, equivalent resistance, equivalent capacitance.
One battery, DC steady state. Parts are drawn in the order written: first on the top rail, the last series part on
the bottom rail, parallel branches stacked top to bottom.

Example: "12 V battery; 4 and 2 in series, that pair in parallel with 6, then 3; find the current in the 2 ohm"
->
source: 12 V
circuit: (4 + 2) || 6 + 3
ask: current through R2

Pick sensible values when the teacher gives none. If the circuit cannot be written this way (two batteries, a bridge,
components other than these), reply with one line starting with "CANNOT:" and the reason."""


def english_to_lingo(client: llm.LLMClient, text: str, rule_error: str = "") -> str:
    """AI fallback.  Its reply must parse and solve as lingo, or it is rejected; one retry with the error."""
    note = f"\n\n(The built-in rules could not read this sentence: {rule_error})" if rule_error else ""
    msgs = [{"role": "user", "content": text + note}]
    for attempt in range(2):
        reply = client.chat(AI_SYSTEM, msgs, max_tokens=400).replace("```", "").strip()
        if reply.upper().startswith("CANNOT"):
            raise llm.LLMError(reply.split(":", 1)[-1].strip() or "this circuit cannot be written in lingo")
        try:
            lingo.solve(lingo.parse(reply))     # raises a LingoError the teacher can read
            return reply
        except lingo.LingoError as e:
            if attempt:
                raise
            msgs += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": f"That lingo gives this error: {e} Reply with corrected lingo only."}]
    raise AssertionError("unreachable")


def load_problem(english: str, lingo_text: str, how: str = "rules") -> None:
    """Put a sentence and its lingo in the two boxes (a new widget version, so the boxes show them)."""
    ss = st.session_state
    ss.english_text, ss.lingo_text, ss.translated_lingo = english, lingo_text, lingo_text
    ss.translation = {"how": how, "error": None}
    ss.version += 1


def translate_english(english: str) -> None:
    """Rules first (deterministic, free).  The AI helper only for sentences the rules cannot read."""
    ss = st.session_state
    try:
        load_problem(english, lingo.translate(english), "rules")
        return
    except lingo.LingoError as rule_error:
        ss.english_text = english
        client = get_client()
        if client is None:
            ss.translation = {"how": "error", "error": str(rule_error), "ai": False}
            return
        try:
            load_problem(english, english_to_lingo(client, english, str(rule_error)), "AI")
        except (llm.LLMError, lingo.LingoError) as e:
            ss.translation = {"how": "error", "error": f"{rule_error}\n\nThe AI translator could not fix it either: {e}",
                              "ai": True}


def new_random() -> None:
    """A new random problem of the chosen type (the dropdown and the dice button both call this)."""
    load_problem(*lingo.random_problem(st.session_state.problem_type))


def retranslate() -> None:
    ss = st.session_state
    translate_english(ss.get(f"english_{ss.version}", ss.english_text))


# ---------------------------------------------------------------------------
# tour (first run only) and help
# ---------------------------------------------------------------------------

TOUR = [
    ("Welcome", "Describe a circuit in plain English and get a worksheet-style figure, the answers and a worked "
                "solution.\n\n> 12 V battery, a 4 ohm and a 2 ohm in series, that pair in parallel with a 6 ohm, "
                "then a 3 ohm. Find the current through the 2 ohm resistor.\n\nFixed rules (no AI) turn the sentence "
                "into **circuit lingo**, the short code the figure and the answers are built from."),
    ("Where things are", "**Create** - pick a **problem type** to get a random problem of that kind (changing the "
                         "type makes a new one, 🎲 gives another), or write your own sentence. Check the figure and "
                         "answers, then **Add to problem set**.\n\n**Questions & Solutions** - your problem set, "
                         "downloaded as a PDF (questions, then worked solutions).\n\n**How to use** - the phrases "
                         "the rules understand, the problem types, and the circuit lingo."),
    ("Order = picture", "Parts are drawn in the order you describe them: the first ones on the top rail, left to "
                        "right; the last one on the bottom rail; parallel branches stack top to bottom.\n\nSo "
                        "*'... that pair in parallel with a 6 ohm, then a 3 ohm'* puts the pair on the upper "
                        "branch, the 6 Ω under it, and the 3 Ω on the bottom rail - like a textbook figure."),
    ("Check and edit", "Under the sentence, **Circuit lingo** shows what the rules made of it: `+` series, `||` "
                       "parallel, parentheses group, `4uF` capacitor, `S1=closed` switch, `A1` ammeter, `V1` "
                       "voltmeter.\n\nEdit whichever you prefer: change the sentence and it is translated again, "
                       "or fix the lingo directly (the figure follows the lingo).\n\nIf the rules can't read a "
                       "sentence, the message names the word. With the **AI translator** connected in the sidebar, "
                       "the AI rewrites that sentence as lingo instead, and the lingo opens for you to check."),
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
    ss.problem_type = DEFAULT_TYPE
    load_problem(*lingo.random_problem(DEFAULT_TYPE))
    ss.exam = []                       # the problem set: dicts with english, text, question, solution, png, answers
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
    with st.expander("🤖 AI translator (for sentences the rules can't read)"):
        st.caption("Only used when the built-in rules cannot read your sentence. It writes circuit lingo, which is "
                   "checked by the parser and shown for you to review. Everything else works without it.")
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
        t1, t2 = st.columns([0.6, 0.4], vertical_alignment="bottom")
        t1.selectbox("Problem type", list(lingo.PROBLEM_TYPES), key="problem_type", on_change=new_random,
                     help="Choosing a type makes a new random problem of that kind. See How to use for what each "
                          "type contains.")
        t2.button("🎲 New random problem", on_click=new_random, width="stretch")
        english = st.text_area("Plain English", ss.english_text, key=f"english_{ss.version}", height=140,
                               placeholder="12 V battery, a 4 ohm and a 2 ohm in series, that pair in parallel with a "
                                           "6 ohm, then a 3 ohm. Find the current through the 2 ohm resistor.",
                               help="Press Ctrl+Enter (⌘+Enter on Mac) or click outside the box to translate. "
                                    "The How to use tab lists the phrases the rules understand.")
        if english != ss.english_text:
            translate_english(english)
            st.rerun()

        tr = ss.translation
        current_lingo = ss.get(f"lingo_{ss.version}", ss.lingo_text)
        s1, s2 = st.columns([0.72, 0.28], vertical_alignment="center")
        if tr["how"] == "error":
            s1.error(tr["error"])
            if not tr.get("ai"):
                s1.caption("Reword the sentence, edit the circuit lingo below, or connect the **AI translator** in "
                           "the sidebar to fix sentences like this automatically.")
        elif current_lingo.strip() != ss.translated_lingo.strip():
            s1.caption("✎ The circuit lingo was edited by hand: the figure follows the lingo, not the sentence. "
                       "Press Translate to go back to the sentence.")
        elif tr["how"] == "AI":
            s1.warning("Translated by the **AI helper** because the rules could not read the sentence. Check the "
                       "circuit lingo below.")
        else:
            s1.caption("✓ Translated by fixed rules (no AI).")
        s2.button("↻ Translate", on_click=retranslate, width="stretch",
                  help="Translate the sentence again (for example after connecting the AI translator).")

        with st.expander("Circuit lingo (what the figure is built from; edit here if you prefer)",
                         expanded=tr["how"] in ("AI", "error")):
            text = st.text_area("Circuit lingo", ss.lingo_text, key=f"lingo_{ss.version}", height=130,
                                label_visibility="collapsed")
            ss.lingo_text = text
            st.caption("`+` series · `||` parallel · `( )` group · `4uF` capacitor · `S1=closed` switch · `A1` "
                       "ammeter · `6 || V1` voltmeter across the 6 Ω · `6?` hidden value. Full guide in How to use.")

        try:
            built = build(text, ss.style)
            error = None
        except lingo.LingoError as e:
            built, error = None, str(e)

        if error:
            st.error(f"Circuit lingo: {error}")
        else:
            st.subheader("2. Question")
            st.markdown(f"> {built['question']}")
            st.subheader("3. Answers")
            if built["answers"]:
                st.success("\n".join(f"- {a}" for a in built["answers"]))
            else:
                st.info("Say what to find, e.g. *Find the current through the 2 ohm resistor.*")
            with st.expander("Worked solution"):
                st.markdown(built["solution"])
            if st.button("➕ Add to problem set", type="primary", disabled=not built["render"].get("ok")):
                ss.exam.append({"english": ss.english_text, "translated": ss.translated_lingo, "how": tr["how"],
                                "text": text, "question": built["question"], "solution": built["solution"],
                                "png": built["render"]["png"], "answers": built["answers"]})
                st.toast(f"Added as problem {len(ss.exam)} of the problem set.", icon="✅")

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
            download(d5, "Lingo", f"# {ss.english_text}\n{text}", f"{name}.txt", "text/plain")
            with st.expander("🔍 What code made this? (transparency)"):
                st.markdown(
                    f"1. **Translator** (`lingo.translate`, fixed phrase rules) turned your sentence into circuit "
                    f"lingo{' - here the AI helper did it, because the rules could not' if tr['how'] == 'AI' else ''}.\n"
                    f"2. **Parser** (`lingo.parse`, plain Python with [regular expressions]({DOCS['python_re']})) "
                    f"read the lingo into a tree: series and parallel groups of parts.\n"
                    f"3. **Layout** (`lingo.draw_code`) walked that tree and wrote the "
                    f"[Schemdraw]({DOCS['schemdraw']}) script below: every part is placed with "
                    f"[`.endpoints()`]({DOCS['schemdraw_placement']}) at exact coordinates, so loops always close.\n"
                    f"4. **Renderer** (`render_worker.py`) ran that script and saved SVG, and "
                    f"PNG/PDF through [Matplotlib]({DOCS['matplotlib']}).\n"
                    f"5. **Solver** (`lingo.solve`) reduced the same tree step by step (series add, parallel "
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
        st.info("No problems yet. Make one in the Create tab and press **Add to problem set**.")
    else:
        title = st.text_input("Problem set title", "Resistors in series and parallel")
        e1, e2, e3 = st.columns(3)
        items = [(x["question"], x["solution"], x["png"], "; ".join(x["answers"])) for x in ss.exam]
        download(e1, "⬇️ Questions + solutions PDF", exam_pdf.build(items, title, True),
                 "problem_set_with_solutions.pdf", "application/pdf")
        download(e2, "⬇️ Questions only PDF", exam_pdf.build(items, title, False),
                 "problem_set_questions.pdf", "application/pdf")
        download(e3, "⬇️ All problems as text (.txt)",
                 "\n\n---\n\n".join(f"# {x.get('english', '')}\n{x['text']}" for x in ss.exam),
                 "problem_set.txt", "text/plain")
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
                    load_problem(x.get("english", ""), x["text"], x.get("how", "rules"))
                    ss.translated_lingo = x.get("translated", x["text"])
                    st.toast("Loaded - see the Create tab.", icon="✏️")
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
### Quick start
1. **Pick a problem type** at the top of the Create tab. Changing the type makes a new random problem of that kind;
   **🎲 New random problem** gives another one of the same type.
2. **Or describe your own circuit** in the **Plain English** box, e.g. *12 V battery, a 4 ohm and a 2 ohm in series,
   that pair in parallel with a 6 ohm, then a 3 ohm. Find the current through the 2 ohm resistor.* Press Ctrl+Enter
   (⌘+Enter on Mac) or click outside the box. Fixed rules (no AI) turn it into circuit lingo.
3. **Check it.** Open **Circuit lingo** under the sentence to see what the rules made of it. Edit whichever you prefer:
   change the sentence and it is translated again, or fix the lingo directly (the figure always follows the lingo).
4. **If the rules can't read a sentence**, the message names the word. With the **AI translator** connected in the
   sidebar, the AI rewrites the sentence as lingo instead; the lingo opens so you can check it. The AI's lingo still
   goes through the same parser and solver, so the figure and answers are never made up.
5. **➕ Add to problem set**, then download the questions and worked solutions as a PDF from the
   **Questions & Solutions** tab.

### Problem types
| Type | What you get |
|---|---|
| Mixed series-parallel | textbook-style resistor networks: a pair in series inside a parallel group, two parallel pairs, groups nested in groups |
| Simple series · Simple parallel | three resistors all in series, or all in parallel |
| Unknown resistor | one resistor is drawn as "R = ?"; the question gives the battery current and asks for that resistance and its current |
| Capacitors | three fully charged capacitors: charge, voltage, stored energy or equivalent capacitance |
| Switch (open or closed) | a resistor with a switch in its branch; the question states whether the switch is open or closed |
| Meters (ammeter and voltmeter readings) | an ideal **ammeter** (A) in series with the battery measures the total current, and an ideal **voltmeter** (V) connected across one resistor measures that resistor's voltage. Students find what each meter reads. |

### The circuit lingo (under the hood)

| You write | Meaning |
|---|---|
| `source: 12 V` | the battery (drawn on the left, + at the top) |
| `circuit: 4 + 2` | **`+` = series** |
| `circuit: 4 \\|\\| 6` | **`\\|\\|` = parallel** (binds tighter than `+`, like × vs +) |
| `circuit: (4 + 2) \\|\\| 6 + 3` | parentheses group: 4 and 2 in series, that pair in parallel with 6, then 3 in series |
| `circuit: R3=6 + 2` | give a resistor your own name |
| `circuit: 2 kohm + 470` | values may carry k / kΩ; bare numbers are ohms |
| `circuit: 4 + 6? + 3` | `?` after a value (or the word **unknown** before it) prints "R2 = ?" on the figure; the answer key still knows it is 6 Ω |
| `circuit: 4uF + 2uF \\|\\| 6uF` | a value with a farad unit (`F`, `mF`, `uF`/`µF`, `nF`, `pF`) is a **capacitor**, named C1, C2 ... |
| `circuit: (4 + S1=closed) \\|\\| 6` | a **switch**: `S1=open` or `S1=closed` (a `switch: S1 closed` line also works) |
| `circuit: A1 + 4 \\|\\| V1` | **meters**: `A1` an ammeter in series (a wire), `V1` a voltmeter in parallel with the part it measures (an open branch) |
| `ask: current through R2` | also `voltage across R2`, `power in R2`, `total current`, `equivalent resistance`, or `the 2 ohm resistor` |
| `ask: charge on C1` | capacitors: `charge on C1`, `energy in C1`, `voltage across C1`, `equivalent capacitance`; meters: `reading of A1`, `reading of the voltmeter` |
| `hide: R3` | the other way to print "R3 = ?" on the figure |
| `text: ...` | your own wording of the question instead of the automatic one |
| `title: Quiz 3` | a title kept with the problem |

Dictation-friendly words work on the circuit line too: **plus**, **in series with**, **then**, **followed by** for `+`;
**parallel**, **in parallel with**, **across**, **with** for `||`; **unknown** for `?`; **ohm(s)**, **kohm**, **microfarad**,
**volt(s)**; **switch**, **ammeter**, **voltmeter** for `S`, `A`, `V`.
So `4 in series with 2 in parallel with 6 then 3` is read as `4 + 2 || 6 + 3` (the usual `||`-first precedence applies).

**The physics used:** one battery, DC, steady state ("the switch has been closed a long time"). Capacitors carry no
current and hold the voltage across them (Q = CV, U = ½CV²); a closed switch and an ideal ammeter are wires (0 Ω);
an open switch and an ideal voltmeter are open branches. Capacitors in series share the same charge; in parallel they
share the same voltage.

### Plain English (no AI needed)

Type a sentence in the **Plain English** box on the Create tab. Fixed rules read it and write the circuit lingo
(open **Circuit lingo** under the sentence to see it). The same sentence always gives the same lingo.

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
| The 6 ohm is unknown. Find **the resistance of** R3 | `hide: R3` · `ask: resistance of R3` (the question then states the battery current) |
| a 4 **microfarad** and a 2 **uF** capacitor in series · capacitors of 4 and 6 uF | `4uF + 2uF` · `4uF + 6uF` |
| a 4 ohm in series with a **closed switch** · an **open switch** · the switch **is closed** | `4 + S1=closed` · `S1=open` · changes the switch already described |
| an **ammeter**, then ... · a **voltmeter across** the 3 ohm · a voltmeter across that pair | `A1 + ...` · `3 \\|\\| V1` · `(...) \\|\\| V1` |
| the **charge on** the 4 uF · the **energy stored in** C1 · the **equivalent capacitance** | `ask: charge on C1` · `ask: energy in C1` · `ask: equivalent capacitance` |
| **what does the ammeter read** · the **reading of** the voltmeter | `ask: reading of A1` · `ask: reading of V1` |

One connection per phrase: write "a 4 ohm and a 2 ohm in series, that pair in parallel with a 6 ohm" rather than
"4 and 2 in series with 6 in parallel". A word the rules do not know stops the translation with a message naming that word,
so nothing is guessed. The AI translator in the sidebar, if connected, is only tried when the rules give up.

### Where the resistors go
Reading order decides the picture. Parts before the last `+` go on the **top rail** left to right;
the **last** series part goes on the **bottom rail**; parallel branches **stack top to bottom** in the order written.
To move a resistor, move it in the text: `3 + (4 + 2) || 6` puts the 3 Ω on the top-left instead of the bottom.
In a sentence it is the same: parts are drawn in the order you describe them.

### Try these sentences
""")
    for name, en in ENGLISH_EXAMPLES.items():
        h1, h2 = st.columns([0.7, 0.3])
        h1.markdown(f"> {en}")
        if h2.button(f"Use: {name}", key=f"help_en_{name}", width="stretch"):
            translate_english(en)
            st.toast("Loaded - see the Create tab.", icon="✏️")
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
| AI translator (optional) | `llm.py` rewrites sentences the rules can't read as lingo; that lingo is checked by the parser and solver and shown for review | - |

**Limits (for now):** DC circuits with one battery, in steady state: resistors, capacitors, switches and ideal meters.
Not yet: RC time constants, multi-battery loops, bridges. Uploading a photo of an existing figure and getting a variation is planned.
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
