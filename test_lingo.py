"""Run:  python -m pytest"""
import pytest
import lingo

P1 = "source: 12 V\ncircuit: (4 + 2) || 6 + 3\nask: current through R2, voltage across R2"
P2 = "source: 6 V\ncircuit: 6 || (2 + 3 || 6) + 1\nask: power in R3"


def test_worksheet_problem_1():
    p = lingo.parse(P1); r = lingo.solve(p)
    assert r.req == pytest.approx(6) and r.total_current == pytest.approx(2)
    assert r.per["R2"]["current"] == pytest.approx(1) and r.per["R2"]["voltage"] == pytest.approx(2)


def test_worksheet_problem_2():
    r = lingo.solve(lingo.parse(P2))
    assert r.req == pytest.approx(3.4)
    assert r.per["R3"]["power"] == pytest.approx((6 / 3.4 * 2.4 / 4 * 2) ** 2 / 3)


def test_precedence_and_words():
    a = lingo.parse("source 9 V\ncircuit 2 plus 4 parallel 4 plus 1 kohm")
    b = lingo.parse("source: 9 V\ncircuit: 2 + (4 || 4) + 1000")
    assert lingo.solve(a).req == pytest.approx(lingo.solve(b).req) == pytest.approx(1004)


def test_names_hide_and_ask_by_value():
    p = lingo.parse("source: 12 V\ncircuit: Ra=4 + 8\nhide: Ra\nask: voltage across the 8 ohm resistor")
    assert [r.name for r in p.resistors()] == ["Ra", "R2"] and p.resistor("Ra").hidden
    assert p.asks[0].target == "R2"


def test_round_trip_and_random_are_valid():
    for seed in range(40):
        t = lingo.random_lingo(seed)
        p = lingo.parse(t)
        assert lingo.to_lingo(lingo.parse(lingo.to_lingo(p))) == lingo.to_lingo(p)
        lingo.solve(p); lingo.draw_code(p); lingo.question_text(p)


def test_power_balance():
    p = lingo.parse(P2); r = lingo.solve(p)
    assert sum(x["power"] for x in r.per.values()) == pytest.approx(r.total_current * p.volts)


@pytest.mark.parametrize("bad, frag", [
    ("source: 12 V\ncircuit: (4 + 2 || 6", "never closed"),
    ("circuit: 4 + 2", "battery voltage"),
    ("source: 12 V\ncircuit: 4 + + 2", "value is missing"),
    ("source: 12 V\ncircuit: 6 || 6\nask: current through the 6 ohm resistor", "several resistors"),
    ("source: 12 V\ncircuit: 4 + 2\nask: current through R9", "no resistor called R9"),
    ("source: 12 V\ncircuit: 4 + 2\nask: mass of R1", "say what to find"),
])
def test_errors_are_readable(bad, frag):
    with pytest.raises(lingo.LingoError, match=frag):
        lingo.parse(bad)


# ---------------------------------------------------------------------------
# plain English -> lingo (rules only).  One test per phrase pattern.
# ---------------------------------------------------------------------------

EN1 = ("12 V battery. A 4 ohm and a 2 ohm in series, that pair in parallel with a 6 ohm, then a 3 ohm. "
       "Find the current through and the voltage across the 2 ohm resistor.")
EN2 = ("6 V battery, a 3 ohm and a 6 ohm in parallel, then a 2 ohm in series with that pair, a 6 ohm across that "
       "whole group, then a 1 ohm. Calculate the power dissipated in the 3 ohm resistor.")


def test_translate_worksheet_problems_match_hand_written_lingo():
    assert lingo.translate(EN1) == lingo.to_lingo(lingo.parse(P1))
    assert lingo.translate(EN2) == lingo.to_lingo(lingo.parse(P2))
    assert lingo.solve(lingo.parse(lingo.translate(EN1))).per["R2"]["current"] == pytest.approx(1)


