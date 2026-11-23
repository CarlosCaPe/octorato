#!/usr/bin/env python3
"""
secret_handoff.py: hand credentials to end users without anyone in the
middle reading them.

The value travels AWS Secrets Manager -> this process's memory -> one small
HTML page per recipient in a private S3 bucket. The only thing that comes out
is a presigned GET URL per recipient. The value is never printed, logged or
written to local disk, so it never enters a terminal scrollback, an agent
transcript or a shell history.

Modes (exactly one):
  (default)       publish: read the secret, write one page per key, sign URLs
  --verify        GET every URL in the links file; print status, byte length
                  and whether the account marker is present. Never the body.
  --revoke        delete the objects (all versions) so the URLs stop working
  --init-bucket   create or harden the bucket: Block Public Access, default
                  SSE-AES256, lifecycle expiry on the prefix

Every mode that changes something is a preview unless --execute is passed.

The secret must be a SecretString holding a JSON object that maps a key
(usually the username) to its value (the password):
    {"alice": "...", "bob": "..."}

Examples:
  secret_handoff.py --init-bucket --bucket BUCKET --region REGION --execute
  secret_handoff.py --secret-id SECRET --keys alice,bob --bucket BUCKET \
      --expires-in 43200 --links ./links.json --profile PROFILE --execute
  secret_handoff.py --verify --links ./links.json
  secret_handoff.py --revoke --links ./links.json --profile PROFILE --execute
  secret_handoff.py --verify --links ./links.json --expect-gone

Requires boto3 for every mode except --verify (stdlib only).

Residual risks are documented in
skills/zero-knowledge-credential-handoff/SKILL.md. Read them before use: a
presigned URL is a bearer token until it expires, and it is not one-time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import secrets
import sys
import urllib.error
import urllib.request

MAX_EXPIRES = 604800  # SigV4 ceiling for a presigned URL: 7 days
DEFAULT_EXPIRES = 43200  # 12 h
DEFAULT_PREFIX = "handoff/"
LIFECYCLE_RULE_ID = "secret-handoff-expiry"
DEFAULT_NOTE = (
    "Type it exactly as shown, including capital letters and symbols. "
    "This link stops working in a few hours. Do not forward it."
)


class HandoffError(Exception):
    """An error whose message is safe to print (never contains a secret)."""


# ----------------------------------------------------------------- helpers

def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _split_keys(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    for chunk in raw or []:
        for name in chunk.split(","):
            name = name.strip()
            if name and name not in out:
                out.append(name)
    return out


def _name_dir(prefix: str, name: str) -> str:
    """Object-key directory for one recipient. Hashed, so the recipient name
    does not appear in the URL."""
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}{digest}/"


def _normalize_prefix(prefix: str) -> str:
    prefix = prefix.lstrip("/")
    if not prefix:
        raise HandoffError("--prefix must not be empty: revoke and lifecycle are scoped to it")
    return prefix if prefix.endswith("/") else prefix + "/"


def _session(args):
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise HandoffError("boto3 is required for this mode (pip install --user boto3)")
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    cfg = Config(signature_version="s3v4", s3={"addressing_style": "virtual"})
    return session, session.client("s3", config=cfg)


def _client_error_code(exc: Exception) -> str:
    return str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))


def _load_links(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise HandoffError(f"links file not found: {path}")
    except ValueError:
        raise HandoffError(f"links file is not valid JSON: {path}")
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        raise HandoffError(f"links file has no 'entries' object: {path}")
    return data


def _write_links(path: str, data: dict) -> None:
    """Write the links file with owner-only permissions. It holds bearer URLs."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
        fh.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # filesystems without POSIX modes


def _page(title: str, account: str, value: str, note: str) -> bytes:
    """Self-contained page: no scripts, no external resources, no referrer."""
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width'>"
        "<meta name=robots content='noindex,nofollow,noarchive'>"
        "<meta name=referrer content=no-referrer>"
        "<meta http-equiv=Content-Security-Policy "
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>{html.escape(title)}</title>"
        "<body style='font-family:sans-serif;max-width:32em;margin:2em auto;"
        "padding:0 1em;font-size:1.2em'>"
        f"<p>Account: <b>{html.escape(account)}</b></p>"
        "<p>Password: <b style='font-family:monospace;font-size:1.3em;"
        f"word-break:break-all'>{html.escape(value)}</b></p>"
        f"<p>{html.escape(note)}</p></body></html>"
    ).encode("utf-8")


# ------------------------------------------------------------ bucket checks

