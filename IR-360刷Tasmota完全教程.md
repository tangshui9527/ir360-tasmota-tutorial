# IR-360 红外遥控器刷 Tasmota + 接入 Home Assistant 完全教程

> 记录时间：2026-09-27 ｜ 全程实际成功案例，含所有踩坑实录
> 成果：涂鸦（Tuya）WiFi 红外万能遥控器 → Tasmota 14.6.0 (tasmota-ir) → Home Assistant 面板按钮控制格力风扇

---

## 一、设备信息

| 项目 | 内容 |
|---|---|
| 设备 | IR-360 涂鸦 WiFi 红外万能遥控器（白色，正面红外发射窗） |
| 主控 | ESP8266EX，MAC `a8:48:fa:c7:8a:82` |
| Flash | 1MB（全量备份验证 E9 魔数） |
| 原固件 | 涂鸦出厂固件 |
| 新固件 | Tasmota **14.6.0 tasmota-ir 变体**（注意不是标准 tasmota.bin，原因见后文） |
| 刷机 IP | 192.168.31.29（DHCP） |
| 刷机方式 | CH340 串口（USB 转 TTL）+ esptool |
| 最终接线 | 板子自供电（原 USB 线），串口只接 TX/RX/GND 三根 |

**GPIO 功能最终确认：**

| GPIO | 功能 | 说明 |
|---|---|---|
| GPIO14 | IRsend（红外发射，功能码 8） | 实测有效（GPIO12 无效） |
| GPIO5 | IRrecv（红外接收，功能码 51） | 实测有效 |
| 其余 | 全 0 | 不要乱配 |

**最终模板：**

```json
{"NAME":"IR-360","GPIO":[0,0,0,0,0,51,0,0,0,0,8,0,0],"FLAG":0,"BASE":18}
```

> 14.6.0 的 `Template` 回显会把 51/8 显示为新编码 1088/1056（功能码<<5 换算），两者等价，不用慌。

---

## 二、来龙去脉

这设备原本走涂鸦云 + 涂鸦 App，想脱离云、接进本地 Home Assistant。路线：串口刷 Tasmota → MQTT 接 HA → 面板按钮发红外。

整个任务分四大阶段：

1. **备份 + 刷机**（串口 + esptool）
2. **配置攻坚**（Web 命令层离奇死亡 → MQTT 通道 → OTA 换固件变体）
3. **红外功能实现**（找发射脚 → 抓码 → 回放）
4. **接入 HA**（MQTT 集成 + 按钮实体 + 面板卡片）

---

## 三、刷机阶段（串口 + esptool）

### 3.1 接线

```
CH340        IR-360 板
TX    ────→  RX（交叉！）
RX    ←────  TX
GND   ─────  GND
（以上三根刷机全程不动）

进刷机模式专用：
IO0   ──碰── GND   RST ──碰── GND
```

**关键经验（实测修正过的认知）：**

- **IO0 只在 RST 复位瞬间被采样一次**。进刷机模式后芯片无限等待握手、不超时退出，**IO0 和 RST 全部可以松手**，再慢慢接 TX/RX/GND（本教程实测，纠正了网上"全程按住"的过度保守说法）。
- 刷机模式下芯片**串口静默是常态**（开机横幅 74880 波特率只打一次），静默 ≠ 没进模式，直接试 esptool 握手。
- 板子**自供电**（原 USB 线供电），esptool 必须 `--before no-reset --after no-reset`，否则自动复位会打乱模式。
- **杜邦线虚碰是头号故障源**：握手成功过一次之后再也连不上 → 重插线就好了。

### 3.2 备份原厂固件（必做！）

```bash
esptool.py --port /dev/ttyUSB0 --baud 115200 \
  --before no-reset --after no-reset \
  read_flash 0x0 1048576 ir360-backup.bin
```

验证：文件 1MB、开头魔数 `E9`。备份保存在 `C:\Users\tang\ir360-backup.bin`（刷机用的 Win11 电脑上）。

**值守循环思路**：写个 python 脚本每 6 秒监听 74880 波特率的串口开机横幅 + 试 esptool 握手，成功自动执行备份。人只负责"IO0 碰 GND + RST 碰 GND"这一个动作，比掐着秒表强得多。

### 3.3 刷入 Tasmota

```bash
esptool.py --port /dev/ttyUSB0 --baud 115200 \
  --before no-reset --after no-reset \
  write_flash 0x0 tasmota.bin
```

