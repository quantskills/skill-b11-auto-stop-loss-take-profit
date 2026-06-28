# Multi-Platform Install Guide

This package contains 1 QuantSkills skill: `skill-b11-auto-stop-loss-take-profit`.

---

## Claude Code

Copy this entire repository directory to your Claude Code skills folder:

```bash
# macOS / Linux
cp -R skill-b11-auto-stop-loss-take-profit ~/.claude/skills/
```

```powershell
# Windows (PowerShell)
New-Item -ItemType Directory -Force "$HOME\.claude\skills"
Copy-Item ".\" "$HOME\.claude\skills\skill-b11-auto-stop-loss-take-profit" -Recurse -Force
```

After installation, invoke in Claude Code:

```
/skill-b11-auto-stop-loss-take-profit
```

Requirements: Python 3.8+ (standard library only, zero third-party dependencies).

---

## Codex (OpenAI)

This skill can be used as a function/tool definition for OpenAI Codex agents.

### As a Codex Tool

Add to your Codex SDK configuration:

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "skill_b11_auto_stop_loss_take_profit",
        "description": "Automated stop-loss, take-profit, and position sizing for A-shares and futures. Supports next-day gap-up take-profit (+5%), next-day gap-down stop-loss (-3%), forced liquidation on holding timeout (≥2 days), and single-stock position cap (>10%). Input: positions list with entry_price, entry_date, current_qty, open_price, available_cash, today. Output: standardized 8-field position adjustment orders.",
        "parameters": {
          "type": "object",
          "properties": {
            "positions": {
              "type": "array",
              "description": "List of position objects",
              "items": {
                "type": "object",
                "properties": {
                  "code": {"type": "string"},
                  "entry_price": {"type": "number"},
                  "entry_date": {"type": "string"},
                  "current_qty": {"type": "integer"},
                  "open_price": {"type": "number"},
                  "available_cash": {"type": "number"},
                  "today": {"type": "string"}
                },
                "required": ["code", "entry_price", "entry_date", "current_qty", "open_price", "available_cash", "today"]
              }
            }
          },
          "required": ["positions"]
        }
      }
    }
  ]
}
```

### Running Locally

```bash
cd skill-b11-auto-stop-loss-take-profit/scripts
python3 build.py
```

The build script is callable from any Codex-managed Python runtime:

```python
import sys
sys.path.insert(0, "/path/to/skill-b11-auto-stop-loss-take-profit/scripts")
from build import run
results = run(positions)
```

---

## Cursor

This skill is compatible with Cursor's custom tools and `.cursorrules`.

### As a Cursor Tool

Add to `.cursor/tools.json` or your project's tool configuration:

```json
{
  "name": "b11-stop-loss-take-profit",
  "description": "Auto stop-loss, take-profit, and position sizing for A-shares and futures",
  "command": "python3",
  "args": ["${WORKSPACE}/skill-b11-auto-stop-loss-take-profit/scripts/build.py"],
  "env": {}
}
```

### As a Cursor Rule

Add to `.cursorrules`:

```
When the user asks about stop-loss, take-profit, forced liquidation, or position sizing for A-shares or futures, use the b11-stop-loss-take-profit skill.

The skill expects 7 input fields per position: code, entry_price, entry_date, current_qty, open_price, available_cash, today.

Run: python3 skill-b11-auto-stop-loss-take-profit/scripts/build.py
```

---

## Hermes

This skill integrates with Hermes as a callable Python module.

### Registering the Skill

In your Hermes skill registry:

```yaml
# hermes_skills.yml
skills:
  b11-auto-stop-loss-take-profit:
    name: skill-b11-auto-stop-loss-take-profit
    type: build
    runtime: python3
    entry: skill-b11-auto-stop-loss-take-profit/scripts/build.py
    description: >
      Automated stop-loss, take-profit, and position sizing for A-shares and futures.
      Four-level priority: next-day take-profit (+5%) → next-day stop-loss (-3%) →
      holding timeout force-close (≥2 days) → single-stock cap (>10%).
    input_schema:
      type: array
      items:
        code: string
        entry_price: float
        entry_date: string
        current_qty: integer
        open_price: float
        available_cash: float
        today: string
    constraints:
      - zero third-party dependencies
      - pure Python standard library
      - research and educational use only
```

### Calling from Hermes

```python
response = hermes.call_skill("b11-auto-stop-loss-take-profit", positions)
```

---

## OpenClaw

This skill can be registered as an OpenClaw tool.

### Tool Configuration

```yaml
# openclaw_tools.yaml
- name: stop_loss_take_profit_b11
  description: >
    Automated stop-loss, take-profit, and position sizing for A-shares and futures.
    Four-level priority engine with holding-day-aware force close.
  type: local
  runtime: python3
  entrypoint: skill-b11-auto-stop-loss-take-profit/scripts/build.py
  schema:
    input:
      type: array
      description: List of position snapshots
      items:
        type: object
        required: [code, entry_price, entry_date, current_qty, open_price, available_cash, today]
        properties:
          code: {type: string, description: "Asset code (e.g., 600036, IF2406)"}
          entry_price: {type: number, description: "Entry price"}
          entry_date: {type: string, description: "Entry date YYYY-MM-DD"}
          current_qty: {type: integer, description: "Current position quantity"}
          open_price: {type: number, description: "Today's open price"}
          available_cash: {type: number, description: "Available cash"}
          today: {type: string, description: "Current date YYYY-MM-DD"}
  limits:
    max_positions_per_call: 1000
  notes: |
    Research and educational use only. No investment advice.
    Zero third-party dependencies. Python 3.8+ standard library only.
```

---

## Usage Boundaries (All Platforms)

- **Research & educational use only** — not investment advice.
- Caller supplies all position data; this skill does not fetch market data.
- Long-only; no short/hedge positions.
- Does not account for price limits, trading halts, liquidity, or slippage.
- Dates are calendar days; may misjudge holding periods on non-trading days.
- See `SKILL.md` for full limitations and `README.md` / `README.en.md` for project overview.
