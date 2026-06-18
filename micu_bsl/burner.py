# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import time
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable

from .packets import BslPacketBuilder
from .parsers import parse_password_file, parse_ti_txt_firmware
from .resources import runtime_path
from .serial_win import WinSerial, find_xds110_port


LogFn = Callable[[str, str], None]
ProgressFn = Callable[[int, str], None]


@dataclass(frozen=True)
class BurnOptions:
    firmware_path: Path
    password_path: Path
    bridge_mode: str
    serial_port: str
    xds_common_dir: Path
    start_application: bool = True


class BurnCancelled(RuntimeError):
    pass


class Mspm0BslBurner:
    def __init__(
        self,
        log: LogFn,
        progress: ProgressFn,
        cancel_event: Event | None = None,
    ):
        self.log = log
        self.progress = progress
        self.cancel_event = cancel_event or Event()
        self.packets = BslPacketBuilder()

    def burn(self, options: BurnOptions) -> None:
        self._check_cancelled()
        self.progress(4, "解析输入文件")
        password = parse_password_file(options.password_path)
        firmware_lines = parse_ti_txt_firmware(options.firmware_path)
        firmware_packets = self.packets.firmware_packets(firmware_lines)
        if not firmware_packets:
            raise RuntimeError("Firmware file did not produce any BSL program packets.")

        self.log("info", f"固件: {options.firmware_path}")
        self.log("info", f"密码: {options.password_path}")
        self.log("info", f"分包数量: {len(firmware_packets)}")

        port = options.serial_port.strip()
        if not port and options.bridge_mode != "manual":
            self.progress(8, "自动查找 XDS110 UART")
            port = find_xds110_port()
        if not port:
            raise RuntimeError("未找到串口。请刷新后手动选择 COM 口。")

        self.progress(12, "进入 BSL 模式")
        self._enter_bsl(options.bridge_mode, options.xds_common_dir)

        self.progress(18, f"打开串口 {port}")
        with WinSerial(port, baudrate=9600, timeout=5.0) as serial:
            self.log("info", f"串口配置: {port}, 9600, 8N1")

            serial.write(self.packets.connection_packet())
            serial.read_exactly(1, timeout=2.0)
            self._release_boot_pin(options.bridge_mode, options.xds_common_dir)

            serial.write(b"\xBB")
            autobaud = serial.read_exactly(1, timeout=5.0)
            if autobaud.hex().upper() != "51":
                raise RuntimeError(f"设备未进入 BSL 模式，自动波特率响应: {autobaud.hex().upper() or '无响应'}")
            self.log("success", "设备已进入 BSL 模式")

            self.progress(25, "读取设备 ID")
            serial.write(self.packets.get_id_packet())
            device_id = serial.read_exactly(33, timeout=5.0)
            self.log("info", f"Device ID raw: {device_id.hex(' ').upper()}")

            self.progress(32, "发送 BSL 密码")
            self._send_command(serial, self.packets.password_packet(password), "密码校验")

            self.progress(40, "整片擦除")
            self._send_command(serial, self.packets.mass_erase_packet(), "Mass erase")

            total = len(firmware_packets)
            for index, packet in enumerate(firmware_packets, start=1):
                self._check_cancelled()
                serial.write(packet)
                ack = self.packets.parse_packet_ack(serial.read_exactly(1, timeout=5.0))
                if not ack.ok:
                    raise RuntimeError(f"固件包 {index}/{total} 发送失败: {ack.message} ({ack.code})")
                response = self.packets.parse_command_response(serial.read_exactly(9, timeout=5.0))
                if not response.ok:
                    raise RuntimeError(f"固件包 {index}/{total} 写入失败: {response.message} ({response.code})")
                if index == 1 or index == total or index % 8 == 0:
                    self.log("info", f"写入固件包 {index}/{total}")
                self.progress(40 + int(index * 52 / total), f"写入固件 {index}/{total}")

            if options.start_application:
                self.progress(96, "启动应用程序")
                serial.write(self.packets.start_app_packet())
                serial.read_exactly(1, timeout=2.0)
                self.log("success", "已发送 Start Application 命令")

        self.progress(100, "烧录完成")
        self.log("success", "----------- Download finished ----------")

    def _send_command(self, serial: WinSerial, packet: bytes, label: str) -> None:
        self._check_cancelled()
        serial.write(packet)
        ack = self.packets.parse_packet_ack(serial.read_exactly(1, timeout=5.0))
        if not ack.ok:
            raise RuntimeError(f"{label} 包错误: {ack.message} ({ack.code})")
        response = self.packets.parse_command_response(serial.read_exactly(9, timeout=5.0))
        if not response.ok:
            raise RuntimeError(f"{label} 失败: {response.message} ({response.code})")
        self.log("success", f"{label}: {response.message}")

    def _enter_bsl(self, bridge_mode: str, common_dir: Path) -> None:
        if bridge_mode == "launchpad":
            self.log("info", "XDS110 LaunchPad: 拉起 BSL 引脚并复位")
            self._run_xds(common_dir, ("uscif", "dbgjtag.exe"), "-f", "@xds110", "-Y", "gpiopins,config=0x1,write=0x1")
            self._run_xds(common_dir, ("uscif", "xds110", "xds110reset.exe"), "-d", "1400")
            return
        if bridge_mode == "standalone":
            self.log("info", "Standalone XDS110: 上电并切换 GPIO 进入 BSL")
            self._run_xds(common_dir, ("uscif", "dbgjtag.exe"), "-f", "@xds110", "-Y", "power,supply=on,voltage=3.2")
            self._run_xds(common_dir, ("uscif", "dbgjtag.exe"), "-f", "@xds110", "-Y", "gpiopins,config=0x3,write=0x02")
            time.sleep(1.4)
            self._run_xds(common_dir, ("uscif", "dbgjtag.exe"), "-f", "@xds110", "-Y", "gpiopins,config=0x3,write=0x03")
            return
        self.log("info", "手动串口模式: 请确认目标芯片已经处于 BSL 模式")

    def _release_boot_pin(self, bridge_mode: str, common_dir: Path) -> None:
        if bridge_mode == "launchpad":
            self._run_xds(common_dir, ("uscif", "dbgjtag.exe"), "-f", "@xds110", "-Y", "gpiopins,config=0x1,write=0x0")
        elif bridge_mode == "standalone":
            self._run_xds(common_dir, ("uscif", "dbgjtag.exe"), "-f", "@xds110", "-Y", "gpiopins,config=0x3,write=0x01")

    def _run_xds(self, common_dir: Path, executable_parts: tuple[str, ...], *args: str) -> None:
        exe = common_dir.joinpath(*executable_parts)
        if not exe.exists():
            raise RuntimeError(f"XDS 工具不存在: {exe}")
        command = [str(exe), *args]
        env = os.environ.copy()
        extra_path = [
            str(common_dir / "bin"),
            str(common_dir / "uscif"),
            str(common_dir / "uscif" / "xds110"),
        ]
        env["PATH"] = os.pathsep.join(extra_path + [env.get("PATH", "")])

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            command,
            cwd=str(common_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=flags,
            timeout=20,
            env=env,
        )
        output = (completed.stdout + completed.stderr).strip()
        if output:
            self.log("debug", output)
        if completed.returncode != 0:
            raise RuntimeError(f"XDS 命令失败: {' '.join(command)}")

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise BurnCancelled("用户已取消烧录。")


def default_common_dir() -> Path:
    return runtime_path("common")
