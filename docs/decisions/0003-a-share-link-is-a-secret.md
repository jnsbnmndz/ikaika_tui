# 3. A share link is a secret, and the checksum is what gets committed

> **Status: ACCEPTED (2026-09-08).** Supersedes the split described in `scripts/lib/signing.ps1`'s header before this record: `share.cert` and `share.debugCert` moved out of the committed `.dti_configs/share.env` and into the gitignored `.dti_configs/signing.env`, with `DTI_CERT_SHARE_URL` and `DTI_DEBUG_CERT_SHARE_URL` as the CI half. Enforced by the `secrets` check in `scripts/check-all.ps1`.

## 1. Context

Signing needs two certificates — a release identity and a debug one, so that testing never
spends the trust the real signature has built up. Neither `.pfx` can be committed, so each
one arrives over a share link, and the toolbox has to know two things per certificate:
where to fetch it, and how to tell whether what arrived is the right file.

The original split put the link in a committed file and the password in a gitignored one,
and argued that this was safe because the two halves are independent: fetching the file
gets you a container you cannot open. That argument is correct about the *password*. It is
wrong about what a link is.

A Dropbox `/scl/fi/` link carries an `rlkey`, and the `rlkey` is not a path — it is the
capability. Anyone holding the link can fetch the container. That is a smaller loss than
the private key in the clear, but it is not nothing: it is an attacker's starting point
that costs them nothing to collect, and it names the folder the signing keys live in.

Worse, and independent of how sensitive the link is: **a committed link cannot be
rotated.** Revoking a secret is an edit in a settings page. Revoking a committed link means
a new link *and* a rewrite of the history of every clone that ever pulled the old one, and
nobody does the second half. So the one artefact that was chosen to be committed is
precisely the one whose exposure is permanent.

## 2. Decision

### 2.1 Both links are secrets, one link per secret

| Secret | Holds |
|---|---|
| `DTI_CERT_PASSWORD` | the password that opens both `.pfx` files |
| `DTI_CERT_SHARE_URL` | one link to `release.pfx` |
| `DTI_DEBUG_CERT_SHARE_URL` | one link to `debug.pfx` |

Two secrets rather than one, because there are two certificates and the fetch verifies
what arrives against a **per-file** committed SHA-256. One link cannot serve both: the
bytes would fail the other's sidecar, which is the check working, not a bug in it.

### 2.2 Locally they are in `signing.env`, beside the password

The gitignored file already holds the password and is already read with an environment
fallback for CI. The links join it under the same key names they had (`share.cert`,
`share.debugCert`), so the only thing that changed is which file they are in.

`Get-ShareUrl` resolves them in the same order `Get-CertPassword` uses — the file first,
the environment last — and also accepts the *variable* name as a key in the file, so a
value copied out of the repository secrets pastes in under the name it already has.

The order is not a precedence anybody has to remember, because nothing has both sources: a
laptop has the file and no variables, a runner has the variables and no file. The file is
the one thing a clone cannot bring with it, which is the whole reason the environment half
exists.

### 2.3 `share.env` stays committed, and carries only the publisher subject

The certificate subject is genuinely not a secret, and it has to be identical everywhere —
`signtool` refuses to sign when the publisher and the certificate's own subject disagree,
so two machines reading two different values is a build that fails on one of them.

### 2.4 The checksums stay committed, and they are the point

`.dti_configs/*.pfx.sha256` is the half that is safe to publish and the only thing that can
tell a fetched certificate from a same-named different one. Moving the link out does not
weaken it; it removes the only committed artefact that was doing double duty as a
credential.

## 3. Consequences

- `setup-signing` **migrates**: a link still sitting in `share.env` is copied into
  `signing.env`, blanked in the committed file, and reported — with a line saying to rotate
  it, because it has been in the repository.
- `check-all` grows a `secrets` check that FAILs when `share.env` carries either link.
  FAIL, not warn: that is the repository being wrong rather than the machine being
  incomplete, which is the line the rest of that script's SKIP/FAIL split is drawn on.
- The release workflow names all three secrets up front and exits 1 with the missing ones
  listed, rather than letting the fetch fail. The fetch cannot tell an unset secret from a
  revoked link, and one of those is fixed in a settings page while the other means
  uploading a certificate again.
- A new machine needs three values out of band instead of one. That is the cost, and it is
  paid once per machine.

## 4. Alternatives rejected

**Leave the link committed.** The argument for it — the password is not there — is true and
answers a different question. It does not survive "how would you revoke this link", which
is the question that actually matters, because the answer is "I cannot".

**Put the `.pfx` in a secret as base64 and drop the link entirely.** Tempting: one secret,
no host to normalise, no HTML-preview failure mode. Rejected because it makes CI the only
place a certificate can come from — a laptop with a secret pasted into a file is now
holding the private key in the clear in a second place, and the sidecar has nothing to
verify against a value that *is* the file. The link plus the committed checksum keeps one
copy of the key and one way to prove it arrived intact.

**A single secret holding a folder link.** One link, both certificates. Rejected: a folder
link answers with a web page, which is exactly the failure `Test-LooksLikeHtml` exists to
catch, and the per-file checksum has nothing to check.

**Keep reading `share.env` as a fallback, for compatibility.** Three sources for one value,
two of which contradict the decision. The migration in `setup-signing` does the same job
once and then the question is settled.
