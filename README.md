# ZCode 多开（Windows）

给 ZCode 桌面客户端开多个**数据完全隔离**的实例：独立的会话/设置/项目列表、独立的任务栏按钮和托盘图标。实测版本：**3.10.2 ~ 3.14.0**（官方 Windows 用户级安装）。

> **先说结论：大胆用。** 这个工具只改 `app.asar` 一个文件且总留原版备份，出任何问题（起不来、闪退、报错）都可以：① 双击 `rollback-patch.cmd` 一键回滚原版；② 或直接重装 ZCode 覆盖一遍——都会完全恢复。处理完手头的问题后，欢迎带上报错信息（`repatch-log.txt` / `rollback-log.txt`）到 GitHub 开 issue，帮助适配你的版本。

## 原理（两层，缺一不可）

**第 1 层：官方运行时环境变量**（启动器脚本设置）

| 环境变量 | 作用 |
|---|---|
| `ZCODE_DATA_BASE_DIR` | 应用数据根目录（原 `~/.zcode`） |
| `ZCODE_DESKTOP_USER_DATA_DIR` | Electron userData + **单实例锁**，隔离不锁互斥全靠它 |
| `ZCODE_DESKTOP_APPLICATION_NAME` | 关于页显示的应用名 |
| `ZCODE_INSTANCE_ICON` | 窗口/任务栏/托盘图标覆盖（**必须 .png**，Electron nativeImage 不认 .ico） |
| `ZCODE_INSTANCE_AUMID` | 独立 AppUserModelID → 任务栏按钮不合并（副作用：该实例的 toast 通知可能不弹） |

**第 2 层：app.asar 补丁**。客户端有两处问题导致仅设环境变量不够：

1. 主进程向宿主进程（zcode-host，管 settings/会话）转发环境变量的条件代码失效，环境变量传不过去；
2. 约 20 处数据路径（settings / cli / checkpoints / 插件元数据）锚定在 `os.homedir()` 而不是数据目录变量上——不补的话项目列表、设置仍会共用 `~/.zcode`。

补丁器（`patch-zcode.py`）用**稳定锚点**（`ZCODE_DATA_BASE_DIR` / `".zcode"` / `getDataBaseDir` 标注 / `icon_windows.png` / `tray_icon.ico` 等混淆后不变的字符串）动态定位补丁点，不写死压缩后的变量名，所以小版本更新通常能自动适配。构建后还会对全部被修改的 chunk 跑 `node --check` 语法自检——语法错误（起不来那种）会在打补丁阶段被直接拦下，不会写入。

已核实：ZCode 的 Electron fuse 里 `EnableEmbeddedAsarIntegrityValidation` 为关闭状态，修改 asar 不会被完整性校验拦截。

## 快速开始

依赖：Python 3.8+；Node.js（语法自检用，强烈建议安装）。

1. **打补丁**：双击 `repatch-after-update.cmd`（会关闭 ZCode → 自动备份原版 `app.asar.bak-<版本>` → 打补丁 → 重启 ZCode）。
2. **生成实例图标**：`python make-instance-icon.py %USERPROFILE%\.zcode\icons\zcode-instance2 orange`（可换 `green/blue/purple/red` 或 `R G B`）。
3. **建实例启动器**：复制 `start-instance-example.cmd` 为 `start-zcode-instance2.cmd`，确认 5 个变量的路径存在。双击即启动实例 2；实例 3 同理再复制一份改路径。
4. 每个实例首次启动需各自登录一次。主实例（直接开 ZCode）不受任何影响。

建议给启动器建桌面快捷方式，图标用生成的 `.ico`。

## ZCode 更新后

更新完成、ZCode 正常打开过一次后，**再双击 `repatch-after-update.cmd`**。流程与首次相同：自动按当前版本重新备份、重新定位、重打补丁。

- 如果引擎打印 `PATCH ABORTED`：说明新版代码结构变化超出锚点覆盖范围（附上 `repatch-log.txt` 提 issue）。
- 任务栏分组偶尔显示错乱：**按 F5 刷新文件资源管理器**即可（Explorer 的分组缓存过期），不用重启。

## 出问题时回滚

双击 `rollback-patch.cmd`：按当前 ZCode 版本找到对应原版备份，恢复 `app.asar` 并重启 ZCode。**任何情况下都不需要重装 ZCode**（补丁只动 `app.asar` 一个文件，且总留有版本匹配的原版备份）。

## 踩坑记录（写进 README 的原因）

- `chcp 65001` + 中文内容的 .bat/cmd 会导致 cmd 解析错乱、**静默退出**——所以本仓库所有 cmd 都是纯 ASCII。
- 补丁产物曾有"图标链尾吞掉逗号"的 bug，产出 `...png"))H$=`，main 进程 ESM 编译直接 `SyntaxError: Unexpected identifier 'H$'`，客户端完全起不来。这就是现在有 `node --check` 语法闸门的原因。
- `--user-data-dir` 命令行参数无效（客户端会主动 `setPath` 覆盖），必须用 `ZCODE_DESKTOP_USER_DATA_DIR`。
- 任务栏/托盘图标是两套代码，`ZCODE_INSTANCE_ICON` 需同时覆盖 window icon 与 tray icon 两个函数。
- 想区分任务栏按钮还需要 `setAppUserModelId` 在图标赋值**之前**执行（AUMID 补丁点在三元表达式里时永远不会跑）。

## 合规提醒

本工具只做本地多开，不改授权/计费逻辑；多开实例登录同一账号时，额度共享同属一个账号，请遵守 ZCode 服务条款。

## License

MIT
