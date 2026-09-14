# 3. A share link is a secret, and the checksum is what gets committed

> **Status: ACCEPTED (2026-09-08).** Links live in the gitignored `.dti_configs/signing.env`, with `DTI_CERT_SHARE_URL` and `DTI_DEBUG_CERT_SHARE_URL` as the CI half. Enforced by the `secrets` check in `check-all`.

## Context

Signing needs two certificates — release and debug — so testing never spends the trust the
real signature has built. Neither `.pfx` can be committed, so each arrives over a share
link, and the toolbox needs to know where to fetch it and how to tell what arrived is the
right file.

The original split committed the link and gitignored the password, arguing the halves are
independent. That is correct about the password and wrong about the link: a Dropbox link's
`rlkey` **is** the capability, so anyone holding it can fetch the container.

Worse, and independent of sensitivity: **a committed link cannot be rotated.** Revoking a
secret is an edit in a settings page; revoking a committed link means a new link *and*
rewriting the history of every clone that pulled the old one. The one artefact chosen to be
committed is precisely the one whose exposure is permanent.

## Decision

**Both links are secrets, one link per secret** — `DTI_CERT_SHARE_URL` and
`DTI_DEBUG_CERT_SHARE_URL`, beside `DTI_CERT_PASSWORD`. Two rather than one because the
fetch verifies each file against a **per-file** committed SHA-256; one link cannot serve
both, since the bytes would fail the other's sidecar.

Locally they sit in `signing.env` beside the password, resolved file-first then
environment. Nothing has both sources — a laptop has the file, a runner has the variables.

`share.env` stays committed carrying **only the publisher subject**, which is not a secret
and has to be identical everywhere: `signtool` refuses to sign when the publisher and the
certificate's subject disagree.

The `.pfx.sha256` sidecars stay committed and are the point — the only thing that can tell
a fetched certificate from a same-named different one.

## Consequences

- `setup-signing` **migrates**: a link still in `share.env` is copied across, blanked, and
  reported with a line saying to rotate it, because it has been in the repository.
- `check-all` FAILs when `share.env` carries either link — the repository being wrong, not
  the machine being incomplete.
- The release workflow names all three secrets up front and exits with the missing ones
  listed; the fetch cannot tell an unset secret from a revoked link.

## Alternatives rejected

- **Leave the link committed.** The argument for it answers a different question, and does
  not survive "how would you revoke this".
- **Put the `.pfx` in a secret as base64.** Makes CI the only place a certificate can come
  from, and a laptop with it pasted into a file holds the private key in the clear in a
  second place. The sidecar has nothing to verify against a value that *is* the file.
- **One folder link for both.** A folder link answers with a web page, and the per-file
  checksum has nothing to check.
