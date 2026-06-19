import { test, expect } from '@playwright/test';
import { stockPoolMock, gateMock, reportMock } from './mocks';

/**
 * P0 冒烟测试：选股 → Gate 展示 → 报告渲染 → 切换股票 → 崩溃检测
 */

test.describe('P0 — 冒烟测试', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/stocks/pool/**', (route) =>
      route.fulfill({ status: 200, json: stockPoolMock })
    );
  });

  test('初始加载：股池渲染 + 空状态提示', async ({ page }) => {
    await page.goto('http://localhost:5173');

    // 股池加载完成
    await expect(page.getByText('贵州茅台')).toBeVisible();
    await expect(page.getByText('海康威视')).toBeVisible();

    // 股票数量 meta — 用 className 定位 (4 只标的在 span.meta 里)
    await expect(page.locator('[class*="meta"]').filter({ hasText: '只标的' })).toBeVisible();

    // 空状态提示
    await expect(page.getByText('请从股池选择一只股票')).toBeVisible();
  });

  test('选股 → Gate 门控标签显示', async ({ page }) => {
    await page.route('**/api/stocks/600519.SH/gates', (route) =>
      route.fulfill({ status: 200, json: gateMock(true) })
    );
    await page.route('**/api/stocks/600519.SH/analysis', (route) =>
      route.fulfill({ status: 200, json: reportMock })
    );

    await page.goto('http://localhost:5173');
    await page.getByText('贵州茅台').click();

    // ScoreCard 展开
    await expect(page.getByText('Q1 生意本质')).toBeVisible({ timeout: 5000 });
  });

  test('选股 → 报告完整渲染，无崩溃', async ({ page }) => {
    await page.route('**/api/stocks/600519.SH/gates', (route) =>
      route.fulfill({ status: 200, json: gateMock(true) })
    );
    await page.route('**/api/stocks/600519.SH/analysis', (route) =>
      route.fulfill({ status: 200, json: reportMock })
    );

    await page.goto('http://localhost:5173');
    await page.getByText('贵州茅台').click();

    // 报告标题 (h1 包含 "贵州茅台 600519.SH")
    await expect(
      page.locator('[class*="reportH1"]').filter({ hasText: '贵州茅台' })
    ).toBeVisible({ timeout: 5000 });

    // TOC 面板
    await expect(page.getByText('报告目录')).toBeVisible();

    // Section 标题可见
    await expect(
      page.locator('[class*="sectionH2"]').first()
    ).toBeVisible();

    // 核心：不能触发 ErrorBoundary
    await expect(page.getByText('页面发生错误')).toHaveCount(0);
  });

  test('切换股票 → 不闪白（placeholderData 生效）', async ({ page }) => {
    await page.route('**/api/stocks/600519.SH/gates', (route) =>
      route.fulfill({ status: 200, json: gateMock(true) })
    );
    await page.route('**/api/stocks/600519.SH/analysis', (route) =>
      route.fulfill({ status: 200, json: reportMock })
    );
    await page.route('**/api/stocks/000651.SZ/gates', (route) =>
      route.fulfill({ status: 200, json: gateMock(true) })
    );
    const greeReport = { ...reportMock, ts_code: '000651.SZ', name: '格力电器' };
    await page.route('**/api/stocks/000651.SZ/analysis', async (route) => {
      await new Promise((r) => setTimeout(r, 3000));
      await route.fulfill({ status: 200, json: greeReport });
    });

    await page.goto('http://localhost:5173');

    // 选茅台
    await page.getByText('贵州茅台').click();
    await expect(
      page.locator('[class*="reportH1"]').filter({ hasText: '贵州茅台' })
    ).toBeVisible({ timeout: 5000 });

    // 切格力（报告还没返回）
    await page.getByText('格力电器').click();

    // 旧报告保留
    await expect(page.getByText('请从股池选择一只股票')).toHaveCount(0);

    // 等格力报告返回
    await expect(
      page.locator('[class*="reportH1"]').filter({ hasText: '格力电器' })
    ).toBeVisible({ timeout: 10000 });

    // 无崩溃
    await expect(page.getByText('页面发生错误')).toHaveCount(0);
  });

  test('TOC 展开/折叠按钮', async ({ page }) => {
    await page.route('**/api/stocks/600519.SH/gates', (route) =>
      route.fulfill({ status: 200, json: gateMock(true) })
    );
    await page.route('**/api/stocks/600519.SH/analysis', (route) =>
      route.fulfill({ status: 200, json: reportMock })
    );

    await page.goto('http://localhost:5173');
    await page.getByText('贵州茅台').click();

    // 默认展开的 section（打分卡 相关的 h2 标题）
    await expect(
      page.locator('[class*="sectionH2"]').first()
    ).toBeVisible({ timeout: 5000 });

    // 找 TOC 面板里的"展开"按钮
    await expect(page.getByRole('button', { name: '展开' })).toBeVisible();

    // 检查 TOC 在
    await expect(page.getByText('报告目录')).toBeVisible();
  });
});
