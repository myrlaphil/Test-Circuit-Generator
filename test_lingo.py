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
    ("12 V battery, 4 and 2 in series, then a capacitor", "give the capacitor a value"),
    ("12 V battery, 4 and 2 in series, then a thermistor", "'thermistor'"),
    ("a 4 ohm and a 2 ohm in series", "battery voltage"),
    ("12 V battery, that pair in parallel with a 6 ohm", "nothing was described before"),
    ("12 V battery, a 6 ohm and a 6 ohm in parallel, the 6 ohm is unknown", "Several resistors are 6.00"),
    ("12 V battery, 4 and 2 in series. Find the current.", "say which part"),
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


# ---------------------------------------------------------------------------
# capacitors, switches and meters (DC steady state).  Hand-worked answers.
# ---------------------------------------------------------------------------

def test_capacitor_network_hand_worked():
    # C2 || C3 = 8 µF; in series with C1 = 4 µF -> C_eq = 8/3 µF; Q = C_eq V = 32 µC; V1 = Q/C1 = 8 V; V23 = 4 V
    p = lingo.parse("source: 12 V\ncircuit: 4uF + 2uF || 6uF\nask: charge on C1, voltage across C2, energy in C1, "
                    "equivalent capacitance")
    r = lingo.solve(p)
    assert r.total_current == 0 and r.req == lingo.INF
    assert r.ceq == pytest.approx(8e-6 / 3)
    assert r.per["C1"]["charge"] == pytest.approx(32e-6) and r.per["C1"]["voltage"] == pytest.approx(8)
    assert r.per["C2"]["voltage"] == pytest.approx(4) and r.per["C3"]["charge"] == pytest.approx(24e-6)
    assert r.per["C1"]["energy"] == pytest.approx(0.5 * 4e-6 * 64)
    assert lingo.answers(p, r) == ["Charge on C1 = 32.00 µC", "Voltage across C2 = 4.00 V",
                                   "Energy stored in C1 = 128.00 µJ", "Equivalent capacitance = 2.67 µF"]
    assert "share the same charge" in " ".join(r.back)


def test_rc_steady_state_capacitor_branch_is_open():
    # the 4 Ω + C branch carries no current: circuit is 6 + 3 = 9 Ω, I = 4/3 A, 8 V across the parallel group -> on C
    p = lingo.parse("source: 12 V\ncircuit: (4 + 2uF) || 6 + 3\nask: charge on C1, current through R1")
    r = lingo.solve(p)
    assert r.req == pytest.approx(9) and r.total_current == pytest.approx(4 / 3)
    assert r.per["R1"]["current"] == 0 and r.per["R1"]["voltage"] == 0
    assert r.per["C1"]["voltage"] == pytest.approx(8) and r.per["C1"]["charge"] == pytest.approx(16e-6)
    # capacitor in parallel with a resistor: charged to that resistor's voltage
    r = lingo.solve(lingo.parse("source: 12 V\ncircuit: 4 + 2uF || 6 + 3"))
    assert r.req == pytest.approx(13) and r.per["C1"]["voltage"] == pytest.approx(12 * 6 / 13)


def test_switch_open_and_closed():
    open_ = lingo.solve(lingo.parse("source: 12 V\ncircuit: (4 + S1=open) || 6 + 3"))
    assert open_.req == pytest.approx(9) and open_.per["R1"]["current"] == 0
    assert open_.per["S1"]["voltage"] == pytest.approx(8)            # the open switch takes the branch voltage
    closed = lingo.solve(lingo.parse("source: 12 V\ncircuit: (4 + S1=open) || 6 + 3\nswitch: S1 closed"))
    assert closed.req == pytest.approx(5.4) and closed.total_current == pytest.approx(12 / 5.4)
    assert closed.per["R1"]["current"] == pytest.approx(16 / 3 / 4) and closed.per["S1"]["voltage"] == 0
    assert "S1 is closed." in lingo.question_text(lingo.parse("source: 12 V\ncircuit: (4 + S1=closed) || 6 + 3"))
    # a closed switch across a resistor shorts it
    r = lingo.solve(lingo.parse("source: 12 V\ncircuit: 4 || S1=closed + 3"))
    assert r.req == pytest.approx(3) and r.per["R1"]["current"] == 0 and r.per["S1"]["current"] == pytest.approx(4)
    # open switch in the only path: nothing flows, the battery voltage sits across the switch
    r = lingo.solve(lingo.parse("source: 12 V\ncircuit: 4 + S1=open"))
    assert r.total_current == 0 and r.per["S1"]["voltage"] == pytest.approx(12)