刷完哈希校验 → 拆 IO0/RST → 重启 → 设备发出 `tasmota-XXXX` 热点 → 手机连上配网（填家里 WiFi）。

---

## 四、配置攻坚（本案例最曲折的部分）

### 4.1 症状：Web 命令层离奇死亡

刷完配网后出现诡异故障：

| 路径 | 状态 |
|---|---|
| `/`（主页静态部分） | ✅ 200 |
| `/cm?cmnd=...`（命令接口） | ❌ 空响应（curl exit 52） |
| `/cs` `/cn` `/in` 等功能页 | ❌ 全死 |
| 未知路径（如 /foo123） | ✅ 404 正常 |

从 Mac 和 armbian 两台机器双点验证同结果；设备**并不重启**（主页 AJAX 一直 200）。

**排查过程中的弯路**（都记录在此免得再踩）：
- 最初误判"GPIO5 红外接收导致中断风暴"→ 不对，全零模板照样死；
- 误判"自定义模板 Module 0 是毒药"→ 不对，Module 1 也死；
- 误判"固件版本 bug"→ 降级 15.6.0→14.6.0 照样死。

**真正的原因**：设备串口 TX 发出的日志文本，被悬空的 RX 耦合回来，解析成命令 → 回 `Unknown` → 又产生新日志 → **无限自激循环**（每秒约 17 条，内容全是"带最新时间戳的日志行"）。这个洪水把 ESP8266 单线程的 Web 命令处理活活吃干。控制台日志里的 `Serial buffer overrun` 刷屏就是它的马甲。

**试过且无效的压制手段**（全部无效，真因是硬件级回环）：
- `SerialLog 0` / `MqttLog 0` / `SysLog 0` / `WebLog 0` 全静音 —— 1.5 秒内 Active 弹回
- `SerialBuffer 520`（官方缓冲扩容偏方）—— 无效
- 开机规则 `Rule1 ON System#Boot DO ... ENDON` —— 无效
- OTA 降级固件版本 —— 无效

**结论：洪水治不了，但也不碍事**——只要控制通道不依赖 Web 命令层。

### 4.2 救命通道盘点（哪个通道什么时候能用）

| 通道 | 可靠性 | 备注 |
|---|---|---|
| Safari 网页控制台（Console → 命令输入框） | ⭐ 洪水中照常工作 | 唯一 Web 侧救命稻草（Chrome 不行；curl 也不行） |
| MQTT（cmnd/tasmota_C78A82/...） | ⭐ 常态可靠 | 洪水期命令能穿透噪音，主力通道 |
| `/.?rst=Restart` 软重启 | 可用 | 设备还没死透时能远程重启 |
| Web `/cm` | ❌ 基本不可用 | 只有 Reset 1 后几分钟活窗 |

> **经验**：这类设备一旦 Web 命令层出问题，第一件事是接 MQTT，别跟 Web 死磕。

### 4.3 MQTT 通道搭建

1. armbian（192.168.31.230）装 `mosquitto` + `mosquitto-clients`
2. `/etc/mosquitto/conf.d/tasmota.conf`：
   ```
   listener 1883 0.0.0.0
   allow_anonymous true
   ```
3. ufw 放行：`ufw allow from 192.168.31.0/24 to any port 1883 proto tcp`
4. 设备侧（Safari 控制台发的）：
   ```
   Backlog MqttHost 192.168.31.230; MqttPort 1883; Restart 1
   ```
5. broker 日志看到 `New client connected ... as DVES_C78A82` 即接入成功。主题前缀 `tasmota_C78A82`。

### 4.4 OTA 换固件（本地两段式）

OTA 是**两段式**：设备先拉 `tasmota-minimal.bin.gz` 腾空间，再拉完整版。**目录里两个文件都必须有**，否则 404 卡死。

外网 OTA 会被洪水拖到超时 → 改**局域网本地 OTA**：

```bash
# armbian 上
curl -o /tmp/tasmota-minimal.bin.gz http://ota.tasmota.com/tasmota/release-14.6.0/tasmota-minimal.bin.gz
curl -o /tmp/tasmota-ir.bin.gz      http://ota.tasmota.com/tasmota/release-14.6.0/tasmota-ir.bin.gz
cd /tmp && nohup python3 -m http.server 8124 &
ufw allow from 192.168.31.0/24 to any port 8124 proto tcp
```

