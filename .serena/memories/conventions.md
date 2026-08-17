# Code conventions
- Focused lowercase `snake_case` modules; preserve type hints and async interaction chain.
- New capabilities remain independent and are wired only in `bootstrap.py`.
- OS/external access goes behind domain ports; never use shell command strings or `shell=True`.
- Validate paths/input before writes or execution; destructive operations default to dry-run plus explicit confirmation.
- No dependencies unless stdlib is insufficient; no narrating comments.
- Cancellation from the first step returns `CANCELLED`; later cancellation walks back one step.
- Test every new decision and error boundary.