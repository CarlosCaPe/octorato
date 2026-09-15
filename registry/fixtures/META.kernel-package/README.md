# META.kernel-package fixture

Three sample package trees for `octo_pkg.py --selftest`. They are the violation and
benign pair of the PACKAGE gate, in package shape rather than hook-stdin shape:

| Tree | Leg | Expected |
|---|---|---|
| `signed/` | benign | installs, then verifies, syncs and uninstalls cleanly |
| `unsigned/` | violation | refused at the signature check; nothing copied |
| `tampered/` | violation | `tree_sha256` does not match the bytes; refused BEFORE the signature is checked |

No signature file ships here, and no key. The selftest mints a throwaway ed25519 key
with `ssh-keygen -t ed25519 -N ""` inside its sandbox, writes the matching
allowed-signers line, and signs `signed/skill.json` and `tampered/skill.json` at run
time. `tampered/` is signed on purpose: a valid signature over a manifest whose hash
does not match the tree is exactly the case that proves the tree check runs first.

`signed/` and `unsigned/` carry a real `tree_sha256` over their own files. Editing a
byte in either tree without recomputing it turns the selftest red, which is the
intended behavior: the hash is the point. So does a `chmod +x`: the digest covers
each file's path, its bytes and a normalized owner-execute bit, so re-run
`python3 scripts/octo_pkg.py hash <tree> --write` after ANY change here, mode
included. No signature is committed and none should be: the selftest signs these
trees at run time with its own throwaway key, and `ssh-keygen -Y sign` over an
existing `.sig` declines on EOF and keeps the old one, so a checked-in signature
would be verified against a key the sandbox does not have and the selftest would
go red.

`tampered/` is `signed/` with a different name and its `tree_sha256` zeroed. That
single field is the whole violation, so the pair stays one edit apart: put the real
hash back and it is a benign package again.
