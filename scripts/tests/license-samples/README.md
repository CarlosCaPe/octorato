# License samples

Verbatim published license texts, used as fixtures by `test_octo_pkg.py`.

They are here rather than read from `/usr/share/common-licenses` so the recognizer's
anchors are hermetic: that directory is a Debian convention, and a test that skips
where it is missing is not an anchor, it is a test that passes by not running.

`Apache-2.0` and `MIT` are not duplicated here. The repository already carries verbatim
copies as real skill licenses (`skills/cloudflare/LICENSE`, `skills/gsap-core/LICENSE`),
and a fixture that is also a shipped file is a fixture that cannot drift from one.

| File | Source |
|---|---|
| `GPL-3.0.txt` | GNU General Public License v3, 29 June 2007, verbatim |
| `MPL-2.0.txt` | Mozilla Public License 2.0, verbatim |
| `AGPL-3.0.txt` | GNU Affero General Public License v3, 19 November 2007, verbatim (fetched from `mastodon/mastodon` `LICENSE` via the GitHub API) |

`AGPL-3.0.txt` was added because it was the one recognizer of the six with no fixture
at all. The tests asserted that every recognizer reads a license whole, and proved it
for five: the sixth was covered by the sentence, not by a test. There is no AGPL text
in `/usr/share/common-licenses`, so it comes from a project that ships the license
verbatim rather than from a directory this machine happens to have.
