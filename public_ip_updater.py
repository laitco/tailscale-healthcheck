"""Synchronize DynDNS IPv4 addresses into Tailscale posture rules.

The Tailscale policy is HuJSON, so this module tokenizes just enough of the
document to replace the address inside a named posture without normalizing or
rewriting any unrelated bytes.
"""
from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import dbstore


API_BASE = "https://api.tailscale.com/api/v2"
RULE_RE = re.compile(r"^(\s*ip:publicAddress\s*(?:==|!=)\s*')([^']+)('\s*)$")
BACKUP_PREFIX = "tailscale-policy-"


class UpdateError(Exception):
    """A safe, expected synchronization failure."""


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    start: int
    end: int


def validate_public_ipv4(value: str, source: str) -> str:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise UpdateError(f"{source} returned an invalid IP address: {value!r}") from exc
    if address.version != 4 or not address.is_global:
        raise UpdateError(f"{source} returned a non-public IPv4 address: {address}")
    return str(address)


def resolve_public_ipv4(hostname: str) -> str:
    try:
        answers = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UpdateError(f"DNS lookup for {hostname!r} failed: {exc}") from exc
    public = []
    for value in sorted({answer[4][0] for answer in answers}, key=ipaddress.ip_address):
        try:
            public.append(validate_public_ipv4(value, f"DNS hostname {hostname!r}"))
        except UpdateError:
            continue
    if not public:
        raise UpdateError(f"DNS hostname {hostname!r} returned no public IPv4 address")
    return public[0]


def _decode_json_string(raw: str) -> str:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise UpdateError(f"Invalid string token in policy: {raw[:80]!r}") from exc
    if not isinstance(value, str):
        raise UpdateError("Internal parser error: expected a string")
    return value


def tokens(text: str) -> list[Token]:
    result = []
    i = 0
    while i < len(text):
        char = text[i]
        if char.isspace():
            i += 1
        elif text.startswith("//", i):
            newline = text.find("\n", i + 2)
            i = len(text) if newline < 0 else newline + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise UpdateError("Unterminated block comment in HuJSON policy")
            i = end + 2
        elif char == '"':
            start = i
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            else:
                raise UpdateError("Unterminated string in HuJSON policy")
            result.append(Token("string", _decode_json_string(text[start:i]), start, i))
        elif char in "{}[]:,":
            result.append(Token(char, char, i, i + 1))
            i += 1
        else:
            start = i
            while i < len(text) and not text[i].isspace() and text[i] not in '{}[]:,"':
                if text.startswith("//", i) or text.startswith("/*", i):
                    break
                i += 1
            if start == i:
                raise UpdateError(f"Unexpected character at policy offset {i}")
            result.append(Token("bare", text[start:i], start, i))
    return result


def _find_matching(items, start, opening, closing):
    depth = 0
    for index in range(start, len(items)):
        if items[index].kind == opening:
            depth += 1
        elif items[index].kind == closing:
            depth -= 1
            if depth == 0:
                return index
    raise UpdateError(f"Unbalanced {opening}{closing} in policy")


def _object_members(items, start, end):
    members = []
    i = start + 1
    while i < end:
        if items[i].kind == ",":
            i += 1
            continue
        if items[i].kind != "string" or i + 1 >= end or items[i + 1].kind != ":":
            raise UpdateError(f"Malformed HuJSON object near offset {items[i].start}")
        value_start = i + 2
        if value_start >= end:
            raise UpdateError("Missing value in HuJSON object")
        kind = items[value_start].kind
        value_end = _find_matching(items, value_start, kind, "}" if kind == "{" else "]") if kind in ("{", "[") else value_start
        members.append((items[i].value, value_start, value_end))
        i = value_end + 1
        if i < end and items[i].kind == ",":
            i += 1
    return members


def locate_rule(text: str, posture_name: str):
    items = tokens(text)
    if not items or items[0].kind != "{":
        raise UpdateError("Policy root is not a HuJSON object")
    root_end = _find_matching(items, 0, "{", "}")
    if root_end != len(items) - 1:
        raise UpdateError("Unexpected content after policy root object")
    sections = [(a, b) for key, a, b in _object_members(items, 0, root_end) if key == "postures"]
    if len(sections) != 1:
        raise UpdateError(f"Top-level 'postures' must exist exactly once; found {len(sections)}")
    postures_start, postures_end = sections[0]
    if items[postures_start].kind != "{":
        raise UpdateError("Top-level 'postures' value is not an object")
    matches = [(a, b) for key, a, b in _object_members(items, postures_start, postures_end) if key == posture_name]
    if len(matches) != 1:
        raise UpdateError(f"{posture_name!r} must exist exactly once; found {len(matches)}")
    array_start, array_end = matches[0]
    if items[array_start].kind != "[":
        raise UpdateError(f"{posture_name!r} must be an array")
    values = [token for token in items[array_start + 1:array_end] if token.kind != ","]
    if len(values) != 1 or values[0].kind != "string":
        raise UpdateError(f"{posture_name!r} must contain exactly one string rule")
    match = RULE_RE.fullmatch(values[0].value)
    if not match:
        raise UpdateError(f"{posture_name!r} must contain exactly one ip:publicAddress == or != rule")
    old_ip = validate_public_ipv4(match.group(2), "Configured posture rule")
    raw = text[values[0].start:values[0].end]
    offset = raw.find(match.group(2))
    if offset < 0 or raw.count(match.group(2)) != 1:
        raise UpdateError("Could not uniquely locate the configured IP token")
    start = values[0].start + offset
    return old_ip, start, start + len(match.group(2))


