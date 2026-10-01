# 羽毛球报名表自动监控与报名 Agent

基于 **Google Sheets API v4 + 服务账号**，周期性监控群里共享的羽毛球报名表（Google Sheets），检测到新场地后
自动为 `.env` 中 `REGISTER_NAMES` 配置的人报名，采用 **读 → 校验 → 写 → 再校验** 的并发安全流程，成功后发邮件通知。

> 📌 **这是一个通用工具**：报名的名字、表格结构、时区、邮箱等全部在 `.env` 里配置，代码里没有写死任何人名。
> 下文中的 `alice`、`bob` 只是示例名字，请替换成你自己（和同伴）的名字。

### 快速适配你自己的报名表

1. `cp .env.example .env`，然后修改：
   - `SPREADSHEET_ID` / `SHEET_NAME`：你的报名表；
   - `REGISTER_NAMES=alice,bob`：要报名的名字，逗号分隔，**顺序即优先级**（位置不够时靠前的先报），一个或多个都可以；
   - `PLAYER_FIRST_COL` / `PLAYER_COUNT` / `HEADER_ROW` / `DATA_START_ROW`：按你的表格布局填写；
   - `TIMEZONE`、SMTP 邮件相关配置。
2. 把 Google 服务账号的 JSON 密钥放到 `credentials/service_account.json`，并把服务账号邮箱以“编辑者”身份共享给这张表。
3. 先用 `DRY_RUN=true` 跑一次确认识别正确，再改成 `false` 正式运行。

> 本工具默认假设表格格式为：每行一个场地，包含 DayOfWeek / Date / Time / Field 列，后面跟 Player 1..N 报名格。
> 如果你的表格格式差别很大，需要调整 `src/parser.py`。

设计目标优先级（严格遵守）：

> **① 不覆盖别人 > ② 不重复报名 > ③ 快速发现新场地 > ④ 尽量所有人都抢到**

---

## ⚠️ 关于并发安全的一句实话

Google Sheets API v4 **没有单元格级别的 compare-and-swap / ETag 条件写**，写入是
“最后写入者获胜（last-write-wins）”。因此“绝对不覆盖任何人”无法只靠 API 在数学上保证。
本项目用三重手段把覆盖窗口压到最小、并做到与其他同类 Agent 之间的**最终一致**：

1. **写前再读目标格**：只向“刚刚这一刻确认为空”的单元格写入，把盲区窗口压到毫秒级；
2. **随机挑空位**：不抢“第一个空位”，而是在所有空位里随机选，两个机器人撞同一格的概率大幅下降；
3. **写后回读 + 重试**：写完立刻回读，发现自己被覆盖就换个新空位重试（最多 N 次，带随机抖动）。

`registrar.py` 严格保证的**不变量**：*绝不向一个刚读到非空的单元格写入*（`tests/` 用注入竞态的方式验证）。
残余风险仅存在于“别人的写入恰好落在我们最后一次校验读与写之间的极短盲区”，这是 Sheets API 的固有限制，已如实说明。

> 另外：报名表红字明确写着“没报名别来 / 不来请删名”。本工具只为你和同伴登记**真实要去**的名额，
> 并且**从不删除或覆盖他人**。请把它当作“帮你手快一点”的助手，别当占位器用。

---

## 一、系统架构

```
                 ┌─────────────────────────────────────────────┐
                 │                  agent.py                    │
                 │  轮询主循环 (poll + jitter, 信号优雅退出)      │
                 └───────┬───────────────┬──────────────┬───────┘
                         │               │              │
              读取整表    │               │ 报名          │ 通知
                         ▼               ▼              ▼
                 ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
                 │ sheets_client │ │  registrar   │ │  notifier    │
                 │  (Sheets API) │ │ 读-校验-写-验 │ │  (SMTP 邮件) │
                 └──────┬───────┘ └──────┬───────┘ └──────────────┘
                        │                │
              parse_table │       state.py │  (SQLite)
                        ▼                ▼
                 ┌──────────────┐ ┌──────────────────────────────┐
                 │  parser.py   │ │ known_venues / registrations │
                 │ 行->Venue    │ │ 幂等 + 去重 + 断电恢复         │
                 │ 日期/时间解析 │ └──────────────────────────────┘
                 └──────────────┘
                        │
                        ▼
                 ┌──────────────┐
                 │  dedupe.py   │  同一时间段多场地 -> 只选一个
                 └──────────────┘
```

