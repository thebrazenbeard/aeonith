# Pinned upstream byte expectations (public metadata)

`qwen3.5-0.8b-2fc06364715b967f1860aea9cf38778875588b17.json` is a
`training.verify_base`-compatible expectation for the **runtime files only**
from public, ungated [Qwen/Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B),
revision `2fc06364715b967f1860aea9cf38778875588b17`.

On 2026-11-03 the download operator retrieved the exact immutable revision
through the publisher's HTTPS model API, compared small-file Git blob OIDs
against the pinned `/tree/<revision>?recursive=true` API, compared LFS payload
SHA-256 against the pinned `/revision/<revision>?blobs=true` metadata, and
independently rehashed the materialized files on the authorized host. The
included SHA-256 values are the observed content digests. The full 12-file
snapshot also includes `LICENSE` and `README.md`, excluded here because
`verify_base` fingerprints only model-loading assets.

On the same authorized Windows host, an independent replay of the exact
`training/verify_base.py` source (SHA-256
`2e9d04d3213feef4e7bbcb5f2ddc00b127b838e20ebf8d83f06cd36d7df5b52f`)
returned `local_bytes_match_supplied_manifest_not_origin_authenticated`,
with **ten runtime files and one safetensors weight shard** checked. The
separate manifest copy matched this repository file byte-for-byte (SHA-256
`d62ec533ddd50102ba8aeaa3682422be51f757e941aab2cd7312303fd4687035`).
No model was loaded, no optimizer ran, and no adapter was created.

This manifest contains **no model weights, training data, credentials, private
paths, or user content**. Its Git publication is not a publisher signature,
does not independently authenticate the HF account or revisions, and does not
prove the bytes are safe to execute, a model loads, gradients update, or an
adapter passes evaluation. `training.verify_base` is a local comparison gate,
not a training or publisher-authentication proof.

Use a **separate owner-private copy** of this manifest outside the checkpoint
directory when running `training.verify_base`. Never place it among the model
runtime files or commit downloaded weights to this repository.
