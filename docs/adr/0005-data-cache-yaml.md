# ADR-0005: 数据缓存层使用 YAML

- **日期**: 2026-06-15
- **状态**: 已接受

## 上下文

个股数据需要从 Tushare 拉取后缓存到本地，后续计算只读缓存。需要选择缓存格式。

## 决策

使用 YAML 文件存储个股缓存数据：
```
stock_cache/{ts_code}/
├── raw_data.yaml        # Tushare原始数据
├── computed.yaml        # 确定性计算结果
├── websearch.yaml       # WebSearch结果
└── analysis_report.md   # 分析报告
```

选择 YAML 的原因：
1. 人类可读，便于调试
2. LLM Agent 可直接读取（不需要 JSON 解析）
3. Python 原生支持良好
4. 版本管理友好（diff 清晰）

## 替代方案

- **SQLite**: 需要额外 ORM 映射，LLM 不可直接读取
- **JSON**: 可读性不如 YAML，不支持注释
- **Pickle**: 不可读，不安全

## 后果

- 全量数据时磁盘占用较大（YAML 比二进制大）
- 不需要数据库即可运行计算
- 缓存文件可被 LLM Agent 直接消费