**一次扫描周期（`agent.run_once`）**：

1. 一次 API 读取整张表 → `parser` 解析成 `Venue` 列表（无法解析日期/时间的行丢弃）；
2. 对每个 `venue_id ∉ known_venues` 打印 `New venue detected`（新场地事件）；
3. 过滤出**未来**场地 → 按 `dedupe_key` 分组；
4. 每组：若该时间段已 `complete` 则跳过；已 `partial` 只回到同一场地补人；否则 `dedupe.select_one` 选一个场地；
5. 对选中的场地跑 `registrar`（读-校验-写-再校验）；
6. 落库 `registrations`，按状态变化决定是否发邮件；
7. 把本次见到的所有 `venue_id` 写入 `known_venues`；
8. `sleep(interval + random(0, jitter))`。

---

## 二、新场地检测算法

- **唯一标识**：`venue_id = 日期 | 开始 | 结束 | 场地名`，例如 `2026-08-18|18:00|20:00|TSH1`。
  **绝不用行号做 ID** —— 行会因插入/删除/排序而移动。
- 维护持久化集合 `known_venues`。`venue_id ∉ known_venues` 即为新场地，触发事件并记日志。
- 一行仅因排序/插入/删除而**位置变化**时，`venue_id` 不变 → **不会误判为新场地**。
- 旧场地被删除只是从表里消失，不影响 `known_venues`；重启后从 SQLite 恢复，**不会把现有场地全部重新当成“新”**。

> 报名候选并不只看 known/new，而是看“该时间段是否已占到场”（见下），这样“一开始满、后来有人退位”的场地仍能补报。

---

## 三、同时间段去重逻辑（`dedupe.py`）

去重键 `dedupe_key = 日期 | 开始 | 结束`（不含场地名）。同一时间段多个场地只报一个：

1. 若该时间段已成功占到任意一个场地（`complete`/`partial`）→ 其余场地全部忽略；
2. 同时出现多个新场地 → 只选一个；
3. **优先选“空位 ≥ 需要人数”的场地**（能一次把所有人都放进去）；
4. 其次空位越多越好；
5. 条件相同 → 选表格中**最先出现**（行号最小）的；
6. 一旦占到，立即停止尝试同时间段其他场地。

---

## 四、并发冲突处理机制（`registrar.register_venue`）

对选中场地，循环最多 `MAX_RETRIES` 次：

1. **新鲜读**整行 24 个位置；
2. 幂等检查：已在表内的名字不再写；算出真实空位；
3. 位置不足时按 `REGISTER_NAMES` 顺序截断（靠前的优先），并在空位里**随机**挑目标格；
4. **写前再读**这几个目标格 → 若已被占 → 记 `Slot conflict detected` → 抖动后重试；
5. **一次批量写入**（缩小盲区窗口）；`DRY_RUN` 下只打印不写；
6. **写后回读**整行，校验自己的名字是否真实存在；
7. 全部命中 → `Registration verified successfully` 返回；
8. 被覆盖（盲区竞态）→ 换新空位重试；
9. 每次重试间 `random(WRITE_RETRY_JITTER_MS_MIN, MAX)` 毫秒抖动，避免与其他自动化完全同步。

**任何情况下都不向非空单元格写入**（这是被测试锁死的硬不变量）。

以 `REGISTER_NAMES=alice,bob` 为例：

| 剩余空位 | 行为 | 结果状态 |
|---|---|---|
| ≥ 2 | 同时写 alice + bob | `complete` |
| = 1 | 只写 alice，记录 bob `no_slot` | `partial` |
| = 0 | 不动表格 | `failed` |

---

## 五、状态持久化（`state.py`, SQLite）

`data/state.db` 两张表：

