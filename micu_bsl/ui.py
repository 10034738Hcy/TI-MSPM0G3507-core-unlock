# -*- coding: utf-8 -*-
from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, APP_VERSION
from .burner import BurnCancelled, BurnOptions, Mspm0BslBurner, default_common_dir
from .parsers import PasswordParseError, FirmwareParseError
from .resources import resource_path
from .serial_win import find_xds110_port, list_serial_ports


class MicuBslApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("980x680")
        self.minsize(880, 620)
        self.configure(bg="#F5F7FB")

        self.firmware_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.bridge_var = tk.StringVar(value="launchpad")
        self.start_app_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.IntVar(value=0)
        self.progress_text_var = tk.StringVar(value="0%")
        self.common_dir_var = tk.StringVar(value=str(default_common_dir()))

        self._event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._ports: list[str] = []
        self._logo: tk.PhotoImage | None = None
        self._activity_canvas: tk.Canvas | None = None
        self._activity_dot: int | None = None
        self._activity_label: ttk.Label | None = None
        self._activity_after_id: str | None = None
        self._activity_step = 0
        self.progress_bar: ttk.Progressbar | None = None

        self._configure_style()
        self._build_ui()
        self._set_icon()
        self.after(120, self._poll_worker_events)
        self.refresh_ports()
        self._log("info", "MICU MSPM0 BSL burner initialized.")

    def _configure_style(self) -> None:
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure(".", font=("Microsoft YaHei UI", 10), background="#F5F7FB", foreground="#182230")
        self.style.configure("Main.TFrame", background="#F5F7FB")
        self.style.configure("Panel.TFrame", background="#FFFFFF", relief="flat")
        self.style.configure("Header.TFrame", background="#0F6CBD")
        self.style.configure("HeaderTitle.TLabel", background="#0F6CBD", foreground="#FFFFFF", font=("Microsoft YaHei UI", 20, "bold"))
        self.style.configure("HeaderSub.TLabel", background="#0F6CBD", foreground="#DCEBFA", font=("Microsoft YaHei UI", 10))
        self.style.configure("Title.TLabel", background="#FFFFFF", foreground="#182230", font=("Microsoft YaHei UI", 12, "bold"))
        self.style.configure("Muted.TLabel", background="#FFFFFF", foreground="#667085")
        self.style.configure("Field.TLabel", background="#FFFFFF", foreground="#344054")
        self.style.configure("ProgressText.TLabel", background="#FFFFFF", foreground="#344054", font=("Microsoft YaHei UI", 10, "bold"))
        self.style.configure("Status.TLabel", background="#E7F6EC", foreground="#087443", padding=(10, 4), font=("Microsoft YaHei UI", 9, "bold"))
        self.style.configure("Accent.TButton", background="#0F6CBD", foreground="#FFFFFF", borderwidth=0, focusthickness=0, padding=(14, 8))
        self.style.map("Accent.TButton", background=[("active", "#0B5CAB"), ("disabled", "#98A2B3")])
        self.style.configure("Danger.TButton", background="#D92D20", foreground="#FFFFFF", borderwidth=0, padding=(14, 8))
        self.style.map("Danger.TButton", background=[("active", "#B42318"), ("disabled", "#FDA29B")])
        self.style.configure("Tool.TButton", padding=(10, 7))
        self.style.configure("Idle.Horizontal.TProgressbar", background="#98A2B3", troughcolor="#E4E7EC", bordercolor="#E4E7EC", lightcolor="#98A2B3", darkcolor="#98A2B3")
        self.style.configure("Active.Horizontal.TProgressbar", background="#0F6CBD", troughcolor="#E4E7EC", bordercolor="#E4E7EC", lightcolor="#0F6CBD", darkcolor="#0F6CBD")
        self.style.configure("Done.Horizontal.TProgressbar", background="#16A34A", troughcolor="#E4E7EC", bordercolor="#E4E7EC", lightcolor="#16A34A", darkcolor="#16A34A")
        self.style.configure("Error.Horizontal.TProgressbar", background="#D92D20", troughcolor="#E4E7EC", bordercolor="#E4E7EC", lightcolor="#D92D20", darkcolor="#D92D20")
        self.style.configure("TRadiobutton", background="#FFFFFF", foreground="#344054")
        self.style.configure("TCheckbutton", background="#FFFFFF", foreground="#344054")
        self.option_add("*TCombobox*Listbox.font", ("Consolas", 10))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="Main.TFrame", padding=18)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, style="Header.TFrame", padding=(22, 18))
        header.pack(fill="x")
        header.columnconfigure(1, weight=1)

        logo_label = ttk.Label(header, background="#0F6CBD")
        logo_label.grid(row=0, column=0, sticky="w", padx=(0, 14))
        self._load_logo(logo_label)

        ttk.Label(header, text=APP_NAME, style="HeaderTitle.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=2, sticky="e")

        body = ttk.Frame(root, style="Main.TFrame")
        body.pack(fill="both", expand=True, pady=(16, 0))
        body.columnconfigure(0, weight=1, minsize=530)
        body.columnconfigure(1, weight=1, minsize=300)
        body.rowconfigure(1, weight=1)

        left = ttk.Frame(body, style="Panel.TFrame", padding=18)
        left.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 12))
        left.columnconfigure(1, weight=1)

        right_top = ttk.Frame(body, style="Panel.TFrame", padding=18)
        right_top.grid(row=0, column=1, sticky="nsew")
        right_top.columnconfigure(0, weight=1)

        right_bottom = ttk.Frame(body, style="Panel.TFrame", padding=18)
        right_bottom.grid(row=1, column=1, sticky="nsew", pady=(12, 0))
        right_bottom.columnconfigure(0, weight=1)
        right_bottom.rowconfigure(1, weight=1)

        self._build_input_panel(left)
        self._build_action_panel(right_top)
        self._build_log_panel(right_bottom)

    def _build_input_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="烧录配置", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")

        self._file_row(parent, 1, "固件文件", self.firmware_var, self.choose_firmware)
        self._file_row(parent, 2, "密码文件", self.password_var, self.choose_password)

        ttk.Label(parent, text="XDS / 串口模式", style="Field.TLabel").grid(row=3, column=0, sticky="nw", pady=(18, 7))
        mode_frame = ttk.Frame(parent, style="Panel.TFrame")
        mode_frame.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(18, 7))
        ttk.Radiobutton(mode_frame, text="XDS110 LaunchPad", variable=self.bridge_var, value="launchpad").pack(anchor="w", pady=2)
        ttk.Radiobutton(mode_frame, text="Standalone XDS110", variable=self.bridge_var, value="standalone").pack(anchor="w", pady=2)
        ttk.Radiobutton(mode_frame, text="手动串口", variable=self.bridge_var, value="manual").pack(anchor="w", pady=2)

        ttk.Label(parent, text="COM 口", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 7))
        self.port_combo = ttk.Combobox(parent, textvariable=self.port_var, state="readonly", width=34)
        self.port_combo.grid(row=4, column=1, sticky="ew", pady=(12, 7), padx=(0, 8))
        ttk.Button(parent, text="刷新", style="Tool.TButton", command=self.refresh_ports).grid(row=4, column=2, sticky="ew", pady=(12, 7))

        ttk.Label(parent, text="XDS 工具目录", style="Field.TLabel").grid(row=5, column=0, sticky="w", pady=(12, 7))
        ttk.Entry(parent, textvariable=self.common_dir_var).grid(row=5, column=1, sticky="ew", pady=(12, 7), padx=(0, 8))
        ttk.Button(parent, text="选择", style="Tool.TButton", command=self.choose_common_dir).grid(row=5, column=2, sticky="ew", pady=(12, 7))

        ttk.Checkbutton(parent, text="烧录完成后启动应用程序", variable=self.start_app_var).grid(row=6, column=1, columnspan=2, sticky="w", pady=(14, 0))

    def _build_action_panel(self, parent: ttk.Frame) -> None:
        title_row = ttk.Frame(parent, style="Panel.TFrame")
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.columnconfigure(1, weight=1)
        ttk.Label(title_row, text="执行", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self._activity_canvas = tk.Canvas(title_row, width=16, height=16, bg="#FFFFFF", highlightthickness=0, bd=0)
        self._activity_canvas.grid(row=0, column=1, sticky="e", padx=(10, 6))
        self._activity_dot = self._activity_canvas.create_oval(4, 4, 12, 12, fill="#98A2B3", outline="")
        self._activity_label = ttk.Label(title_row, text="待命", style="Muted.TLabel")
        self._activity_label.grid(row=0, column=2, sticky="e")

        progress_row = ttk.Frame(parent, style="Panel.TFrame")
        progress_row.grid(row=1, column=0, sticky="ew", pady=(18, 4))
        progress_row.columnconfigure(1, weight=1)
        ttk.Label(progress_row, text="进度", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(progress_row, textvariable=self.progress_text_var, style="ProgressText.TLabel").grid(row=0, column=1, sticky="e")
        self.progress_bar = ttk.Progressbar(parent, variable=self.progress_var, maximum=100, style="Idle.Horizontal.TProgressbar")
        self.progress_bar.grid(row=2, column=0, sticky="ew")

        button_row = ttk.Frame(parent, style="Panel.TFrame")
        button_row.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)

        self.burn_button = ttk.Button(button_row, text="开始烧录", style="Accent.TButton", command=self.start_burn)
        self.burn_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.cancel_button = ttk.Button(button_row, text="取消", style="Danger.TButton", command=self.cancel_burn, state="disabled")
        self.cancel_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self.phase_label = ttk.Label(parent, text="等待任务", style="Muted.TLabel")
        self.phase_label.grid(row=4, column=0, sticky="w", pady=(14, 0))

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        title_row = ttk.Frame(parent, style="Panel.TFrame")
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.columnconfigure(0, weight=1)
        ttk.Label(title_row, text="日志", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(title_row, text="清空", style="Tool.TButton", command=self.clear_log).grid(row=0, column=1, sticky="e")

        text_frame = ttk.Frame(parent, style="Panel.TFrame")
        text_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            text_frame,
            wrap="word",
            height=18,
            relief="flat",
            bg="#101828",
            fg="#EAECF0",
            insertbackground="#EAECF0",
            font=("Consolas", 10),
            padx=10,
            pady=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.tag_configure("info", foreground="#EAECF0")
        self.log_text.tag_configure("success", foreground="#86EFAC")
        self.log_text.tag_configure("warning", foreground="#FDE68A")
        self.log_text.tag_configure("error", foreground="#FDA29B")
        self.log_text.tag_configure("debug", foreground="#93C5FD")
        self.log_text.configure(state="disabled")

    def _file_row(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, command) -> None:
        ttk.Label(parent, text=label, style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(18, 7))
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=(18, 7), padx=(0, 8))
        ttk.Button(parent, text="浏览", style="Tool.TButton", command=command).grid(row=row, column=2, sticky="ew", pady=(18, 7))

    def _load_logo(self, label: ttk.Label) -> None:
        logo_path = resource_path("assets", "logo.png")
        if not logo_path.exists():
            return
        image = tk.PhotoImage(file=str(logo_path))
        factor = max(1, round(max(image.width(), image.height()) / 58))
        self._logo = image.subsample(factor, factor)
        label.configure(image=self._logo)

    def _set_icon(self) -> None:
        ico_path = resource_path("assets", "logo.ico")
        png_path = resource_path("assets", "logo.png")
        try:
            if ico_path.exists():
                self.iconbitmap(str(ico_path))
            elif png_path.exists():
                icon = tk.PhotoImage(file=str(png_path))
                self.iconphoto(True, icon)
        except tk.TclError:
            pass

    def choose_firmware(self) -> None:
        path = filedialog.askopenfilename(title="选择固件文件", filetypes=[("TI-TXT firmware", "*.txt"), ("All files", "*.*")])
        if path:
            self.firmware_var.set(path)
            self._log("info", f"Firmware selected: {path}")

    def choose_password(self) -> None:
        path = filedialog.askopenfilename(title="选择密码文件", filetypes=[("Password text", "*.txt"), ("All files", "*.*")])
        if path:
            self.password_var.set(path)
            self._log("info", f"Password selected: {path}")

    def choose_common_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 common 工具目录")
        if path:
            self.common_dir_var.set(path)

    def refresh_ports(self) -> None:
        try:
            infos = list_serial_ports()
        except Exception as exc:
            self._log("error", f"Refresh COM ports failed: {exc}")
            return
        self._ports = [
            item.device if item.description.strip().upper() == item.device.upper() else f"{item.device} - {item.description}"
            for item in infos
        ]
        self.port_combo.configure(values=self._ports)
        xds_port = find_xds110_port()
        if xds_port:
            for item in self._ports:
                if item.upper().startswith(xds_port.upper()):
                    self.port_var.set(item)
                    break
            self._log("success", f"Found XDS110 UART: {xds_port}")
        elif self._ports and not self.port_var.get():
            self.port_var.set(self._ports[0])
        self._log("info", f"COM ports: {len(self._ports)}")

    def start_burn(self) -> None:
        if self._worker and self._worker.is_alive():
            return

        try:
            options = self._collect_options()
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc))
            return

        self._cancel_event.clear()
        self._set_progress(0)
        self._set_running(True)
        self._log("info", "Burn started.")
        self._worker = threading.Thread(target=self._burn_worker, args=(options,), daemon=True)
        self._worker.start()
        self._start_activity_animation()

    def cancel_burn(self) -> None:
        self._cancel_event.set()
        self.status_var.set("Cancelling")
        self._set_action_state("cancelling", "正在取消...")
        self._log("warning", "Cancel requested.")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _collect_options(self) -> BurnOptions:
        firmware = Path(self.firmware_var.get().strip())
        password = Path(self.password_var.get().strip())
        common_dir = Path(self.common_dir_var.get().strip())
        if not firmware.exists():
            raise ValueError("请选择有效的固件 .txt 文件。")
        if not password.exists():
            raise ValueError("请选择有效的密码文件。")
        if self.bridge_var.get() != "manual" and not common_dir.exists():
            raise ValueError("XDS 模式需要有效的 common 工具目录。")

        selected_port = self.port_var.get().strip()
        port = selected_port.split(" - ", 1)[0].strip() if selected_port else ""
        return BurnOptions(
            firmware_path=firmware,
            password_path=password,
            bridge_mode=self.bridge_var.get(),
            serial_port=port,
            xds_common_dir=common_dir,
            start_application=self.start_app_var.get(),
        )

    def _burn_worker(self, options: BurnOptions) -> None:
        burner = Mspm0BslBurner(
            log=lambda level, message: self._event_queue.put(("log", (level, message))),
            progress=lambda value, message: self._event_queue.put(("progress", (value, message))),
            cancel_event=self._cancel_event,
        )
        try:
            burner.burn(options)
        except BurnCancelled as exc:
            self._event_queue.put(("cancelled", str(exc)))
        except (FirmwareParseError, PasswordParseError, RuntimeError, OSError) as exc:
            self._event_queue.put(("failed", str(exc)))
        except Exception as exc:
            self._event_queue.put(("failed", f"Unexpected error: {exc}"))
        else:
            self._event_queue.put(("done", "烧录完成。"))

    def _poll_worker_events(self) -> None:
        while True:
            try:
                event, payload = self._event_queue.get_nowait()
            except queue.Empty:
                break
            if event == "log":
                level, message = payload  # type: ignore[misc]
                self._log(level, message)
            elif event == "progress":
                value, message = payload  # type: ignore[misc]
                self._set_progress(int(value))
                self.status_var.set(str(message))
                self._set_action_state("running", str(message))
            elif event == "done":
                self._set_progress(100)
                self.status_var.set("Done")
                self._log("success", str(payload))
                self._set_running(False)
                self._set_action_state("done", str(payload))
                messagebox.showinfo(APP_NAME, str(payload))
            elif event == "cancelled":
                self.status_var.set("Cancelled")
                self._log("warning", str(payload))
                self._set_running(False)
                self._set_action_state("cancelled", str(payload))
            elif event == "failed":
                self.status_var.set("Failed")
                self._log("error", str(payload))
                self._set_running(False)
                self._set_action_state("failed", "烧录失败")
                messagebox.showerror(APP_NAME, str(payload))
        self.after(120, self._poll_worker_events)

    def _set_running(self, running: bool) -> None:
        self.burn_button.configure(text="烧录中..." if running else "开始烧录", state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        if running:
            self.status_var.set("Running")
            self._set_action_state("running", "正在准备烧录...")
        else:
            self._stop_activity_animation()
            self._cancel_event.clear()

    def _set_progress(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self.progress_var.set(value)
        self.progress_text_var.set(f"{value}%")

    def _set_action_state(self, state: str, message: str) -> None:
        states = {
            "idle": ("#98A2B3", "待命", "Idle.Horizontal.TProgressbar"),
            "running": ("#0F6CBD", "运行中", "Active.Horizontal.TProgressbar"),
            "cancelling": ("#F79009", "取消中", "Active.Horizontal.TProgressbar"),
            "done": ("#16A34A", "完成", "Done.Horizontal.TProgressbar"),
            "cancelled": ("#667085", "已取消", "Idle.Horizontal.TProgressbar"),
            "failed": ("#D92D20", "失败", "Error.Horizontal.TProgressbar"),
        }
        color, label, progress_style = states.get(state, states["idle"])
        if self._activity_canvas is not None and self._activity_dot is not None:
            self._activity_canvas.itemconfigure(self._activity_dot, fill=color)
            self._activity_canvas.coords(self._activity_dot, 4, 4, 12, 12)
        if self._activity_label is not None:
            self._activity_label.configure(text=label)
        if self.progress_bar is not None:
            self.progress_bar.configure(style=progress_style)
        self.phase_label.configure(text=message)

    def _start_activity_animation(self) -> None:
        self._stop_activity_animation()
        self._activity_step = 0
        self._animate_activity()

    def _animate_activity(self) -> None:
        if not (self._worker and self._worker.is_alive()):
            self._activity_after_id = None
            return
        if self._activity_canvas is not None and self._activity_dot is not None:
            radius = 4 + (self._activity_step % 3)
            center = 8
            self._activity_canvas.coords(
                self._activity_dot,
                center - radius,
                center - radius,
                center + radius,
                center + radius,
            )
            self._activity_step = (self._activity_step + 1) % 6
        self._activity_after_id = self.after(180, self._animate_activity)

    def _stop_activity_animation(self) -> None:
        if self._activity_after_id is not None:
            self.after_cancel(self._activity_after_id)
            self._activity_after_id = None

    def _log(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        tag = level if level in {"info", "success", "warning", "error", "debug"} else "info"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


def main() -> None:
    app = MicuBslApp()
    app.mainloop()
