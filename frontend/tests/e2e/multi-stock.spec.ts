import { test, expect } from '@playwright/test';
import { stockPoolMock, gateMock, reportMock } from './mocks';

/**
 * P0 多股并行分析模拟全流程
 */

const stageConfig = [
  { status: 'fetching', progress: 10, message: '正在拉取财务数据...', delay: 200 },
  { status: 'computing', progress: 30, message: '正在计算门控指标...', delay: 300 },
  { status: 'websearch', progress: 56, message: '正在网络搜索...', delay: 400 },
  { status: 'analyzing', progress: 85, message: 'AI 正在深度分析...', delay: 500 },
  { status: 'done', progress: 100, message: '分析完成', delay: 100 },
];

test.describe('P0 — 多股并行分析模拟全流程', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/stocks/pool/**', (route) =>
      route.fulfill({ status: 200, json: stockPoolMock })
    );
  });

  test('单股完整分析流程：POST→轮询→done→报告渲染', async ({ page }) => {
    // Mock POST /analyze
    await page.route('**/api/stocks/002555.SZ/analyze', (route) =>
      route.fulfill({ status: 200, body: '{}' })
    );

    // Mock /analyze/status — 分段返回
    const statusCounts: Record<string, number> = {};
    await page.route('**/api/stocks/*/analyze/status', async (route) => {
      const url = route.request().url();
      const code = url.match(/stocks\/([^/]+)\/analyze/)?.[1] ?? 'unknown';
      statusCounts[code] = (statusCounts[code] || 0);
      const stage = stageConfig[Math.min(statusCounts[code], stageConfig.length - 1)];
      statusCounts[code]++;
      await new Promise((r) => setTimeout(r, stage.delay));
      await route.fulfill({ status: 200, json: stage });
    });

    // Mock Gate
    await page.route('**/api/stocks/002555.SZ/gates', (route) =>
      route.fulfill({ status: 200, json: gateMock(true) })
    );

    // Mock Analysis — 条件：分析触发后才返回报告，否则 404
    await page.route('**/api/stocks/002555.SZ/analysis', async (route) => {
      if ((statusCounts['002555.SZ'] || 0) >= 5) {
        await route.fulfill({
          status: 200,
          json: { ...reportMock, ts_code: '002555.SZ', name: '三七互娱' },
        });
      } else {
        await route.fulfill({ status: 404, body: 'Not Found' });
      }
    });

    await page.goto('http://localhost:5173');

    // 选三七互娱（has_report: false, analysis mock 返回 404）
    await page.getByText('三七互娱').click();

    // 应显示 "暂无分析报告"
    await expect(page.getByText('暂无分析报告')).toBeVisible({ timeout: 5000 });

    // 点击分析按钮
    await page.getByRole('button', { name: /分析个股/ }).click();

    // 进度文本出现 (使用 .first() 避免 strict mode)
    await expect(page.getByText(/正在/).first()).toBeVisible({ timeout: 5000 });

    // 等待完成
    await expect(
      page.locator('[class*="reportH1"]').filter({ hasText: '三七互娱' })
    ).toBeVisible({ timeout: 30000 });

    // 无崩溃
    await expect(page.getByText('页面发生错误')).toHaveCount(0);
  });

  test('三股并行分析不崩溃', async ({ page }) => {
    const analysisCodes = ['600519.SH', '000651.SZ', '002555.SZ'];

    // Mock POST /analyze for all
    await page.route('**/api/stocks/*/analyze', (route) =>
      route.fulfill({ status: 200, body: '{}' })
    );

    // Shared status counter
    const statusCounts: Record<string, number> = {};
    await page.route('**/api/stocks/*/analyze/status', async (route) => {
      const url = route.request().url();
      const code = url.match(/stocks\/([^/]+)\/analyze/)?.[1] ?? 'unknown';
      statusCounts[code] = (statusCounts[code] || 0);
      const stage = stageConfig[Math.min(statusCounts[code], stageConfig.length - 1)];
      statusCounts[code]++;
      await new Promise((r) => setTimeout(r, stage.delay));
      await route.fulfill({ status: 200, json: stage });
    });

    // Mock Gate + Analysis for each stock
    for (const code of analysisCodes) {
      const name = stockPoolMock.find((s) => s.ts_code === code)?.name ?? code;
      await page.route(`**/api/stocks/${code}/gates`, (route) =>
        route.fulfill({ status: 200, json: gateMock(true) })
      );
      await page.route(`**/api/stocks/${code}/analysis`, (route) =>
        route.fulfill({ status: 200, json: { ...reportMock, ts_code: code, name } })
      );
    }

    await page.goto('http://localhost:5173');

    // 触发 3 只股票并行分析
    for (const code of analysisCodes) {
      const name = stockPoolMock.find((s) => s.ts_code === code)!.name;
      // 在股池中点击股票名（使用 first() 避免 strict mode 冲突）
      await page.getByText(name).first().click();
      const analyzeBtn = page.getByRole('button', { name: /分析个股/ });
      if (await analyzeBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await analyzeBtn.click();
      }
    }

    // 等全部完成
    await page.waitForTimeout(20000);

    // 不崩
    await expect(page.getByText('页面发生错误')).toHaveCount(0);

    // 最终选中的股票应该有报告
    const lastStock = analysisCodes[analysisCodes.length - 1];
    const lastName = stockPoolMock.find((s) => s.ts_code === lastStock)!.name;
    await page.getByText(lastName).first().click();
    await expect(
      page.locator('[class*="reportH1"]').filter({ hasText: lastName })
    ).toBeVisible({ timeout: 5000 });
  });
});