```
MQTT: OtaUrl http://192.168.31.230:8124/tasmota-ir.bin.gz
MQTT: Upgrade 1
```

本案例共 OTA 两次：15.6.0 → 14.6.0（tasmota.bin），再 tasmota.bin → **tasmota-ir**（14.6.0）。设置（WiFi/MQTT/模板）全程幸存。

> **为什么最后必须用 tasmota-ir**：标准 tasmota.bin 的 IRSend 发送协议表里**没有 RAW/Pronto**，回放原始波形会报 `Protocol not supported` 或 `Invalid JSON`。tasmota-ir 变体才支持完整发送。

---

## 五、红外功能实现

### 5.1 找发射脚（手机相机大法）

配置模板逐个试，每次 `IRSend` 发 NEC 测试码，**手机前置摄像头**看红外窗：

```
GPIO12 = 8（IRsend）→ 灯不亮 ✗
GPIO14 = 8（IRsend）→ 灯闪了 ✓
```

> 后置摄像头多有红外滤镜，用**前置**；离红外窗 10~20cm；闪的是暗紫/暗白小点。

### 5.2 抓码（SetOption58）

```
MQTT: SetOption58 1      ← 开启原始波形解码
```

之后拿格力风扇遥控器逐键对准按一次，`tele/tasmota_C78A82/RESULT` 里就有：

```json
{"IrReceived":{"Protocol":"UNKNOWN","Bits":50,"Hash":"0xABD4D16E",
 "RawData":"+1250-435Ab+485-1200+1280-410AbCdCdCd...","RawDataInfo":[99,99,1]}}
```

格力风扇是私有协议 → `Protocol: UNKNOWN` 是正常的，**Hash + RawData 就是它的指纹**。

### 5.3 回放（关键语法！）

压缩 RawData **可以原样回填**，语法是 `IRSend 0,<RawData>`（`0` = 38kHz 默认载波）：

```
MQTT: IRSend 0,+1250-435Ab+485-1200+1280-410AbCdCdCd+480-1205G-...
```

驱动回 `{"IRSend":"Done"}`，风扇物理响应 = 闭环成功。

> ⚠️ 踩坑：`IRSend {"Protocol":"RAW","Buffer":"..."}` 在标准 tasmota.bin 上报 "Protocol not supported"；JSON 里给 `ProntoData` 也不支持。**必须 tasmota-ir 变体 + `IRSend 0,<raw>` 命令行语法**。
> 另一个坑：如果用逗号微秒格式（`0,1250,435,...`），`Bits` 给 0 会报 "No Protocol, Bits or Data"。

### 5.4 抓码错位事故与修正

按"开关 → 调速 → 模式 → 摇头 → 定时"逐键各按一次，结果"开关"抓出**两条**波形（一长一短）。我按时间顺序想当然地把第 3 条贴给了"调速"，导致中间 4 个键整体错位一格——用户实测"点定时出的是风速"才暴露。

**修正后的真实映射**（如需复刻请以此为准）：

| 键 | Hash | 备注 |
|---|---|---|
| 开关 | 0xABD4D16E | 第一次抓的 50 位波形 |
| 调速 | 0xDA0AE878 | 24 位短波形 |
| 摇头 | 0xD8E4DC16 | |
| 定时 | 0x575183E6 | |
| ~~模式~~ | 0xDB05A496 | 无作用，弃用 |

**教训：逐键抓码时每个键之间留足间隔，抓完立即回放验证一个再继续，别攒到最后。**

完整码库（含 raw 波形）见仓库内 `ir360-gree-fan-codes.json`。

---

## 六、接入 Home Assistant

### 6.1 MQTT 集成（版本坑！）

HA 2026.3 中 **broker 不能写在 configuration.yaml**（会报 `mqtt->0->broker is an invalid option`），yaml 里只放实体定义，broker 走 config entry（UI 配置）。

因设备远程无法点 UI，直接向 `.storage/core.config_entries` 注入 entry（改前备份！）：

```json
{"domain":"mqtt","title":"MQTT","source":"user",
 "data":{"broker":"192.168.31.230","port":1883,"discovery":true},
 "version":1,"minor_version":1,...}
```

### 6.2 按钮实体（yaml）

```yaml
mqtt:
  button:
    - name: "格力风扇 电源"
      unique_id: gree_fan_ir_power
      icon: mdi:power
      command_topic: cmnd/tasmota_C78A82/IRsend
      payload_press: "0,+1250-435Ab+485-1200..."   # 该键的原始波形
    # 风速 / 摇头 / 定时 同理
```