- **known_venues**(`venue_id` PK, `first_seen`, `last_seen`) —— 新场地判定；
- **registrations**(`venue_id` PK, `dedupe_key`, `date`, `start`, `end`, `field`,
  `status`, `name_status`(JSON：每个名字的报名状态), `detected_at`, `registered_at`)。

`status ∈ {complete, partial, failed}`；`name_status` 中每个名字的值 ∈ {registered, already, no_slot}。
断电/崩溃/重启后从这里恢复，天然幂等，`launchd` 拉起后不会重复报名、不会误判新场地。

---

## 六、邮件通知方案（`notifier.py`）

SMTP + STARTTLS（默认 Office365，也可换成 Gmail/QQ 等任意支持 SMTP 的邮箱）。按结果分三种：

- `complete`：**《羽毛球场地已自动报名》**，列出日期/时间/场地 + 报名的人 + “不来请提前删名”提醒；
- `partial`：成功邮件但注明哪些人已报名成功、哪些人因剩余位置不足未能报名；
- `failed`：**《发现新羽毛球场地但报名失败》**异常通知（仅首次变失败时发一次，不刷屏）。

邮件失败只记日志，**绝不影响报名主流程**。同一状态不重复发信（靠 `state` 里的状态变化判断）。

---

## 七、项目目录结构

```
badminton-agent/
├── README.md
├── requirements.txt
├── .env.example              # 配置示例
├── .gitignore
├── run.sh                    # 一键建 venv + 运行
├── credentials/              # 放 service_account.json (git 忽略)
├── data/                     # state.db + 日志 (git 忽略)
├── scripts/
│   └── com.badminton.agent.plist   # macOS launchd 后台常驻
├── src/
│   ├── __main__.py           # 入口: python -m src [once|loop]
│   ├── config.py             # .env 配置
│   ├── logging_setup.py      # [HH:MM:SS] 日志
│   ├── a1.py                 # 列号<->列字母
│   ├── models.py             # Venue / Slot / RegistrationResult
│   ├── parser.py             # 行->Venue, 日期/时间解析
│   ├── sheets_client.py      # Google Sheets API 封装(含退避重试)
│   ├── state.py              # SQLite 持久化
│   ├── dedupe.py             # 同时间段去重
│   ├── registrar.py          # 并发安全报名核心
│   ├── notifier.py           # 邮件
│   └── agent.py              # 主循环编排
└── tests/
    ├── conftest.py           # FakeSheetsClient(LWW 内存表) + 夹具
    ├── test_parser.py
    ├── test_dedupe.py
    └── test_registrar.py     # 含 8 线程并发抢位测试
```

---

## 八、安装

```bash
cd badminton-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 配置 Google Sheets 服务账号（一次性）

1. 打开 [Google Cloud Console](https://console.cloud.google.com/) → 新建项目；
2. **APIs & Services → 启用 “Google Sheets API”**；
3. **Credentials → Create credentials → Service account** → 建好后进入该服务账号
   → **Keys → Add key → JSON**，下载得到一个 `xxx.json`；
4. 把它放到 `credentials/service_account.json`；
5. 打开 JSON 里的 `client_email`（形如 `xxx@yyy.iam.gserviceaccount.com`），
   **在报名表里点“共享”，把这个邮箱加为“编辑者”**（这一步最关键，否则无权写）；
6. 复制表格 URL 里的 `SPREADSHEET_ID` 填进 `.env`。

```bash
cp .env.example .env
# 编辑 .env：SPREADSHEET_ID、SHEET_NAME、PLAYER_FIRST_COL/PLAYER_COUNT、邮箱等
```

> **首次务必先 `DRY_RUN=true`**：只读、只打印“将要写入哪一格”，确认列位置和解析都对，再改成 `false`。

---

## 九、运行方法

```bash
# 只扫描一次（调试 / 配合 cron）
./run.sh once
#   等价于  python -m src once

# 长期轮询运行
./run.sh
#   等价于  python -m src loop
```

`.env` 关键项：`POLL_INTERVAL_SECONDS`（建议 15–30s，别太快以免触发 Sheets API 配额）、
`REGISTER_NAMES=alice,bob`、`MAX_RETRIES`。

---

## 十、macOS 长期后台运行（launchd）

`launchd` 比 `nohup` 更稳：开机自启、崩溃自动重启、退出后靠 SQLite 恢复状态。

```bash
# 1. 确认 scripts/com.badminton.agent.plist 里的路径正确(默认已按本项目填好)
# 2. 安装并启动
cp scripts/com.badminton.agent.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.badminton.agent.plist
launchctl start com.badminton.agent

