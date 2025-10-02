from __future__ import annotations
import json, os
from dataclasses import fields
from typing import Any, get_type_hints
from flask import Flask, render_template, request

from pricing import Inputs, Params, price_quote

app = Flask(__name__)

with open(os.path.join(os.path.dirname(__file__), "presets.json"), "r", encoding="utf-8") as f:
    PRESETS = json.load(f)

DEFAULTS = PRESETS["defaults"]
INPUT_TYPE_HINTS = get_type_hints(Inputs)
PARAM_TYPE_HINTS = get_type_hints(Params)

INPUT_FIELD_NAMES = tuple(f.name for f in fields(Inputs))
MATERIAL_OPTIONS = tuple(DEFAULTS["material_prices"].keys())
FINISH_OPTIONS = tuple(DEFAULTS["finish_costs"].keys())
SHIP_ZONE_OPTIONS = tuple(DEFAULTS["ship_zone_factor"].keys())

def _to_float(name: str, default: float) -> float:
    v = request.form.get(name, str(default)).strip()
    try:
        return float(v)
    except ValueError:
        raise ValueError(f"{name} must be a number")

def _to_int(name: str, default: int) -> int:
    v = request.form.get(name, str(default)).strip()
    try:
        return int(v)
    except ValueError:
        raise ValueError(f"{name} must be an integer")

def _validate(d: dict[str, Any]) -> list[str]:
    errs = []
    if not (5 <= d["width"] <= 650): errs.append("Width must be 5–650 mm.")
    if not (5 <= d["height"] <= 650): errs.append("Height must be 5–650 mm.")
    if not (1 <= d["layers"] <= 40): errs.append("Layers must be 1–40.")
    if d["panel_boards"] < 1: errs.append("Boards per panel must be >= 1.")
    if d.get("direct_pth_holes", 0) < 0: errs.append("Direct PTH holes must be >= 0.")
    if d.get("cnc_pth_holes", 0) < 0: errs.append("CNC PTH holes must be >= 0.")
    if d.get("cutting_cost", 0.0) < 0: errs.append("Cutting cost must be >= 0.")
    if d.get("routing_cost", 0.0) < 0: errs.append("Routing cost must be >= 0.")
    if d.get("e_test_cost", 0.0) < 0: errs.append("E-test cost must be >= 0.")
    if d.get("v_cut_cost", 0.0) < 0: errs.append("V-cut cost must be >= 0.")
    if d.get("fqc_cost", 0.0) < 0: errs.append("FQC cost must be >= 0.")
    if d.get("package_cost", 0.0) < 0: errs.append("Package cost must be >= 0.")
    return errs

def _make_inputs() -> Inputs:
    payload: dict[str, Any] = {}
    for name, hint in INPUT_TYPE_HINTS.items():
        default = DEFAULTS[name]
        if hint is int:
            payload[name] = _to_int(name, int(default))
        elif hint is float:
            payload[name] = _to_float(name, float(default))
        else:
            payload[name] = request.form.get(name, str(default))
    return Inputs(**payload)

def _make_params() -> Params:
    payload: dict[str, Any] = {}
    for name, hint in PARAM_TYPE_HINTS.items():
        default = DEFAULTS.get(name)
        if hint is float and default is not None:
            payload[name] = _to_float(name, float(default))
        elif hint is int and default is not None:
            payload[name] = _to_int(name, int(default))
        else:
            value = default
            if isinstance(value, dict):
                value = value.copy()
            payload[name] = value
    return Params(**payload)

@app.route("/", methods=["GET", "POST"])
def index():
    param_defaults = {
        name: DEFAULTS[name]
        for name, hint in PARAM_TYPE_HINTS.items()
        if hint in (int, float) and name in DEFAULTS
    }
    form_defaults = {
        name: DEFAULTS[name]
        for name in INPUT_FIELD_NAMES 
        if name in DEFAULTS
    }
    form_values = {k: request.form.get(k, str(v)) for k, v in form_defaults.items()}
    param_values = {k: request.form.get(k, str(v)) for k, v in param_defaults.items()}

    error_msgs, result = [], None

    if request.method == "POST":
        try:
            inp = _make_inputs()
            errs = _validate(vars(inp))
            if errs:
                error_msgs = errs
            else:
                prm = _make_params()
                result = price_quote(inp, prm)
        except Exception as e:
            error_msgs = [str(e)]

    return render_template("index.html",
                           defaults=form_defaults,
                           values=form_values,
                           params_defaults=param_defaults,
                           params_values=param_values,
                           material_options=MATERIAL_OPTIONS,
                           finish_options=FINISH_OPTIONS,
                           ship_zone_options=SHIP_ZONE_OPTIONS,
                           error_msgs=error_msgs,
                           result=result)

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("DEBUG", "0") in ["1", "true", "True"]
    app.run(host=host, port=port, debug=debug)
