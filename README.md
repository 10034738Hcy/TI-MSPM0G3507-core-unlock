# TI-MSPM0G3507-core-unlock

基于原 `MSPM0 BSL GUI` 的 BSL 流程重构。

## 使用

1. 选择 TI-TXT 格式固件 `.txt`。
2. 选择 32 字节 BSL 密码文件，默认文件位于 `BSL_Password32_Default.txt`。
3. 选择 XDS110 LaunchPad、Standalone XDS110 或手动串口模式。
4. 刷新并确认 COM 口。
5. 点击 `开始烧录`。

## 官方 LaunchPad 板

1. 直接插 USB，让电脑识别到 XDS110。
2. 打开 MICU MSPM0 BSL烧录工具.exe。
3. 固件文件选择 CCS/IAR/Keil 导出的 TI-TXT `.txt`。
4. 密码文件用默认的 `BSL_Password32_Default.txt`。
5. 模式选 XDS110 LaunchPad。
6. COM 口一般会自动识别 XDS110 Class Application/User UART，没有就点刷新。
7. 点开始烧录。

官方 LP-MSPM0G3507 的 BOOT 键是 S1(PA18)。使用 XDS110 LaunchPad 模式时，正常不需要手动按 BOOT，工具会通过 XDS110 控制进入 BSL。

## 最小系统板 / 自己画的板

推荐用手动串口模式，接普通 USB-TTL：

```text
USB-TTL TXD -> MSPM0G3507 PA11 / BSLRX
USB-TTL RXD -> MSPM0G3507 PA10 / BSLTX
USB-TTL GND -> 板子 GND
```

电平必须是 3.3V TTL，不要用 RS232 电平。板子自己供电即可，USB-TTL 的 3V3 不一定要接，除非你确认它能稳定供电。

进入 BSL 的方法：

1. 按住 BOOT/BSL 按键，也就是把 PA18 置为有效状态。
2. 按一下复位 NRST，或者按住 BOOT 后重新上电。
3. 松开复位，保持/松开 BOOT 取决于你的板子电路，通常复位释放后即可。
4. 在工具里选手动串口，选择 USB-TTL 对应 COM 口。
5. 尽快点开始烧录，本地资料提醒进入 BSL 后最好 5 秒内开始下载。

MSPM0G3507 默认 UART BSL 引脚是：PA10 = BSLTX，PA11 = BSLRX。注意连接 USB-TTL 时 TX/RX 要交叉接。
