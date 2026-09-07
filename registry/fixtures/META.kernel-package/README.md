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
intended behavior: the hash is the point.
