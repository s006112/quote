from __future__ import annotations
import json, os
from typing import Any
from wsgiref.simple_server import make_server
from flask import Flask, render_template, request

from pricing import Inputs, Params, price_quote

app = Flask(__name__)

with open(os.path.join(os.path.dirname(__file__), "presets.json"), "r", encoding="utf-8") as f:
    PRESETS = json.load(f)

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
    df = PRESETS["defaults"]
    return Inputs(
        width=_to_float("width", df["width"]),
        height=_to_float("height", df["height"]),
        layers=_to_int("layers", df["layers"]),
        panel_boards=_to_int("panel_boards", df["panel_boards"]),
        direct_pth_holes=_to_int("direct_pth_holes", df["direct_pth_holes"]),
        cnc_pth_holes=_to_int("cnc_pth_holes", df["cnc_pth_holes"]),
        material=request.form.get("material", df["material"]),
        finish=request.form.get("finish", df["finish"]),
        film_cost=_to_float("film_cost", df["film_cost"]),
        masking_cost=_to_float("masking_cost", df["masking_cost"]),
        silkscreen_cost=_to_float("silkscreen_cost", df["silkscreen_cost"]),
        etching_cost=_to_float("etching_cost", df["etching_cost"]),
        cutting_cost=_to_float("cutting_cost", df["cutting_cost"]),
        routing_cost=_to_float("routing_cost", df["routing_cost"]),
        e_test_cost=_to_float("e_test_cost", df["e_test_cost"]),
        v_cut_cost=_to_float("v_cut_cost", df["v_cut_cost"]),
        fqc_cost=_to_float("fqc_cost", df["fqc_cost"]),
        package_cost=_to_float("package_cost", df["package_cost"]),
        sewage_water=_to_float("sewage_water", df["sewage_water"]),
        sewage_electricity=_to_float("sewage_electricity", df["sewage_electricity"]),
        via_type=request.form.get("via_type", df["via_type"]),
        ship_zone=request.form.get("ship_zone", df["ship_zone"]),
    )

def _make_params() -> Params:
    p = PRESETS["costing_params"]
    return Params(
        machine_rates=p["machine_rates"],
        material_prices=p["material_prices"],
        finish_costs=p["finish_costs"],
        overheads_pct=p["overheads_pct"],
        yield_baseline_pct=p["yield_baseline_pct"],
        risk_buffer_pct=p["risk_buffer_pct"],
        customer_discount_pct=p["customer_discount_pct"],
        target_margin_pct=p["target_margin_pct"],
        ship_zone_factor=p["ship_zone_factor"]
    )

@app.route("/", methods=["GET", "POST"])
def index():
    df = PRESETS["defaults"]
    error_msgs, result = [], None
    form_values = {k: request.form.get(k, str(v)) for k, v in df.items()}

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
                           defaults=df,
                           values=form_values,
                           error_msgs=error_msgs,
                           result=result)

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("DEBUG", "0") in ["1", "true", "True"]
    app.run(host=host, port=port, debug=debug)
