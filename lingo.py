"""
lingo.py - the "circuit lingo" a teacher types, and everything derived from it.

    source: 12 V
    circuit: (4 + 2) || 6 + 3
    ask: current through R2, voltage across R2

    +   series          ||  parallel (binds tighter, like multiplication)      ( ) grouping
    4        a 4 Ω resistor (named R1, R2 ... in reading order)      R3=6      names it
    4uF      a capacitor (C1, C2 ...); units F mF uF nF pF          6?        hidden value, drawn "R = ?"
    S1=open  a switch (or S1=closed)      A1  ammeter (in series)     V1  voltmeter (in parallel: 6 || V1)

Physics: one battery, DC, steady state ("after a long time"): capacitors carry no current,
ideal ammeters are wires, ideal voltmeters are open branches, closed switches are wires.

No AI anywhere in this file.  The same text always gives the same figure,
the same answers and the same worked solution.

Pipeline:  text --parse()--> Problem --draw_code()--> Schemdraw code
                                     --solve()-----> answers + worked steps
           English --translate()--> text  (section 6, rules only)
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

INF = math.inf
KINDS = {"R": "resistor", "C": "capacitor", "S": "switch", "A": "ammeter", "V": "voltmeter"}

# ---------------------------------------------------------------------------
# 1. Data model
# ---------------------------------------------------------------------------

@dataclass
class R:
    """One two-terminal part.  kind R: value in Ω, C: value in F, S/A/V: no value."""
    name: str
    value: float = 0.0
    hidden: bool = False
    kind: str = "R"
    closed: bool = False          # switches only

    @property
    def ohms(self) -> float:
        return self.value

    @property
    def farads(self) -> float:
        return self.value

    @property
    def what(self) -> str:
        return KINDS[self.kind]


@dataclass
class Group:
    kind: str                     # "series" | "parallel"
    items: List["Node"]


Node = Union[R, Group]


@dataclass
class Ask:
    quantity: str                 # current | voltage | power | charge | energy | reading | req | ceq | total_current
    target: Optional[str] = None  # part name


@dataclass
class Problem:
    volts: float
    tree: Node
    asks: List[Ask] = field(default_factory=list)
    title: str = ""
    text: str = ""                # teacher's own wording (optional)

    def parts(self) -> List[R]:
        out: List[R] = []

        def walk(n: Node):
            if isinstance(n, R):
                out.append(n)
            else:
                for i in n.items:
                    walk(i)
        walk(self.tree)
        return out

    def resistors(self) -> List[R]:
        return [p for p in self.parts() if p.kind == "R"]

    def capacitors(self) -> List[R]:
        return [p for p in self.parts() if p.kind == "C"]

    def part(self, name: str) -> R:
        for p in self.parts():
            if p.name.lower() == name.lower():
                return p
        what = "resistor" if name[:1].upper() == "R" else "part"
        raise LingoError(f"There is no {what} called {name}.")

    resistor = part


class LingoError(ValueError):
    """A readable error that points at the problem."""


# ---------------------------------------------------------------------------
# 2. Parsing
# ---------------------------------------------------------------------------

# Words allowed on the circuit line (dictation-friendly).  Longer phrases come first so that
# "in series with" becomes + before "with" alone could become ||.
_WORDS = [
    (r"\bin\s+series\s+with\b|\bin\s+series\b|\bseries\b|\bplus\b|\bthen\b|\bfollowed\s+by\b", "+"),
    (r"\bin\s+parallel\s+with\b|\bin\s+parallel\b|\bparallel\b|\bpar\b|\bpll\b|\bacross\b|\bwith\b|//", "||"),
    (r"\bunknown\b", "?"),
    (r"\bk(?:ilo)?-?\s?ohms?\b", "kΩ"),
    (r"\bohms?\b|Ω", "Ω"),
    (r"\bmicro-?\s?farads?\b|[µμ]\s*F\b", "uF"),
    (r"\bnano-?\s?farads?\b", "nF"),
    (r"\bpico-?\s?farads?\b", "pF"),
    (r"\bmilli-?\s?farads?\b", "mF"),
    (r"\bfarads?\b", "F"),
    (r"\bvolts?\b", "V"),
    (r"\bswitch\b", "S"),
    (r"\bammeter\b", "A"),
    (r"\bvoltmeter\b", "V"),
]
_UNIT_MULT = {"kΩ": 1000.0, "Ω": 1.0, "F": 1.0, "mF": 1e-3, "uF": 1e-6, "nF": 1e-9, "pF": 1e-12}
_UNIT_RE = r"(kΩ|Ω|[mnpu]?F)"
_TOKEN = re.compile(r"\s*(?:(\|\||\+|\(|\))"
                    r"|([A-Za-z][A-Za-z0-9]*)\s*=\s*([0-9]*\.?[0-9]+)\s*" + _UNIT_RE + r"?(\s*\?)?"
                    r"|([0-9]*\.?[0-9]+)\s*" + _UNIT_RE + r"?(\s*\?)?"
                    r"|([A-Za-z][A-Za-z0-9]*)(?:\s*=?\s*(open|closed|close|shut|on|off)\b)?)")
_PART_NAME = re.compile(r"^[SAV][0-9]*$", re.I)


def _normalise(s: str) -> str:
    for pat, rep in _WORDS:
        s = re.sub(pat, rep, s, flags=re.I)
    # "? 6" (from "unknown 6") -> "6?" : the question mark goes after the value it belongs to
    s = re.sub(r"\?\s*((?:[A-Za-z][A-Za-z0-9]*\s*=\s*)?[0-9]*\.?[0-9]+\s*(?:" + _UNIT_RE[1:-1] + r")?)", r"\1?", s)
    return s


def _unit_value(num: str, unit: Optional[str]) -> Tuple[float, str]:
    """-> (value, kind) from a number and its unit."""
    if not unit:
        return float(num), "R"
    key = unit if unit in _UNIT_MULT else unit.upper() if unit.upper() == "F" else unit[0].lower() + "F"
    return float(num) * _UNIT_MULT[key], "C" if key.endswith("F") else "R"


@dataclass
class _Tok:
    kind: str                     # op | value | part
    text: str = ""
    value: float = 0.0
    named: bool = False
    hidden: bool = False
    pkind: str = "R"              # R | C | S | A | V
    closed: bool = False


def _tokenize(expr: str) -> List[_Tok]:
    expr = _normalise(expr)
    pos, out = 0, []
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m or m.end() == pos:
            rest = expr[pos:].strip()
            if rest.startswith("?"):
                raise LingoError("'?' needs a value for the answer key: write 6? for a hidden 6 Ω resistor "
                                 "(it is drawn as 'R = ?').")
            raise LingoError(f"I don't understand '{rest[:20]}' in the circuit line. Use numbers, +, || and parentheses, "
                             f"e.g. (4 + 2) || 6 + 3.")
        op, name, nval, nunit, nhid, val, unit, hid, bare, state = m.groups()
        if op:
            out.append(_Tok("op", op))
        elif name:
            v, k = _unit_value(nval, nunit)
            out.append(_Tok("value", name, v, True, bool(nhid), k))
        elif val:
            v, k = _unit_value(val, unit)
            out.append(_Tok("value", "", v, False, bool(hid), k))
        elif bare:
            if _PART_NAME.match(bare):
                pk = bare[0].upper()
                if state and pk != "S":
                    raise LingoError(f"'{state}' only makes sense after a switch (S1=open or S1=closed), not {bare}.")
                out.append(_Tok("part", bare.upper(), 0.0, len(bare) > 1, False, pk,
                                (state or "open").lower() in ("closed", "close", "shut", "on")))
                pos = m.end()
                continue
            if re.match(r"\s*=\s*\?", expr[m.end():]):
                raise LingoError(f"{bare}=? needs the value for the answer key: write {bare}=6? "
                                 f"(it is drawn as '{bare} = ?').")
            raise LingoError(f"'{bare}' has no value. Write it as {bare}=6 (a 6 Ω resistor named {bare}), "
                             f"or use S1 (switch), A1 (ammeter), V1 (voltmeter), 4uF (capacitor).")
        pos = m.end()
    return out


class _Parser:
    """Recursive descent:  sum := prod ('+' prod)*   prod := atom ('||' atom)*   atom := part | '(' sum ')'"""

    def __init__(self, tokens):
        self.t, self.i = tokens, 0
        self.counter: Dict[str, int] = {k: 0 for k in KINDS}
        self.names: List[str] = []

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def sum(self) -> Node:
        items = [self.prod()]
        while self.peek() and self.peek().text == "+":
            self.take()
            items.append(self.prod())
        return items[0] if len(items) == 1 else Group("series", items)

    def prod(self) -> Node:
        items = [self.atom()]
        while self.peek() and self.peek().text == "||":
            self.take()
            items.append(self.atom())
        return items[0] if len(items) == 1 else Group("parallel", items)

    def _name(self, tok: _Tok) -> str:
        self.counter[tok.pkind] += 1
        name = tok.text if tok.named else f"{tok.pkind}{self.counter[tok.pkind]}"
        if name.lower() in [n.lower() for n in self.names]:
            raise LingoError(f"The name {name} is used twice. Give each part a different name.")
        self.names.append(name)
        return name

    def atom(self) -> Node:
        tok = self.take()
        if tok is None:
            raise LingoError("The circuit line ends too early - a value is missing after the last + or ||.")
        if tok.kind == "value":
            name = self._name(tok)
            if tok.value <= 0:
                raise LingoError(f"{name} must be greater than 0 {'F' if tok.pkind == 'C' else 'Ω'}.")
            return R(name, tok.value, tok.hidden, tok.pkind)
        if tok.kind == "part":
            return R(self._name(tok), 0.0, False, tok.pkind, tok.closed)
        if tok.text == "(":
            inner = self.sum()
            close = self.take()
            if close is None or close.text != ")":
                raise LingoError("A '(' is never closed. Add the missing ')'.")
            return inner
        if tok.text == ")":
            raise LingoError("There is a ')' without a matching '('.")
        raise LingoError(f"A value is missing before '{tok.text}'.")


def parse_expression(expr: str) -> Node:
    tokens = _tokenize(expr)
    if not tokens:
        raise LingoError("The circuit line is empty. Example:  circuit: (4 + 2) || 6 + 3")
    p = _Parser(tokens)
    tree = p.sum()
    if p.peek() is not None:
        raise LingoError(f"Unexpected '{p.peek().text}' - check the parentheses.")
    return tree


_QUANT = [
    (r"equivalent\s+capacitance|total\s+capacitance|c_?eq\b", "ceq"),
    (r"equivalent|total\s+resistance|r_?eq\b", "req"),
    (r"total\s+current|battery\s+current|current\s+(from|drawn|supplied)", "total_current"),
    (r"reading|\bread|\bshow|indicat|display", "reading"),
    (r"\bcharge\b", "charge"),
    (r"energy|stored", "energy"),
    (r"current", "current"),
    (r"voltage|potential|volt", "voltage"),
    (r"power|dissipat", "power"),
]
_KIND_WORDS = {"resistor": "R", "capacitor": "C", "ammeter": "A", "voltmeter": "V", "switch": "S", "meter": None}
_NOT_NAMES = {"resistor", "ohm", "ohms", "capacitor", "ammeter", "voltmeter", "switch", "meter", "battery",
              "circuit", "shown", "each", "every", "all", "farad", "farads"}


def _parse_ask(chunk: str, problem: Problem) -> Ask:
    low = chunk.lower().strip()
    quantity = next((q for pat, q in _QUANT if re.search(pat, low)), None)
    if quantity is None:
        raise LingoError(f"In 'ask: {chunk}': say what to find - current through, voltage across, power in, "
                         "charge on, energy in, reading of, total current, equivalent resistance or capacitance.")
    if quantity in ("req", "total_current", "ceq"):
        return Ask(quantity)
    target: Optional[R] = None
    m = re.search(r"\b([A-Za-z][A-Za-z0-9]*)\s*$", chunk.strip()) or re.search(r"\b([RCSAV][0-9]+)\b", chunk)
    if m and m.group(1).lower() not in _NOT_NAMES:
        target = problem.part(m.group(1))
    if target is None:
        norm = _normalise(chunk)
        m = re.search(r"([0-9]*\.?[0-9]+)\s*(kΩ|Ω|[mnpu]?F)\b", norm)
        if m:
            value, kind = _unit_value(m.group(1), m.group(2))
            hits = [p for p in problem.parts() if p.kind == kind and abs(p.value - value) < 1e-15 + 1e-9 * value]
            shown = f"{m.group(1)} {m.group(2)}"
            if not hits:
                raise LingoError(f"In 'ask: {chunk}': there is no {shown} {KINDS[kind]} in the circuit.")
            if len(hits) > 1:
                raise LingoError(f"In 'ask: {chunk}': several {KINDS[kind]}s are {shown} - use the name "
                                 f"({', '.join(p.name for p in hits)}).")
            target = hits[0]
    if target is None:
        for word, kind in _KIND_WORDS.items():
            if re.search(rf"\b{word}s?\b", low):
                hits = [p for p in problem.parts() if (p.kind == kind if kind else p.kind in "AV")]
                if len(hits) == 1:
                    target = hits[0]
                    break
                if len(hits) > 1:
                    raise LingoError(f"In 'ask: {chunk}': there are several {word}s - use the name "
                                     f"({', '.join(p.name for p in hits)}).")
                raise LingoError(f"In 'ask: {chunk}': there is no {word} in the circuit.")
    if target is None:
        raise LingoError(f"In 'ask: {chunk}': say which part, e.g. 'current through R2', 'the 2 ohm resistor', "
                         "'charge on C1' or 'reading of A1'.")
    if quantity == "reading" and target.kind not in "AV":
        raise LingoError(f"In 'ask: {chunk}': {target.name} is a {target.what}, not a meter - ask for the current "
                         f"through or the voltage across it.")
    if quantity in ("charge", "energy") and target.kind != "C":
        raise LingoError(f"In 'ask: {chunk}': {target.name} is a {target.what}; charge and stored energy apply to "
                         "capacitors.")
    return Ask(quantity, target.name)


def parse(text: str) -> Problem:
    """Parse the whole lingo block."""
    fields: Dict[str, List[str]] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^(source|battery|volts?|circuit|ask|find|hide|title|text|question|switch|switches)\b\s*[:=]?\s*(.*)$",
                     line, re.I)
        if m:
            key = m.group(1).lower()
            key = {"battery": "source", "volt": "source", "volts": "source", "find": "ask", "question": "text",
                   "switches": "switch"}.get(key, key)
            fields.setdefault(key, []).append(m.group(2).strip())
        elif re.fullmatch(r"[0-9]*\.?[0-9]+\s*(V|volts?)", line, re.I):
            fields.setdefault("source", []).append(line)
        elif "circuit" not in fields and re.search(r"\+|\|\||\bpar|\bplus\b|\(", line, re.I):
            fields.setdefault("circuit", []).append(line)
        else:
            raise LingoError(f"I don't know what to do with the line '{line}'. Lines start with source:, circuit:, "
                             "ask:, hide:, switch:, title: or text:.")
    if "circuit" not in fields:
        raise LingoError("Add a circuit line, e.g.  circuit: (4 + 2) || 6 + 3")
    if "source" not in fields:
        raise LingoError("Add the battery voltage, e.g.  source: 12 V")
    sv = re.search(r"([0-9]*\.?[0-9]+)", fields["source"][0])
    if not sv:
        raise LingoError(f"'source: {fields['source'][0]}' needs a number, e.g. source: 12 V")
    volts = float(sv.group(1))
    if volts <= 0:
        raise LingoError("The source voltage must be greater than 0 V.")
    tree = parse_expression(" ".join(fields["circuit"]))
    prob = Problem(volts, tree, title=" ".join(fields.get("title", [])), text=" ".join(fields.get("text", [])))
    for chunk in fields.get("hide", []):
        for name in re.split(r"[,\s]+", chunk.strip()):
            if name:
                prob.part(name).hidden = True
    for line in fields.get("switch", []):
        for chunk in re.split(r",|;", line):
            m = re.match(r"\s*(?:([A-Za-z][A-Za-z0-9]*)\s*)?[:=]?\s*(?:is\s+)?(open|closed|close|shut|on|off)\b", chunk, re.I)
            if not m:
                raise LingoError(f"In 'switch: {chunk.strip()}': write S1 open or S1 closed.")
            switches = [p for p in prob.parts() if p.kind == "S"]
            if m.group(1):
                sw = prob.part(m.group(1))
                if sw.kind != "S":
                    raise LingoError(f"{sw.name} is a {sw.what}, not a switch.")
            elif len(switches) == 1:
                sw = switches[0]
            else:
                raise LingoError("In 'switch: ...': say which switch, e.g. switch: S1 closed.")
            sw.closed = m.group(2).lower() in ("closed", "close", "shut", "on")
    for line in fields.get("ask", []):
        for chunk in re.split(r",|;|\band\b", line):
            if chunk.strip():
                prob.asks.append(_parse_ask(chunk, prob))
    return prob


def _lingo_farads(x: float) -> str:
    for p, m in (("", 1.0), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if x >= m * 0.9995:
            return f"{round(x / m, 6):g}{p}F"
    return f"{round(x / 1e-12, 6):g}pF"


def _part_lingo(p: R) -> str:
    auto = bool(re.fullmatch(r"[RC]\d+", p.name))
    if p.kind == "R":
        v = f"{p.value:g}"
        return v if auto else f"{p.name}={v}"
    if p.kind == "C":
        v = _lingo_farads(p.value)
        return v if auto else f"{p.name}={v}"
    if p.kind == "S":
        return f"{p.name}={'closed' if p.closed else 'open'}"
    return p.name


ASK_WORDS = {"current": "current through", "voltage": "voltage across", "power": "power in", "charge": "charge on",
             "energy": "energy in", "reading": "reading of", "req": "equivalent resistance",
             "ceq": "equivalent capacitance", "total_current": "total current"}


def to_lingo(p: Problem) -> str:
    """Problem -> lingo text (used by the random generator and the translator)."""
    def expr(n: Node, top=True) -> str:
        if isinstance(n, R):
            return _part_lingo(n)
        sep = " + " if n.kind == "series" else " || "
        parts = []
        for i in n.items:
            s = expr(i, False)
            if isinstance(i, Group) and (i.kind == "series" and n.kind == "parallel"):
                s = f"({s})"
            parts.append(s)
        return sep.join(parts)

    lines = [f"source: {p.volts:g} V", f"circuit: {expr(p.tree)}"]
    asks = [ASK_WORDS[a.quantity] + (f" {a.target}" if a.target else "") for a in p.asks]
    if asks:
        lines.append("ask: " + ", ".join(asks))
    hidden = [r.name for r in p.parts() if r.hidden]
    if hidden:
        lines.append("hide: " + " ".join(hidden))
    if p.title:
        lines.append(f"title: {p.title}")
    if p.text:
        lines.append(f"text: {p.text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Layout -> Schemdraw code (worksheet style)
# ---------------------------------------------------------------------------

W = 3.0            # width of one part (schemdraw unit)
LEAD = 0.75        # short wire on each side of a parallel stack
GAP = 0.9          # vertical space between stacked branches
UP, DOWN = 1.15, 0.35


def _si(x: float, unit: str) -> str:
    ax = abs(x)
    for p, m in (("", 1.0), ("m", 1e-3), ("µ", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if ax >= m * 0.9995:
            return f"{x / m:.2f} {p}{unit}"
    return f"0.00 {unit}" if x == 0 else f"{x / 1e-12:.2f} p{unit}"


def fmt_ohms(x: float) -> str:
    if x == INF:
        return "∞ Ω"
    return f"{x / 1000:.2f} kΩ" if x >= 1000 else f"{x:.2f} Ω"


def fmt_farads(x: float) -> str:
    return _si(x, "F")


def fmt_value(p: R) -> str:
    return fmt_farads(p.value) if p.kind == "C" else fmt_ohms(p.value)


def _tex_name(name: str) -> str:
    return f"${name[0]}_{{{name[1:]}}}$" if re.fullmatch(r"[A-Za-z][A-Za-z0-9]+", name) else name


def _label(p: R) -> str:
    if p.hidden:
        return f"{p.name} = ?"
    if p.kind in ("R", "C"):
        return f"{_tex_name(p.name)}\n{fmt_value(p)}"
    if p.kind == "S":
        return f"{_tex_name(p.name)}\n({'closed' if p.closed else 'open'})"
    return _tex_name(p.name)


def _elm(p: R) -> str:
    if p.kind == "S":
        return "elm.Switch(nc=True)" if p.closed else "elm.Switch()"
    return {"R": "elm.Resistor()", "C": "elm.Capacitor()", "A": "elm.MeterA()", "V": "elm.MeterV()"}[p.kind]


def _size(n: Node) -> Tuple[float, float, float]:
    """(width, up, down) of a node drawn horizontally on its centre line."""
    if isinstance(n, R):
        return W, UP, DOWN
    sizes = [_size(i) for i in n.items]
    if n.kind == "series":
        return sum(s[0] for s in sizes), max(s[1] for s in sizes), max(s[2] for s in sizes)
    total = sum(s[1] + s[2] for s in sizes) + GAP * (len(sizes) - 1)
    return max(s[0] for s in sizes) + 2 * LEAD, total / 2, total / 2


def _pt(x, y) -> str:
    return f"({x:g}, {y:g})"


def _draw(n: Node, x: float, y: float, L: List[str], loc: Optional[str] = None) -> None:
    w, up, down = _size(n)
    if isinstance(n, R):
        lab = f".label({_label(n)!r}" + (f", loc='{loc}')" if loc else ")")
        L.append(f"{n.name} = d.add({_elm(n)}.endpoints({_pt(x, y)}, {_pt(x + W, y)}){lab})")
        return
    if n.kind == "series":
        for i in n.items:
            _draw(i, x, y, L, loc)
            x += _size(i)[0]
        return
    xl, xr = x + LEAD, x + w - LEAD
    inner = xr - xl
    L.append(f"d += elm.Line().endpoints({_pt(x, y)}, {_pt(xl, y)})")
    L.append(f"d += elm.Line().endpoints({_pt(xr, y)}, {_pt(x + w, y)})")
    ytop = y + up
    ys = []
    for i in n.items:
        bw, bup, bdown = _size(i)
        yi = ytop - bup
        ys.append(yi)
        bx = xl + (inner - bw) / 2
        if bx > xl:
            L.append(f"d += elm.Line().endpoints({_pt(xl, yi)}, {_pt(bx, yi)})")
            L.append(f"d += elm.Line().endpoints({_pt(bx + bw, yi)}, {_pt(xr, yi)})")
        _draw(i, bx, yi, L, None)
        ytop = yi - bdown - GAP
    L.append(f"d += elm.Line().endpoints({_pt(xl, ys[0])}, {_pt(xl, ys[-1])})")
    L.append(f"d += elm.Line().endpoints({_pt(xr, ys[0])}, {_pt(xr, ys[-1])})")
    L.append(f"d += elm.Dot().at({_pt(xl, y)})")
    L.append(f"d += elm.Dot().at({_pt(xr, y)})")


def draw_code(p: Problem, style: str = "US") -> str:
    """Problem -> complete Schemdraw script.  The last series item goes on the bottom rail, like a worksheet."""
    top: List[Node]
    bottom: Optional[Node]
    if isinstance(p.tree, Group) and p.tree.kind == "series" and len(p.tree.items) >= 2:
        top, bottom = p.tree.items[:-1], p.tree.items[-1]
    else:
        top, bottom = [p.tree], None
    top_node: Node = top[0] if len(top) == 1 else Group("series", top)
    tw, tup, tdown = _size(top_node)
    bw, bup, bdown = _size(bottom) if bottom else (0.0, 0.0, 0.0)
    width = max(tw, bw) + 2 * 1.5
    H = max(4.0, tdown + bup + 2.2)
    L = ["import schemdraw", "import schemdraw.elements as elm", "",
         f"elm.style(elm.STYLE_{'IEC' if style == 'IEC' else 'IEEE'})",
         "d = schemdraw.Drawing(show=False)", f"d.config(unit={W:g}, fontsize=12)", "",
         "# battery on the left (+ at the top)",
         f"battery = d.add(elm.BatteryCell().endpoints({_pt(0, H)}, {_pt(0, 0)}).label({f'{p.volts:.1f} V'!r}))",
         "", "# top rail"]
    tx = 1.5 + (width - 3 - tw) / 2
    L.append(f"d += elm.Line().endpoints({_pt(0, H)}, {_pt(tx, H)})")
    _draw(top_node, tx, H, L)
    L.append(f"d += elm.Line().endpoints({_pt(tx + tw, H)}, {_pt(width, H)})")
    L += ["", "# right side", f"d += elm.Line().endpoints({_pt(width, H)}, {_pt(width, 0)})", "", "# bottom rail"]
    if bottom:
        bx = 1.5 + (width - 3 - bw) / 2
        L.append(f"d += elm.Line().endpoints({_pt(width, 0)}, {_pt(bx + bw, 0)})")
        _draw(bottom, bx, 0, L, "bottom")
        L.append(f"d += elm.Line().endpoints({_pt(bx, 0)}, {_pt(0, 0)})")
    else:
        L.append(f"d += elm.Line().endpoints({_pt(width, 0)}, {_pt(0, 0)})")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# 4. Solving by reduction, with the steps a student would write
#    DC steady state: capacitors and voltmeters are open, ammeters and closed switches are wires.
# ---------------------------------------------------------------------------

@dataclass
class Result:
    req: float                            # Ω seen by the battery (inf = no current path)
    ceq: Optional[float]                  # F seen by the battery when the circuit is purely capacitive
    total_current: float
    per: Dict[str, Dict[str, float]]      # name -> {"current", "voltage", "power", [charge, energy, reading]}
    steps: List[str]                      # reduction steps
    back: List[str]                       # working back down the tree


def _res(n: Node) -> float:
    """Resistance of a node in steady state (inf = open, 0 = wire)."""
    if isinstance(n, R):
        return {"R": n.value, "C": INF, "V": INF, "A": 0.0, "S": 0.0 if n.closed else INF}[n.kind]
    vals = [_res(i) for i in n.items]
    if n.kind == "series":
        return INF if any(v == INF for v in vals) else sum(vals)
    finite = [v for v in vals if v != INF]
    if not finite:
        return INF
    if any(v == 0 for v in finite):
        return 0.0
    return 1 / sum(1 / v for v in finite)


def _cap(n: Node) -> float:
    """Capacitance of a path that carries no current.  inf = a wire (resistor, closed switch, ammeter drop 0 V),
    0 = no charge can flow through it (open switch, voltmeter)."""
    if isinstance(n, R):
        return {"R": INF, "C": n.value, "V": 0.0, "A": INF, "S": INF if n.closed else 0.0}[n.kind]
    vals = [_cap(i) for i in n.items]
    if n.kind == "series":
        if any(v == 0 for v in vals):
            return 0.0
        finite = [v for v in vals if v != INF]
        return INF if not finite else 1 / sum(1 / v for v in finite)
    if any(v == INF for v in vals):
        return INF
    return sum(vals)


def _leaves(n: Node) -> List[R]:
    return [n] if isinstance(n, R) else [p for i in n.items for p in _leaves(i)]


def _name_of(n: Node, memo: Dict[int, str]) -> str:
    return n.name if isinstance(n, R) else memo[id(n)]


def _combo(names: List[str], prefix: str) -> str:
    return prefix + "".join(re.sub(rf"^{prefix}", "", x) for x in names)


def _rdigits(n: Node, memo: Dict[int, str]) -> str:
    """What a member contributes to a combined resistor name: R1 -> '1', R12 -> '12', S1/C1/V1/A1 -> nothing."""
    if _res(n) == INF:
        return ""                                       # an open path carries no current: it drops out
    if isinstance(n, R):
        return re.sub(r"^R", "", n.name) if n.kind == "R" else ""
    nm = memo[id(n)]
    return re.sub(r"^R", "", nm) if nm.startswith("R") and any(q.kind == "R" for q in _leaves(n)) else ""


def _plural(names: List[str], one: str, many: str) -> str:
    return one if len(names) == 1 else many


def solve(p: Problem) -> Result:
    steps: List[str] = []
    memo: Dict[int, str] = {}          # group id -> combined name, e.g. R12
    parts = p.parts()

    # 0. what each special part does
    for q in parts:
        if q.kind == "C":
            steps.append(f"{q.name} is a capacitor: once charged (steady state) no current flows through it, "
                         f"so its branch is open; it holds the voltage across it.")
        elif q.kind == "S":
            steps.append(f"{q.name} is {'closed: it acts as a wire (0 Ω, 0 V across it)' if q.closed else 'open: no current flows through it'}.")
        elif q.kind == "A":
            steps.append(f"{q.name} is an ideal ammeter: a wire (0 Ω) that reads the current through it.")
        elif q.kind == "V":
            steps.append(f"{q.name} is an ideal voltmeter: an open branch (no current) that reads the voltage across it.")

    # 1. resistive reduction
    def reduce(n: Node) -> float:
        if isinstance(n, R):
            return _res(n)
        vals = [reduce(i) for i in n.items]
        names = [_name_of(i, memo) for i in n.items]
        total = _res(n)
        # the combined name: wires and open parts drop out, e.g. R1 + S1 -> R1,  (R1 + R2) || R3 -> R123
        contrib = [(nm, _rdigits(i, memo)) for nm, i in zip(names, n.items) if _rdigits(i, memo)]
        if total == INF and n.kind == "series":
            combo = "".join(names)                     # an open path keeps every name: R1C1
        elif len(contrib) == 1:
            combo = contrib[0][0]
        elif contrib:
            combo = "R" + "".join(d for _, d in contrib)
        else:
            combo = "".join(names)
        memo[id(n)] = combo
        if not any(q.kind == "R" for q in _leaves(n)):
            return total
        if n.kind == "series":
            opens = [nm for nm, v in zip(names, vals) if v == INF]
            wires = [nm for nm, v in zip(names, vals) if v == 0]
            if opens:
                steps.append(f"{_join(names)} are in series, but {_join(opens)} {_plural(opens, 'carries', 'carry')} "
                             f"no current, so the whole path {combo} is open (no current).")
            elif len(contrib) == 1:
                steps.append(f"{_join(names)} are in series; {_join(wires)} {_plural(wires, 'is a wire', 'are wires')} "
                             f"(0 Ω), so this path is just {combo} = **{fmt_ohms(total)}**")
            else:
                terms = [fmt_ohms(v) for v in vals if v > 0]
                extra = f" ({_join(wires)} {_plural(wires, 'is a wire', 'are wires')}, 0 Ω)" if wires else ""
                steps.append(f"{_join(names)} are in series: {combo} = {' + '.join(terms)} = **{fmt_ohms(total)}**{extra}")
        else:
            opens = [nm for nm, v in zip(names, vals) if v == INF]
            live = [(nm, v) for nm, v in zip(names, vals) if v != INF]
            shorts = [nm for nm, v in live if v == 0]
            note = f" ({_join(opens)} {_plural(opens, 'carries', 'carry')} no current)" if opens else ""
            if shorts:
                steps.append(f"{_join(names)} are in parallel, and {_join(shorts)} {_plural(shorts, 'is', 'are')} a wire "
                             f"(0 Ω), so {combo} = **0 Ω**: all the current takes that path{note}.")
            elif len(live) == 1:
                steps.append(f"{_join(names)} are in parallel{note}, so this is just {live[0][0]} = **{fmt_ohms(total)}**")
            elif not live:
                steps.append(f"{_join(names)} are in parallel and none carries current, so {combo} is open.")
            else:
                steps.append(f"{_join([nm for nm, _ in live])} are in parallel{note}: 1/{combo} = "
                             f"{' + '.join(f'1/{fmt_ohms(v)}' for _, v in live)}, so {combo} = **{fmt_ohms(total)}**")
        return total

    req = reduce(p.tree)

    # 2. capacitor reduction for groups made only of capacitors
    def creduce(n: Node) -> float:
        if isinstance(n, R):
            return n.value
        vals = [creduce(i) for i in n.items]
        names = [_name_of(i, memo) for i in n.items]
        combo = _combo(names, "C")
        memo[id(n)] = combo
        total = _cap(n)
        if n.kind == "series":
            steps.append(f"{_join(names)} are in series: 1/{combo} = {' + '.join(f'1/{fmt_farads(v)}' for v in vals)}, "
                         f"so {combo} = **{fmt_farads(total)}**")
        else:
            steps.append(f"{_join(names)} are in parallel: {combo} = {' + '.join(fmt_farads(v) for v in vals)} "
                         f"= **{fmt_farads(total)}**")
        return total

    def walk_caps(n: Node) -> None:
        if isinstance(n, Group):
            if all(q.kind == "C" for q in _leaves(n)):
                creduce(n)
            else:
                for i in n.items:
                    walk_caps(i)
    walk_caps(p.tree)

    if req == 0:
        raise LingoError("The battery is short-circuited: a path of only wires (closed switches / ammeters) connects "
                         "its terminals. Put a resistor in that path.")
    total_i = 0.0 if req == INF else p.volts / req
    ctot = _cap(p.tree) if req == INF else None
    ceq = ctot if ctot is not None and 0 < ctot < INF else None
    per: Dict[str, Dict[str, float]] = {}
    back: List[str] = []
    if req == INF:
        if ceq:
            back.append(f"No current flows once the capacitors are charged. The whole {p.volts:.2f} V appears across "
                        f"the capacitor network {_name_of(p.tree, memo)} = {fmt_farads(ceq)}, so the total charge is "
                        f"Q = C × V = {fmt_farads(ceq)} × {p.volts:.2f} V = **{_fq(ceq * p.volts)}**.")
        else:
            back.append(f"No current flows: there is no closed path for it. The battery voltage {p.volts:.2f} V "
                        f"appears across the open part.")
    else:
        back.append(f"The battery sees {_name_of(p.tree, memo)} = {fmt_ohms(req)}, so the total current is "
                    f"I = V / R = {p.volts:.2f} V / {fmt_ohms(req)} = **{_fa(total_i)}**.")

    def leaf(q: R, i: float, v: float) -> None:
        d = {"current": i, "voltage": v, "power": i * v}
        if q.kind == "C":
            d.update(current=0.0, power=0.0, charge=q.value * v, energy=0.5 * q.value * v * v)
        elif q.kind == "A":
            d.update(voltage=0.0, power=0.0, reading=i)
        elif q.kind == "V":
            d.update(current=0.0, power=0.0, reading=v)
        elif q.kind == "S":
            d["power"] = 0.0
        per[q.name] = d

    def down(n: Node, i: float, v: float) -> None:
        if isinstance(n, R):
            leaf(n, i, v)
            return
        name = memo[id(n)]
        members = [_name_of(it, memo) for it in n.items]
        tag = "" if name in members else f" ({name})"
        if n.kind == "series":
            if i > 0:
                back.append(f"{_join(members)} are in series{tag}, so each carries the same current {_fa(i)}; "
                            f"each voltage is I × R (0 V across a wire).")
                for it in n.items:
                    down(it, i, i * _res(it))
                return
            caps = [(it, _cap(it)) for it in n.items]
            blockers = [it for it, c in caps if c == 0]
            if v == 0:
                for it in n.items:
                    down(it, 0.0, 0.0)
            elif blockers:
                names = [_name_of(b, memo) for b in blockers]
                back.append(f"No current flows in {name}: {_join(names)} {_plural(names, 'is', 'are')} open, so the "
                            f"full {_fv(v)} appears across {_plural(names, 'it', 'them')} and every other part gets 0 V.")
                for it in n.items:
                    down(it, 0.0, v / len(blockers) if it in blockers else 0.0)
            else:
                cs = _cap(n)
                if cs == INF:
                    for it in n.items:
                        down(it, 0.0, 0.0)
                else:
                    q = cs * v
                    back.append(f"No current flows in {name} once the capacitors are charged, so the parts in series "
                                f"share the same charge Q = C × V = {fmt_farads(cs)} × {_fv(v)} = {_fq(q)}; each "
                                f"capacitor voltage is Q / C. Resistors and wires in this path drop 0 V.")
                    for it, c in caps:
                        down(it, 0.0, 0.0 if c == INF else q / c)
        else:
            r = _res(n)
            if r == 0 and i > 0:
                shorts = [it for it in n.items if _res(it) == 0]
                names = [_name_of(s, memo) for s in shorts]
                back.append(f"{name} is shorted by {_join(names)} (0 Ω): every branch has 0 V across it and the whole "
                            f"{_fa(i)} flows through {_plural(names, 'it', 'them')}.")
                for it in n.items:
                    down(it, i / len(shorts) if it in shorts else 0.0, 0.0)
                return
            back.append(f"{_join(members)} are in parallel{tag}, so each branch has the same voltage {_fv(v)}; "
                        f"each current is V / R (0 A through an open branch).")
            for it in n.items:
                rk = _res(it)
                down(it, 0.0 if rk == INF or rk == 0 else v / rk, v)

    down(p.tree, total_i, p.volts)
    return Result(req, ceq, total_i, per, steps, back)


def _join(names: List[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _fa(a: float) -> str:
    return f"{a * 1000:.2f} mA" if 0 < a < 0.1 else f"{a:.2f} A"


def _fv(v: float) -> str:
    return f"{v * 1000:.2f} mV" if 0 < v < 0.1 else f"{v:.2f} V"


def _fp(w: float) -> str:
    return f"{w * 1000:.2f} mW" if 0 < w < 0.1 else f"{w:.2f} W"


def _fq(q: float) -> str:
    return _si(q, "C")


def _fj(u: float) -> str:
    return _si(u, "J")


def answers(p: Problem, res: Result) -> List[str]:
    out = []
    for a in p.asks:
        if a.quantity == "req":
            out.append("Equivalent resistance = " + ("∞ (no closed path - no current flows)" if res.req == INF
                                                    else fmt_ohms(res.req)))
        elif a.quantity == "ceq":
            out.append("Equivalent capacitance = " + (fmt_farads(res.ceq) if res.ceq else
                                                     "not defined here (resistors carry current)"))
        elif a.quantity == "total_current":
            out.append(f"Total current from the battery = {_fa(res.total_current)}")
        else:
            r = res.per[a.target]
            q = p.part(a.target)
            if a.quantity == "reading":
                out.append(f"{a.target} reads {_fa(r['reading']) if q.kind == 'A' else _fv(r['reading'])}")
            elif a.quantity == "charge":
                out.append(f"Charge on {a.target} = {_fq(r.get('charge', 0.0))}")
            elif a.quantity == "energy":
                out.append(f"Energy stored in {a.target} = {_fj(r.get('energy', 0.0))}")
            else:
                out.append({"current": f"Current through {a.target} = {_fa(r['current'])}",
                            "voltage": f"Voltage across {a.target} = {_fv(r['voltage'])}",
                            "power": f"Power dissipated in {a.target} = {_fp(r['power'])}"}[a.quantity])
    return out


def _who(q: R) -> str:
    if q.kind in ("R", "C"):
        return q.name if q.hidden else f"the {fmt_value(q)} {q.what} ({q.name})"
    return f"{q.what} {q.name}"


def question_text(p: Problem) -> str:
    """Worksheet wording, generated from the asks (unless the teacher wrote their own)."""
    if p.text:
        return p.text
    notes = " ".join(f"{s.name} is {'closed' if s.closed else 'open'}." for s in p.parts() if s.kind == "S")
    lead = "The capacitors are fully charged. " if p.capacitors() else ""
    if not p.asks:
        body = "For the circuit shown, find the current through and the voltage across every part."
        return " ".join(x for x in (lead + body, notes) if x)
    by_target: Dict[Optional[str], List[str]] = {}
    for a in p.asks:
        by_target.setdefault(a.target, []).append(a.quantity)
    parts = []
    for target, qs in by_target.items():
        if target is None:
            for q in qs:
                parts.append({"req": "the equivalent resistance", "ceq": "the equivalent capacitance",
                              "total_current": "the total current supplied by the battery"}[q])
            continue
        phr = {"current": "the current through", "voltage": "the voltage across", "power": "the power dissipated in",
               "charge": "the charge on", "energy": "the energy stored in", "reading": "the reading of"}
        parts.append(_join([phr[q] for q in qs]) + " " + _who(p.part(target)))
    tail = "of the circuit shown" if all(a.target is None for a in p.asks) else "in the circuit shown"
    return " ".join(x for x in (f"{lead}Determine {_join(parts)} {tail}.", notes) if x)


def solution_markdown(p: Problem, res: Result) -> str:
    L = ["**Reduce the circuit**", ""]
    L += [f"{i}. {s}" for i, s in enumerate(res.steps, 1)]
    L += ["", "**Work back to the individual parts**", ""]
    L += [f"{i}. {s}" for i, s in enumerate(res.back, 1)]
    others = [q for q in p.parts() if q.kind != "C"]
    if others:
        L += ["", "| Part | Current | Voltage | Power |", "|---|---|---|---|"]
        for q in others:
            x = res.per[q.name]
            desc = f"{q.name} ({fmt_ohms(q.value)})" if q.kind == "R" else \
                f"{q.name} ({q.what}{', closed' if q.kind == 'S' and q.closed else ', open' if q.kind == 'S' else ''})"
            L.append(f"| {desc} | {_fa(x['current'])} | {_fv(x['voltage'])} | {_fp(x['power'])} |")
        L += [f"| Battery | {_fa(res.total_current)} | {p.volts:.2f} V | {_fp(res.total_current * p.volts)} (delivered) |"]
    caps = p.capacitors()
    if caps:
        L += ["", "| Capacitor | Voltage | Charge Q = CV | Energy ½CV² |", "|---|---|---|---|"]
        for q in caps:
            x = res.per[q.name]
            L.append(f"| {q.name} ({fmt_farads(q.value)}) | {_fv(x['voltage'])} | {_fq(x['charge'])} | {_fj(x['energy'])} |")
    ans = answers(p, res)
    if ans:
        L += ["", "**Answer**", ""] + [f"- {a}" for a in ans]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 5. Random problems at the Physics 2 level
# ---------------------------------------------------------------------------

SHAPES = {
    "series": "{a} + {b} + {c}",
    "parallel": "{a} || {b} || {c}",
    "series-parallel": "({a} + {b}) || {c} + {d}",
    "parallel then series": "{a} || {b} + {c}",
    "two parallel pairs": "{a} || {b} + {c} || {d}",
    "nested (worksheet style)": "{a} || ({b} + {c} || {d}) + {e}",
    "capacitors": "{a}uF + {b}uF || {c}uF",
    "capacitors (parallel then series)": "{a}uF || {b}uF + {c}uF",
    "switch": "({a} + S1={s}) || {b} + {c}",
    "meters": "A1 + ({a} + {b}) || {c} + {d} || V1",
}
OHMS = [1, 2, 3, 4, 5, 6, 8, 10, 12]
VOLTS = [6, 9, 12, 24]


def random_lingo(seed: Optional[int] = None, shape: Optional[str] = None) -> str:
    rng = random.Random(seed)
    shape = shape or rng.choice(list(SHAPES))
    values = {k: rng.choice(OHMS) for k in "abcde"}
    values["s"] = rng.choice(["open", "closed"])
    prob = Problem(rng.choice(VOLTS), parse_expression(SHAPES[shape].format(**values)))
    parts = prob.parts()
    options = {"R": ["current", "voltage", "power"], "C": ["charge", "voltage", "energy"], "A": ["reading"],
               "V": ["reading"], "S": ["current", "voltage"]}
    candidates = [q for q in parts if q.kind != "S"]
    kind = rng.choice(["one", "one", "two", "total"])
    if kind == "total":
        prob.asks = [Ask("ceq" if not prob.resistors() else "total_current")]
    elif kind == "one":
        t = rng.choice(candidates)
        prob.asks = [Ask(rng.choice(options[t.kind]), t.name)]
    else:
        t = rng.choice([q for q in candidates if q.kind in "RC"])
        prob.asks = [Ask(q, t.name) for q in options[t.kind][:2]]
    return to_lingo(prob)


# ---------------------------------------------------------------------------
# 6. Plain English -> lingo  (rules only - no AI; every sentence gives the same lingo)
# ---------------------------------------------------------------------------
#
#   "12 V battery. A 4 ohm and a 2 ohm in series, that pair in parallel with a 6 ohm,
#    then a 3 ohm. Find the current through and the voltage across the 2 ohm."
#
# Sentences are cut into clauses (commas, periods, "then", "and that ...").  Each clause is
# one of: the battery, a connection ("... in series", "... in parallel with ..."), a note that
# a part is unknown or a switch is closed, a voltmeter placed across something, or a question
# ("find ...").  A clause that refers back ("that pair", "them") attaches its parts to
# everything built so far.  Anything the rules cannot read raises a LingoError naming the word.

_NUMWORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
            "fifty": 50, "hundred": 100, "thousand": 1000}
_NUMWORD_RE = re.compile(r"\b(" + "|".join(_NUMWORD) + r")\b(?=\s*-?\s*(?:k\b|kilo|ohm|Ω|Ω|volt|v\b|\d|[mnpu]?F\b))", re.I)
_UNIT = r"(?:\s*-?\s*(?:k(?:ilo)?)?\s*-?\s*(?:ohms?|Ω|Ω)|\s*-?\s*[mnpu]?F)"
_VALUE = re.compile(r"(?<![A-Za-z0-9.])(?P<num>\d+(?:\.\d+)?)"
                    r"(?:\s*-?\s*(?P<k>k)(?:ilo)?(?:\s*-?\s*(?:ohms?|Ω|Ω))?\b"
                    r"|\s*-?\s*(?P<ohm>ohms?|Ω|Ω)\b"
                    r"|\s*-?\s*(?P<f>[mnpu]?F)\b)?", re.I)
_VOLTS = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)\s*-?\s*(?:v|volts?)\b", re.I)
_SEP = re.compile(r"(,|;|\.(?!\d)|:|\bthen\b|\bfollowed\s+by\b|\bnext\b|\bfinally\b|\bafter\s+that\b|\band\s+(?=(?:that|this|"
                  r"those|these|them|both|the\s+(?:pair|group|combination|combo|set|branch|network|whole)|find|determine|"
                  r"calculate|compute|what|ask|all\b|a\s+voltmeter|an\s+ammeter)))", re.I)
_THEN = re.compile(r"then|followed\s+by|next|finally|after\s+that", re.I)
_REF = re.compile(r"\b(?:that|this|those|these|the)\s+(?:pair|group|combination|combo|set|branch|network|whole(?:\s+\w+)?|"
                  r"two|three|four|result|circuit\s+so\s+far)\b|\b(?:them|both)\b|^\s*(?:and\s+)?(?:that|this|those|these)\b"
                  r"|\b(?:with|to|across|and)\s+(?:that|this|those|these)\b", re.I)
_OP = re.compile(r"\b(series|parallel|across)\b", re.I)
_ASK_VERB = re.compile(r"\b(find|determine|calculate|compute|evaluate|solve|ask|asks|asked|question|what|how\s+much|"
                       r"work\s+out|give|students?)\b", re.I)
_QUANT_RE = re.compile(r"equivalent\s+capacitance|total\s+capacitance|c_?eq\b|equivalent(?:\s+resistance)?|"
                       r"total\s+resistance|r_?eq\b|total\s+current|battery\s+current|"
                       r"current(?:\s+(?:from|drawn|supplied|leaving|delivered))?|voltage|potential(?:\s+difference)?|"
                       r"power|dissipat\w*|\bcharge\b|energy|stored|reading|\breads?\b|\bshows?\b|indicates?", re.I)
_HIDE_VERB = re.compile(r"\b(is|are|be|being|as|mark(?:ed)?|label(?:l?ed)?|leave|left|make|made|hide|hidden|call(?:ed)?|"
                        r"keep|kept|treat(?:ed)?)\b", re.I)
_SWITCH = re.compile(r"\bswitch(?:es)?\b", re.I)
_AMMETER = re.compile(r"\bammeters?\b", re.I)
_VOLTMETER = re.compile(r"\bvoltmeters?\b", re.I)
_CLOSED = re.compile(r"\b(closed|shut)\b", re.I)
_FILLER = set("""a an the and with in of to is are be by connected connect connecting connection connections combination
    combined combine pair group resistor resistors ohm ohms rated each other one another together it its them this that
    those these all both which whose first second third last also plus battery source supply cell circuit has have
    having contains containing consisting consists made up wired hooked placed put attached joined join branch branches
    between ends end set sits sitting lies lying goes going runs running placed then followed next finally after
    whole thing two three four value valued rating there is are we you i on into from for at as so along chain string
    unknown identical equal same more resistance capacitor capacitors switch switches ammeter ammeters voltmeter
    voltmeters meter meters open closed shut steady state long time fully charged charge ideal initially wire wires
    capacitance""".split())


def _clauses(text: str) -> List[Tuple[str, bool]]:
    """-> [(clause, started_with_then)]"""
    parts = _SEP.split(text)
    out, then = [], False
    for i, p in enumerate(parts):
        if i % 2:                                   # a separator
            then = bool(_THEN.fullmatch(p.strip()))
            continue
        if p.strip():
            out.append((p.strip(), then))
        then = False
    return out


def _tidy(s: str) -> str:
    s = re.sub(r"[µμ]\s*F\b|\bmicro-?\s?farads?\b", "uF", s, flags=re.I)
    s = re.sub(r"\bnano-?\s?farads?\b", "nF", s, flags=re.I)
    s = re.sub(r"\bpico-?\s?farads?\b", "pF", s, flags=re.I)
    s = re.sub(r"\bmilli-?\s?farads?\b", "mF", s, flags=re.I)
    s = re.sub(r"\bfarads?\b", "F", s, flags=re.I)
    s = _NUMWORD_RE.sub(lambda m: str(_NUMWORD[m.group(1).lower()]), s)
    # "two 4 ohm resistors" / "3 capacitors of 6 uF" -> "4 ohm and 4 ohm" / "6uF and 6uF and 6uF"
    s = re.sub(r"\b(\d+)\s+(?:identical\s+|equal\s+|more\s+)?(\d+(?:\.\d+)?)(" + _UNIT + r")\s*(?:resistors?|capacitors?)\b",
               lambda m: " and ".join([m.group(2) + m.group(3)] * int(m.group(1))), s, flags=re.I)
    s = re.sub(r"\b(\d+)\s+(?:identical\s+|equal\s+)?(?:resistors?|capacitors?)\s+(?:of|at|rated(?:\s+at)?|each(?:\s+of)?)\s+"
               r"(\d+(?:\.\d+)?)(" + _UNIT + r")(?:\s+each)?",
               lambda m: " and ".join([m.group(2) + m.group(3)] * int(m.group(1))), s, flags=re.I)
    s = re.sub(r"\b\d+\s+(?:identical\s+|equal\s+|different\s+)?(resistors|capacitors)\b", r"\1", s, flags=re.I)
    s = re.sub(r"\bin\s+parallel\s+with\s+each\s+other\b|\bin\s+parallel\s+together\b", "in parallel", s, flags=re.I)
    s = re.sub(r"\bin\s+series\s+with\s+each\s+other\b|\bin\s+series\s+together\b", "in series", s, flags=re.I)
    return s


def _combine(kind: str, parts: List[Node]) -> Node:
    items: List[Node] = []
    for p in parts:
        if isinstance(p, Group) and p.kind == kind:
            items.extend(p.items)
        else:
            items.append(p)
    return items[0] if len(items) == 1 else Group(kind, items)


def _check_words(clause: str, cleaned: str) -> None:
    for w in re.findall(r"[A-Za-z]+", cleaned):
        if w.lower() not in _FILLER:
            raise LingoError(f"I don't understand the word '{w}' in \"{clause}\". Describe parts as '4 ohm', '4 uF', "
                             f"'a switch', 'an ammeter'; join them with 'in series' / 'in parallel'; refer back with "
                             f"'that pair'; continue with 'then'.")


def _find_by_value(tree: Node, kind: str, value: float, clause: str) -> R:
    hits = [q for q in _leaves(tree) if q.kind == kind and abs(q.value - value) < 1e-15 + 1e-9 * value]
    shown = fmt_farads(value) if kind == "C" else fmt_ohms(value)
    if not hits:
        raise LingoError(f"In \"{clause}\": there is no {shown} {KINDS[kind]} described so far.")
    if len(hits) > 1:
        raise LingoError(f"In \"{clause}\": several {KINDS[kind]}s are {shown} ({', '.join(q.name for q in hits)}) - "
                         f"say which one by name.")
    return hits[0]


def _wrap(tree: Node, target: Node, extra: R) -> Node:
    """Put `extra` in parallel with `target` inside the tree."""
    return _replace(tree, target, Group("parallel", [target, extra]))


def _replace(tree: Node, old: Node, new: Node) -> Node:
    if tree is old:
        return new
    if isinstance(tree, Group):
        tree.items = [_replace(i, old, new) for i in tree.items]
    return tree


def _seq(acc: Optional[Node], node: Node) -> Node:
    """Put `node` after everything so far, in series, keeping `node` as its own group."""
    if acc is None:
        return node
    if isinstance(acc, Group) and acc.kind == "series":
        acc.items.append(node)
        return acc
    return Group("series", [acc, node])


_WHOLE = re.compile(r"\b(whole|entire|everything|circuit\s+so\s+far|all\s+of\s+(?:it|them|that))\b", re.I)


def translate(text: str) -> str:
    """Plain English -> lingo.  Raises LingoError (naming the word) for anything the rules cannot read."""
    text = _tidy(" ".join(text.split()))
    if not text.strip():
        raise LingoError("Describe the circuit, e.g. '12 V battery, a 4 ohm and a 2 ohm in series, then a 3 ohm'.")
    volts: Optional[float] = None
    acc: Optional[Node] = None
    last: Optional[Node] = None            # what the previous clause built ("that pair" points here)
    pending: List[R] = []
    asks: List[str] = []
    hides: List[Tuple[str, float]] = []
    counter = 0

    def new_part(kind: str, v: float = 0.0, hidden: bool = False, closed: bool = False) -> R:
        nonlocal counter
        counter += 1
        return R(f"{kind}{counter}", v, hidden, kind, closed)

    def flush() -> None:
        nonlocal acc, last, pending
        if not pending:
            return
        if len(pending) > 1:
            vals = _join([fmt_value(r) if r.kind in "RC" else r.what for r in pending])
            raise LingoError(f"Say whether {vals} are in series or in parallel.")
        acc = _seq(acc, pending[0])
        last = pending[0]
        pending = []

    def referent(m: "re.Match") -> Node:
        """'that pair' = the previous clause's group; 'that whole group' = everything so far."""
        if _WHOLE.search(m.group(0)) or last is None:
            return acc
        return last

    for clause, then in _clauses(text):
        # 1. the battery
        for m in _VOLTS.finditer(clause):
            if volts is not None:
                raise LingoError(f"Two battery voltages ({volts:g} V and {m.group(1)} V) - use one battery for now.")
            volts = float(m.group(1))
        body = _VOLTS.sub(" ", clause)
        body = re.sub(r"\b(powered|driven|supplied|fed)\s+by\b|\bconnected\s+(?:to|across)\b", " ", body, flags=re.I)
        # 2. a question
        if _ASK_VERB.search(body) or (_QUANT_RE.search(body) and not _VALUE.search(_QUANT_RE.sub(" ", body))
                                      and not re.search(r"\bvolt", body, re.I)):
            asks.append(body)
            continue
        # values (resistors and capacitors)
        cap_clause = bool(re.search(r"\bcapacitors?\b", body, re.I))
        cap_unit = next((m.group("f") for m in _VALUE.finditer(body) if m.group("f")), None)
        vals: List[Tuple[int, R]] = []
        for m in _VALUE.finditer(body):
            if m.group("f"):
                v, kind = _unit_value(m.group("num"), m.group("f"))
            elif m.group("k") or m.group("ohm"):
                v, kind = float(m.group("num")) * (1000 if m.group("k") else 1), "R"
            elif cap_clause or cap_unit:
                if not cap_unit:
                    raise LingoError(f"In \"{clause}\": give the capacitor units, e.g. '4 uF' or '4 microfarad'.")
                v, kind = _unit_value(m.group("num"), cap_unit)
            else:
                v, kind = float(m.group("num")), "R"
            vals.append((m.start(), R("", v, False, kind)))
        ops = {o.lower() for o in _OP.findall(body)}
        ops = {"parallel" if o == "across" else o for o in ops}
        ref = _REF.search(body)
        unknown = bool(re.search(r"\bunknown\b|\?", body))
        sw = _SWITCH.search(body)
        am = _AMMETER.search(body)
        vm = _VOLTMETER.search(body)
        # words we do not know -> a readable error naming the word
        cleaned = _VALUE.sub(" ", body)
        cleaned = _OP.sub(" ", cleaned)
        cleaned = _REF.sub(" ", cleaned)
        cleaned = _HIDE_VERB.sub(" ", cleaned) if (unknown or sw) else cleaned
        cleaned = re.sub(r"\bk(?:ilo)?\b|\bohms?\b|\?|\b[mnpu]?F\b|\b[RCSAV]\d+\b", " ", cleaned, flags=re.I)
        _check_words(clause, cleaned)
        if not vals and not ops and not ref and not (sw or am or vm):
            if cap_clause:
                raise LingoError(f"In \"{clause}\": give the capacitor a value, e.g. 'a 4 uF capacitor'.")
            if unknown:
                raise LingoError(f"In \"{clause}\": say which part is unknown, e.g. 'the 6 ohm is unknown'.")
            continue                                    # "a battery", "resistors" - nothing to add
        if len(ops) > 1:
            raise LingoError(f"\"{clause}\" mixes series and parallel. Use one connection per phrase, separated by commas: "
                             f"'a 2 ohm and a 3 ohm in series, that pair in parallel with a 6 ohm'.")
        op = "series" if "series" in ops else "parallel" if "parallel" in ops else None
        # 3a. "the switch is closed" - a note about a switch already placed
        if sw and not vals and not op and not ref and _HIDE_VERB.search(body) and acc is not None \
                and re.search(r"\b(open|closed|shut)\b", body, re.I):
            switches = [q for q in _leaves(acc) if q.kind == "S"]
            named = re.search(r"\b(S\d+)\b", body)
            if named:
                target_sw = next((q for q in switches if q.name.lower() == named.group(1).lower()), None)
            elif len(switches) == 1:
                target_sw = switches[0]
            else:
                raise LingoError(f"In \"{clause}\": there are {len(switches)} switches - say which one (S1, S2 ...).")
            if target_sw is None:
                raise LingoError(f"In \"{clause}\": there is no switch called {named.group(1)}.")
            target_sw.closed = bool(_CLOSED.search(body))
            continue
        # 3b. "the 6 ohm is unknown"  (a note about a part already placed)
        if unknown and vals and not op and not ref and _HIDE_VERB.search(body) and not then and not (sw or am or vm):
            hides.extend((r.kind, r.value) for _, r in vals)
            continue
        # 3c. "a voltmeter across the 6 ohm" / "a voltmeter across that pair"
        if vm and (ref or vals) and op in (None, "parallel") and not am and not sw:
            flush()
            meter = new_part("V")
            if ref:
                if acc is None:
                    raise LingoError(f"\"{clause}\" refers back to '{ref.group(0).strip()}' but nothing was described before it.")
                acc = _wrap(acc, referent(ref), meter)
            else:
                if acc is None:
                    raise LingoError(f"In \"{clause}\": describe the part first, then put the voltmeter across it.")
                if len(vals) > 1:
                    raise LingoError(f"In \"{clause}\": a voltmeter goes across one part - which one?")
                _, want = vals[0]
                acc = _wrap(acc, _find_by_value(acc, want.kind, want.value, clause), meter)
            continue
        # parts in this clause, in the order they are said
        hidden_pos = set()
        if unknown:
            for pos, r in vals:
                before = body[max(0, pos - 30):pos]
                after = body[pos:pos + 40]
                if len(vals) == 1 or re.search(r"unknown|\?", before + " " + after, re.I):
                    hidden_pos.add(pos)
        occ: List[Tuple[int, R]] = [(pos, new_part(r.kind, r.value, pos in hidden_pos)) for pos, r in vals]
        for m in _SWITCH.finditer(body):
            occ.append((m.start(), new_part("S", closed=bool(_CLOSED.search(body)))))
        for m in _AMMETER.finditer(body):
            occ.append((m.start(), new_part("A")))
        if vm:
            raise LingoError(f"In \"{clause}\": say what the voltmeter is across, e.g. 'a voltmeter across the 6 ohm' "
                             f"or 'a voltmeter across that pair'.")
        occ.sort(key=lambda t: t[0])
        rs = [r for _, r in occ]
        # 4. a connection
        if then:
            flush()
        if ref:
            flush()
            if acc is None:
                raise LingoError(f"\"{clause}\" refers back to '{ref.group(0).strip()}' but nothing was described before it.")
            if op is None:
                raise LingoError(f"In \"{clause}\": say how '{ref.group(0).strip()}' connects - 'in series with' or "
                                 f"'in parallel with'.")
            if not rs:
                raise LingoError(f"In \"{clause}\": give the part that joins '{ref.group(0).strip()}', e.g. "
                                 f"'that pair in parallel with a 6 ohm'.")
            new = rs[0] if len(rs) == 1 else _combine(op, rs)
            values_first = occ[0][0] < ref.start()
            target = referent(ref)
            combined = _combine(op, [new, target] if values_first else [target, new])
            acc = combined if target is acc else _replace(acc, target, combined)
            last = combined
        elif op and rs:
            group_rs: List[Node] = list(pending) + list(rs) if pending else list(rs)
            pending = []
            if len(group_rs) == 1:
                if acc is None:
                    raise LingoError(f"In \"{clause}\": '{op}' needs at least two parts, e.g. '4 and 2 in {op}'.")
                acc = _combine(op, [acc, group_rs[0]])       # "then a 6 ohm in parallel" = with everything so far
                last = acc
            else:
                grp = _combine(op, group_rs)
                acc = _seq(acc, grp)
                last = grp
        elif op:
            if len(pending) < 2:
                raise LingoError(f"In \"{clause}\": '{op}' needs at least two parts before it, e.g. '4, 2 and 6 in {op}'.")
            grp = _combine(op, list(pending))
            pending = []
            acc = _seq(acc, grp)
            last = grp
        else:
            pending.extend(rs)
    flush()
    if acc is None:
        raise LingoError("Describe the parts, e.g. 'a 4 ohm and a 2 ohm in series, then a 3 ohm'.")
    if volts is None:
        raise LingoError("Say the battery voltage, e.g. '12 V battery' or 'a 6 volt source'.")
    prob = Problem(volts, acc)
    counters: Dict[str, int] = {k: 0 for k in KINDS}
    for q in prob.parts():                              # names follow reading order, like parse() does
        counters[q.kind] += 1
        q.name = f"{q.kind}{counters[q.kind]}"
    for kind, v in hides:
        hits = [q for q in prob.parts() if q.kind == kind and abs(q.value - v) < 1e-15 + 1e-9 * v]
        shown = fmt_farads(v) if kind == "C" else fmt_ohms(v)
        if not hits:
            raise LingoError(f"There is no {shown} {KINDS[kind]} to mark unknown.")
        if len(hits) > 1:
            raise LingoError(f"Several {KINDS[kind]}s are {shown} ({', '.join(q.name for q in hits)}) - say which one is "
                             f"unknown using its name, e.g. 'hide: {hits[0].name}' in the lingo.")
        hits[0].hidden = True
    for a in asks:
        prob.asks.extend(_translate_ask(a, prob))
    return to_lingo(prob)


