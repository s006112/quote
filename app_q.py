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
    if d["thickness_mm"] <= 0: errs.append("Thickness must be > 0.")
    if d["panel_boards"] < 1: errs.append("Boards per panel must be >= 1.")
    if d["panel_area_cm2"] < 50: errs.append("Panel area must be >= 50 cm².")
    if d["min_hole_mm"] < d["thickness_mm"]/10.0:
        errs.append("Finished hole violates 10:1 aspect ratio.")
    if d["outer_oz"] < 0.25 or d["outer_oz"] > 3.0:
        errs.append("Outer copper must be 0.25–3 oz.")
    if d["inner_oz"] is not None and (d["inner_oz"] < 0.25 or d["inner_oz"] > 3.0):
        errs.append("Inner copper must be 0.25–3 oz.")
    return errs

def _make_inputs() -> Inputs:
    df = PRESETS["defaults"]
    qty_raw = request.form.get("qty_tiers", df["qty_tiers"]).strip()
    qty_tiers = []
    for tok in qty_raw.replace(" ", "").split(","):
        if tok:
            n = int(tok)
            if n <= 0: raise ValueError("Quantities must be positive")
            qty_tiers.append(n)

    return Inputs(
        width=_to_float("width", df["width"]),
        height=_to_float("height", df["height"]),
        layers=_to_int("layers", df["layers"]),
        qty_tiers=qty_tiers,
        panel_boards=_to_int("panel_boards", df["panel_boards"]),
        panel_area_cm2=_to_float("panel_area_cm2", df["panel_area_cm2"]),
        material=request.form.get("material", df["material"]),
        thickness_mm=_to_float("thickness_mm", df["thickness_mm"]),
        outer_oz=_to_float("outer_oz", df["outer_oz"]),
        inner_oz=float(request.form.get("inner_oz", df["inner_oz"])) if request.form.get("inner_oz", "") else None,
        finish=request.form.get("finish", df["finish"]),
        min_track_mm=_to_float("min_track_mm", df["min_track_mm"]),
        min_space_mm=_to_float("min_space_mm", df["min_space_mm"]),
        min_hole_mm=_to_float("min_hole_mm", df["min_hole_mm"]),
        via_type=request.form.get("via_type", df["via_type"]),
        ipc_class=request.form.get("ipc_class", df["ipc_class"]),
        etest=request.form.get("etest", df["etest"]),
        lead_time_class=request.form.get("lead_time_class", df["lead_time_class"]),
        ship_zone=request.form.get("ship_zone", df["ship_zone"]),
    )

def _make_params() -> Params:
    p = PRESETS["costing_params"]
    return Params(
        labor_rates=p["labor_rates"],
        machine_rates=p["machine_rates"],
        material_prices=p["material_prices"],
        overheads_pct=p["overheads_pct"],
        yield_baseline_pct=p["yield_baseline_pct"],
        risk_buffer_pct=p["risk_buffer_pct"],
        customer_discount_pct=p["customer_discount_pct"],
        target_margin_pct=p["target_margin_pct"],
        lead_time_mult=p["lead_time_mult"],
        scarcity_mult=p["scarcity_mult"]
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
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "5000"))
    with make_server(host, port, app) as httpd:
        print(f"Serving on http://{host}:{port}")
        httpd.serve_forever()

