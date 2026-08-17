# Project core
- Python developer-toolbox TUI with inward dependency flow: presentation/infrastructure/capabilities/templates → domain; application orchestrates; `bootstrap.py` is the sole composition root.
- Capabilities are independent and registered in `bootstrap.py`; interactive workflows remain async end-to-end.
- UI architecture and invariants: `mem:ui/core`.
- Stack and commands: `mem:tech_stack`, `mem:suggested_commands`.
- Engineering conventions and completion gates: `mem:conventions`, `mem:task_completion`.