@pytest.mark.parametrize("english, circuit", [
    ("12 V battery, a 4 ohm in series with a 2 ohm, then a 3 ohm", "4 + 2 + 3"),                 # "in series with"
    ("12 V battery, a 4 ohm in parallel with a 2 ohm, then a 3 ohm", "4 || 2 + 3"),               # "in parallel with"
    ("12 V battery, a 4 ohm and a 2 ohm in series, a 6 ohm across that pair", "6 || (4 + 2)"),   # "across" + values first
    ("12 V battery, a 4 ohm and a 2 ohm in series, that pair in parallel with a 6 ohm", "(4 + 2) || 6"),
    ("9 volt battery with 2, 4 and 6 ohms in parallel", "2 || 4 || 6"),                           # comma list
    ("9 V, 2 ohm, 4 ohm and 6 ohm, all in series", "2 + 4 + 6"),                                  # trailing "all in"
    ("twelve volt source, two 4 ohm resistors in series, then a 6 ohm", "4 + 4 + 6"),             # number words, counts
    ("24 V battery, 3 resistors of 6 ohms in parallel", "6 || 6 || 6"),
    ("12 V battery, a 4.7 kilo-ohm and a 2.2k in series", "4700 + 2200"),                          # k units
    ("12 V battery, 4 and 2 in series and that pair in parallel with 6 and then 3", "(4 + 2) || 6 + 3"),  # "and" joins
    ("12 V battery, 4 and 2 in series, followed by 3, next 5", "4 + 2 + 3 + 5"),                  # other "then" words
    ("12 V battery, a 4 ohm and 2 ohm in series, then a 6 ohm in parallel", "(4 + 2) || 6"),      # lone "in parallel"
])
def test_translate_connection_phrases(english, circuit):
    assert lingo.translate(english).splitlines()[1] == f"circuit: {circuit}"


def test_translate_unknown_and_questions():
    t = lingo.translate("12 V, a 4 ohm and a 2 ohm in series, then an unknown 6 ohm. Ask for the current through the 6 ohm")
    assert t == "source: 12 V\ncircuit: 4 + 2 + 6\nask: current through R3\nhide: R3"
    t = lingo.translate("12 V, 4 and 2 in series, then 3. The 3 ohm is unknown. What is the voltage across each resistor?")
    assert "hide: R3" in t and "ask: voltage across R1, voltage across R2, voltage across R3" in t
    t = lingo.translate("12 V battery, 3 || 6 in parallel then 2. Find the total current and the equivalent resistance.")
    assert t.splitlines()[2] == "ask: total current, equivalent resistance"
    t = lingo.translate("12 V battery, 4 and 2 in series. Find the potential difference across R1 and the power in the 2 ohm.")
    assert t.splitlines()[2] == "ask: voltage across R1, power in R2"


@pytest.mark.parametrize("english, frag", [
    ("12 V battery, a 4 ohm and a 2 ohm in series with a 6 ohm in parallel", "mixes series and parallel"),
    ("12 V battery, a 4 ohm and a 2 ohm", "in series or in parallel"),
    ("12 V battery, 4 and 2 in series, then a capacitor", "'capacitor'"),
    ("a 4 ohm and a 2 ohm in series", "battery voltage"),
    ("12 V battery, that pair in parallel with a 6 ohm", "nothing was described before"),
    ("12 V battery, a 6 ohm and a 6 ohm in parallel, the 6 ohm is unknown", "Several resistors are 6.00"),
    ("12 V battery, 4 and 2 in series. Find the current.", "say which resistor"),
    ("12 V battery, 4 and 2 in series. Find the mass of the 4 ohm", "say what to find"),
    ("12 V and 6 V batteries, 4 and 2 in series", "one battery"),
    ("", "Describe the circuit"),
])
def test_translate_errors_name_the_problem(english, frag):
    with pytest.raises(lingo.LingoError, match=frag):
        lingo.translate(english)


def test_lingo_line_aliases_and_unknown_marker():
    p = lingo.parse("source: 12 V\ncircuit: 4 in series with 2 in parallel with 6 then 3")
    assert lingo.to_lingo(p).splitlines()[1] == "circuit: 4 + 2 || 6 + 3"
    assert lingo.to_lingo(lingo.parse("source: 12 V\ncircuit: 4 across 6 + 3")).splitlines()[1] == "circuit: 4 || 6 + 3"
    for line in ("4 + 6? + 3", "4 + unknown 6 + 3", "4 + ?6 + 3"):
        p = lingo.parse(f"source: 12 V\ncircuit: {line}")
        assert [r.hidden for r in p.resistors()] == [False, True, False]
    with pytest.raises(lingo.LingoError, match="needs a value"):
        lingo.parse("source: 12 V\ncircuit: 4 + ? + 3")
    with pytest.raises(lingo.LingoError, match="R2=6\\?"):
        lingo.parse("source: 12 V\ncircuit: 4 + R2=? + 3")


def test_translated_problems_round_trip():
    for en in (EN1, EN2):
        t = lingo.translate(en)
        assert lingo.to_lingo(lingo.parse(t)) == t