def test_meters_read_current_and_voltage():
    p = lingo.parse("source: 12 V\ncircuit: A1 + (4 + 2) || 6 + 3 || V1\nask: reading of A1, reading of the voltmeter")
    r = lingo.solve(p)
    assert r.req == pytest.approx(6) and r.per["A1"]["reading"] == pytest.approx(2)
    assert r.per["V1"]["reading"] == pytest.approx(6) and r.per["V1"]["current"] == 0
    assert lingo.answers(p, r) == ["A1 reads 2.00 A", "V1 reads 6.00 V"]
    r = lingo.solve(lingo.parse("source: 12 V\ncircuit: (A2 + 4 + 2) || 6 + 3"))
    assert r.per["A2"]["reading"] == pytest.approx(1)


@pytest.mark.parametrize("bad, frag", [
    ("source: 12 V\ncircuit: A1 + S1=closed", "short-circuited"),
    ("source: 12 V\ncircuit: 4 + 2\nask: charge on R1", "charge and stored energy apply to capacitors"),
    ("source: 12 V\ncircuit: 4 + 2\nask: reading of R1", "not a meter"),
    ("source: 12 V\ncircuit: 4 + 2\nask: reading of the ammeter", "no ammeter"),
    ("source: 12 V\ncircuit: 4 + A1=closed", "only makes sense after a switch"),
    ("source: 12 V\ncircuit: 4 + S1\nswitch: R1 closed", "not a switch"),
])
def test_part_errors_are_readable(bad, frag):
    with pytest.raises(lingo.LingoError, match=frag):
        lingo.solve(lingo.parse(bad))


def test_units_words_and_round_trip_for_new_parts():
    p = lingo.parse("source: 12 V\ncircuit: 4 microfarad + 2 µF || 470 nF + switch + ammeter\nask: charge on the 4 uF capacitor")
    assert [(q.kind, q.name) for q in p.parts()] == [("C", "C1"), ("C", "C2"), ("C", "C3"), ("S", "S1"), ("A", "A1")]
    assert p.asks[0].target == "C1" and p.parts()[2].value == pytest.approx(470e-9)
    t = "source: 12 V\ncircuit: (4 + S1=closed) || 6 + 3 || 2uF\nask: current through R1, charge on C1"
    assert lingo.to_lingo(lingo.parse(t)) == t
    for shape in ("capacitors", "switch", "meters"):
        for seed in range(15):
            t = lingo.random_lingo(seed, shape)
            p = lingo.parse(t)
            assert lingo.to_lingo(lingo.parse(lingo.to_lingo(p))) == t
            lingo.solve(p); lingo.draw_code(p); lingo.question_text(p)


def test_draw_code_uses_the_right_symbols():
    code = lingo.draw_code(lingo.parse("source: 12 V\ncircuit: A1 + (4 + S1=closed) || 2uF + 3 || V1"))
    assert "elm.MeterA()" in code and "elm.MeterV()" in code and "elm.Capacitor()" in code
    assert "elm.Switch(nc=True)" in code and "(closed)" in code
    assert "elm.Switch()" in lingo.draw_code(lingo.parse("source: 12 V\ncircuit: 4 + S1=open"))


