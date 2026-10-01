# 在 Windows 电脑上部署（朋友的常开电脑）

目标：把这个羽毛球报名 Agent 放到一台**全天开机、不睡眠**的 Windows 电脑上，24 小时自动盯着报名表抢位。

> ⚠️ **同一时间只能跑一个实例！** 在这台 Windows 上跑起来后，记得把你 Mac 上的停掉：
> `launchctl unload ~/Library/LaunchAgents/com.badminton.agent.plist`

---

## 第 0 步：先处理两个密码文件（安全）

这个压缩包里**故意不含**你的两个秘密文件，需要在这台 Windows 上单独补上：

1. **`credentials\service_account.json`** —— 服务账号密钥。把你的那份拷进 `credentials\` 文件夹即可（它只能改那一张报名表，风险可控）。
2. **`.env`** —— 里面要填 Gmail 应用专用密码。**强烈建议**去 https://myaccount.google.com/apppasswords **另外生成一个新的应用密码**专给这台机器用（以后能单独撤销，不影响你自己）。或者干脆在 `.env` 里设 `EMAIL_ENABLED=false`，就不用把 Gmail 密码放到别人电脑上（代价是不发通知邮件）。

---

## 第 1 步：装 Python

1. 打开 https://www.python.org/downloads/ → 下载 Python 3（最新版即可）
2. 运行安装包，**第一屏务必勾选 “Add python.exe to PATH”**，再点 Install
3. 装完可在“命令提示符”输入 `python --version` 验证

## 第 2 步：放好文件

把这个 `badminton-agent` 文件夹解压到一个固定位置，比如：
`C:\Users\<用户名>\badminton-agent`

然后：
- 复制 `.env.example`，改名为 `.env`，用记事本打开，填好 `SPREADSHEET_ID` 等（可参照你 Mac 上那份 `.env`）
- 把 `service_account.json` 放进 `credentials\` 文件夹

## 第 3 步：安装依赖（双击即可）

双击 `scripts\setup_windows.bat`
→ 它会自动建虚拟环境并装好所有依赖。看到“完成！”就成功。

## 第 4 步：先试跑一次

双击 `scripts\test_once_windows.bat`
→ 会前台扫描一次并打印日志。确认能连上表格、行为正常（能看到 New venue / Registered / Available slots 等日志）。

## 第 5 步：设为开机自启、后台常驻

双击 `scripts\install_task_windows.bat`
→ 它会创建一个名为 **BadmintonAgent** 的计划任务：登录后自动在后台运行（用 `pythonw` 启动，**没有黑窗口**），并立即启动一次。

**（可选）让它崩溃也能自动重启**：打开“任务计划程序” → 找到 `BadmintonAgent` → 右键“属性” → “设置”选项卡 → 勾选“**如果任务失败，则每隔 1 分钟重新启动**”。

## 第 6 步：关掉睡眠（关键！）

“开着”不等于“不睡”。设置 → 系统 → 电源和睡眠：
- **屏幕**：可以关（不影响后台）
- **睡眠**：改成“**从不 / Never**”

否则电脑一睡，程序就停了。

---

## 日常管理

| 操作 | 做法 |
|---|---|
| 看日志 | 记事本打开 `data\agent.log` |
| 确认在运行 | 任务管理器里能看到 `pythonw.exe`；或“任务计划程序”里 BadmintonAgent 状态为“正在运行” |
| 改了 `.env` / 代码后 | 双击 `uninstall_task_windows.bat` 再双击 `install_task_windows.bat` |
| 停止 / 卸载 | 双击 `scripts\uninstall_task_windows.bat` |

---

## 常见问题

- **提示找不到 python**：Python 没装或没勾“Add to PATH”，重装并勾选。
- **time zone 相关报错**：确保 `setup_windows.bat` 成功装了依赖（其中的 `tzdata` 是 Windows 必需的时区库）。
- **403 / 权限错误**：`service_account.json` 里的机器人邮箱没被“共享为编辑者”到报名表；或密钥文件没放对位置。
- **计划任务创建失败**：右键 `install_task_windows.bat` → “以管理员身份运行”。
