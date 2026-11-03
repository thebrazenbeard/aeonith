# Optional trusted-release static-asset digest policy

Aeonith's local editor remains editable by default. The process serves the
four known public assets from a source checkout or installed wheel and already
rejects unsafe filesystem nodes. Those node checks **do not** establish that
ordinary regular-file bytes came from an approved release.

An operator deploying a **separately reviewed and verified exact release** may
set `AEONITH_STATIC_ASSET_SHA256_JSON` to a JSON object containing SHA-256
hex digests for **all four** files: `index.html`, `app.js`, `styles.css`, and
`docx-import-worker.js`. No file URLs, shell expansion, relative paths, or
auto-generated-on-start hashes are accepted. The server validates the entire
policy before binding its listener, then hashes the actual bytes from each
opened asset before serving them. Any mismatch returns HTTP 503 without
returning the candidate content. An absent variable preserves source-editing
behavior; a present but invalid/empty variable refuses startup.

The operator must derive these values from the *verified Git commit or wheel
artifact*, not by hashing a possibly modified live asset directory after
deployment. Regenerate a separately reviewed policy whenever the release
changes. The policy is deliberately optional because automatic pinning would
break live editing of the existing source checkout.

## Evidence boundary

- This is an opt-in **byte-drift alarm** with a trust assumption: the expected
  hashes and running code are protected from the actor who can modify assets.
- It does **not** authenticate a publisher, sign releases, establish trusted
  source custody, or enforce immutable filesystem ownership. If a same-user
  attacker can rewrite the policy/process code as well as the assets, a hash
  comparison is not an effective security boundary.
- Stronger production custody requires a **separate OS deployment owner** with
  write-denied assets for the serving process, plus verified release provenance
  and a recoverable upgrade path. Source/wheel CI alone does not implement it.
- No token, model, manuscript, paid service, Funnel exposure, service restart,
  or optimizer permission is involved in this option.
