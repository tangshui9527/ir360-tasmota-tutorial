# IR-360 刷 Tasmota 完全教程

把涂鸦（Tuya）红外遥控器 IR-360 从涂鸦云彻底解放：备份原厂固件 → 刷 Tasmota → 打通红外收发 → 接入 Home Assistant，全程可复现。

## 设备信息

| 项目 | 参数 |
|---|---|
| 设备 | IR-360 涂鸦红外遥控桥 |
| 主控 | ESP8266EX，1MB flash |
| MAC | a8:48:fa:c7:8a:82 |
| 最终固件 | Tasmota **tasmota-ir 14.6.0** 变体（必须用 IR 变体才有 RAW 回放能力） |
| 红外发射脚 | **GPIO14**（GPIO12 实测无效） |
| 红外接收脚 | **GPIO5** |
| 模板 | `{"NAME":"IR-360","GPIO":[0,0,0,0,0,51,0,0,0,0,8,0,0],"FLAG":0,"BASE":18}` |
| 命令通道 | MQTT → `cmnd/tasmota_C78A82/`（Web `/cm` 需带 `Referer` 头，见后记） |

## 文件清单

- **[IR-360刷Tasmota完全教程.md](./IR-360刷Tasmota完全教程.md)** — 完整教程：刷机、Web 故障攻坚、OTA 两段式、找红外脚、抓码回放、HA 集成、12 条经验教训
- **[ir360-backup.bin](./ir360-backup.bin)** — 原厂固件全量备份（1MB，E9 魔数已验证），随时可回刷
- **[tasmota-ir-14.6.0.bin.gz](./tasmota-ir-14.6.0.bin.gz)** — 实际刷入的固件（Tasmota 官方发布包原样）
- **[ir360-gree-fan-codes.json](./ir360-gree-fan-codes.json)** — 格力风扇遥控完整码库（开关/风速/摇头/定时 5 键，实测可回放）

## 快速复现路线

1. **备份**：IO0 在 RST 复位瞬间接地一次进下载模式 → esptool `read_flash 0x0 0x100000` 全量备份
2. **刷机**：esptool 写入 `tasmota-ir.bin`（先删 flash 或直接覆盖均可）
3. **配网**：手机连 Tasmota AP → 配置 WiFi
4. **命令通道**：`MqttHost <broker IP>` 指向局域网 mosquitto（避开 Web 命令层的坑）
5. **红外配置**：模板设 GPIO14 发射 + GPIO5 接收 → `SetOption58 1` 抓原始码 → `IRSend 0,<RawData>` 回放

## 核心教训（详见教程）

- ESP8266 只在**复位瞬间采样 IO0 一次**，进下载模式后可松手，芯片无限等待
- 杜邦线虚碰是刷机失败的头号原因
- 标准 `tasmota.bin` **不支持 RAW/Pronto 回放**，红外设备必选 `tasmota-ir` 变体
- OTA 升级是**两段式**：先拉 `tasmota-minimal.bin.gz` 再拉完整版，本地 OTA 服务器目录必须两个都有
- Tasmota 的 MQTT broker 配置在新版 HA 里必须走 config entry，不能写 yaml
- **串口洪水根治法**：`SerialLog 0` + `SaveData 1`（MQTT 断开时 SerialLog 会动态恢复成保存值，必须把保存值本身改掉）
- **tasmota-ir 14.6.0 的 `/cm` 有 CSRF 校验**：必须带 `Referer: http://<设备IP>/` 头，curl 裸请求会被秒掐

## 现状

设备运行于局域网，红外收发双向可用，格力风扇 5 个按键已做成 HA 面板按钮，彻底脱离涂鸦云。
