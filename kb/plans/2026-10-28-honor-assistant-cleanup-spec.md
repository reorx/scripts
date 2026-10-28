---
created: 2026-10-28
tags: [android, honor, cleanup]
---

# 第一期：精简助手、推荐和游戏入口

## PRD

属于[系统精简总计划](2026-10-28-honor-system-cleanup.md)。用户已确认第一批 14 项全部处理，2026-10-29 设备重新连接后执行。

移除 YOYO 助手及推荐、负一屏、快应用、小游戏等闲置入口。接受相关卡片、全局搜索、语音助手和免安装应用功能消失；基本桌面、系统界面及日常功能应保持正常。魔法画报先停用，其余项目优先卸载，不支持时停用。

## Tech Design

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
