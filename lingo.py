"""
lingo.py - the "circuit lingo" a teacher types, and everything derived from it.

    source: 12 V
    circuit: (4 + 2) || 6 + 3
    ask: current through R2, voltage across R2

    +   series          ||  parallel (binds tighter, like multiplication)
    ( ) grouping        R3=6  names a resistor      hide: R3  prints "R3 = ?"

No AI anywhere in this file.  The same text always gives the same figure,
the same answers and the same worked solution.

Pipeline:  text --parse()--> Problem --draw_code()--> Schemdraw code
                                     --solve()-----> answers + worked steps
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# 1. Data model
# ---------------------------------------------------------------------------

@dataclass
class R:
    """One resistor."""
    name: str
    ohms: float
    hidden: bool = False


@dataclass
class Group:
    kind: str                     # "series" | "parallel"
    items: List["Node"]


Node = Union[R, Group]


@dataclass
class Ask:
    quantity: str                 # current | voltage | power | req | total_current
    target: Optional[str] = None  # resistor name


@dataclass
class Problem:
    volts: float
    tree: Node
    asks: List[Ask] = field(default_factory=list)
    title: str = ""
    text: str = ""                # teacher's own wording (optional)

    def resistors(self) -> List[R]:
        out: List[R] = []

        def walk(n: Node):
            if isinstance(n, R):
                out.append(n)
            else:
                for i in n.items:
                    walk(i)
        walk(self.tree)
        return out

    def resistor(self, name: str) -> R:
        for r in self.resistors():
            if r.name.lower() == name.lower():
                return r
        raise LingoError(f"There is no resistor called {name}.")


class LingoError(ValueError):
    """A readable error that points at the problem."""


# ---------------------------------------------------------------------------
# 2. Parsing
# ---------------------------------------------------------------------------

_WORDS = [
    (r"\bparallel\b|\bpar\b|\bwith\b|\bpll\b|//", "||"),
    (r"\bplus\b|\bseries\b|\bthen\b", "+"),
    (r"\bk(?:ilo)?-?\s?ohms?\b", "kΩ"),
    (r"\bohms?\b|\u2126", "Ω"),
    (r"\bvolts?\b", "V"),
]

_TOKEN = re.compile(r"\s*(?:(\|\||\+|\(|\))|([A-Za-z][A-Za-z0-9]*)\s*=\s*([0-9]*\.?[0-9]+)\s*(kΩ|Ω)?"
                    r"|([0-9]*\.?[0-9]+)\s*(kΩ|Ω)?|([A-Za-z][A-Za-z0-9]*))")


def _normalise(s: str) -> str:
    for pat, rep in _WORDS:
        s = re.sub(pat, rep, s, flags=re.I)
    return s


def _tokenize(expr: str) -> List[Tuple[str, str, Optional[float], bool]]:
    """-> list of (kind, text, value, named).  kind: op | res"""
    expr = _normalise(expr)
    pos, out = 0, []
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m or m.end() == pos:
            rest = expr[pos:].strip()
            raise LingoError(f"I don't understand '{rest[:20]}' in the circuit line. Use numbers, +, || and parentheses, "
                             f"e.g. (4 + 2) || 6 + 3.")
        op, name, nval, nunit, val, unit, bare = m.groups()
        if op:
            out.append(("op", op, None, False))
        elif name:
            v = float(nval) * (1000 if nunit == "kΩ" else 1)
            out.append(("res", name, v, True))
        elif val:
            v = float(val) * (1000 if unit == "kΩ" else 1)
            out.append(("res", "", v, False))
        elif bare:
            raise LingoError(f"'{bare}' has no value. Write it as {bare}=6 (a 6 Ω resistor named {bare}).")
        pos = m.end()
    return out


class _Parser:
    """Recursive descent:  sum := prod ('+' prod)*   prod := atom ('||' atom)*   atom := res | '(' sum ')'"""

    def __init__(self, tokens):
        self.t, self.i, self.counter = tokens, 0, 0
        self.names: List[str] = []

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def sum(self) -> Node:
        items = [self.prod()]
        while self.peek() and self.peek()[1] == "+":
            self.take()
            items.append(self.prod())
        return items[0] if len(items) == 1 else Group("series", items)

    def prod(self) -> Node:
        items = [self.atom()]
        while self.peek() and self.peek()[1] == "||":
            self.take()
            items.append(self.atom())
        return items[0] if len(items) == 1 else Group("parallel", items)

    def atom(self) -> Node:
        tok = self.take()
        if tok is None:
            raise LingoError("The circuit line ends too early - a value is missing after the last + or ||.")
        kind, text, val, named = tok
        if kind == "res":
            self.counter += 1
            name = text if named else f"R{self.counter}"
            if name.lower() in [n.lower() for n in self.names]:
                raise LingoError(f"The name {name} is used twice. Give each resistor a different name.")
            self.names.append(name)
            if val <= 0:
                raise LingoError(f"{name} must be greater than 0 Ω.")
            return R(name, val)
        if text == "(":
            inner = self.sum()
            close = self.take()
            if close is None or close[1] != ")":
                raise LingoError("A '(' is never closed. Add the missing ')'.")
            return inner
        if text == ")":
            raise LingoError("There is a ')' without a matching '('.")
        raise LingoError(f"A value is missing before '{text}'.")


def parse_expression(expr: str) -> Node:
    tokens = _tokenize(expr)
    if not tokens:
        raise LingoError("The circuit line is empty. Example:  circuit: (4 + 2) || 6 + 3")
    p = _Parser(tokens)
    tree = p.sum()
    if p.peek() is not None:
        raise LingoError(f"Unexpected '{p.peek()[1]}' - check the parentheses.")
    return tree


_QUANT = [
    (r"equivalent|total\s+resistance|r_?eq", "req"),
    (r"total\s+current|battery\s+current|current\s+(from|drawn|supplied)", "total_current"),
    (r"current", "current"),
    (r"voltage|potential|volt", "voltage"),
    (r"power|dissipat", "power"),
]


def _parse_ask(chunk: str, problem: Problem) -> Ask:
    low = chunk.lower().strip()
    quantity = next((q for pat, q in _QUANT if re.search(pat, low)), None)
    if quantity is None:
        raise LingoError(f"In 'ask: {chunk}': say what to find - current through, voltage across, power in, "
                         "total current, or equivalent resistance.")
    if quantity in ("req", "total_current"):
        return Ask(quantity)
    m = re.search(r"\b([A-Za-z][A-Za-z0-9]*)\s*$", chunk.strip()) or re.search(r"\b(R[0-9]+)\b", chunk)
    if m and m.group(1).lower() not in ("resistor", "ohm", "ohms"):
        return Ask(quantity, problem.resistor(m.group(1)).name)
    m = re.search(r"([0-9]*\.?[0-9]+)\s*(k?)\s*(?:Ω|ohms?|\u2126)", chunk, flags=re.I)
    if m:
        ohms = float(m.group(1)) * (1000 if m.group(2).lower() == "k" else 1)
        hits = [r for r in problem.resistors() if abs(r.ohms - ohms) < 1e-9]
        if len(hits) == 1:
            return Ask(quantity, hits[0].name)
        if not hits:
            raise LingoError(f"In 'ask: {chunk}': there is no {m.group(1)} Ω resistor in the circuit.")
        raise LingoError(f"In 'ask: {chunk}': several resistors are {m.group(1)} Ω - use the name "
                         f"({', '.join(r.name for r in hits)}).")
    raise LingoError(f"In 'ask: {chunk}': say which resistor, e.g. 'current through R2' or 'the 2 Ω resistor'.")


def parse(text: str) -> Problem:
    """Parse the whole lingo block."""
    fields: Dict[str, List[str]] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^(source|battery|volts?|circuit|ask|find|hide|title|text|question)\b\s*[:=]?\s*(.*)$", line, re.I)
        if m:
            key = m.group(1).lower()
            key = {"battery": "source", "volt": "source", "volts": "source", "find": "ask", "question": "text"}.get(key, key)
            fields.setdefault(key, []).append(m.group(2).strip())
        elif re.fullmatch(r"[0-9]*\.?[0-9]+\s*(V|volts?)", line, re.I):
            fields.setdefault("source", []).append(line)
        elif "circuit" not in fields and re.search(r"\+|\|\||\bpar|\bplus\b|\(", line, re.I):
            fields.setdefault("circuit", []).append(line)
        else:
            raise LingoError(f"I don't know what to do with the line '{line}'. Lines start with source:, circuit:, "
                             "ask:, hide:, title: or text:.")
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
                prob.resistor(name).hidden = True
    for line in fields.get("ask", []):
        for chunk in re.split(r",|;|\band\b", line):
            if chunk.strip():
                prob.asks.append(_parse_ask(chunk, prob))
    return prob


def to_lingo(p: Problem) -> str:
    """Problem -> lingo text (used by the random generator and the AI helper)."""
    def expr(n: Node, top=True) -> str:
        if isinstance(n, R):
            v = f"{n.ohms:g}"
            return f"{n.name}={v}" if not re.fullmatch(r"R\d+", n.name) else v
        sep = " + " if n.kind == "series" else " || "
        parts = []
        for i in n.items:
            s = expr(i, False)
            if isinstance(i, Group) and (i.kind == "series" and n.kind == "parallel"):
                s = f"({s})"
            parts.append(s)
        return sep.join(parts)

    lines = [f"source: {p.volts:g} V", f"circuit: {expr(p.tree)}"]
    asks = []
    for a in p.asks:
        asks.append({"current": f"current through {a.target}", "voltage": f"voltage across {a.target}",
                     "power": f"power in {a.target}", "req": "equivalent resistance",
                     "total_current": "total current"}[a.quantity])
    if asks:
        lines.append("ask: " + ", ".join(asks))
    hidden = [r.name for r in p.resistors() if r.hidden]
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

W = 3.0            # width of one resistor (schemdraw unit)
LEAD = 0.75        # short wire on each side of a parallel stack
GAP = 0.9          # vertical space between stacked branches
UP, DOWN = 1.15, 0.35


def fmt_ohms(x: float) -> str:
    return f"{x / 1000:.2f} kΩ" if x >= 1000 else f"{x:.2f} Ω"


def _label(r: R) -> str:
    return f"{r.name} = ?" if r.hidden else f"${r.name[0]}_{{{r.name[1:]}}}$\n{fmt_ohms(r.ohms)}" \
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]+", r.name) else f"{r.name}\n{fmt_ohms(r.ohms)}"


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
        L.append(f"{n.name} = d.add(elm.Resistor().endpoints({_pt(x, y)}, {_pt(x + W, y)}){lab})")
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
         f"V = d.add(elm.BatteryCell().endpoints({_pt(0, H)}, {_pt(0, 0)}).label({f'{p.volts:.1f} V'!r}))",
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
# ---------------------------------------------------------------------------

@dataclass
class Result:
    req: float
    total_current: float
    per: Dict[str, Dict[str, float]]      # name -> {"current", "voltage", "power"}
    steps: List[str]                      # reduction steps
    back: List[str]                       # working back down the tree


def _name_of(n: Node, memo: Dict[int, str]) -> str:
    return n.name if isinstance(n, R) else memo[id(n)]


def solve(p: Problem) -> Result:
    steps: List[str] = []
    memo: Dict[int, str] = {}          # group id -> combined name, e.g. R12
    req_of: Dict[int, float] = {}

    def reduce(n: Node) -> float:
        if isinstance(n, R):
            return n.ohms
        vals = [reduce(i) for i in n.items]
        names = [_name_of(i, memo) for i in n.items]
        combo = "R" + "".join(re.sub(r"^R", "", x) for x in names)
        memo[id(n)] = combo
        if n.kind == "series":
            total = sum(vals)
            steps.append(f"{_join(names)} are in series: {combo} = {' + '.join(fmt_ohms(v) for v in vals)} "
                         f"= **{fmt_ohms(total)}**")
        else:
            total = 1 / sum(1 / v for v in vals)
            steps.append(f"{_join(names)} are in parallel: 1/{combo} = {' + '.join(f'1/{fmt_ohms(v)}' for v in vals)}"
                         f", so {combo} = **{fmt_ohms(total)}**")
        req_of[id(n)] = total
        return total

    req = reduce(p.tree)
    total_i = p.volts / req
    per: Dict[str, Dict[str, float]] = {}
    back: List[str] = [f"The battery sees {_name_of(p.tree, memo)} = {fmt_ohms(req)}, so the total current is "
                       f"I = V / R = {p.volts:.2f} V / {fmt_ohms(req)} = **{_fa(total_i)}**."]

    def down(n: Node, i: float, v: float) -> None:
        if isinstance(n, R):
            per[n.name] = {"current": i, "voltage": v, "power": i * v}
            return
        name = memo[id(n)]
        if n.kind == "series":
            back.append(f"{name} is a series group, so each part carries the same current {_fa(i)}; "
                        f"each voltage is I × R.")
            for it in n.items:
                r = it.ohms if isinstance(it, R) else req_of[id(it)]
                down(it, i, i * r)
        else:
            back.append(f"{name} is a parallel group, so each branch has the same voltage {_fv(v)}; "
                        f"each current is V / R.")
            for it in n.items:
                r = it.ohms if isinstance(it, R) else req_of[id(it)]
                down(it, v / r, v)

    down(p.tree, total_i, p.volts)
    return Result(req, total_i, per, steps, back)


def _join(names: List[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _fa(a: float) -> str:
    return f"{a * 1000:.2f} mA" if a < 0.1 else f"{a:.2f} A"


def _fv(v: float) -> str:
    return f"{v * 1000:.2f} mV" if v < 0.1 else f"{v:.2f} V"


def _fp(w: float) -> str:
    return f"{w * 1000:.2f} mW" if w < 0.1 else f"{w:.2f} W"


def answers(p: Problem, res: Result) -> List[str]:
    out = []
    for a in p.asks:
        if a.quantity == "req":
            out.append(f"Equivalent resistance = {fmt_ohms(res.req)}")
        elif a.quantity == "total_current":
            out.append(f"Total current from the battery = {_fa(res.total_current)}")
        else:
            r = res.per[a.target]
            out.append({"current": f"Current through {a.target} = {_fa(r['current'])}",
                        "voltage": f"Voltage across {a.target} = {_fv(r['voltage'])}",
                        "power": f"Power dissipated in {a.target} = {_fp(r['power'])}"}[a.quantity])
    return out


def question_text(p: Problem) -> str:
    """Worksheet wording, generated from the asks (unless the teacher wrote their own)."""
    if p.text:
        return p.text
    if not p.asks:
        return "For the circuit shown, find the current through and the voltage across every resistor."
    by_target: Dict[Optional[str], List[str]] = {}
    for a in p.asks:
        by_target.setdefault(a.target, []).append(a.quantity)
    parts = []
    for target, qs in by_target.items():
        if target is None:
            for q in qs:
                parts.append("the equivalent resistance" if q == "req"
                             else "the total current supplied by the battery")
            continue
        r = p.resistor(target)
        who = f"{target}" if r.hidden else f"the {fmt_ohms(r.ohms)} resistor ({target})"
        phr = {"current": "the current through", "voltage": "the voltage across", "power": "the power dissipated in"}
        parts.append(_join([phr[q] for q in qs]) + " " + who)
    tail = "of the circuit shown" if all(a.target is None for a in p.asks) else "in the circuit shown"
    return f"Determine {_join(parts)} {tail}."


def solution_markdown(p: Problem, res: Result) -> str:
    L = ["**Reduce the circuit**", ""]
    L += [f"{i}. {s}" for i, s in enumerate(res.steps, 1)]
    L += ["", "**Work back to the individual resistors**", ""]
    L += [f"{i}. {s}" for i, s in enumerate(res.back, 1)]
    L += ["", "| Resistor | Current | Voltage | Power |", "|---|---|---|---|"]
    for r in p.resistors():
        x = res.per[r.name]
        L.append(f"| {r.name} ({fmt_ohms(r.ohms)}) | {_fa(x['current'])} | {_fv(x['voltage'])} | {_fp(x['power'])} |")
    L += [f"| Battery | {_fa(res.total_current)} | {p.volts:.2f} V | {_fp(res.total_current * p.volts)} (delivered) |"]
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
}
OHMS = [1, 2, 3, 4, 5, 6, 8, 10, 12]
VOLTS = [6, 9, 12, 24]


def random_lingo(seed: Optional[int] = None, shape: Optional[str] = None) -> str:
    rng = random.Random(seed)
    shape = shape or rng.choice(list(SHAPES))
    expr = SHAPES[shape].format(**{k: rng.choice(OHMS) for k in "abcde"})
    prob = Problem(rng.choice(VOLTS), parse_expression(expr))
    names = [r.name for r in prob.resistors()]
    kind = rng.choice(["one", "one", "two", "req", "total"])
    if kind == "req":
        prob.asks = [Ask("req")]
    elif kind == "total":
        prob.asks = [Ask("total_current")]
    elif kind == "one":
        prob.asks = [Ask(rng.choice(["current", "voltage", "power"]), rng.choice(names))]
    else:
        t = rng.choice(names)
        prob.asks = [Ask("current", t), Ask("voltage", t)]
    return to_lingo(prob)
