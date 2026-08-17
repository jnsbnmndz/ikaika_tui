# Completion gates
Run all before handoff:
1. `python -m unittest discover`
2. `python -m company_tui list`
3. `python -m company_tui doctor`
4. After source edits: `graphify update .`
Also confirm new external interactions are behind ports, new capabilities are composed only in `bootstrap.py`, and existing capabilities remain independently runnable.