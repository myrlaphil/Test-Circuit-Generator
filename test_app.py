"""App-level checks with Streamlit's AppTest (runs app.py headless).  Run:  python -m pytest"""
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(Path(__file__).with_name("app.py"))
SENTENCE = "9 V battery, a 3 ohm and a 6 ohm in parallel, then a 4 ohm. Find the total current."


@pytest.fixture
def at(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))          # the first-run flag file goes to a temp folder
    return AppTest.from_file(APP, default_timeout=90).run()


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _english(at):
    return at.text_area(key=f"english_{at.session_state.version}")


def test_edit_sentence_then_click_translate(at):
    # the reported crash: a changed sentence and the Translate button in the same rerun
    _english(at).input(SENTENCE)
    _button(at, "↻ Translate").click()
    at.run()
    assert not at.exception
    assert [s.value for s in at.success] == ["- Total current from the battery = 1.50 A"]
    assert at.session_state.problem_type == "Custom (your own sentence)"
    assert _button(at, "🎲 New random problem").disabled


def test_translate_button_alone_and_type_switch_restores_custom(at):
    _button(at, "↻ Translate").click()                 # no edit: translates the same random sentence again
    at.run()
    assert not at.exception and at.session_state.problem_type == "Mixed series-parallel"
    _english(at).input(SENTENCE)
    at.run()
    at.selectbox(key="problem_type").select("Capacitors")
    at.run()
    assert "uF" in at.session_state.lingo_text and not _button(at, "🎲 New random problem").disabled
    at.selectbox(key="problem_type").select("Custom (your own sentence)")
    at.run()
    assert not at.exception and at.session_state.english_text == SENTENCE
    assert [s.value for s in at.success] == ["- Total current from the battery = 1.50 A"]


def test_unreadable_sentence_shows_the_word(at):
    _english(at).input("9 V battery, a 3 ohm and a 6 ohm in parallel, then a thermistor.")
    at.run()
    assert not at.exception
    assert any("thermistor" in e.value for e in at.error)


def test_key_instructions_follow_the_selected_service(at):
    text = " ".join(m.value for m in at.sidebar.markdown)
    assert "console.anthropic.com" in text and "Create Key" in text
    at.sidebar.selectbox(key="ai_preset").select("Google Gemini (free tier available)")
    at.run()
    text = " ".join(m.value for m in at.sidebar.markdown)
    assert "aistudio.google.com" in text and "console.anthropic.com" not in text and not at.exception
