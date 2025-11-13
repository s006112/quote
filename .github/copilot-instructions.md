# Quote Application — AI Agent Instructions

## Project Overview

This is a **PCB pricing and panelization calculator** with two parallel Flask applications:
- `app_qp.py`: Quotation + Panelizer (pricing + layout optimization)
- `app_p.py`: Legacy Panelizer-only app (for reference)

**Core purpose**: Calculate manufacturing costs for PCBs and optimize panel layouts given customer constraints.

## Architecture & Key Components

### Separation of Concerns

The refactored architecture (post-v1.0) enforces strict separation:

#### `manipulation.py` — Pure Computation Engine
- **Inputs**: Dataclass with 18 input fields (layers, hole counts, cost components, dimensions)
- **Params**: Dataclass with 9 parameter fields (cost multipliers, percentages, drilling rates)
- **Two major functions**:
  1. `price_quote(inp: Inputs, prm: Params) -> dict` — Cost breakdown calculation
  2. Panelizer module (see below)

**Key principle**: Zero Flask dependencies. Testable and reusable independently.

#### `app_qp.py` — Flask Web Layer
- Preset/config loading and merging
- HTTP form parsing & validation  
- Session state persistence (user preferences)
- Template rendering with calculated results
- **Imports from manipulation**: `Inputs`, `Params`, `price_quote`, panelizer APIs

**Key principle**: Thin web layer; all business logic delegates to `manipulation.py`.

### Data Flow: The Quotation Path

```
HTTP POST with form data
    ↓
_make_inputs() → parse form → Inputs dataclass
_make_params() → extract cost config → Params dataclass
_validate() → check field ranges
    ↓
price_quote(inp, prm) [in manipulation.py]
    ↓
JSON breakdown dict → template rendering
```

### Panelizer Module (in `manipulation.py`)

**Purpose**: Optimize PCB board placement on manufacturing panels.

**Public APIs** (called from app_qp.py):
- `build_panelizer_config(args, defaults)` → Extract form args into panelizer config dict
- `compute_panelizer_rows(cfg, panel_options, jumbo_multiplier)` → Generate layout candidates
- `summarize_panelizer_results(rows, cfg)` → Select best layout + compute utilization

**Key algorithm components** (private helpers):
- `_panelizer_enumerate_layouts()` — Brute-force layout search with rotation variants
- `_panelizer_pairwise_no_overlap()` — Overlap detection for board placement
- `_panelizer_utilization()` — Compute panel fill efficiency  
- Grid fitting helpers (`_panelizer_upper_bound_grid`, `_panelizer_almost_le`, etc.)

**Configuration keys** (see `PANELIZER_CONFIG_KEYS`):
- Board/panel dimensions (min/max, margins, gaps)
- Rotation toggles, kerf allowance, result limit
- Panel style filters (`include_set_A–E`)

## Preset System & Defaults

### Config Hierarchy

1. **`presets_qp.json`** (checked into repo)
   - Base defaults for quotation + panelizer
   - Material/finish/plating cost tables
   - PCB thickness options, CNC hole sizes
   - Stack quantity lookup table (`stack_qty_map`)

2. **`presets_qp.local.json`** (git-ignored)
   - Local environment overrides (sensitive pricing, testing tweaks)
   - Recursively merged over base using `_deep_merge()`

3. **Runtime in-memory `DEFAULTS`** (in `app_qp.py`)
   - Loaded at startup, updated on form POST if no panelizer errors
   - Persisted back to disk only if new values differ

### How Defaults are Used

- Form rendering: Pre-fill input fields with user's last submission
- Panelizer: Extract layout constraints (panel options, jumbo multiplier)
- Params: Cost tables and overhead/yield/margin percentages
- Type hints: `INPUT_TYPE_HINTS`, `PARAM_TYPE_HINTS` for runtime dataclass construction

## Form Parsing & Validation

### Parsing Flow (in `app_qp.py`)

```python
_make_inputs()  # Extracts & type-casts form fields → Inputs dataclass
_make_params()  # Looks up cost dicts from DEFAULTS → Params dataclass
_validate()     # Checks numeric ranges (layers 1–40, costs ≥ 0, etc.)
```

### Key Patterns

- **Type coercion**: `_to_float(name, default)`, `_to_int(name, default)` handle invalid input gracefully
- **Priced fields**: 4 dropdown + text price pairs (material, finish, masking, plating)
  - Dropdown selects from lookup table; text field can override price
  - Template renders both and merges via JavaScript client-side
- **Stack quantity lookup**: Special case — looked up from `stack_qty_map[thickness][hole_dimension]`

### Validation Rules (in `_validate()`)

- `layers`: 1–40
- `panel_boards`, `stack_qty`: ≥ 1
- Cost fields: ≥ 0
- **No panelizer-specific validation** — panelizer errors caught separately during layout computation

## Template Rendering

### Key Context Variables Passed to `index_qp.html`