注意：中文 name 生成的 entity_id 是拼音（`button.ge_li_feng_shan_dian_yuan`），面板引用时要用真实 entity_id，别想当然写 `gree_fan_ir_power`。

### 6.3 面板卡片（Home 视图底部竖向列表）

```yaml
- type: vertical-stack
  cards:
    - type: custom:mushroom-template-card
      entity: button.ge_li_feng_shan_dian_yuan
      primary: 风扇电源
      icon: mdi:power
      icon_color: deep-orange
      tap_action:
        action: call-service
        service: button.press
        target: {entity_id: button.ge_li_feng_shan_dian_yuan}
    # 其余三个同理
```

### 6.4 已知残留问题

- Tasmota 每隔几秒短暂断连 MQTT 又重连（洪水病的副产品）。QoS0 消息偶尔落在断连窗口丢失——**按钮没反应就再按一次**。
- 端到端时延约 1~2 秒（MQTT + 红外帧长）。

---

## 七、命令速查（本设备实战版）

```bash
# 串口备份 / 刷机（Win11 + CH340）
esptool.py --port COM6 --baud 115200 --before no-reset --after no-reset read_flash 0x0 1048576 backup.bin
esptool.py --port COM6 --baud 115200 --before no-reset --after no-reset write_flash 0x0 tasmota.bin

# MQTT 查询 / 配置
mosquitto_pub -h 127.0.0.1 -t 'cmnd/tasmota_C78A82/Status' -m '3'
mosquitto_pub -h 127.0.0.1 -t 'cmnd/tasmota_C78A82/Template' -n
mosquitto_pub -h 127.0.0.1 -t 'cmnd/tasmota_C78A82/SetOption58' -m '1'

# 红外回放
mosquitto_pub -h 127.0.0.1 -t 'cmnd/tasmota_C78A82/IRsend' -m '0,+1250-435Ab+485-...'

# 本地 OTA（armbian）
cd /tmp && nohup python3 -m http.server 8124 &
# 设备侧: OtaUrl http://192.168.31.230:8124/tasmota-ir.bin.gz → Upgrade 1
```

---

## 八、经验教训清单

1. **ESP8266 只在复位瞬间采样一次 IO0**，进下载模式后可全松手。
2. **刷机前全量备份**（`read_flash 0x0 1048576`），验证魔数，任何时候都能回滚。
3. **杜邦线虚碰**是串口刷机头号故障源，握手失败先重插线。
4. **涂鸦红外桥类设备**：先试 GPIO14 发射 / GPIO5 接收（YTF/NEO Coolcam 同款），别从 GPIO12 开始瞎试。
5. **ESP8266 是单线程**——不存在"CGI 层崩了静态层活着"；看到主页活/功能页死，去查串口回环类自激。
6. **悬空 RX 会耦合 TX 的日志形成自激洪水**，能吃干 Web 命令层，且软件手段（全静音/扩缓冲/开机规则）未必治得了——绕开它（MQTT），别死磕。
7. **要回放未知协议红外**，固件必须选 **tasmota-ir** 变体；标准版没有 RAW 发送。
8. **OTA 是两段式**（minimal + 完整版），本地 OTA 服务目录两个文件都得有。
9. **抓码逐键验证**，尤其当某键抓出多条波形时——时间顺序对位会错位一格。
10. **HA 2026.x**：MQTT broker 只能走 config entry（UI），yaml 只放实体定义；中文实体名会变拼音 entity_id。
11. **Safari 网页控制台**是涂鸦类设备 Web 命令层全死时最后的救命稻草。
12. 改 HA 存储（.storage）前必备份 + 用 `docker stop ha` 停机再改。

---

## 九、文件清单

| 文件 | 位置 | 说明 |
|---|---|---|
| `ir360-gree-fan-codes.json` | 本仓库 | 格力风扇 5 键完整码库（raw 波形 + hash） |
| `ir360-backup.bin` | Win11 `C:\Users\tang\` | 原厂固件全量备份（1MB，勿删！） |
| HA 配置 | armbian `/DATA/AppData/HomeAssistant/config/` | mqtt button 定义在 configuration.yaml |
| mosquitto | armbian `/etc/mosquitto/conf.d/tasmota.conf` | 局域网匿名 broker |