def _preflight(s3, bucket: str, prefix: str) -> None:
    """Refuse to publish into a bucket that could be public. Fail closed."""
    try:
        cfg = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    except Exception as exc:  # noqa: BLE001
        code = _client_error_code(exc) or type(exc).__name__
        raise HandoffError(
            f"cannot confirm Block Public Access on the bucket ({code}). "
            "Run --init-bucket, or pass --skip-preflight if an account-level "
            "block already covers it."
        )
    wanted = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
    missing = [k for k in wanted if not cfg.get(k)]
    if missing:
        raise HandoffError(
            "Block Public Access is not fully on (" + ", ".join(missing) + "). Run --init-bucket."
        )
    try:
        rules = s3.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", [])
    except Exception:  # noqa: BLE001
        rules = []
    covered = False
    for rule in rules:
        if rule.get("Status") != "Enabled" or "Expiration" not in rule:
            continue
        flt = rule.get("Filter") or {}
        rule_prefix = flt.get("Prefix", rule.get("Prefix", "")) or ""
        if prefix.startswith(rule_prefix) and not (set(flt) - {"Prefix"}):
            covered = True
    if not covered:
        print(
            "warning: no enabled lifecycle expiry covers this prefix. Objects "
            "will outlive their URLs until revoked. Run --init-bucket.",
            file=sys.stderr,
        )


def _list_versions(s3, bucket: str, prefix: str) -> list[dict]:
    """Every version and delete marker under a prefix. Falls back to the
    current-version listing when the caller cannot list versions."""
    found: list[dict] = []
    try:
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Versions", []) + page.get("DeleteMarkers", []):
                found.append({"Key": item["Key"], "VersionId": item["VersionId"]})
        return found
    except Exception as exc:  # noqa: BLE001
        if _client_error_code(exc) not in ("AccessDenied", "NotImplemented"):
            raise
    print(
        "warning: cannot list object versions; deleting current versions only. "
        "On a versioned bucket the old bytes stay until lifecycle removes them.",
        file=sys.stderr,
    )
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            found.append({"Key": item["Key"]})
    return found


def _delete(s3, bucket: str, objects: list[dict]) -> int:
    failed = 0
    for i in range(0, len(objects), 1000):
        resp = s3.delete_objects(
            Bucket=bucket, Delete={"Objects": objects[i : i + 1000], "Quiet": True}
        )
        failed += len(resp.get("Errors", []))
    return failed


# -------------------------------------------------------------------- modes