def _translate_ask(clause: str, prob: Problem) -> List[Ask]:
    out: List[Ask] = []
    quants = list(_QUANT_RE.finditer(clause))
    if not quants:
        raise LingoError(f"In \"{clause}\": say what to find - current through, voltage across, power in, charge on, "
                         f"energy in, reading of, total current, or equivalent resistance / capacitance.")
    targets: List[Tuple[int, str]] = []
    for m in _VALUE.finditer(clause):
        if m.group("f"):
            targets.append((m.start(), f"the {m.group('num')} {m.group('f')} capacitor"))
        elif m.group("k") or m.group("ohm"):
            targets.append((m.start(), f"the {m.group('num')} {'k' if m.group('k') else ''}ohm resistor"))
    targets += [(m.start(), m.group(0)) for m in re.finditer(r"\b[RCSAV]\d+\b", clause)]
    targets += [(m.start(), f"the {m.group(1).lower()}") for m in
                re.finditer(r"\b(ammeter|voltmeter|switch|capacitor|resistor)\b", clause, re.I)
                if not re.search(r"\b(each|every|all)\s*$", clause[:m.start()], re.I)]
    targets.sort()
    every = re.search(r"\b(each|every|all)\b", clause, re.I)
    for q in quants:
        word = q.group(0).lower()
        if word.startswith(("equivalent capacitance", "total capacitance", "c_eq", "ceq")):
            out.append(Ask("ceq"))
            continue
        if word.startswith(("equivalent", "total resistance", "r_eq", "req")):
            out.append(Ask("req"))
            continue
        if word.startswith(("total", "battery")) or re.match(r"current\s+\w", word):
            out.append(Ask("total_current"))
            continue
        phrase = ("current through" if word.startswith("current") else
                  "voltage across" if word.startswith(("voltage", "potential")) else
                  "charge on" if word.startswith("charge") else
                  "energy in" if word.startswith(("energy", "stored")) else
                  "reading of" if word.startswith(("reading", "read", "show", "indicat")) else "power in")
        after = [t for t in targets if t[0] > q.end()]
        tgt = after[0][1] if after else targets[-1][1] if targets else None
        if tgt is None:
            if every:
                out.extend(_parse_ask(f"{phrase} {r.name}", prob) for r in prob.parts()
                           if (phrase.startswith(("charge", "energy")) and r.kind == "C")
                           or (phrase.startswith("reading") and r.kind in "AV")
                           or (phrase.startswith(("current", "voltage", "power")) and r.kind in "RC"))
                continue
            raise LingoError(f"In \"{clause}\": say which part, e.g. '{phrase} the 2 ohm resistor' or '{phrase} R2'.")
        out.append(_parse_ask(f"{phrase} {tgt}", prob))
    seen, unique = set(), []                        # "power dissipated" matches twice - keep one
    for a in out:
        if (a.quantity, a.target) not in seen:
            seen.add((a.quantity, a.target))
            unique.append(a)
    return unique
