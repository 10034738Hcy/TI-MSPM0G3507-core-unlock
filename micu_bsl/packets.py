# -*- coding: utf-8 -*-
from __future__ import annotations

import struct
from dataclasses import dataclass


class BslPacketError(ValueError):
    pass


@dataclass(frozen=True)
class BslResponse:
    ok: bool
    code: str
    message: str


class BslPacketBuilder:
    HEADER = b"\x80"
    CMD_CONNECTION = b"\x12"
    CMD_GET_ID = b"\x19"
    CMD_PASSWORD = b"\x21"
    CMD_MASS_ERASE = b"\x15"
    CMD_PROGRAM = b"\x20"
    CMD_START_APP = b"\x40"

    PACKET_ACK = {
        "00": "Send package successfully",
        "51": "Header incorrect",
        "52": "Checksum incorrect",
        "53": "Packet size zero",
        "54": "Packet size too big",
        "55": "Unknown packet error",
        "56": "Unknown baud rate",
    }

    COMMAND_RESPONSE = {
        "00": "Operation success",
        "01": "Flash program failed",
        "02": "Mass erase failed",
        "04": "BSL locked",
        "05": "BSL password error",
        "06": "Multiple BSL password errors",
        "07": "Unknown command",
        "08": "Invalid memory range",
        "0B": "Factory reset disabled",
        "0C": "Factory reset password error",
    }

    def connection_packet(self) -> bytes:
        return self._command_only(self.CMD_CONNECTION)

    def get_id_packet(self) -> bytes:
        return self._command_only(self.CMD_GET_ID)

    def password_packet(self, password: bytes) -> bytes:
        if len(password) != 32:
            raise BslPacketError("Password must be exactly 32 bytes.")
        return self._packet(self.CMD_PASSWORD + password)

    def mass_erase_packet(self) -> bytes:
        return self._command_only(self.CMD_MASS_ERASE)

    def start_app_packet(self) -> bytes:
        return self._command_only(self.CMD_START_APP)

    def firmware_packets(self, firmware_lines: list[str]) -> list[bytes]:
        grouped_lines = self._split_to_128_byte_blocks(firmware_lines)
        packets: list[bytes] = []
        data_buffer = b""
        address_payload = b""

        for line in grouped_lines:
            if not line:
                continue
            tag = line[0]
            if tag == "q":
                continue
            if tag == "@":
                address_hex = line[1:].strip().zfill(8)
                address_bytes = bytearray(bytes.fromhex(address_hex))
                address_bytes.reverse()
                address_payload = self.CMD_PROGRAM + bytes(address_bytes)
                data_buffer = b""
                continue
            if tag == "&":
                if not address_payload:
                    raise BslPacketError("Firmware data block does not have an address.")
                packets.append(self._packet(address_payload + data_buffer))
                data_buffer = b""
                continue
            data_buffer += bytes.fromhex(line.strip())

        return packets

    def parse_packet_ack(self, ack: bytes) -> BslResponse:
        code = ack.hex().upper()
        return BslResponse(code == "00", code, self.PACKET_ACK.get(code, "Unknown packet ACK"))

    def parse_command_response(self, response: bytes) -> BslResponse:
        code = self.command_response_code(response)
        return BslResponse(code == "00", code, self.COMMAND_RESPONSE.get(code, "Unknown command response"))

    @staticmethod
    def command_response_code(response: bytes) -> str:
        if len(response) >= 5:
            return response[4:5].hex().upper()
        return ""

    def _command_only(self, command: bytes) -> bytes:
        return self._packet(command)

    def _packet(self, payload: bytes) -> bytes:
        if len(payload) > 0xFFFF:
            raise BslPacketError("Payload is too large for a BSL packet.")
        return self.HEADER + struct.pack("<H", len(payload)) + payload + struct.pack("<I", self.crc32(payload))

    @staticmethod
    def crc32(data: bytes) -> int:
        crc = 0xFFFFFFFF
        poly = 0xEDB88320
        for value in data:
            crc ^= value
            for _ in range(8):
                mask = -(crc & 1)
                crc = (crc >> 1) ^ (poly & mask)
        return crc

    @staticmethod
    def _split_to_128_byte_blocks(firmware_lines: list[str]) -> list[str]:
        data_array: list[str] = []
        send_count = 0
        address_count = 0

        for raw_line in firmware_lines:
            line = raw_line.strip()
            if not line:
                continue
            if line[0] == "q":
                data_array.append("&")
                data_array.append(line)
                continue
            if line[0] == "@":
                address_count = int(line[1:], 16)
                if send_count:
                    data_array.append("&")
                send_count = 0
                data_array.append(line)
                continue

            data = bytes.fromhex(line)
            send_count += len(data)
            address_count += len(data)
            if send_count > 128:
                block_start = address_count - len(data)
                data_array.append("&")
                data_array.append("@" + f"{block_start:X}")
                send_count = len(data)
            data_array.append(line)

        return data_array