def cmd_init_bucket(args) -> int:
    if not args.bucket:
        raise HandoffError("--init-bucket needs --bucket")
    prefix = _normalize_prefix(args.prefix)
    session, s3 = _session(args)
    region = session.region_name
    exists = True
    try:
        s3.head_bucket(Bucket=args.bucket)
    except Exception as exc:  # noqa: BLE001
        if _client_error_code(exc) in ("404", "NoSuchBucket", "NotFound"):
            exists = False
        else:
            raise
    plan = [
        "create bucket" if not exists else "bucket exists",
        "Block Public Access: all four settings on",
        "default encryption: SSE-AES256",
        f"lifecycle rule '{LIFECYCLE_RULE_ID}': expire {prefix}* after "
        f"{args.lifecycle_days} day(s), noncurrent versions after 1 day",
    ]
    for step in plan:
        print("plan:", step)
    if not args.execute:
        print("PREVIEW ONLY. Nothing changed. Re-run with --execute.")
        return 2
    if not exists:
        kwargs = {"Bucket": args.bucket}
        if region and region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**kwargs)
    s3.put_public_access_block(
        Bucket=args.bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket=args.bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    # Lifecycle PUT replaces the whole configuration, so merge with what exists.
    try:
        rules = s3.get_bucket_lifecycle_configuration(Bucket=args.bucket).get("Rules", [])
    except Exception as exc:  # noqa: BLE001
        if _client_error_code(exc) != "NoSuchLifecycleConfiguration":
            raise
        rules = []
    rules = [r for r in rules if r.get("ID") != LIFECYCLE_RULE_ID]
    rules.append(
        {
            "ID": LIFECYCLE_RULE_ID,
            "Status": "Enabled",
            "Filter": {"Prefix": prefix},
            "Expiration": {"Days": args.lifecycle_days},
            "NoncurrentVersionExpiration": {"NoncurrentDays": 1},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
        }
    )
    s3.put_bucket_lifecycle_configuration(
        Bucket=args.bucket, LifecycleConfiguration={"Rules": rules}
    )
    print("bucket ready")
    return 0


def cmd_publish(args) -> int:
    names = _split_keys(args.keys)
    for flag, value in (("--secret-id", args.secret_id), ("--bucket", args.bucket),
                        ("--keys", names), ("--links", args.links)):
        if not value:
            raise HandoffError(f"publish needs {flag}")
    if not 60 <= args.expires_in <= MAX_EXPIRES:
        raise HandoffError(f"--expires-in must be between 60 and {MAX_EXPIRES} seconds")
    if "{key}" not in args.account_format:
        raise HandoffError("--account-format must contain {key}")
    prefix = _normalize_prefix(args.prefix)
    session, s3 = _session(args)

    if not args.skip_preflight:
        _preflight(s3, args.bucket, prefix)

    creds = session.get_credentials()
    if creds is not None and getattr(creds, "token", None):
        print(
            "warning: signing with temporary credentials. Each URL dies when "
            "that session expires, which can be earlier than --expires-in.",
            file=sys.stderr,
        )

    try:
        raw = session.client("secretsmanager").get_secret_value(SecretId=args.secret_id)
    except Exception as exc:  # noqa: BLE001
        raise HandoffError(
            f"cannot read the secret ({_client_error_code(exc) or type(exc).__name__})"
        )
    if "SecretString" not in raw:
        raise HandoffError("the secret is binary; a JSON SecretString is required")
    try:
        values = json.loads(raw["SecretString"])
    except ValueError:
        # Deliberately generic: a decoder message could quote the content.
        raise HandoffError("the secret is not valid JSON; a JSON object is required")
    finally:
        del raw
    if not isinstance(values, dict):
        raise HandoffError("the secret must be a JSON object mapping key to value")
    missing = [n for n in names if n not in values]
    bad = [n for n in names if n in values and (not isinstance(values[n], str) or not values[n])]
    if missing or bad:
        del values
        raise HandoffError(
            "secret does not cover the request. missing keys: "
            + (", ".join(missing) or "none")
            + "; empty or non-string values: "
            + (", ".join(bad) or "none")
        )

    if not args.execute:
        del values
        for name in names:
            print(name, "WOULD-PUBLISH")
        print("PREVIEW ONLY. Nothing written. Re-run with --execute.")
        return 2

    created = _utcnow()
    expires = created + dt.timedelta(seconds=args.expires_in)
    entries: dict[str, dict] = {}
    if os.path.exists(args.links):
        previous = _load_links(args.links)
        if previous.get("bucket") == args.bucket and previous.get("prefix") == prefix:
            entries = dict(previous["entries"])

    for name in names:
        name_dir = _name_dir(prefix, name)
        # Remove earlier pages for this recipient so an older link cannot
        # outlive a re-publish.
        stale = _list_versions(s3, args.bucket, name_dir)
        if stale and _delete(s3, args.bucket, stale):
            del values
            raise HandoffError(f"could not remove the previous page for {name}")
        account = args.account_format.replace("{key}", name)
        object_key = f"{name_dir}{secrets.token_urlsafe(18)}.html"
        s3.put_object(
            Bucket=args.bucket,
            Key=object_key,
            Body=_page(args.title, account, values[name], args.note),
            ContentType="text/html; charset=utf-8",
            CacheControl="no-store",
            ServerSideEncryption="AES256",
        )
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": args.bucket, "Key": object_key},
            ExpiresIn=args.expires_in,
        )
        entries[name] = {
            "url": url,
            "object_key": object_key,
            "marker": account,
            "expires_at": expires.isoformat(),
        }
    del values  # best effort; Python cannot guarantee the memory is wiped

    _write_links(
        args.links,
        {"bucket": args.bucket, "prefix": prefix, "created_at": created.isoformat(),
         "entries": entries},
    )
    for name in names:
        line = f"{name} OK expires={entries[name]['expires_at']}"
        if args.print_urls:
            line += " " + entries[name]["url"]
        print(line)
    print(f"links file (bearer URLs, mode 0600): {args.links}")
    return 0


def cmd_verify(args) -> int:
    if not args.links:
        raise HandoffError("--verify needs --links")
    data = _load_links(args.links)
    names = _split_keys(args.keys) or list(data["entries"])
    failures = 0
    for name in names:
        entry = data["entries"].get(name)
        if not entry:
            print(name, "NOT-IN-LINKS-FILE")
            failures += 1
            continue
        url = entry.get("url", "")
        if not url.startswith("https://"):
            print(name, "REFUSED non-https URL")
            failures += 1
            continue
        try:
            with urllib.request.urlopen(url, timeout=args.timeout) as resp:  # noqa: S310
                body = resp.read()
                status = resp.status
                cache = resp.headers.get("Cache-Control", "")
                sse = resp.headers.get("x-amz-server-side-encryption", "")
        except urllib.error.HTTPError as exc:
            gone = exc.code in (403, 404)
            ok = gone and args.expect_gone
            print(name, exc.code, "GONE" if ok else "FAIL")
            failures += 0 if ok else 1
            continue
        except (urllib.error.URLError, OSError) as exc:
            print(name, "UNREACHABLE", type(exc).__name__)
            failures += 1
            continue
        if args.expect_gone:
            del body
            print(name, status, "FAIL still-served")
            failures += 1
            continue
        marker = html.escape(str(entry.get("marker", name))).encode("utf-8")
        checks = {
            "marker": marker in body,
            "no-store": "no-store" in cache.lower(),
            "sse": bool(sse),
        }
        size = len(body)
        del body  # never printed
        ok = status == 200 and size > 0 and all(checks.values())
        failures += 0 if ok else 1
        print(
            name, status, f"bytes={size}",
            " ".join(f"{k}={'yes' if v else 'NO'}" for k, v in checks.items()),
            "OK" if ok else "FAIL",
        )
    return 1 if failures else 0


