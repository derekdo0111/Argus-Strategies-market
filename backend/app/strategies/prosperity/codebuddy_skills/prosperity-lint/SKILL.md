# Prosperity Lint

知识库巡检工具。

## 职责
1. 扫描 wiki/ 目录所有页面
2. 更新 index.md 索引
3. 查找孤页（未被引用的页面）
4. 巡检跟踪项（check_watchlist）
5. 向用户报告巡检结果

## 使用
调用 POST /api/prosperity/lint 获取巡检报告。
