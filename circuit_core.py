"""
circuit_core.py - the engine behind Circuit Problem Studio.

Everything here is plain Python (no Streamlit, no AI), so it can be tested and
reused on its own.  The flow is:

    CircuitSpec (JSON)  --build_code()-->  Schemdraw code  --render_worker-->  SVG/PNG/PDF
           |
           +--solve()-->  answer key          +--to_netlist()-->  SPICE-style netlist

The JSON spec is the single source of truth: the drawing, the answer key and
the netlist are all derived from it, so they cannot drift apart.
"""
from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field, ValidationError, model_validator

# ---------------------------------------------------------------------------
# 1. The spec
# ---------------------------------------------------------------------------

ComponentType = Literal[
    "resistor", "bulb", "battery", "vsource", "isource", "capacitor",
    "inductor", "switch", "ammeter", "voltmeter", "diode", "led", "wire",
]

BASE_UNIT = {
    "resistor": "Ω", "bulb": "Ω", "battery": "V", "vsource": "V",
    "isource": "A", "capacitor": "F", "inductor": "H",
}
PREFIX = {
    "": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "m": 1e-3,
    "u": 1e-6, "μ": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12,
}
SOURCE_TYPES = {"battery", "vsource", "isource"}
NEEDS_VALUE = set(BASE_UNIT)          # types whose value matters to the solver
DRAW_ONLY = {"diode", "led"}          # drawn, but the linear solver cannot handle them


def _normalise_unit(unit: str) -> str:
    u = unit.strip().replace("\u2126", "Ω")
    u = re.sub(r"(?i)ohms?$", "Ω", u)
    return u


