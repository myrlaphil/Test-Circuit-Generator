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
