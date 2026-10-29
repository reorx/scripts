---
created: 2026-10-28
tags: [android, honor, cleanup]
---

# 第二期：停用闲置功能并保留指定服务

## PRD

属于[系统精简总计划](2026-10-28-honor-system-cleanup.md)，依赖[第一期验收](2026-10-28-honor-assistant-cleanup-spec.md)。用户确认第二批中保留 Windows 连接、荣耀云、荣耀智慧空间基础服务，其余全部停用。此期不将“停掉”扩大为卸载。

取消闲置的多屏协同、AI 通话、智能提醒、剪辑、动态壁纸、打印和平行空间功能，保持用户指定的保留功能及基本通信正常。

## Tech Design

### 2026-10-29 本次确认与结果

用户重新选择本次范围，仅停用以下 4 项，覆盖此前「其余全部停用」的批量安排：

| 项目 | 执行结果 |
| --- | --- |
| 剪辑 `com.hihonor.videoeditor` | 已停用，`installed=true enabled=3` |
| 平行空间 `com.hihonor.parallelspace` | 已停用，`installed=true enabled=3` |
| AI 通话 `com.hihonor.recordassistant` | 已停用，`installed=true enabled=3` |
| 多屏协同 `com.hihonor.pcassistant` | 已停用，`installed=true enabled=3` |

4 项变更前均为 `enabled=0`，未卸载、未清除数据。设备身份与用户 0 已核实；`dumpsys user` 仅见机主，没有额外用户或空间配置。多屏协同仅按包操作，没有操作系统共享 UID。

智能提醒、动态壁纸、打印助手、默认打印服务本次未操作。它们及下列 5 个保留包的用户状态均已与基线对比一致。拨号界面可正常打开，截图已检查，没有发起通话。Windows 连接的 launcher 入口解析无结果，显式启动 `.StartUpSettingActivity` 返回 Activity 不存在；缺少操作前入口测试，无法归因于本次停用，也不能宣称连接功能通过验收。未修改其组件状态。

真实通话、Windows 连接、荣耀云和智慧空间端到端使用，以及重启后状态仍待验证。如 Windows 连接出现影响，优先恢复多屏协同再对比。第一期完整体验验收尚未记录；本次依用户新确认执行此 4 项，不代表两期整体验收完成。第三期未执行。

基线、逐项日志、回读结果及截图位于 `tmp/2026-10-29-honor-system-cleanup/batch2/`。恢复任一目标使用 `adb -s AB9UUT4510000125 shell pm default-state --user 0 <包名>` 后回读（4 项原状态均为 default）。

### 停用清单

| 名称 | 包名 |
| --- | --- |
| 多屏协同 | `com.hihonor.pcassistant` |
| AI 通话 | `com.hihonor.recordassistant` |
| 智能提醒 | `com.hihonor.suggestion` |
| 剪辑 | `com.hihonor.videoeditor` |
| 动态壁纸 | `com.hihonor.livewallpaper.paradise` |
| 打印助手 | `com.hihonor.printassistant` |
| 默认打印服务 | `com.hihonor.printservice` |
| 平行空间 | `com.hihonor.parallelspace` |

### 明确保留

| 名称 | 包名 |
| --- | --- |
| 连接至 Windows | `com.microsoft.appmanager` |
| 连接至 Windows 服务 | `com.microsoftsdk.crossdeviceservicebroker` |
| 连接至 Windows 服务 | `com.hihonor.linktowindowsservice` |
| 荣耀云 | `com.hihonor.hncloud` |
| 荣耀智慧空间基础服务 | `com.hihonor.sceneservice` |

不操作这些包的安装、enabled、权限或应用数据。其它包若实际是这些保留功能的必要依赖，也不能以“顺手清理”删除。

### 执行与验收

- [ ] 保存 8 个目标和 5 个保留包的基线，核实是否新增用户/平行空间数据；若有待保护的数据先停止对应项。
- [ ] 先逐项停用剪辑、动态壁纸、两个打印组件、平行空间。停用动态壁纸前检查当前壁纸是否依赖该包；需要切换时保留原配置供恢复。
- [ ] 停用智能提醒，验证基础闹钟与日历仍正常；不调整通知权限白名单。
- [ ] 停用 AI 通话，验证系统拨号界面与正常通话；出现影响即恢复该包。
- [ ] 最后单独停用多屏协同。其 UID 为 1000，禁止对整个 UID 执行操作；验证保留的 Windows 连接。若存在必要依赖或功能受损，恢复 pcassistant，记录“因保留 Windows 功能而暂缓”，不牺牲用户明确保留的功能。
- [ ] 回读所有目标状态，确认 5 个保留包状态未变，重启后复查。

没有 Windows 电脑、荣耀云账号或智慧空间使用场景时，能完成包状态与入口检查，但不能宣称对应端到端功能已验证；明确留下实际未测项目。恢复和截图归档遵循总计划。
