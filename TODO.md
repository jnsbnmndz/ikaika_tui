# TODO

Open items only. Finished work is described in `CLAUDE.md`, recorded in
`docs/decisions/`, and in git history — a plan is the wrong place for a retrospective.

## Smaller open items (DON'T TOUCH IT FOR NOW)

- **Generator folders are guesses.** `app/screens`, `components`, `services`, `hooks` for
  React Native, and `tests` for Python. They are editable in the form, but should default
  to the real layout of the structure repo. Confirm and correct.
- **Flutter and React packs are stubs.** Both return `available=False`. Once there is a
  structure repo for each, they become a `TemplateSource` plus an `IdentityRewrite` for the
  file carrying the project's name — `pubspec.yaml` for Flutter, `package.json` for React —
  and follow `templates/react_native/`.
- **`build` only reports the Python version.** It does not build anything.
- **`deploy` is a placeholder.** `scripts` is not: it reads the `dti.script.json` a project
  carries and runs what that declares (`docs/decisions/0001`).
- **Doctor never fails.** It reports a missing tool and still exits 0, so it cannot gate
  anything in CI. Deliberate for now; revisit if that changes.
- **Other noisy commands want `QuietRun`.** `npm install` goes through it. Gradle,
  `flutter pub get`, `pod install` and `pip install` are the same shape and should use it
  when those packs land. `git clone` deliberately does not — its output is short, and the
  progress percentages are the reassurance that something is happening.
