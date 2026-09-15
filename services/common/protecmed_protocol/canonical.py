"""Restricted canonical JSON profile and the hash recipes of blueprint 4.3.

ASCII strings and keys only; null, booleans and integers with absolute value at most
2**53-1; arrays and objects; sorted keys; no insignificant whitespace; no floats.
Duplicate keys are rejected while parsing raw request bytes.

This is deliberately NOT advertised as a general RFC 8785 implementation. Full
Unicode/JCS support would be a versioned extension, not a quiet upgrade.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .errors import ProtocolError

DOMAIN = b"PROTECMed/v2/"
MAX_SAFE_INTEGER = 2**53 - 1
MAX_JSON_BYTES = 65536
MAX_DEPTH = 16
HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
UTC_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _validate(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise ProtocolError("JSON_DEPTH")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if abs(value) > MAX_SAFE_INTEGER:
            raise ProtocolError("JSON_INTEGER_RANGE")
        return
    if type(value) is str:
        if not value.isascii():
            raise ProtocolError("JSON_ASCII_ONLY")
        return
    if type(value) is list:
        for item in value:
            _validate(item, depth + 1)
        return
    if type(value) is dict:
        if any(type(key) is not str or not key.isascii() for key in value):
            raise ProtocolError("JSON_KEY")
        for item in value.values():
            _validate(item, depth + 1)
        return
    # float, Decimal, bytes, tuple, set, custom objects: all rejected.
    raise ProtocolError("JSON_UNSUPPORTED_TYPE")


def canonical_bytes(value: Any) -> bytes:
    _validate(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def parse_json(raw: bytes) -> Any:
    """Parse untrusted request bytes. Duplicate keys are a rejection, not a last-wins."""
    if type(raw) is not bytes:
        raise ProtocolError("JSON_TYPE")
    if len(raw) > MAX_JSON_BYTES:
        raise ProtocolError("JSON_SIZE")

    def pairs(items):
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ProtocolError("JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    def reject_constant(_):
        raise ProtocolError("JSON_CONSTANT")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=reject_constant)
    except ProtocolError:
        raise
    except (ValueError, UnicodeDecodeError):
        raise ProtocolError("JSON_MALFORMED") from None
    _validate(value)
    return value


def sha256_hex(raw: bytes) -> str:
    if type(raw) is not bytes:
        raise ProtocolError("HASH_INPUT_TYPE")
    return hashlib.sha256(raw).hexdigest()


def payload_hash(payload: Any) -> str:
    """SHA-256 over canonical payload bytes, excluding any envelope or signature."""
    if type(payload) is dict and ("signature_b64" in payload or "payload" in payload):
        # Never hash an object that carries its own signature (blueprint 4.3).
        raise ProtocolError("HASH_OF_SIGNED_ENVELOPE")
    return sha256_hex(canonical_bytes(payload))


def hash_list(values: list[Any]) -> str:
    """Hash of an ordered canonical array; used for transcripts and recipient lists."""
    if type(values) is not list:
        raise ProtocolError("HASH_LIST_TYPE")
    return sha256_hex(canonical_bytes(values))


def is_hex64(value: Any) -> bool:
    return type(value) is str and bool(HEX64.fullmatch(value))


def is_identifier(value: Any) -> bool:
    return type(value) is str and bool(IDENTIFIER.fullmatch(value))


def format_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ProtocolError("NAIVE_CLOCK")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: Any) -> datetime:
    """Parse as a real date, not merely a regex match."""
    if type(value) is not str or not UTC_FORMAT.fullmatch(value):
        raise ProtocolError("UTC_FORMAT")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ProtocolError("UTC_NOT_A_DATE") from None


def require_aware(now: datetime) -> datetime:
    if type(now) is not datetime or now.tzinfo is None:
        raise ProtocolError("NAIVE_CLOCK")
    return now.astimezone(timezone.utc)


def plus_seconds(moment: datetime, seconds: int) -> datetime:
    return require_aware(moment) + timedelta(seconds=seconds)
