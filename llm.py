"""
llm.py - everything that talks to an AI model.

The AI never draws.  It only fills in (or edits) the JSON spec that
circuit_core.py understands.  Two kinds of provider are supported:

  * "anthropic"  - Claude models via https://api.anthropic.com
  * "openai"     - anything that speaks the OpenAI chat format: OpenAI itself,
                   Google Gemini's compatible endpoint, Groq, or a free local
                   model through Ollama (http://localhost:11434/v1).
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

import circuit_core as cc

PRESETS = {
    "Anthropic (Claude)": {"provider": "anthropic", "base_url": "https://api.anthropic.com",
                           "model": "claude-sonnet-5", "env": "ANTHROPIC_API_KEY"},
    "OpenAI": {"provider": "openai", "base_url": "https://api.openai.com/v1",
               "model": "gpt-4o", "env": "OPENAI_API_KEY"},
    "Google Gemini (free tier available)": {
        "provider": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash", "env": "GEMINI_API_KEY"},
    "Ollama (free, runs on this computer)": {"provider": "openai", "base_url": "http://localhost:11434/v1",
                                             "model": "llama3.1", "env": ""},
    "Other OpenAI-compatible service": {"provider": "openai", "base_url": "", "model": "", "env": ""},
}


class LLMError(Exception):
    pass


@dataclass
class LLMClient:
    provider: str
    api_key: str
    model: str
    base_url: str
    timeout: int = 120

    def chat(self, system: str, messages: List[Dict[str, Any]], max_tokens: int = 3000,
             image_png: Optional[bytes] = None) -> str:
        """messages: [{'role': 'user'|'assistant', 'content': str}, ...].
        If image_png is given it is attached to the LAST user message."""
        try:
            if self.provider == "anthropic":
                return self._anthropic(system, messages, max_tokens, image_png)
            return self._openai(system, messages, max_tokens, image_png)
        except requests.RequestException as e:
            raise LLMError(f"Could not reach the AI service: {e}") from e

    def _anthropic(self, system, messages, max_tokens, image_png) -> str:
        msgs = [dict(m) for m in messages]
        if image_png:
            msgs[-1] = {"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.b64encode(image_png).decode()}},
                {"type": "text", "text": msgs[-1]["content"]}]}
        r = requests.post(
            self.base_url.rstrip("/") + "/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.model, "max_tokens": max_tokens, "system": system, "messages": msgs},
            timeout=self.timeout)
        if r.status_code != 200:
            raise LLMError(_explain_http(r))
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")

    def _openai(self, system, messages, max_tokens, image_png) -> str:
        msgs = [{"role": "system", "content": system}] + [dict(m) for m in messages]
        if image_png:
            url = "data:image/png;base64," + base64.b64encode(image_png).decode()
            msgs[-1] = {"role": "user", "content": [
                {"type": "text", "text": msgs[-1]["content"]},
                {"type": "image_url", "image_url": {"url": url}}]}
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        r = requests.post(self.base_url.rstrip("/") + "/chat/completions", headers=headers,
                          json={"model": self.model, "messages": msgs, "max_tokens": max_tokens},
                          timeout=self.timeout)
        if r.status_code != 200:
            raise LLMError(_explain_http(r))
        return r.json()["choices"][0]["message"]["content"] or ""


def _explain_http(r: requests.Response) -> str:
    try:
        body = r.json()
        detail = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
    except Exception:
        detail = r.text[:300]
    hint = {401: "The API key was rejected - check it in the sidebar.",
            403: "The key does not have permission for this model.",
            404: "Model or address not found - check the model name and base URL in the sidebar.",
            429: "Rate limit or quota reached - wait a moment or check your plan."}.get(r.status_code, "")
    return f"AI service returned error {r.status_code}. {hint} {detail or ''}".strip()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def _few_shot() -> str:
    keep = ["Series-parallel combination", "Two-loop Kirchhoff (two batteries)", "RC charging circuit",
            "Wheatstone bridge"]
    return "\n\n".join(f"Example - {k}:\n{json.dumps(cc.EXAMPLES[k], ensure_ascii=False)}" for k in keep)


SPEC_GUIDE = """
You turn a physics teacher's request into a JSON "circuit spec". Software then draws the diagram
and computes the answer key from that JSON, so the JSON must be exact. Reply with ONE JSON object
and nothing else (no markdown fences, no commentary).