def cmd_revoke(args) -> int:
    data = _load_links(args.links) if args.links and os.path.exists(args.links) else None
    bucket = args.bucket or (data or {}).get("bucket")
    if not bucket:
        raise HandoffError("--revoke needs --bucket or a --links file that names it")
    prefix = _normalize_prefix((data or {}).get("prefix") or args.prefix)
    names = _split_keys(args.keys)
    if args.all:
        targets = {"*": prefix}
    else:
        if not names and data:
            names = list(data["entries"])
        if not names:
            raise HandoffError("--revoke needs --keys, a --links file, or --all")
        targets = {n: _name_dir(prefix, n) for n in names}

    _, s3 = _session(args)
    failures = 0
    for name, target in targets.items():
        objects = _list_versions(s3, bucket, target)
        if not args.execute:
            print(name, f"WOULD-DELETE objects={len(objects)}")
            continue
        failed = _delete(s3, bucket, objects) if objects else 0
        left = len(_list_versions(s3, bucket, target))
        ok = not failed and not left
        failures += 0 if ok else 1
        print(name, f"deleted={len(objects) - failed}", f"remaining={left}",
              "REVOKED" if ok else "FAIL")
    if not args.execute:
        print("PREVIEW ONLY. NOTHING DELETED. The URLs still work. Re-run with --execute.")
        return 2
    if data is not None and not failures:
        if args.all:
            data["entries"] = {}
        else:
            for name in targets:
                data["entries"].pop(name, None)
        if data["entries"]:
            _write_links(args.links, data)
        else:
            os.remove(args.links)
            print(f"links file removed: {args.links}")
    return 1 if failures else 0


# --------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Zero-knowledge credential handoff: Secrets Manager to "
        "short-lived presigned S3 pages. The value is never printed.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true",
                      help="check every URL in the links file without printing the body")
    mode.add_argument("--revoke", action="store_true",
                      help="delete the objects so the URLs stop working")
    mode.add_argument("--init-bucket", action="store_true",
                      help="create or harden the bucket")

    p.add_argument("--secret-id", help="Secrets Manager secret id or ARN (JSON object)")
    p.add_argument("--keys", action="append", metavar="K1,K2",
                   help="keys inside the secret, one page each; comma-separated or repeated")
    p.add_argument("--bucket", help="private S3 bucket")
    p.add_argument("--prefix", default=DEFAULT_PREFIX,
                   help=f"object-key prefix (default {DEFAULT_PREFIX})")
    p.add_argument("--expires-in", type=int, default=DEFAULT_EXPIRES, metavar="SECONDS",
                   help=f"URL lifetime (default {DEFAULT_EXPIRES}, max {MAX_EXPIRES})")
    p.add_argument("--profile", help="AWS profile name")
    p.add_argument("--region", help="AWS region")
    p.add_argument("--links", metavar="FILE",
                   help="JSON file of URLs: written by publish, read by --verify and --revoke")
    p.add_argument("--account-format", default="{key}", metavar="FMT",
                   help=r"how the account is shown on the page, e.g. 'DOMAIN\{key}'")
    p.add_argument("--title", default="Account access", help="page title")
    p.add_argument("--note", default=DEFAULT_NOTE, help="instruction line shown on the page")
    p.add_argument("--print-urls", action="store_true",
                   help="also print each URL to stdout (it then lands in logs and transcripts)")
    p.add_argument("--skip-preflight", action="store_true",
                   help="publish without confirming bucket-level Block Public Access")
    p.add_argument("--lifecycle-days", type=int, default=2,
                   help="--init-bucket: expire objects after N days (default 2)")
    p.add_argument("--expect-gone", action="store_true",
                   help="--verify: pass only when every URL returns 403 or 404")
    p.add_argument("--all", action="store_true",
                   help="--revoke: delete everything under the prefix")
    p.add_argument("--timeout", type=float, default=20.0, help="--verify: seconds per request")
    p.add_argument("--execute", action="store_true",
                   help="apply changes; without it publish, revoke and init-bucket only preview")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify:
            return cmd_verify(args)
        if args.revoke:
            return cmd_revoke(args)
        if args.init_bucket:
            return cmd_init_bucket(args)
        return cmd_publish(args)
    except HandoffError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        # No traceback and no exception text: neither may carry secret content.
        code = _client_error_code(exc)
        print(f"error: {type(exc).__name__}" + (f" ({code})" if code else ""), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
