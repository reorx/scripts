---
created: 2026-10-28
tags: [android, honor, cleanup]
---

# 第一期：精简助手、推荐和游戏入口

## PRD

属于[系统精简总计划](2026-10-28-honor-system-cleanup.md)。用户已确认第一批 14 项全部处理，2026-10-29 设备重新连接后执行。

移除 YOYO 助手及推荐、负一屏、快应用、小游戏等闲置入口。接受相关卡片、全局搜索、语音助手和免安装应用功能消失；基本桌面、系统界面及日常功能应保持正常。魔法画报先停用，其余项目优先卸载，不支持时停用。

## Tech Design

### 2026-10-29 执行结果

用户本次要求「先把第一批禁了看看效果」，覆盖下表原定卸载策略：**14 项全部仅停用**，未卸载、未清数据；第二、三期未执行。

- 已核实设备 `AB9UUT4510000125`、`ALI-AN00`、当前用户 0、机主已解锁。14 项均是已安装系统包，变更前均为 `enabled=0`。
- 按下述依赖顺序逐项执行 `pm disable-user --user 0`，14 项全部回读为 `installed=true enabled=3`，无失败或恢复项。
- magicvoice 停用前，将原来指向它的 `voice_interaction_service`、`voice_recognition_service` 设为空字符串；`assistant` 原本为空，未修改。后续发现交互服务引用被系统回填，包仍为停用；再次清空后两项均为空，`dumpsys voiceinteraction` 显示 `No active implementation`。重启后需再检查引用是否回填。未改输入法设置或厂商手势开关，长按电源等入口及输入法语音仍待实测。
- 魔法画报仍与 SystemUI 共享 UID 10061；只停用了画报包，SystemUI 保持 `enabled=0`。桌面与状态栏显示已检查，未发现错误弹框；桌面仍有「YOYO 建议」文字，未整理桌面布局。
- 第三方清单操作前后相同：11 项，白名单外 0；闲鱼、哔哩哔哩在本次操作前已不在清单，原因未调查。
- 未重启，未完成完整功能验收；锁屏、桌面滑动、相机/图库、输入法语音、电话/短信、银行/支付宝及保留服务待用户体验。当前不得据此认定第一期验收通过，也不自动推进第二期。
- 原始状态、默认设置完整快照、依赖服务、逐项日志及截图保存在 `tmp/2026-10-29-honor-system-cleanup/`，不提交设备原始数据。

恢复任一目标包：`adb -s AB9UUT4510000125 shell pm default-state --user 0 <包名>`（系统已确认支持，原状态均为 default）。恢复 YOYO 时还需将两个 secure 设置分别还原为 `com.hihonor.magicvoice/com.hihonor.magicvoice.voiceui.service.MagicVoiceInteractionService` 和 `com.hihonor.magicvoice/.voiceui.service.MagicVoiceRecognitionService`，并回读确认。

### 精确目标

| 名称 | 包名 | 动作 |
| --- | --- | --- |
| YOYO 智能体 | `com.hihonor.magicvoice` | 解除默认语音服务引用后，卸载优先 |
| YOYO 建议 | `com.hihonor.assistant` | 卸载优先 |
| YOYO 记忆 | `com.hihonor.collectcenter` | 卸载优先 |
| YOYO 拍照问 | `com.hihonor.lens` | 卸载优先 |
| App 建议 | `com.honor.yoyoappsug` | 卸载优先 |
| YOYO 建议卡片集 | `com.honor.yoyocards` | 卸载优先 |
| 负一屏 | `com.hihonor.hiboard` | 卸载优先 |
| 快应用引擎 | `com.hihonor.quickengine` | 卸载优先 |
| 小游戏引擎 | `com.hihonor.quickgame` | 卸载优先 |
| 游戏管家 | `com.hihonor.gameassistant` | 卸载优先 |
| 每日视频 | `com.hihonor.video` | 卸载优先 |
| 荣耀搜索 | `com.hihonor.search` | 卸载优先 |
| 智能小程序 | `com.baidu.swan` | 卸载优先 |
| 魔法画报 | `com.hihonor.magazine` | 仅停用验证 |

### 依赖与执行顺序

2026-10-28 实测：`voice_interaction_service` 和 `voice_recognition_service` 指向 magicvoice；hiboard 被荣耀桌面绑定；magazine 与 `com.android.systemui` 同为 UID 10061。执行前重新确认，不能按旧值盲写。

- [ ] 保存目标包和默认语音服务的原值，区分设置原本不存在与空字符串。
- [ ] 先处理每日视频、游戏管家、小游戏引擎、智能小程序，逐项回读状态。
- [ ] 处理 YOYO 记忆、拍照问、建议、App 建议、卡片集、负一屏、荣耀搜索，再移除快应用引擎，减少上层入口继续调用已删引擎。
- [ ] 通过当前系统支持的设置界面/接口取消 YOYO 默认语音交互和唤醒入口，确认相关默认引用不再指向待删除服务后处理 magicvoice。不要顺带清空密码保险箱或输入法设置；输入法语音输入也需验证。
- [ ] 停用魔法画报；不操作整个共享 UID，不停止或停用 systemui。检查锁屏、状态栏、通知栏和桌面。
- [ ] 验收并记录 14 项分别是卸载、停用、恢复还是未完成。

### 验收与恢复

采用总计划中的状态回读、恢复和归档规则。重点验证：桌面滑动与应用启动正常；原 YOYO/负一屏入口不再拉起被处理组件；失效搜索/语音手势不造成循环弹框；锁屏、相机、图库、输入法、Wi-Fi 正常。需要用户辅助核对正常通话、短信和银行/支付宝使用，不发起真实交易。首次重启后再次回读安装状态，正常安全更新不视为异常回装。