FIELDS
- title: short title.
- topology: "ladder" | "bridge" | "opamp_inverting" | "opamp_noninverting" | "custom".
- components: list of {id, type, value, unit, hide_value?, flip?, closed?, label?}
    id: letter then letters/digits, e.g. V1, R1, C1, S, A1. Unique.
    type: resistor | bulb | battery | vsource | isource | capacitor | inductor | switch |
          ammeter | voltmeter | diode | led | wire
    value + unit: number and unit with prefix, e.g. 4.7 and "kΩ", 100 and "μF", 12 and "V", 2 and "mA".
          A bulb takes a resistance. Switches, meters and wires take no value.
    hide_value: true prints "R3 = ?" (use for the unknown the student must find). Keep the real value in
          "value" so the answer key can be computed.
    closed: switches only (default true). The answer key analyses the switch in this state.
    flip: reverses polarity / direction (see rule below).
- layout: depends on topology (see below).
- problem_text: the full problem statement for students, consistent with the values.
- ask: very short summary of what to find.
- targets: list of {component?, quantity} with quantity in current | voltage | power | charge | energy |
          equivalent_resistance | time_constant | gain | vout. Used to highlight answers.
- show_values: false prints only names (R1, R2, ...) for symbolic problems.
- current_arrows: ids of components that get a current arrow (I_R2 ...) on the drawing.
- node_labels: ladder only, e.g. {"T1": "a", "B1": "b"} to mark points for "find V_ab".
- style: "US" (zig-zag resistors) or "IEC" (box resistors).

TOPOLOGY "ladder"  (use this for almost everything: series, parallel, combinations, ladders,
multi-loop Kirchhoff circuits with several batteries, RC and RL circuits with a switch)
  Picture vertical branches ("columns") standing between a top rail and a bottom rail.
  layout = {"columns": [[...], [...], ...], "top": [[...], ...], "bottom": [[...], ...]}
  - columns: left to right, each a list of ids in series from top to bottom. At least 2 columns.
    An empty list is a plain wire.
  - top[i] / bottom[i]: ids in series on the rail BETWEEN column i and column i+1 (left to right);
    [] means plain wire. Both lists have exactly len(columns)-1 entries.
  - The source normally goes in column 0. A simple series loop is: columns [["V1"],["R3"]],
    top [["R1","R2"]], bottom [[]]. Parallel resistors are separate columns joined by empty rails.
  - Polarity rule: a battery/source in a column has + at the TOP; on a rail it has + toward the RIGHT
    (current-source arrows point up / right). Set "flip": true to reverse.
  - Node names for node_labels: T0..Tn-1 are the tops of the columns, B0..Bn-1 the bottoms.
  - Ammeters go in series (in a column or rail). A voltmeter gets its own column next to the part
    it measures.

TOPOLOGY "bridge" (Wheatstone bridge)
  layout = {"source","top_left","top_right","bottom_left","bottom_right","detector"(optional)}
  Corners are labelled a (top), b (left), c (right), d (bottom); the source connects a (+) to d.

TOPOLOGY "opamp_inverting": layout = {"vin","r_in","r_f"};  "opamp_noninverting": layout = {"vin","r_g","r_f"}

TOPOLOGY "custom" - LAST RESORT, only when the circuit truly cannot be drawn as a ladder or bridge.
  Add "custom_code": Schemdraw (Python) code, and give every component "between": [nodeA, nodeB]
  (for sources nodeA is the + terminal; call the reference node "0") so the answer key still works.
  Code rules: start with `import schemdraw` and `import schemdraw.elements as elm`; create
  `d = schemdraw.Drawing(show=False)`; add parts with `d += elm.Resistor().right().label('R1')` or
  `.endpoints((x1, y1), (x2, y2))`; never call d.draw() or d.save(); import nothing else.
  Make sure every loop closes (use .endpoints or .to / .tox / .toy with saved positions).