# 查看状态 / 日志
launchctl list | grep badminton
tail -f data/agent.log
tail -f data/launchd.err.log

# 停止 / 卸载
launchctl unload ~/Library/LaunchAgents/com.badminton.agent.plist
```

---

## 十一、测试方案

```bash
pip install pytest
pytest -q          # 17 个用例，含并发
```

覆盖：

| 用例 | 验证点 |
|---|---|
| `test_parser` | `16/8`/`18:30-20:30`/en-dash 时间、跨年日期、`venue_id` 构造、异常行丢弃 |
| `test_dedupe` | 优先“能放下所有人”的场地、行号平手规则、分组 |
| `test_basic_registration` | 空场地所有人都报到 = `complete` |
| `test_only_one_slot_left_prioritises_alice` | 只剩 1 位 → 只报排第一的 alice = `partial` |
| `test_no_slot_left` | 满场不动表格 = `failed`，原内容一字不改 |
| **`test_idempotent`** | 已有 `alice,bob` → 再跑不产生 `alice,bob,alice,bob` |
| **`test_never_overwrites_existing`** | 已有别人名字全部保留，`intent_overwrites == []` |
| **`test_conflict_then_retry_no_overwrite`** | 写前目标格被抢占 → 换位重试，绝不覆盖“抢先者” |
| **`test_concurrent_cooperating_agents`** | 见下 |

---

## 十二、如何模拟“多人同时抢位”并验证不会覆盖别人

`tests/conftest.py` 的 `FakeSheetsClient` 精确复刻 Sheets 的并发语义：

- 每次 `read/batch_get/batch_update` **单独一次调用是原子的**，但**多次调用之间可被别的线程插入**；
- 写入是 **LWW（最后写入者获胜）**；
- 可注入 `write_latency` 放大盲区窗口，逼出真实竞态；
- 记录 `intent_overwrites`：任何一次“写到当时非空且非本次值”的格子都会被登记。

**`test_concurrent_cooperating_agents`**：起 8 个线程，各自抢一个不同名字写进同一场地行，
带 10ms 写延迟制造激烈竞争。断言：

- 8 个名字**最终全部在表内**；
- **无重复、无永久丢失**（即使发生瞬时覆盖，被覆盖方靠“写后回读”发现自己不见了 → 换新空位重试自愈）；
- 结论：只要各方都遵循“读-校验-写-再校验”，就能达到最终一致。

**单机手动演练真实表**：

```bash
# 终端 A、B 同时对同一张真实测试表跑(先复制一张废表，别在正式群表上做)
DRY_RUN=false REGISTER_NAMES=alice ./run.sh once   # A
DRY_RUN=false REGISTER_NAMES=bob   ./run.sh once   # B
# 结束后检查该场地行：两个名字都在、无重复、没有覆盖既有人名
```

> 面对**不重试的真人**，我们能保证“绝不主动写非空格”，并把盲区窗口压到最小；
> 但 LWW 的固有盲区无法用 Sheets API 彻底消除——这一点在本文件顶部已如实说明。

---

## 十三、异常处理与安全边界

**异常**（均不破坏原表内容）：网络断开 / 表暂时不可访问 / 凭证过期 / API 失败 →
`sheets_client` 指数退避重试；单周期异常被 `agent.run_forever` 捕获，仅本周期跳过、下周期继续；
写后校验失败 → 换位重试；场地报名中被删/突然满位 → 记 `failed` 并（首次）通知；邮件失败只记日志。

**安全边界**——程序**只会**：① 读表；② 向确认为空的位置写入 `REGISTER_NAMES` 中的名字；③ 发通知邮件。
**绝不**：改/删他人姓名、改场地时间或名称、动任何非报名区域、覆盖任何非空单元格。
服务账号仅被授予这一张表的编辑权限，权限面最小。