class Component(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    type: ComponentType
    value: Optional[float] = None          # number as the teacher wrote it, e.g. 4.7
    unit: Optional[str] = None             # unit as the teacher wrote it, e.g. "kΩ"
    label: Optional[str] = None            # overrides the automatic name label
    hide_value: bool = False               # show "= ?" instead of the value (the unknown)
    flip: bool = False                     # reverse polarity / direction
    closed: bool = True                    # switches only
    between: Optional[List[str]] = None    # only for topology "custom": [node_a, node_b]

    @model_validator(mode="after")
    def _check(self) -> "Component":
        if self.unit is not None:
            self.unit = _normalise_unit(self.unit)
            base = BASE_UNIT.get(self.type)
            if base is None:
                raise ValueError(f"{self.id}: a {self.type} does not take a unit")
            if not self.unit.endswith(base):
                raise ValueError(f"{self.id}: unit '{self.unit}' should end in '{base}' for a {self.type}")
            if self.unit[: -len(base)] not in PREFIX:
                raise ValueError(f"{self.id}: unknown unit prefix in '{self.unit}'")
        if self.between is not None and len(self.between) != 2:
            raise ValueError(f"{self.id}: 'between' must list exactly two node names")
        return self

    # value in base SI units (ohms, volts, amps, farads, henries)
    def si(self) -> Optional[float]:
        if self.value is None:
            return None
        base = BASE_UNIT.get(self.type, "")
        unit = self.unit or base
        return self.value * PREFIX[unit[: len(unit) - len(base)]]

    def value_text(self) -> str:
        if self.value is None:
            return ""
        v = int(self.value) if float(self.value).is_integer() else self.value
        return f"{v:g} {self.unit or BASE_UNIT.get(self.type, '')}".strip()


class Target(BaseModel):
    """What the question asks for, so the app can highlight the right number."""
    component: Optional[str] = None
    quantity: Literal["current", "voltage", "power", "charge", "energy",
                      "equivalent_resistance", "time_constant", "gain", "vout"]


class CircuitSpec(BaseModel):
    title: str = ""
    topology: Literal["ladder", "bridge", "opamp_inverting", "opamp_noninverting", "custom"]
    components: List[Component]
    layout: Dict[str, Any] = Field(default_factory=dict)
    problem_text: str = ""                 # wording for students
    ask: str = ""                          # short version of what to find
    targets: List[Target] = Field(default_factory=list)
    show_values: bool = True
    style: Literal["US", "IEC"] = "US"
    current_arrows: List[str] = Field(default_factory=list)   # ids that get a current arrow
    node_labels: Dict[str, str] = Field(default_factory=dict) # ladder only, e.g. {"T1": "a"}
    custom_code: Optional[str] = None      # only for topology "custom"

    # -- helpers -----------------------------------------------------------
    def comp(self, cid: str) -> Component:
        for c in self.components:
            if c.id == cid:
                return c
        raise KeyError(cid)

    @model_validator(mode="after")
    def _check(self) -> "CircuitSpec":
        ids = [c.id for c in self.components]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate component ids: {sorted(dupes)}")
        used: List[str] = []
        lay = self.layout

        if self.topology == "ladder":
            cols = lay.get("columns")
            if not isinstance(cols, list) or len(cols) < 2:
                raise ValueError("ladder layout needs 'columns': a list of at least 2 lists of component ids")
            n = len(cols)
            top = lay.get("top", [[] for _ in range(n - 1)])
            bottom = lay.get("bottom", [[] for _ in range(n - 1)])
            if len(top) != n - 1 or len(bottom) != n - 1:
                raise ValueError(f"with {n} columns, 'top' and 'bottom' must each have {n - 1} lists")
            for group in (cols, top, bottom):
                for chain in group:
                    if not isinstance(chain, list):
                        raise ValueError("every column / top / bottom entry must be a list of ids")
                    used += chain
            self.layout = {"columns": cols, "top": top, "bottom": bottom}
            for key in self.node_labels:
                if not re.fullmatch(r"[TB]\d+", key) or int(key[1:]) >= n:
                    raise ValueError(f"node_labels key '{key}' must look like T0..T{n-1} or B0..B{n-1}")
        elif self.topology == "bridge":
            need = ["source", "top_left", "top_right", "bottom_left", "bottom_right"]
            for k in need:
                if not lay.get(k):
                    raise ValueError(f"bridge layout needs '{k}'")
            used = [lay[k] for k in need] + ([lay["detector"]] if lay.get("detector") else [])
        elif self.topology in ("opamp_inverting", "opamp_noninverting"):
            need = ["vin", "r_in", "r_f"] if self.topology == "opamp_inverting" else ["vin", "r_g", "r_f"]
            for k in need:
                if not lay.get(k):
                    raise ValueError(f"{self.topology} layout needs '{k}'")
            used = [lay[k] for k in need]
        elif self.topology == "custom":
            if not self.custom_code:
                raise ValueError("topology 'custom' needs 'custom_code' (Schemdraw code)")
            used = ids

        for u in used:
            if u not in ids:
                raise ValueError(f"layout mentions '{u}' but there is no component with that id")
        multi = {u for u in used if used.count(u) > 1}
        if multi:
            raise ValueError(f"components placed more than once: {sorted(multi)}")
        unused = [i for i in ids if i not in used]
        if unused:
            raise ValueError(f"components not placed anywhere in the layout: {unused}")
        for a in self.current_arrows:
            if a not in ids:
                raise ValueError(f"current_arrows mentions unknown component '{a}'")
        for t in self.targets:
            if t.component and t.component not in ids:
                raise ValueError(f"targets mentions unknown component '{t.component}'")
        return self


def parse_spec(data: Any) -> CircuitSpec:
    """Accept a dict or JSON string; raise ValueError with a readable message."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"That is not valid JSON: {e}") from e
    try:
        return CircuitSpec.model_validate(data)
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            msgs.append(f"{loc}: {err['msg']}" if loc else err["msg"])
        raise ValueError("; ".join(msgs)) from e


def spec_to_json(spec: CircuitSpec) -> str:
    return json.dumps(spec.model_dump(exclude_none=True, exclude_defaults=False), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 2. Spec -> Schemdraw code (templates)
# ---------------------------------------------------------------------------

U = 3.0  # length of one element in drawing units

ELEMENT_CLASS = {
    "resistor": "Resistor", "bulb": "Lamp", "battery": "BatteryCell", "vsource": "SourceV",
    "isource": "SourceI", "capacitor": "Capacitor", "inductor": "Inductor2", "switch": "Switch",
    "ammeter": "MeterA", "voltmeter": "MeterV", "diode": "Diode", "led": "LED", "wire": "Line",
}


def pretty_name(cid: str) -> str:
    m = re.fullmatch(r"([A-Za-z])([A-Za-z0-9]+)", cid)
    if not m:
        return cid
    return f"${m.group(1)}_{{{m.group(2)}}}$"


def label_text(c: Component, show_values: bool) -> str:
    name = c.label if c.label is not None else pretty_name(c.id)
    if c.type == "wire":
        return ""
    if c.type in ("ammeter", "voltmeter") and c.label is None and len(c.id) == 1:
        return ""                     # the symbol already says A or V
    if c.type == "switch":
        return name
    if c.hide_value:
        return f"{name} = ?"
    if show_values and c.value is not None:
        return f"{name}\n{c.value_text()}"
    return name


def _pt(p: Tuple[float, float]) -> str:
    return f"({p[0]:g}, {p[1]:g})"


def _element_line(c: Component, start, end, spec: CircuitSpec, loc: Optional[str] = None,
                  plus_at_start: Optional[bool] = None) -> str:
    """One line of Schemdraw code placing component c between two points.

    start/end follow the reference direction (top->bottom or left->right).
    plus_at_start says where the + terminal of a source goes.
    """
    cls = ELEMENT_CLASS[c.type]
    args = ""
    a, b = start, end
    if c.type == "switch":
        args = "action='close'" if c.closed else "action='open'"
    if c.type in SOURCE_TYPES:
        # Schemdraw: BatteryCell has its long (+) plate at the START;
        # SourceV has + at the END; SourceI's arrow points to the END.
        plus_start = bool(plus_at_start)
        if c.type == "battery":
            a, b = (start, end) if plus_start else (end, start)
        else:
            a, b = (end, start) if plus_start else (start, end)
    elif c.type in ("diode", "led") and c.flip:
        a, b = end, start
    code = f"elm.{cls}({args}).endpoints({_pt(a)}, {_pt(b)})"
    text = label_text(c, spec.show_values)
    if text:
        loc_arg = f", loc='{loc}'" if loc else ""
        code += f".label({text!r}{loc_arg})"
    return f"{c.id} = d.add({code})"


def _header(spec: CircuitSpec) -> List[str]:
    lines = [
        "import schemdraw",
        "import schemdraw.elements as elm",
        "",
    ]
    if spec.style == "IEC":
        lines.append("elm.style(elm.STYLE_IEC)      # box-style resistors")
    else:
        lines.append("elm.style(elm.STYLE_IEEE)     # zig-zag resistors")
    lines += [
        "d = schemdraw.Drawing(show=False)",
        f"d.config(unit={U:g}, fontsize=13)",
        "",
    ]
    return lines


def _arrows(spec: CircuitSpec) -> List[str]:
    out = []
    for cid in spec.current_arrows:
        out.append(f"d += elm.CurrentLabelInline(direction='in').at({cid}).label('$I_{{{cid}}}$')")
    if out:
        out = ["", "# current arrows"] + out
    return out


def ladder_geometry(spec: CircuitSpec):
    cols, top, bottom = spec.layout["columns"], spec.layout["top"], spec.layout["bottom"]
    n = len(cols)
    xs = [0.0]
    for i in range(n - 1):
        xs.append(xs[-1] + U * max(1, len(top[i]), len(bottom[i])))
    height = U * max(1, max(len(c) for c in cols))
    return cols, top, bottom, xs, height


def gen_ladder(spec: CircuitSpec) -> str:
    cols, top, bottom, xs, H = ladder_geometry(spec)
    n = len(cols)
    L = _header(spec)

    def chain(ids, p0, p1, kind, loc=None):
        """Place a chain of components evenly between p0 and p1."""
        if not ids:
            L.append(f"d += elm.Line().endpoints({_pt(p0)}, {_pt(p1)})")
            return
        k = len(ids)
        for j, cid in enumerate(ids):
            a = (p0[0] + (p1[0] - p0[0]) * j / k, p0[1] + (p1[1] - p0[1]) * j / k)
            b = (p0[0] + (p1[0] - p0[0]) * (j + 1) / k, p0[1] + (p1[1] - p0[1]) * (j + 1) / k)
            c = spec.comp(cid)
            # rule: "+ is up / to the right" unless the component is flipped.
            # columns start at the top, rails start at the left.
            plus_at_start = (not c.flip) if kind == "col" else c.flip
            L.append(_element_line(c, a, b, spec, loc=loc, plus_at_start=plus_at_start))

    L.append("# vertical branches (listed left to right; each drawn top -> bottom)")
    for i, ids in enumerate(cols):
        loc = "bottom" if (i == n - 1 and n > 1) else None   # right-most labels go outside
        chain(ids, (xs[i], H), (xs[i], 0.0), "col", loc)
    L.append("")
    L.append("# top rail (left -> right)")
    for i, ids in enumerate(top):
        chain(ids, (xs[i], H), (xs[i + 1], H), "rail")
    L.append("")
    L.append("# bottom rail (left -> right)")
    for i, ids in enumerate(bottom):
        chain(ids, (xs[i], 0.0), (xs[i + 1], 0.0), "rail", loc="bottom")

    dots = []
    for i in range(1, n - 1):
        dots.append(f"d += elm.Dot().at({_pt((xs[i], H))})")
        dots.append(f"d += elm.Dot().at({_pt((xs[i], 0.0))})")
    if dots:
        L += ["", "# junction dots"] + dots
    if spec.node_labels:
        L += ["", "# node labels"]
        for key, text in spec.node_labels.items():
            i = int(key[1:])
            y, loc = (H, "top") if key[0] == "T" else (0.0, "bottom")
            L.append(f"d += elm.Dot(radius=0.09).at({_pt((xs[i], y))}).label({text!r}, loc='{loc}')")
    L += _arrows(spec)
    return "\n".join(L) + "\n"


BRIDGE_PTS = {"a": (3.0, 6.0), "b": (0.0, 3.0), "c": (6.0, 3.0), "d": (3.0, 0.0)}


def gen_bridge(spec: CircuitSpec) -> str:
    lay, P = spec.layout, BRIDGE_PTS
    L = _header(spec)
    src = spec.comp(lay["source"])
    L.append("# source on the left, feeding the top (a) and bottom (d) corners")
    L.append(_element_line(src, (-3.0, 6.0), (-3.0, 0.0), spec, plus_at_start=not src.flip))
    L.append(f"d += elm.Line().endpoints((-3, 6), {_pt(P['a'])})")
    L.append(f"d += elm.Line().endpoints((-3, 0), {_pt(P['d'])})")
    L.append("")
    L.append("# the four arms of the diamond")
    L.append(_element_line(spec.comp(lay["top_left"]), P["a"], P["b"], spec))
    L.append(_element_line(spec.comp(lay["top_right"]), P["a"], P["c"], spec, loc="top"))
    L.append(_element_line(spec.comp(lay["bottom_left"]), P["b"], P["d"], spec, loc="bottom"))
    L.append(_element_line(spec.comp(lay["bottom_right"]), P["c"], P["d"], spec, loc="bottom"))
    if lay.get("detector"):
        L.append("")
        L.append("# detector between the side corners b and c")
        L.append(_element_line(spec.comp(lay["detector"]), P["b"], P["c"], spec))
    L.append("")
    L.append("# corner labels")
    for name, loc in (("a", "top"), ("b", "left"), ("c", "right"), ("d", "bottom")):
        L.append(f"d += elm.Dot().at({_pt(P[name])}).label('{name}', loc='{loc}')")
    L += _arrows(spec)
    return "\n".join(L) + "\n"


def gen_opamp(spec: CircuitSpec) -> str:
    lay = spec.layout
    L = _header(spec)
    vin, rf = spec.comp(lay["vin"]), spec.comp(lay["r_f"])
    sv = spec.show_values
    if spec.topology == "opamp_inverting":
        rin = spec.comp(lay["r_in"])
        L += [
            "op = d.add(elm.Opamp(leads=True))",
            "d += elm.Line().down(d.unit/3).at(op.in2)",
            "d += elm.Ground()",
            f"{rin.id} = d.add(elm.Resistor().at(op.in1).left().idot().label({label_text(rin, sv)!r}))",
            f"{vin.id} = d.add(elm.SourceV().down().reverse().label({label_text(vin, sv)!r}))",
            "d += elm.Ground()",
            "d += elm.Line().up(d.unit/2 + 0.5).at(op.in1)",
            f"{rf.id} = d.add(elm.Resistor().tox(op.out).label({label_text(rf, sv)!r}))",
            "d += elm.Line().toy(op.out).dot()",
            "d += elm.Line().right(d.unit/3).at(op.out).label('$V_{out}$', loc='right')",
        ]
    else:
        rg = spec.comp(lay["r_g"])
        L += [
            "op = d.add(elm.Opamp(leads=True))",
            "d += elm.Line().left(d.unit/2).at(op.in2)",
            f"{vin.id} = d.add(elm.SourceV().down().reverse().label({label_text(vin, sv)!r}))",
            "d += elm.Ground()",
            "d += elm.Line().up(d.unit/2 + 0.5).at(op.in1).dot()",
            "d.push()",
            f"{rg.id} = d.add(elm.Resistor().left().label({label_text(rg, sv)!r}))",
            "d += elm.Line().down(d.unit/2)",
            "d += elm.Ground()",
            "d.pop()",
            f"{rf.id} = d.add(elm.Resistor().tox(op.out).label({label_text(rf, sv)!r}))",
            "d += elm.Line().toy(op.out).dot()",
            "d += elm.Line().right(d.unit/3).at(op.out).label('$V_{out}$', loc='right')",
        ]
    return "\n".join(L) + "\n"


def build_code(spec: CircuitSpec) -> str:
    """Spec -> Schemdraw source code."""
    if spec.topology == "ladder":
        return gen_ladder(spec)
    if spec.topology == "bridge":
        return gen_bridge(spec)
    if spec.topology in ("opamp_inverting", "opamp_noninverting"):
        return gen_opamp(spec)
    return spec.custom_code or ""


# ---------------------------------------------------------------------------
# 3. Safety check for code that did not come from our own templates
# ---------------------------------------------------------------------------

ALLOWED_IMPORTS = ("schemdraw", "math")
BANNED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "breakpoint", "exit", "quit", "help", "memoryview",
}


def check_code_safety(code: str) -> List[str]:
    """Return a list of problems (empty list = looks fine).

    This is a guard rail, not a security boundary: it stops accidents and the
    obvious tricks.  The code additionally runs in a separate process with a
    time limit and a reduced set of built-ins.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Syntax error on line {e.lineno}: {e.msg}"]
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"line {node.lineno}: import of '{a.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                problems.append(f"line {node.lineno}: import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            problems.append(f"line {node.lineno}: '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"line {node.lineno}: access to '{node.attr}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr in ("save", "draw"):
            problems.append(f"line {node.lineno}: don't call .{node.attr}(); the app saves the drawing itself")
    return problems


# ---------------------------------------------------------------------------
# 4. Spec -> electrical network -> answer key
# ---------------------------------------------------------------------------

@dataclass
class Elem:
    comp: Component
    n1: str                 # reference direction is n1 -> n2
    n2: str
    plus: Optional[str]     # + terminal (sources only)
    dir_pos: str            # words used when current flows n1 -> n2
    dir_neg: str


class Unsolvable(Exception):
    pass


class _UF:
    def __init__(self):
        self.p: Dict[str, str] = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def build_network(spec: CircuitSpec) -> Tuple[List[Elem], str]:
    """Turn the layout into a list of two-terminal elements plus a ground node."""
    elems: List[Elem] = []

    if spec.topology == "ladder":
        cols, top, bottom = spec.layout["columns"], spec.layout["top"], spec.layout["bottom"]
        uf, raw = _UF(), []

        def chain(ids, a, b, tag, kind):
            if not ids:
                uf.union(a, b)
                return
            nodes = [a] + [f"{tag}_{j}" for j in range(1, len(ids))] + [b]
            for j, cid in enumerate(ids):
                raw.append((cid, nodes[j], nodes[j + 1], kind))

        for i, ids in enumerate(cols):
            chain(ids, f"T{i}", f"B{i}", f"c{i}", "col")
        for i, ids in enumerate(top):
            chain(ids, f"T{i}", f"T{i+1}", f"t{i}", "rail")
        for i, ids in enumerate(bottom):
            chain(ids, f"B{i}", f"B{i+1}", f"b{i}", "rail")
        for cid, a, b, kind in raw:
            c = spec.comp(cid)
            a, b = uf.find(a), uf.find(b)
            if kind == "col":
                plus = (b if c.flip else a)
                words = ("downward", "upward")
            else:
                plus = (a if c.flip else b)
                words = ("to the right", "to the left")
            elems.append(Elem(c, a, b, plus if c.type in SOURCE_TYPES else None, *words))
        return elems, uf.find("B0")

    if spec.topology == "bridge":
        lay = spec.layout
        arms = [("top_left", "a", "b"), ("top_right", "a", "c"), ("bottom_left", "b", "d"),
                ("bottom_right", "c", "d"), ("detector", "b", "c")]
        src = spec.comp(lay["source"])
        elems.append(Elem(src, "a", "d", "d" if src.flip else "a", "a → d", "d → a"))
        for key, a, b in arms:
            if lay.get(key):
                elems.append(Elem(spec.comp(lay[key]), a, b, None, f"{a} → {b}", f"{b} → {a}"))
        return elems, "d"

    if spec.topology == "custom":
        for c in spec.components:
            if not c.between:
                raise Unsolvable(
                    f"No answer key: component {c.id} has no 'between' nodes. For custom drawings the "
                    "spec must say which two nodes each component connects.")
            a, b = c.between
            elems.append(Elem(c, a, b, a if c.type in SOURCE_TYPES else None, f"{a} → {b}", f"{b} → {a}"))
        nodes = [n for e in elems for n in (e.n1, e.n2)]
        ground = next((n for n in nodes if n.lower() in ("0", "gnd", "ground")), None)
        if ground is None:
            src = next((e for e in elems if e.comp.type in SOURCE_TYPES), None)
            ground = (src.n2 if src else nodes[0])
        return elems, ground

    raise Unsolvable("op-amp templates are solved by formula, not by the network solver")


def _mna(prims: List[tuple], ground: str) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Modified nodal analysis.

    prims: ('R', a, b, ohms) | ('V', plus, minus, volts, key) | ('I', plus, minus, amps)
    Returns node voltages and, for each 'V', the current flowing plus -> minus INSIDE it.
    """
    nodes = sorted({n for p in prims for n in (p[1], p[2])} | {ground})
    nodes.remove(ground)
    idx = {n: i for i, n in enumerate(nodes)}
    vs = [p for p in prims if p[0] == "V"]
    N, M = len(nodes), len(vs)
    A = np.zeros((N + M, N + M))
    z = np.zeros(N + M)
    for p in prims:
        if p[0] == "R":
            g = 1.0 / p[3]
            for x, y, s in ((p[1], p[1], g), (p[2], p[2], g), (p[1], p[2], -g), (p[2], p[1], -g)):
                if x in idx and y in idx:
                    A[idx[x], idx[y]] += s
        elif p[0] == "I":
            if p[1] in idx:
                z[idx[p[1]]] += p[3]
            if p[2] in idx:
                z[idx[p[2]]] -= p[3]
    for k, p in enumerate(vs):
        row = N + k
        if p[1] in idx:
            A[row, idx[p[1]]] = 1.0
            A[idx[p[1]], row] = 1.0
        if p[2] in idx:
            A[row, idx[p[2]]] = -1.0
            A[idx[p[2]], row] = -1.0
        z[row] = p[3]
    def _try(matrix):
        if matrix.size and np.linalg.cond(matrix) > 1e13:
            raise np.linalg.LinAlgError
        return np.linalg.solve(matrix, z) if matrix.size else np.zeros(0)

    try:
        x = _try(A)
    except np.linalg.LinAlgError:
        # A part of the circuit may simply be isolated (e.g. behind an open switch).
        # A tiny leak to ground fixes that case without changing any real answer.
        leaky = A.copy()
        for i in range(N):
            leaky[i, i] += 1e-12
        try:
            x = _try(leaky)
        except np.linalg.LinAlgError:
            raise Unsolvable(
                "The circuit has no unique solution. Usual causes: a wire or closed switch directly "
                "across a battery, two ideal sources fighting each other, or ideal wires in parallel.")
        x[np.abs(x) < 1e-9] = 0.0
    if not np.all(np.isfinite(x)) or np.max(np.abs(x)) > 1e9:
        raise Unsolvable("The numbers blow up - a source is probably short-circuited or a part is floating.")
    volts = {n: float(x[idx[n]]) for n in nodes}
    volts[ground] = 0.0
    currents = {p[4]: float(x[N + k]) for k, p in enumerate(vs)}
    return volts, currents


def _prims(elems: List[Elem], mode: str, zero_sources=False, skip: Optional[str] = None) -> List[tuple]:
    out = []
    for e in elems:
        c, t = e.comp, e.comp.type
        if c.id == skip:
            continue
        if t in DRAW_ONLY:
            raise Unsolvable(f"{c.id} is a {t}. Diodes are drawn, but the answer key only handles linear parts.")
        if t in NEEDS_VALUE and c.si() is None and not (t in ("capacitor", "inductor")):
            raise Unsolvable(f"{c.id} has no numeric value, so numbers cannot be computed.")
        short = (t in ("ammeter", "wire") or (t == "switch" and c.closed)
                 or (t == "inductor" and mode == "steady") or (t == "capacitor" and mode == "initial"))
        is_open = ((t == "switch" and not c.closed) or t == "voltmeter"
                   or (t == "capacitor" and mode == "steady") or (t == "inductor" and mode == "initial"))
        if t in ("resistor", "bulb"):
            if c.si() <= 0:
                raise Unsolvable(f"{c.id} must have a resistance greater than zero.")
            out.append(("R", e.n1, e.n2, c.si()))
        elif t in ("battery", "vsource"):
            minus = e.n2 if e.plus == e.n1 else e.n1
            out.append(("V", e.plus, minus, 0.0 if zero_sources else c.si(), c.id))
        elif t == "isource":
            minus = e.n2 if e.plus == e.n1 else e.n1
            if not zero_sources:
                out.append(("I", e.plus, minus, c.si()))
        elif short:
            out.append(("V", e.n1, e.n2, 0.0, c.id))
        elif is_open:
            pass
    return out


def _analyse(elems: List[Elem], ground: str, mode: str) -> Dict[str, Any]:
    volts, jv = _mna(_prims(elems, mode), ground)
    rows = []
    for e in elems:
        c, t = e.comp, e.comp.type
        v = volts.get(e.n1, 0.0) - volts.get(e.n2, 0.0)
        if t in ("resistor", "bulb"):
            i = v / c.si()
        elif t == "isource":
            i = c.si() if e.plus == e.n2 else -c.si()
        elif c.id in jv:
            # jv is the current plus -> minus inside the element
            i = jv[c.id] if (e.plus in (None, e.n1)) else -jv[c.id]
        else:
            i = 0.0
        v = 0.0 if abs(v) < 1e-9 else v
        i = 0.0 if abs(i) < 1e-12 else i
        if t in SOURCE_TYPES:
            v_src = volts.get(e.plus, 0.0) - volts.get(e.n2 if e.plus == e.n1 else e.n1, 0.0)
            i_out = -i if e.plus == e.n1 else i          # current leaving the + terminal
            power = v_src * i_out                        # delivered
        else:
            power = v * i                                # absorbed
        rows.append({
            "id": c.id, "type": t, "voltage": abs(v), "current": abs(i), "power": power,
            "signed_current": i, "signed_voltage": v,
            "direction": ("-" if i == 0 else (e.dir_pos if i > 0 else e.dir_neg)),
        })
    return {"rows": rows, "node_voltages": volts}


def solve(spec: CircuitSpec) -> Dict[str, Any]:
    """Answer key as a dictionary.  Raises Unsolvable with a teacher-readable reason."""
    if spec.topology in ("opamp_inverting", "opamp_noninverting"):
        lay = spec.layout
        vin, rf = spec.comp(lay["vin"]), spec.comp(lay["r_f"])
        r1 = spec.comp(lay["r_in"] if spec.topology == "opamp_inverting" else lay["r_g"])
        if rf.si() is None or r1.si() is None:
            raise Unsolvable("Both resistors need numeric values.")
        gain = -rf.si() / r1.si() if spec.topology == "opamp_inverting" else 1 + rf.si() / r1.si()
        formula = "−R_f / R_in" if spec.topology == "opamp_inverting" else "1 + R_f / R_g"
        return {"kind": "opamp", "gain": gain, "formula": formula,
                "vout": None if vin.si() is None else gain * vin.si()}

    elems, ground = build_network(spec)
    types = [e.comp.type for e in elems]
    out: Dict[str, Any] = {"kind": "network", "steady": _analyse(elems, ground, "steady")}
    reactive = [e for e in elems if e.comp.type in ("capacitor", "inductor")]
    if reactive:
        try:
            out["initial"] = _analyse(elems, ground, "initial")
        except Unsolvable:
            pass
        for e in reactive:                     # stored charge / energy in the steady state
            row = next(r for r in out["steady"]["rows"] if r["id"] == e.comp.id)
            if e.comp.si() is not None:
                if e.comp.type == "capacitor":
                    row["charge"] = e.comp.si() * row["voltage"]
                    row["energy"] = 0.5 * e.comp.si() * row["voltage"] ** 2
                else:
                    row["energy"] = 0.5 * e.comp.si() * row["current"] ** 2
    # equivalent resistance seen by a single source
    sources = [e for e in elems if e.comp.type in ("battery", "vsource")]
    if len(sources) == 1 and "isource" not in types:
        row = next(r for r in out["steady"]["rows"] if r["id"] == sources[0].comp.id)
        if row["current"] > 0:
            out["req"] = sources[0].comp.si() / row["current"]
    # time constant for a single capacitor or inductor
    if len(reactive) == 1 and reactive[0].comp.si() is not None:
        e = reactive[0]
        try:
            prims = _prims(elems, "steady", zero_sources=True, skip=e.comp.id) + [("I", e.n1, e.n2, 1.0)]
            v, _ = _mna(prims, ground)
            rth = abs(v.get(e.n1, 0.0) - v.get(e.n2, 0.0))
            if 0 < rth < 1e9:
                out["rth"] = rth
                out["tau"] = rth * e.comp.si() if e.comp.type == "capacitor" else e.comp.si() / rth
        except Unsolvable:
            pass
    return out


# ---------------------------------------------------------------------------
# 5. Formatting the answer key
# ---------------------------------------------------------------------------

def eng(x: Optional[float], unit: str, sig: int = 3) -> str:
    """1.333e-3, 'A' -> '1.33 mA'."""
    if x is None:
        return "-"
    if x == 0 or abs(x) < 1e-15:
        return f"0 {unit}"
    x = float(f"{x:.{sig - 1}e}")                 # round to sig figs first (9999.9 -> 10000)
    exp = int(math.floor(math.log10(abs(x)) / 3.0) * 3)
    exp = max(-12, min(9, exp))
    prefix = {-12: "p", -9: "n", -6: "μ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}[exp]
    m = x / 10 ** exp
    digits = max(0, sig - 1 - int(math.floor(math.log10(abs(m)))))
    s = f"{m:.{digits}f}"
    if abs(float(s)) >= 1000:                     # rounding pushed us over, e.g. 999.6 -> 1000
        return eng(float(s) * 10 ** exp, unit, sig)
    return f"{s} {prefix}{unit}"


def _table(rows, sig) -> str:
    lines = ["| Part | Voltage across | Current through | Direction of current | Power |",
             "|---|---|---|---|---|"]
    for r in rows:
        if r["type"] == "wire":
            continue
        tag = ""
        if r["type"] in SOURCE_TYPES and abs(r["power"]) > 0:
            tag = " (delivers)" if r["power"] > 0 else " (absorbs)"
        lines.append(f"| {r['id']} | {eng(r['voltage'], 'V', sig)} | {eng(r['current'], 'A', sig)} | "
                     f"{r['direction']} | {eng(abs(r['power']), 'W', sig)}{tag} |")
    return "\n".join(lines)


def target_answers(spec: CircuitSpec, result: Dict[str, Any], sig: int = 3) -> List[str]:
    out = []
    for t in spec.targets:
        if result["kind"] == "opamp":
            if t.quantity == "gain":
                out.append(f"Gain = {result['gain']:.{sig}g}")
            elif t.quantity == "vout" and result.get("vout") is not None:
                out.append(f"V_out = {eng(result['vout'], 'V', sig)}")
            continue
        if t.quantity == "equivalent_resistance" and "req" in result:
            out.append(f"Equivalent resistance = {eng(result['req'], 'Ω', sig)}")
        elif t.quantity == "time_constant" and "tau" in result:
            out.append(f"Time constant τ = {eng(result['tau'], 's', sig)}")
        elif t.component:
            row = next((r for r in result["steady"]["rows"] if r["id"] == t.component), None)
            if not row:
                continue
            if t.quantity == "current":
                out.append(f"Current through {t.component} = {eng(row['current'], 'A', sig)} ({row['direction']})")
            elif t.quantity == "voltage":
                out.append(f"Voltage across {t.component} = {eng(row['voltage'], 'V', sig)}")
            elif t.quantity == "power":
                out.append(f"Power in {t.component} = {eng(abs(row['power']), 'W', sig)}")
            elif t.quantity == "charge" and "charge" in row:
                out.append(f"Charge on {t.component} = {eng(row['charge'], 'C', sig)}")
            elif t.quantity == "energy" and "energy" in row:
                out.append(f"Energy stored in {t.component} = {eng(row['energy'], 'J', sig)}")
    return out


def answer_key_markdown(spec: CircuitSpec, result: Dict[str, Any], sig: int = 3) -> str:
    L = [f"# Answer key{': ' + spec.title if spec.title else ''}", ""]
    if spec.problem_text:
        L += [f"**Problem.** {spec.problem_text}", ""]
    elif spec.ask:
        L += [f"**Find.** {spec.ask}", ""]
    hits = target_answers(spec, result, sig)
    if hits:
        L += ["## Answer to the question"] + [f"- **{h}**" for h in hits] + [""]
    if result["kind"] == "opamp":
        L += ["## Ideal op-amp", f"- Gain = {result['formula']} = **{result['gain']:.{sig}g}**"]
        if result.get("vout") is not None:
            L.append(f"- V_out = gain × V_in = **{eng(result['vout'], 'V', sig)}**")
        return "\n".join(L) + "\n"
    has_reactive = "initial" in result
    L += ["## " + ("After a long time (steady state: capacitors act open, inductors act like wire)"
                   if has_reactive else "All voltages, currents and powers"), "",
          _table(result["steady"]["rows"], sig), ""]
    extras = []
    if "req" in result:
        extras.append(f"- Equivalent resistance seen by the source: **{eng(result['req'], 'Ω', sig)}**")
    if "tau" in result:
        extras.append(f"- Resistance seen by the capacitor/inductor: {eng(result['rth'], 'Ω', sig)}; "
                      f"time constant **τ = {eng(result['tau'], 's', sig)}**")
    for r in result["steady"]["rows"]:
        if "charge" in r:
            extras.append(f"- Final charge on {r['id']}: **{eng(r['charge'], 'C', sig)}**; "
                          f"stored energy {eng(r['energy'], 'J', sig)}")
        elif "energy" in r:
            extras.append(f"- Final energy stored in {r['id']}: {eng(r['energy'], 'J', sig)}")
    if extras:
        L += extras + [""]
    if has_reactive:
        L += ["## Just after switching (t = 0⁺: uncharged capacitors act like wire, inductors act open)", "",
              _table(result["initial"]["rows"], sig), ""]
    L += ["_Switches are analysed in the state shown in the diagram. Meters are ideal._"]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# 6. Netlist export (SPICE / Lcapy flavoured)
# ---------------------------------------------------------------------------

def to_netlist(spec: CircuitSpec, for_lcapy: bool = False) -> str:
    elems, ground = build_network(spec)
    names: Dict[str, str] = {ground: "0"}
    for e in elems:
        for n in (e.n1, e.n2):
            names.setdefault(n, str(len(names)))
    L = [] if for_lcapy else [f"* {spec.title or 'circuit'} - exported by Circuit Problem Studio",
                              "* node 0 is the reference (bottom-left of the drawing)"]
    for e in elems:
        c, t = e.comp, e.comp.type
        a, b = names[e.n1], names[e.n2]
        val = "" if c.si() is None else f"{c.si():g}"
        def named(letter: str) -> str:          # SPICE wants the first letter to give the type
            return c.id if c.id.upper().startswith(letter) else f"{letter}{c.id}"

        if t in ("resistor", "bulb"):
            L.append(f"{named('R')} {a} {b} {val}".rstrip())
        elif t in ("battery", "vsource", "isource"):
            p = names[e.plus]
            m = b if p == a else a
            name = named("I" if t == "isource" else "V")
            if t == "isource":
                # SPICE: current flows first-node -> second-node INSIDE the source.
                # Lcapy uses the opposite convention (checked against the built-in solver).
                L.append((f"{name} {p} {m} dc {val}" if for_lcapy else f"{name} {m} {p} dc {val}").rstrip())
            else:
                L.append(f"{name} {p} {m} dc {val}".rstrip())
        elif t == "capacitor":
            if not for_lcapy:
                L.append(f"{named('C')} {a} {b} {val}".rstrip())
        elif t == "inductor":
            L.append(f"W {a} {b}" if for_lcapy else f"{named('L')} {a} {b} {val}".rstrip())
        elif t in ("ammeter", "wire") or (t == "switch" and c.closed):
            L.append(f"W {a} {b}" if for_lcapy else f"V{c.id} {a} {b} dc 0   ; ideal {t}")
        elif not for_lcapy:
            L.append(f"* {c.id} ({t}) is an open circuit between nodes {a} and {b}")
    return "\n".join(L) + "\n"


def lcapy_available() -> bool:
    try:
        import lcapy  # noqa: F401
        return True
    except Exception:
        return False


def lcapy_exact(spec: CircuitSpec) -> str:
    """Exact (fractions) or symbolic steady-state answers from Lcapy, as markdown."""
    from lcapy import Circuit
    net = to_netlist(spec, for_lcapy=True)
    cct = Circuit(net)
    lines = ["| Part | Voltage across | Current through |", "|---|---|---|"]
    for line in net.strip().splitlines():
        name = line.split()[0]
        if name == "W":
            continue
        try:
            lines.append(f"| {name} | `{cct[name].v}` | `{cct[name].i}` |")
        except Exception as ex:  # pragma: no cover - depends on Lcapy internals
            lines.append(f"| {name} | could not solve ({type(ex).__name__}) | |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. Built-in examples (also used as few-shot examples for the AI)
# ---------------------------------------------------------------------------

EXAMPLES: Dict[str, Dict[str, Any]] = {
    "Series circuit": {
        "title": "Series circuit",
        "topology": "ladder",
        "components": [
            {"id": "V1", "type": "battery", "value": 12, "unit": "V"},
            {"id": "R1", "type": "resistor", "value": 2, "unit": "Ω"},
            {"id": "R2", "type": "resistor", "value": 4, "unit": "Ω"},
        ],
        "layout": {"columns": [["V1"], ["R2"]], "top": [["R1"]], "bottom": [[]]},
        "problem_text": "A 12 V battery is connected in series with a 2 Ω and a 4 Ω resistor. "
                        "Find the current in the circuit and the voltage across R2.",
        "ask": "Current in the circuit; voltage across R2",
        "targets": [{"component": "R2", "quantity": "current"}, {"component": "R2", "quantity": "voltage"}],
    },
    "Parallel circuit": {
        "title": "Three resistors in parallel",
        "topology": "ladder",
        "components": [
            {"id": "V1", "type": "battery", "value": 9, "unit": "V"},
            {"id": "R1", "type": "resistor", "value": 3, "unit": "Ω"},
            {"id": "R2", "type": "resistor", "value": 6, "unit": "Ω"},
            {"id": "R3", "type": "resistor", "value": 9, "unit": "Ω"},
        ],
        "layout": {"columns": [["V1"], ["R1"], ["R2"], ["R3"]], "top": [[], [], []], "bottom": [[], [], []]},
        "problem_text": "Three resistors (3 Ω, 6 Ω and 9 Ω) are connected in parallel across a 9 V battery. "
                        "Find the equivalent resistance and the current drawn from the battery.",
        "ask": "Equivalent resistance; battery current",
        "targets": [{"quantity": "equivalent_resistance"}, {"component": "V1", "quantity": "current"}],
    },
    "Series-parallel combination": {
        "title": "Combination circuit",
        "topology": "ladder",
        "components": [
            {"id": "V1", "type": "battery", "value": 24, "unit": "V"},
            {"id": "R1", "type": "resistor", "value": 4, "unit": "Ω"},
            {"id": "R2", "type": "resistor", "value": 12, "unit": "Ω"},
            {"id": "R3", "type": "resistor", "value": 6, "unit": "Ω"},
            {"id": "R4", "type": "resistor", "value": 4, "unit": "Ω"},
        ],
        "layout": {"columns": [["V1"], ["R2"], ["R3"]], "top": [["R1"], []], "bottom": [["R4"], []]},
        "problem_text": "In the circuit shown, R1 and R4 are in series with the parallel pair R2 and R3. "
                        "Find the current through R3.",
        "ask": "Current through R3",
        "targets": [{"component": "R3", "quantity": "current"}],
        "current_arrows": ["R3"],
    },
    "Two-loop Kirchhoff (two batteries)": {
        "title": "Two-loop circuit",
        "topology": "ladder",
        "components": [
            {"id": "V1", "type": "battery", "value": 10, "unit": "V"},
            {"id": "V2", "type": "battery", "value": 5, "unit": "V"},
            {"id": "R1", "type": "resistor", "value": 2, "unit": "Ω"},
            {"id": "R2", "type": "resistor", "value": 4, "unit": "Ω"},
            {"id": "R3", "type": "resistor", "value": 3, "unit": "Ω"},
        ],
        "layout": {"columns": [["V1"], ["R2"], ["V2"]], "top": [["R1"], ["R3"]], "bottom": [[], []]},
        "problem_text": "Use Kirchhoff's rules to find the current through each resistor.",
        "ask": "Current through R1, R2 and R3",
        "targets": [{"component": "R1", "quantity": "current"}, {"component": "R2", "quantity": "current"},
                    {"component": "R3", "quantity": "current"}],
        "node_labels": {"T1": "a", "B1": "b"},
    },
    "RC charging circuit": {
        "title": "Charging a capacitor",
        "topology": "ladder",
        "components": [
            {"id": "V1", "type": "battery", "value": 12, "unit": "V"},
            {"id": "S", "type": "switch", "closed": True},
            {"id": "R1", "type": "resistor", "value": 10, "unit": "kΩ"},
            {"id": "C1", "type": "capacitor", "value": 100, "unit": "μF"},
        ],
        "layout": {"columns": [["V1"], ["C1"]], "top": [["S", "R1"]], "bottom": [[]]},
        "problem_text": "The capacitor is initially uncharged. The switch is closed at t = 0. Find the time "
                        "constant, the initial current, and the final charge on the capacitor.",
        "ask": "Time constant; initial current; final charge",
        "targets": [{"quantity": "time_constant"}, {"component": "C1", "quantity": "charge"}],
    },
    "Wheatstone bridge": {
        "title": "Wheatstone bridge",
        "topology": "bridge",
        "components": [
            {"id": "V1", "type": "battery", "value": 10, "unit": "V"},
            {"id": "R1", "type": "resistor", "value": 100, "unit": "Ω"},
            {"id": "R2", "type": "resistor", "value": 200, "unit": "Ω"},
            {"id": "R3", "type": "resistor", "value": 150, "unit": "Ω"},
            {"id": "R4", "type": "resistor", "value": 250, "unit": "Ω"},
            {"id": "R5", "type": "resistor", "value": 50, "unit": "Ω"},
        ],
        "layout": {"source": "V1", "top_left": "R1", "top_right": "R2", "bottom_left": "R3",
                   "bottom_right": "R4", "detector": "R5"},
        "problem_text": "Find the current through the 50 Ω resistor R5 in the bridge circuit shown.",
        "ask": "Current through R5",
        "targets": [{"component": "R5", "quantity": "current"}],
    },
    "Inverting op-amp": {
        "title": "Inverting amplifier",
        "topology": "opamp_inverting",
        "components": [
            {"id": "Vin", "type": "vsource", "value": 0.5, "unit": "V"},
            {"id": "R1", "type": "resistor", "value": 1, "unit": "kΩ"},
            {"id": "Rf", "type": "resistor", "value": 10, "unit": "kΩ"},
        ],
        "layout": {"vin": "Vin", "r_in": "R1", "r_f": "Rf"},
        "problem_text": "Assuming an ideal op-amp, find the gain and the output voltage.",
        "ask": "Gain and V_out",
        "targets": [{"quantity": "gain"}, {"quantity": "vout"}],
    },
}
