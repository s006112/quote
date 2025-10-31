from __future__ import annotations
import json, os
from dataclasses import fields
from typing import Any, get_type_hints
from flask import Flask, render_template, request, send_file

from pricing import Inputs, Params, price_quote

app = Flask(__name__)

ICON_FILENAME = "lt.png"
ICON_PATH = os.path.join(os.path.dirname(__file__), ICON_FILENAME)

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
    if d.get("plating_cost", 0.0) < 0: errs.append("Plating cost must be >= 0.")
    if d.get("cnc_pth_holes", 0) < 0: errs.append("CNC PTH holes must be >= 0.")
    if d.get("cutting_cost", 0.0) < 0: errs.append("Cutting cost must be >= 0.")
    if d.get("routing_cost", 0.0) < 0: errs.append("Routing cost must be >= 0.")
    if d.get("stamping_cost", 0.0) < 0: errs.append("Stamping cost must be >= 0.")
    if d.get("post_process_cost", 0.0) < 0: errs.append("Post Process cost must be >= 0.")
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

    selected_material = request.form.get("material", DEFAULTS.get("material"))
    selected_finish = request.form.get("finish", DEFAULTS.get("finish"))

    def _apply_override(form_key: str, map_key: str, selected: str | None, err_msg: str) -> None:
        raw = request.form.get(form_key)
        if raw in (None, ""):
            return
        try:
            value = float(raw)
        except ValueError:
            raise ValueError(err_msg)
        if not selected:
            return
        price_map = payload.get(map_key)
        if price_map is None:
            price_map = {}
            payload[map_key] = price_map
        price_map[selected] = value

    _apply_override("material_price", "material_prices", selected_material, "Material price must be a number")
    _apply_override("finish_price", "finish_costs", selected_finish, "Finish cost must be a number")
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

    selected_material = form_values.get("material", str(DEFAULTS.get("material", "")))
    selected_finish = form_values.get("finish", str(DEFAULTS.get("finish", "")))

    default_material_prices = DEFAULTS.get("material_prices", {})
    default_finish_costs = DEFAULTS.get("finish_costs", {})

    def _form_price_value(field_name: str, defaults_map: dict[str, Any], selected: str) -> str:
        raw = request.form.get(field_name)
        if raw not in (None, ""):
            return raw
        default_value = defaults_map.get(selected)
        return "" if default_value in (None, "") else str(default_value)

    material_price_value = _form_price_value("material_price", default_material_prices, selected_material)
    finish_price_value = _form_price_value("finish_price", default_finish_costs, selected_finish)

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
                           material_prices=default_material_prices,
                           finish_costs=default_finish_costs,
                           material_price_value=material_price_value,
                           finish_price_value=finish_price_value,
                           ship_zone_options=SHIP_ZONE_OPTIONS,
                           error_msgs=error_msgs,
                           result=result)


@app.route("/lt.png")
@app.route("/favicon.ico")
def serve_icon():
    return send_file(ICON_PATH, mimetype="image/png")

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("DEBUG", "0") in ["1", "true", "True"]
    app.run(host=host, port=port, debug=debug)
