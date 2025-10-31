from __future__ import annotations
import json, os
from dataclasses import fields
from typing import Any, NamedTuple, get_type_hints
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
SHIP_ZONE_OPTIONS = tuple(DEFAULTS["ship_zone_factor"].keys())


class PricedField(NamedTuple):
    name: str
    price_field: str
    map_key: str
    error: str


PRICED_FIELDS: tuple[PricedField, ...] = (
    PricedField("material", "material_price", "material_prices", "Material price must be a number"),
    PricedField("finish", "finish_price", "finish_costs", "Finish cost must be a number"),
    PricedField("plating", "plating_price", "plating_costs", "Plating cost must be a number"),
)


def _defaults_map(key: str) -> dict[str, Any]:
    value = DEFAULTS.get(key, {})
    return value.copy() if isinstance(value, dict) else {}


PRICED_DEFAULT_MAPS = {field.name: _defaults_map(field.map_key) for field in PRICED_FIELDS}
SELECT_OPTIONS = {field.name: tuple(PRICED_DEFAULT_MAPS[field.name].keys()) for field in PRICED_FIELDS}
PRICED_LABELS = {"material": "板材", "finish": "表面处理", "plating": "电铜"}

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

    selected_choices = {
        field.name: request.form.get(field.name, DEFAULTS.get(field.name))
        for field in PRICED_FIELDS
    }

    def _apply_override(price_field: str, map_key: str, selected: str | None, err_msg: str) -> None:
        raw = request.form.get(price_field)
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

    for field in PRICED_FIELDS:
        form_key = field.price_field
        _apply_override(form_key, field.map_key, selected_choices.get(field.name), field.error)
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

    selected_choices = {
        field.name: form_values.get(field.name, str(DEFAULTS.get(field.name, "")))
        for field in PRICED_FIELDS
    }

    def _form_price_value(field_name: str, defaults_map: dict[str, Any], selected: str) -> str:
        raw = request.form.get(field_name)
        if raw not in (None, ""):
            return raw
        default_value = defaults_map.get(selected)
        return "" if default_value in (None, "") else str(default_value)

    price_value_kwargs = {}
    for field in PRICED_FIELDS:
        defaults_map = PRICED_DEFAULT_MAPS[field.name]
        price_value_kwargs[f"{field.price_field}_value"] = _form_price_value(
            field.price_field, defaults_map, selected_choices[field.name]
        )

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

    return render_template(
        "index.html",
        defaults=form_defaults,
        values=form_values,
        params_defaults=param_defaults,
        params_values=param_values,
        ship_zone_options=SHIP_ZONE_OPTIONS,
        error_msgs=error_msgs,
        result=result,
        priced_fields=PRICED_FIELDS,
        priced_labels=PRICED_LABELS,
        priced_options=SELECT_OPTIONS,
        priced_costs=PRICED_DEFAULT_MAPS,
        priced_client_config=[{"name": field.name, "priceField": field.price_field} for field in PRICED_FIELDS],
        **price_value_kwargs,
    )


@app.route("/lt.png")
@app.route("/favicon.ico")
def serve_icon():
    return send_file(ICON_PATH, mimetype="image/png")

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("DEBUG", "0") in ["1", "true", "True"]
    app.run(host=host, port=port, debug=debug)
