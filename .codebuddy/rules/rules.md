---
enabled: true
alwaysApply: true
---

# AI Agent 强制规则

> 每次会话自动注入。违反任一条 = 不合格。

---

## 1. 工作流：先文档，后代码，闭环管理

**必须按顺序**：

```
1. 理解 → 判断策略归属 → 加载对应 SPEC 文档（见 §2）
2. 计划 → 列出改动范围（哪些文件）→ 向用户确认
3. 文档 → 先更新 SPEC 文档 / CONTEXT.md
4. 代码 → 再改代码
5. 测试 → pytest 全部通过
6. 闭环 → 更新项目文档：
   - .codebuddy/memory/YYYY-MM-DD.md（每日日志）
   - CHANGELOG.md（版本变更记录）
   - 版本号（pyproject.toml / 项目文件）
7. 有 Issue → 先写 Issue 再写代码，修复后关 Issue
```

**禁止**：
- ❌ 跳过确认直接改代码
- ❌ 先改代码后补文档（先污染后治理）
- ❌ 测试没跑完说"完成"
- ❌ 破坏性改动不记录 memory / 不更新版本号

---

## 2. 策略上下文自动加载

> 根据用户请求中涉及的策略关键词，必须加载对应的 SPEC 文档。各策略 SPEC 文档内含该策略专属的开发约束（如公式同步规则、硬门边界等），**必须一并遵守**。

### 匹配规则

| 策略 | 触发关键词 | 加载文档 |
|------|-----------|---------|
| **龟龟策略** | 龟龟、turtle、CQ、PR、QRV、穿透回报率、现金质量、选股器、screener、coordinator、qrv_agent、cash_quality、penetration_return | `backend/app/strategies/turtle/turtle-coordinator.md` |

### 执行逻辑

```
用户请求
  │
  ├─ 命中「龟龟策略」关键词 → 加载 turtle-coordinator.md
  │     └─ 遵循其中的「维护规则」章节（公式四件套/硬门确定性/测试铁律）
  │
  └─ 均未命中 → 通用开发任务，无需加载策略 SPEC
```

---

## 3. 配置：`.env` 是最高权威

| | `.env` | `config.py` |
|---|--------|-------------|
| 优先级 | **最高**，覆盖默认值 | 第二，被 `.env` 覆盖 |
| 存什么 | 密钥 + 常调参数（URL/KEY/THRESHOLD） | 一切参数 + 默认值 |
| 安全 | 不入版本控制 | 入版本控制 |

**规则**：
1. 改任何阈值/参数前 → **第一步：读 `.env`**
2. `.env` 有 → 改 `.env`
3. `.env` 无 → 改 `config.py` 默认值 + 同步加到 `.env`
4. 新增可调参数 → `config.py` 默认值 + `.env` 当前值，两处同步

---

## 4. 数据：外部 API 字段名一字不改，输出用中文

### 代码层
- `data_fetcher.py` 中 `row.get()` 的 key → 必须和外部 API 文档**一字不差**
- `raw_data.yaml` 中 → 保留 API 原始字段名
- Python 变量可简化为英文含义名，但**必须注释标注 API 原始字段名**

**反例**：
- ❌ `row.get("c_pay_for_tan_il")` — 此字段不存在，正确是 `c_pay_acq_const_fiolta`
- ❌ `raw_data["interest_expense"]` — 原名是 `finan_exp`（财务费用，范围更广）

### 输出层
- 向用户展示数据时：**中文名 + 代码**，如「海澜之家 600398.SH」
- 字段名 → 中文含义的对照表存于 `docs/TUSHARE_FIELDS.md`

---

## 5. 缓存：新字段 = 全量重拉

`data_fetcher.py` 新增/修改外部字段 → 所有 `raw_data.yaml` 缺少该字段 → **必须 `--full` 全量重拉**，不得用 `--compute-only` 在旧缓存上跑。

```
正确顺序：
1. 改 data_fetcher.py（加字段）
2. 跑 --full（全量重拉）
3. 跑 --compute-only（用新数据算）
```

---

## 6. 测试：不过不叫完成

- 改完代码必须 `pytest tests/` 全部通过
- 阈值变更 → 同步更新测试边界值

---

## 7. 环境：PowerShell 输出不重定向

Windows PowerShell 下 stdout 重定向会产生 CLIXML 乱码。

```
❌ python script.py > output.txt 2>&1
❌ python script.py | Out-File output.txt

✅ python script.py 2>&1 | Out-File -FilePath output.txt -Encoding utf8
✅ cmd /c "python script.py > output.txt 2>&1"
✅ 直接用 write_to_file 写脚本 → execute_command 看 stdout
```
