# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


class FirmwareParseError(ValueError):
    pass


class PasswordParseError(ValueError):
    pass


def parse_password_file(path: str | Path) -> bytes:
    password = b""
    marker_found = False
    payload_lines = 0

    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in lines:
        clean = line.strip()
        if not clean:
            continue
        if clean.startswith("@password"):
            marker_found = True
            continue
        if marker_found:
            try:
                password += bytes.fromhex(clean)
            except ValueError as exc:
                raise PasswordParseError(f"Password line is not valid hex: {clean}") from exc
            payload_lines += 1
            if payload_lines == 2:
                break

    if not marker_found:
        raise PasswordParseError("Password file must contain an @password marker.")
    if len(password) != 32:
        raise PasswordParseError("Password must contain exactly 32 bytes after @password.")
    return password


def parse_ti_txt_firmware(path: str | Path) -> list[str]:
    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    normalized = _split_segment_crossing_0x10000(lines)
    adjusted: list[str] = []
    saw_address = False
    saw_quit = False

    for raw_line in normalized:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("@"):
            _require_hex(line[1:], "address")
            address = int(line[1:], 16)
            if 0xFFA2 <= address <= 0xFFFF:
                address -= 0xC2
            adjusted.append("@" + f"{address:X}")
            saw_address = True
            continue
        if line == "q":
            adjusted.append(line)
            saw_quit = True
            continue
        _require_hex(line.replace(" ", ""), "firmware data")
        adjusted.append(" ".join(line.split()))

    if not saw_address:
        raise FirmwareParseError("Firmware file does not contain a TI-TXT address line.")
    if not saw_quit:
        adjusted.append("q")
    return adjusted


def _split_segment_crossing_0x10000(lines: list[str]) -> list[str]:
    last_low_segment_index = -1
    last_low_segment_address = 0

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if line.startswith("@"):
            address = int(line[1:], 16)
            if address <= 0xFFFF:
                last_low_segment_index = index
                last_low_segment_address = address
            else:
                break

    if last_low_segment_index < 0:
        return lines[:]

    byte_count = 0
    counting = False
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("@"):
            if counting:
                break
            counting = int(line[1:], 16) == last_low_segment_address
            continue
        if counting:
            if line == "q":
                break
            byte_count += len(line.split())

    if last_low_segment_address + byte_count <= 0x10000:
        return lines[:]

    result: list[str] = []
    remaining_before_boundary = 0
    split_active = False

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("@"):
            result.append(line)
            if int(line[1:], 16) == last_low_segment_address:
                remaining_before_boundary = 0x10000 - last_low_segment_address
                split_active = True
            continue
        if not split_active or line == "q":
            result.append(line)
            continue
        values = line.split()
        if len(values) < remaining_before_boundary:
            remaining_before_boundary -= len(values)
            result.append(line)
            continue
        before = values[:remaining_before_boundary]
        after = values[remaining_before_boundary:]
        if before:
            result.append(" ".join(before))
        result.append("@10000")
        if after:
            result.append(" ".join(after))
        split_active = False

    return result


def _require_hex(value: str, label: str) -> None:
    try:
        int(value, 16)
    except ValueError as exc:
        raise FirmwareParseError(f"Invalid {label}: {value}") from exc