Choose sensible, "nice" component values when the teacher does not give them, and make
problem_text agree with the components exactly.
""".strip()


def system_prompt() -> str:
    return SPEC_GUIDE + "\n\n" + _few_shot()


def extract_json(text: str) -> str:
    text = re.sub(r"```(?:json)?", "", text).strip()
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b <= a:
        raise ValueError("The AI reply did not contain a JSON object.")
    return text[a:b + 1]


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------

RenderFn = Callable[[str], Optional[str]]     # code -> error text (None when fine)


def _spec_loop(client: LLMClient, messages: List[Dict[str, str]], render_check: Optional[RenderFn],
               max_attempts: int = 3) -> Tuple[cc.CircuitSpec, List[str]]:
    """Ask, validate, and if something is wrong hand the error back to the AI and ask again."""
    log: List[str] = []
    for attempt in range(1, max_attempts + 1):
        reply = client.chat(system_prompt(), messages)
        problem = None
        try:
            spec = cc.parse_spec(extract_json(reply))
        except ValueError as e:
            problem = f"The JSON was rejected: {e}"
        else:
            if spec.topology == "custom":
                issues = cc.check_code_safety(spec.custom_code or "")
                if issues:
                    problem = "custom_code was rejected: " + "; ".join(issues)
                elif render_check is not None:
                    err = render_check(spec.custom_code or "")
                    if err:
                        problem = f"custom_code failed to run: {err}"
            if problem is None:
                try:
                    cc.solve(spec)
                except cc.Unsolvable as e:
                    # not fatal (symbolic problems are fine) but worth one retry for short circuits
                    if "no unique solution" in str(e) and attempt < max_attempts:
                        problem = f"The circuit cannot be solved: {e}"
                    else:
                        log.append(f"Note: {e}")
        if problem is None:
            log.append(f"Attempt {attempt}: accepted.")
            return spec, log
        log.append(f"Attempt {attempt}: {problem}")
        messages = messages + [{"role": "assistant", "content": reply},
                               {"role": "user", "content": problem + " Send the full corrected JSON only."}]
    raise LLMError("The AI could not produce a valid circuit after several tries:\n- " + "\n- ".join(log))


def generate_spec(client: LLMClient, request: str, style: str = "US",
                  render_check: Optional[RenderFn] = None) -> Tuple[cc.CircuitSpec, List[str]]:
    msg = f"Teacher's request:\n{request.strip()}\n\nUse \"style\": \"{style}\"."
    return _spec_loop(client, [{"role": "user", "content": msg}], render_check)


def edit_spec(client: LLMClient, spec: cc.CircuitSpec, instruction: str,
              render_check: Optional[RenderFn] = None) -> Tuple[cc.CircuitSpec, List[str]]:
    msg = ("Here is the current circuit spec:\n" + cc.spec_to_json(spec) +
           f"\n\nThe teacher wants this change:\n{instruction.strip()}\n\n"
           "Return the complete updated JSON. Change only what is needed, and keep problem_text, ask and "
           "targets consistent with the new circuit.")
    return _spec_loop(client, [{"role": "user", "content": msg}], render_check)


def vision_check(client: LLMClient, spec: cc.CircuitSpec, png: bytes) -> Dict[str, Any]:
    system = ("You proof-read circuit diagrams for a physics teacher. Compare the picture with the JSON spec. "
              "Check: every component in the spec appears exactly once with the right label and value; all loops "
              "are closed (no dangling wires); nothing overlaps or is unreadable; battery polarity matches "
              "(long plate is +). Reply with JSON only: "
              '{"matches": true|false, "issues": ["..."], "suggestions": ["..."]}')
    reply = client.chat(system, [{"role": "user", "content": "Spec:\n" + cc.spec_to_json(spec)}],
                        max_tokens=800, image_png=png)
    try:
        return json.loads(extract_json(reply))
    except Exception:
        return {"matches": None, "issues": [], "suggestions": [], "raw": reply}


def worked_solution(client: LLMClient, spec: cc.CircuitSpec, answer_md: str) -> str:
    system = ("You write clear worked solutions for an introductory physics course. The numbers in the "
              "'Verified answer key' were computed by circuit-analysis software and are correct: your working "
              "must arrive at exactly those numbers. Show the reasoning a student should follow (series/parallel "
              "reduction, Kirchhoff's rules, time constants...) in numbered steps with units. Use plain Markdown.")
    user = ("Circuit spec:\n" + cc.spec_to_json(spec) + "\n\nVerified answer key:\n" + answer_md +
            "\n\nWrite the worked solution.")
    return client.chat(system, [{"role": "user", "content": user}], max_tokens=2500)