| Variable | Type | Purpose |
|----------|------|---------|
| `values` | dict | Form input defaults + last submission |
| `params_values` | dict | Cost multipliers, percentages |
| `result` | dict \| None | Quotation breakdown (if no errors) |
| `panelizer_summary` | dict \| None | Best layout + utilization stats |
| `panelizer_rows` | list | All candidate layouts (for debugging) |
| `error_msgs` | list | Validation/parsing errors |
| `priced_fields`, `priced_options`, `priced_costs` | Metadata for cost dropdowns |
| `stack_qty_map` | dict | For JavaScript lookup on thickness/hole change |

### Panelizer Display

- Shows candidate layouts sorted by utilization  
- Displays best layout's board count, gaps, panel style
- If panelizer fails, displays error but quotation may still compute

## Common Development Workflows

### Adding a New Cost Component

1. Add field to `Inputs` dataclass (manipulation.py)
2. Add default + cost table to `presets_qp.json`
3. Add validation rule in `_validate()` (app_qp.py)
4. Update template `index_qp.html` to render new input + label
5. Update `price_quote()` logic to include component in breakdown

### Tweaking Panelizer Constraints

1. Edit `presets_qp.json` under `defaults` section (e.g., `panel_edge_margin_w`)
2. No code changes needed — uses `PANELIZER_CONFIG_KEYS` lookup
3. Test via form UI: panelizer re-runs on every GET/POST

### Debugging Quotation Mismatch

1. Check `price_quote()` logic in `manipulation.py` for calculation error
2. Verify `Params` construction in `_make_params()` extracts correct cost dicts
3. Inspect template rendering — price may differ due to rounding

### Debugging Panelizer Failures

1. Panelizer errors caught in `index()` route → `panelizer_error` displayed in template
2. Enable `panelizer_rows` display to see all candidates (may reveal constraint conflict)
3. Check `PANELIZER_CONFIG_KEYS` extraction in `build_panelizer_config()`

## Testing & Deployment

### Manual Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Run web server (debug mode)
export DEBUG=1 HOST=localhost PORT=5000
python app_qp.py
# Visit http://localhost:5000

# Test with local preset overrides
export PRESETS_OVERRIDE_PATH=/custom/presets_qp.local.json
python app_qp.py
```

### Production

- `run.sh`: Wrapper script that auto-restarts crashed app; logs to `panel.log`
- Environment: Python 3.10+, Flask 3.0.3
- No external service dependencies (pure Flask + JSON config)

## Code Style & Conventions

### Naming
- **Private helpers**: `_function_name` (lowercase, leading underscore)
- **Constants**: `UPPER_CASE` (e.g., `PANELIZER_CONFIG_KEYS`)
- **Panelizer-specific**: `_panelizer_*` prefix (consistency with module organization)

### Type Hints
- All function signatures include return types (PEP 484)
- Dataclasses use `from __future__ import annotations` for forward refs
- App uses Python 3.10+ union syntax: `str | None` instead of `Optional[str]`

### Docstrings
- Module-level: Describe purpose + key exports
- Functions: Include Args, Returns, Raises if non-obvious
- Panelizer functions documented for overlap detection, grid fitting logic

### Error Handling
- Validation errors → user-facing message list (no exceptions)
- Panelizer errors → caught, displayed to user (quotation still computes)
- Preset loading errors → raised immediately (fatal at startup)

## Anti-Patterns to Avoid

❌ **Don't**: Add Flask-specific logic to `manipulation.py`  
✓ **Do**: Keep `manipulation.py` pure; wrap calls in app if needed

❌ **Don't**: Hard-code cost tables or panel options in `price_quote()` or panelizer functions  
✓ **Do**: Pass them as function arguments or via `Params` dataclass

❌ **Don't**: Modify `DEFAULTS` directly outside the preset system  
✓ **Do**: Update via `_persist_defaults()` to keep in-memory state + disk sync

❌ **Don't**: Add new panelizer layout algorithms directly in app_qp.py  
✓ **Do**: Add to `manipulation.py` under panelizer module section

❌ **Don't**: Change preset JSON structure without updating `_deep_merge()` or loader  
✓ **Do**: Document schema changes in commit message

## File Locations & Key References

| File | Purpose |
|------|---------|
| `app_qp.py` | Flask web layer + form/validation logic |
| `manipulation.py` | Pure quotation + panelizer computation |
| `presets_qp.json` | Base configuration (repo-checked) |
| `presets_qp.local.json` | Local overrides (git-ignored) |
| `templates/index_qp.html` | Web UI form + results display |
| `static/{panel.css, qp.css}` | Styling |

## Circular Import Prevention

- `manipulation.py` imports: `math`, `dataclasses`, `typing` only (NO Flask)
- `app_qp.py` imports: `Flask`, form utilities, `manipulation` (one-way dependency)
- Result: Safe to refactor panelizer or add new computation modules without breaking imports

---

**Last updated**: November 2025  
**Refactored**: Panelizer logic moved from app_qp.py → manipulation.py module (v1.0+)