@pytest.mark.parametrize("english, lines", [
    ("12 V battery, a 4 microfarad and a 2 microfarad capacitor in series, that pair in parallel with a 6 uF. "
     "Find the charge on the 4 uF capacitor and the equivalent capacitance.",
     "circuit: (4uF + 2uF) || 6uF\nask: charge on C1, equivalent capacitance"),
    ("12 V battery, a 4 ohm in series with a closed switch, that pair in parallel with a 6 ohm, then a 3 ohm. "
     "Find the current through the 4 ohm.", "circuit: (4 + S1=closed) || 6 + 3\nask: current through R1"),
    ("12 V battery, a 4 ohm and an open switch in series, that pair in parallel with a 6 ohm, then a 3 ohm. "
     "The switch is closed. Find the total current.", "circuit: (4 + S1=closed) || 6 + 3\nask: total current"),
    ("12 V battery, an ammeter, then a 4 ohm and a 2 ohm in series, that pair in parallel with a 6 ohm, then a 3 ohm, "
     "a voltmeter across the 3 ohm. What does the ammeter read and what does the voltmeter read?",
     "circuit: A1 + (4 + 2) || 6 + 3 || V1\nask: reading of A1, reading of V1"),
    ("6 V battery, a 3 uF and a 6 uF in parallel, then a 2 uF in series with that pair. What is the energy stored in "
     "each capacitor?", "circuit: 2uF + 3uF || 6uF\nask: energy in C1, energy in C2, energy in C3"),
    ("12 V battery, capacitors of 4 and 6 microfarads in series, a voltmeter across that pair",
     "circuit: (4uF + 6uF) || V1"),
])
def test_translate_new_parts(english, lines):
    assert lines in lingo.translate(english)


def test_translate_new_part_errors():
    with pytest.raises(lingo.LingoError, match="capacitor units"):
        lingo.translate("12 V battery, capacitors of 4 and 6 in series")
    with pytest.raises(lingo.LingoError, match="what the voltmeter is across"):
        lingo.translate("12 V battery, 4 and 2 in series, then a voltmeter")


# ---------------------------------------------------------------------------
# problem types: every random problem comes with English that translates back to the same lingo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", list(lingo.PROBLEM_TYPES))
def test_random_problem_english_round_trips(kind):
    for seed in range(40):
        english, text = lingo.random_problem(kind, seed)
        assert lingo.translate(english) == text, english
        p = lingo.parse(text)
        lingo.solve(p); lingo.draw_code(p); lingo.question_text(p)


def test_problem_type_contents():
    en, text = lingo.random_problem("Meters (ammeter and voltmeter readings)", 1)
    assert "ammeter" in en and "voltmeter across" in en and "ask: reading of A1, reading of V1" in text
    assert "S1=" in lingo.random_problem("Switch (open or closed)", 1)[1]
    assert "uF" in lingo.random_problem("Capacitors", 1)[1]
    with pytest.raises(lingo.LingoError, match="Unknown problem type"):
        lingo.random_problem("Worksheet problem 1")


def test_unknown_resistor_gives_battery_current_and_asks_resistance():
    p = lingo.parse("source: 24 V\ncircuit: 4 + 12 + 6\nhide: R3\nask: resistance of R3, current through R3")
    q = lingo.question_text(p)
    assert q.startswith("The battery supplies 1.09 A.") and "resistance of" in q
    assert lingo.answers(p, lingo.solve(p)) == ["R3 = 6.00 Ω", "Current through R3 = 1.09 A"]
    with pytest.raises(lingo.LingoError, match="resistance of a resistor"):
        lingo.parse("source: 12 V\ncircuit: 4 + 2uF\nask: resistance of C1")
    assert lingo.translate("24 V battery, a 4 ohm in series with a 12 ohm, then a 6 ohm. The 6 ohm is unknown. "
                           "Find the resistance of R3 and the current through R3.").endswith(
        "ask: resistance of R3, current through R3\nhide: R3")