def update_rules(policy: str, replacements: dict[str, str]):
    located = []
    old_ips = {}
    for posture_name, new_ip in replacements.items():
        validate_public_ipv4(new_ip, "New address")
        old_ip, start, end = locate_rule(policy, posture_name)
        located.append((start, end, new_ip))
        old_ips[posture_name] = old_ip
    changed = policy
    for start, end, new_ip in sorted(located, reverse=True):
        changed = changed[:start] + new_ip + changed[end:]
    for posture_name, new_ip in replacements.items():
        verified, _start, _end = locate_rule(changed, posture_name)
        if verified != new_ip:
            raise UpdateError(f"Post-update verification failed for {posture_name!r}")
    return old_ips, changed


def _backup_dir():
    return Path(dbstore.DATABASE_PATH).parent / "public-ip-policy-backups"


def backup_policy(policy: bytes, retention_days: int) -> Path:
    directory = _backup_dir()
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        path = directory / f"{BACKUP_PREFIX}{timestamp}.hujson"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(policy)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
        for candidate in directory.iterdir():
            if not candidate.name.startswith(BACKUP_PREFIX) or candidate.suffix != ".hujson" or candidate.is_symlink():
                continue
            if candidate.is_file() and datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc) < cutoff:
                candidate.unlink()
    except OSError as exc:
        raise UpdateError(f"Could not create or prune policy backups: {exc}") from exc
    return path


def _api_request(method, url, auth_headers, timeout, body=None, content_type=None, etag=None):
    headers = dict(auth_headers)
    headers.update({"Accept": "application/hujson", "User-Agent": "tailscale-healthcheck/1"})
    if content_type:
        headers["Content-Type"] = content_type
    if etag:
        headers["If-Match"] = etag
    try:
        response = requests.request(method, url, headers=headers, data=body, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        detail = ""
        if getattr(exc, "response", None) is not None:
            detail = exc.response.text[:4096].strip()
        raise UpdateError(f"Tailscale API {method} failed: {detail or exc}") from exc


def _lock_path():
    return str(Path(dbstore.DATABASE_PATH).parent / "public-ip-updater.lock")


def try_lock():
    handle = open(_lock_path(), "w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except (BlockingIOError, OSError):
        handle.close()
        return None


def release_lock(handle):
    if handle:
        handle.close()


def sync(mappings, tailnet: str, auth_headers: dict, timeout: float, actor="poller", record=None):
    """Synchronize a supplied mapping batch. The caller owns serialization."""
    if not mappings:
        return {"ok": True, "changed": 0, "message": "No enabled mappings."}
    resolved = {}
    try:
        for mapping in mappings:
            resolved[mapping["id"]] = resolve_public_ipv4(mapping["hostname"])
        url = f"{API_BASE}/tailnet/{requests.utils.quote(tailnet, safe='')}/acl"
        response = _api_request("GET", url, auth_headers, timeout)
        policy_bytes = response.content
        if not policy_bytes:
            raise UpdateError("Tailscale returned an empty policy")
        policy = policy_bytes.decode("utf-8")
        replacements = {mapping["posture_name"]: resolved[mapping["id"]] for mapping in mappings}
        old_ips, candidate = update_rules(policy, replacements)
        changed_mappings = [m for m in mappings if old_ips[m["posture_name"]] != resolved[m["id"]]]
        if not changed_mappings:
            for mapping in mappings:
                ip = resolved[mapping["id"]]
                dbstore.set_public_ip_mapping_result(mapping["id"], status="healthy", resolved_ip=ip,
                                                     configured_ip=ip, success=True)
            if record:
                record("public_ip_unchanged", f"Public-IP posture mappings already current ({len(mappings)} checked).")
            return {"ok": True, "changed": 0, "message": "All mappings already current."}
        etag = response.headers.get("ETag")
        if not etag:
            raise UpdateError("Tailscale response did not contain an ETag")
        candidate_bytes = candidate.encode("utf-8")
        _api_request("POST", url + "/validate", auth_headers, timeout, candidate_bytes, "application/hujson")
        retention = dbstore.get_setting_typed("public_ip_backup_retention_days")
        backup = backup_policy(policy_bytes, retention)
        _api_request("POST", url, auth_headers, timeout, candidate_bytes, "application/hujson", etag)
        for mapping in mappings:
            mapping_id = mapping["id"]
            new_ip = resolved[mapping_id]
            old_ip = old_ips[mapping["posture_name"]]
            changed = old_ip != new_ip
            dbstore.set_public_ip_mapping_result(
                mapping_id, status="healthy", resolved_ip=new_ip, configured_ip=new_ip,
                backup=backup.name if changed else None, success=True, changed=changed,
            )
            if changed:
                dbstore.audit_public_ip_sync(mapping_id, mapping["posture_name"], mapping["hostname"],
                                             old_ip, new_ip, backup.name, actor)
        if record:
            record("public_ip_updated", f"Updated {len(changed_mappings)} public-IP posture mapping(s).",
                   {"changed": len(changed_mappings), "backup": backup.name})
        return {"ok": True, "changed": len(changed_mappings), "backup": backup.name}
    except Exception as exc:
        message = str(exc) if isinstance(exc, (UpdateError, UnicodeDecodeError)) else f"Unexpected failure: {exc}"
        for mapping in mappings:
            mapping_error = message if mapping["id"] not in resolved else f"Batch aborted: {message}"
            dbstore.set_public_ip_mapping_result(mapping["id"], status="error",
                                                 resolved_ip=resolved.get(mapping["id"]), error=mapping_error)
        if record:
            record("public_ip_error", f"Public-IP posture synchronization failed: {message}", {"error": message})
        return {"ok": False, "changed": 0, "error": message}
