# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
import base64
import re
import subprocess
import sys
import time
import winreg
from ctypes import wintypes
from dataclasses import dataclass


GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str


class SerialError(OSError):
    pass


class DCB(ctypes.Structure):
    _fields_ = [
        ("DCBlength", wintypes.DWORD),
        ("BaudRate", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("wReserved", wintypes.WORD),
        ("XonLim", wintypes.WORD),
        ("XoffLim", wintypes.WORD),
        ("ByteSize", ctypes.c_ubyte),
        ("Parity", ctypes.c_ubyte),
        ("StopBits", ctypes.c_ubyte),
        ("XonChar", ctypes.c_char),
        ("XoffChar", ctypes.c_char),
        ("ErrorChar", ctypes.c_char),
        ("EofChar", ctypes.c_char),
        ("EvtChar", ctypes.c_char),
        ("wReserved1", wintypes.WORD),
    ]


class COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [
        ("ReadIntervalTimeout", wintypes.DWORD),
        ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
        ("ReadTotalTimeoutConstant", wintypes.DWORD),
        ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
        ("WriteTotalTimeoutConstant", wintypes.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.BuildCommDCBW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(DCB)]
kernel32.BuildCommDCBW.restype = wintypes.BOOL
kernel32.SetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(DCB)]
kernel32.SetCommState.restype = wintypes.BOOL
kernel32.SetCommTimeouts.argtypes = [wintypes.HANDLE, ctypes.POINTER(COMMTIMEOUTS)]
kernel32.SetCommTimeouts.restype = wintypes.BOOL
kernel32.SetupComm.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
kernel32.SetupComm.restype = wintypes.BOOL
kernel32.PurgeComm.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.PurgeComm.restype = wintypes.BOOL
kernel32.ReadFile.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
kernel32.WriteFile.restype = wintypes.BOOL


def list_serial_ports() -> list[SerialPortInfo]:
    ports = _registry_ports()
    descriptions = _pnp_descriptions()
    return [
        SerialPortInfo(port, descriptions.get(port, port))
        for port in sorted(ports, key=_port_sort_key)
    ]


def find_xds110_port() -> str:
    for port in list_serial_ports():
        if "XDS110 Class Application/User UART" in port.description:
            return port.device
    return ""


class WinSerial:
    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 5.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.handle: int | None = None

    def __enter__(self) -> "WinSerial":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> None:
        if self.handle is not None:
            return
        path = self.port if self.port.startswith("\\\\.\\") else "\\\\.\\" + self.port
        handle = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
        if handle == INVALID_HANDLE_VALUE:
            raise SerialError(f"Cannot open {self.port}: {_last_error()}")

        self.handle = handle
        self._check(kernel32.SetupComm(handle, 4096, 4096), "SetupComm")

        dcb = DCB()
        dcb.DCBlength = ctypes.sizeof(DCB)
        self._check(kernel32.BuildCommDCBW(f"baud={self.baudrate} parity=N data=8 stop=1", ctypes.byref(dcb)), "BuildCommDCB")
        self._check(kernel32.SetCommState(handle, ctypes.byref(dcb)), "SetCommState")

        timeout_ms = max(1, int(self.timeout * 1000))
        timeouts = COMMTIMEOUTS(
            ReadIntervalTimeout=50,
            ReadTotalTimeoutMultiplier=0,
            ReadTotalTimeoutConstant=timeout_ms,
            WriteTotalTimeoutMultiplier=0,
            WriteTotalTimeoutConstant=timeout_ms,
        )
        self._check(kernel32.SetCommTimeouts(handle, ctypes.byref(timeouts)), "SetCommTimeouts")
        kernel32.PurgeComm(handle, 0x000F)

    def close(self) -> None:
        if self.handle is not None:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def write(self, data: bytes) -> int:
        self._ensure_open()
        written = wintypes.DWORD(0)
        buffer = ctypes.create_string_buffer(data)
        ok = kernel32.WriteFile(self.handle, buffer, len(data), ctypes.byref(written), None)
        self._check(ok, f"WriteFile {self.port}")
        return int(written.value)

    def read_exactly(self, count: int, timeout: float | None = None) -> bytes:
        self._ensure_open()
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        chunks: list[bytes] = []
        received = 0

        while received < count and time.monotonic() < deadline:
            remaining = count - received
            buffer = ctypes.create_string_buffer(remaining)
            read_count = wintypes.DWORD(0)
            ok = kernel32.ReadFile(self.handle, buffer, remaining, ctypes.byref(read_count), None)
            self._check(ok, f"ReadFile {self.port}")
            if read_count.value:
                chunk = buffer.raw[: read_count.value]
                chunks.append(chunk)
                received += len(chunk)
            else:
                time.sleep(0.02)

        return b"".join(chunks)

    def _ensure_open(self) -> None:
        if self.handle is None:
            raise SerialError(f"{self.port} is not open.")

    @staticmethod
    def _check(ok: bool, label: str) -> None:
        if not ok:
            raise SerialError(f"{label} failed: {_last_error()}")


def _registry_ports() -> set[str]:
    ports: set[str] = set()
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
            index = 0
            while True:
                try:
                    _, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                if isinstance(value, str) and value.upper().startswith("COM"):
                    ports.add(value)
                index += 1
    except OSError:
        pass
    return ports


def _pnp_descriptions() -> dict[str, str]:
    if not sys.platform.startswith("win"):
        return {}
    command = (
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.Name -match '\\(COM\\d+\\)' } | "
        "ForEach-Object { [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($_.Name)) }"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=flags,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    descriptions: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            description = base64.b64decode(line).decode("utf-8", errors="replace")
        except ValueError:
            description = line
        match = re.search(r"\((COM\d+)\)", line, flags=re.IGNORECASE)
        if not match:
            match = re.search(r"\((COM\d+)\)", description, flags=re.IGNORECASE)
        if match:
            descriptions[match.group(1).upper()] = description.strip()
    return descriptions


def _port_sort_key(port: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", port)
    return (int(match.group(1)) if match else 9999, port)


def _last_error() -> str:
    code = ctypes.get_last_error()
    if not code:
        return "unknown error"
    return ctypes.FormatError(code).strip()
