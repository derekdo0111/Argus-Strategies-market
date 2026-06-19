import { test, expect } from '@playwright/test';
import { stockPoolMock, gateMock, reportMock } from './mocks';

/**
 * P1 交互测试：Gate 门控展示、引用跳转、API 故障、汉堡菜单
 */

test.describe('P1 — Gate 门控展示', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/stocks/pool/**', (route) =>
      route.fulfill({ status: 200, json: stockPoolMock })
    );
  });

  test('CQ PASS + PR PASS → 报告区标签', async ({ page }) => {
    await page.route('**/api/stocks/600519.SH/gates', (route) =>
      route.fulfill({ status: 200, json: gateMock(true) })
    );
    await page.route('**/api/stocks/600519.SH/analysis', (route) =>
      route.fulfill({ status: 200, json: reportMock })
    );

    await page.goto('http://localhost:5173');

    // 股池表中茅台行有 PASS badge
    await expect(
      page.locator('table [class*="gatePass"]').first()
    ).toBeVisible({ timeout: 5000 });

    // 点击切换到报告区
    await page.getByText('贵州茅台').click();
    await expect(
      page.locator('[class*="gateBadge"]').filter({ hasText: 'CQ PASS' })
    ).toBeVisible({ timeout: 5000 });
  });

  test('CQ FAIL → 红色标签在股池中', async ({ page }) => {
    await page.goto('http://localhost:5173');

    // 海康在股池中 CQ FAIL — 在表格行内查找
    await expect(
      page.locator('table [class*="gateFail"]').first()
    ).toBeVisible({ timeout: 5000 });
  });
});

test.describe('P1 — 引用跳转 (cite click)', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/stocks/pool/**', (route) =>
      route.fulfill({ status: 200, json: stockPoolMock })
    );
    await page.route('**/api/stocks/600519.SH/gates', (route) =>
      route.fulfill({ status: 200, json: gateMock(true) })
    );
    await page.route('**/api/stocks/600519.SH/analysis', (route) =>
      route.fulfill({ status: 200, json: reportMock })
    );
  });

  test('点击 cite → 参考来源 section 展开 → 定位到 ref-row', async ({ page }) => {
    await page.goto('http://localhost:5173');
    await page.getByText('贵州茅台').click();
    await page.waitForTimeout(2000);

    // "参考来源" 默认折叠 — 需要先展开（点击 section h2）
    const refHeading = page.locator('[class*="sectionH2"]').filter({ hasText: '参考来源' });
    await refHeading.click();
    await page.waitForTimeout(500);

    // 展开后 cite 元素应可见
    const firstCite = page.locator('cite').first();
    await expect(firstCite).toBeVisible({ timeout: 5000 });

    // 点击 cite
    await firstCite.click();
    await page.waitForTimeout(1500);

    // 应该能看到 ref-row 高亮
    const refRow = page.locator('[id^="ref-row-"]');
    await expect(refRow.first()).toBeVisible({ timeout: 3000 });
  });
});

test.describe('P1 — API 故障处理', () => {
  test('API 500 → 显示错误 + 重试按钮', async ({ page }) => {
    // 阻止 JSON 预加载注入缓存（main.tsx init() 会 fetch /data/turtle_pool.json）
    await page.route('**/data/turtle_pool.json', (route) =>
      route.fulfill({ status: 404 })
    );

    // 股池 API 返回 500
    await page.route('**/api/stocks/pool/turtle**', (route) =>
      route.fulfill({ status: 500, body: JSON.stringify({ detail: 'Server Error' }) })
    );

    await page.goto('http://localhost:5173');

    // React Query retry=1，约 2s 后进入 error 状态
    await expect(page.getByText(/加载失败/)).toBeVisible({ timeout: 15000 });

    // 重试按钮
    const retryBtn = page.getByRole('button', { name: '重试' });
    await expect(retryBtn).toBeVisible();

    // 清除旧路由，改为正常 mock
    await page.unroute('**/api/stocks/pool/turtle**');
    await page.route('**/api/stocks/pool/turtle**', (route) =>
      route.fulfill({ status: 200, json: stockPoolMock })
    );
    await retryBtn.click();

    // 加载成功
    await expect(page.getByText('贵州茅台')).toBeVisible({ timeout: 5000 });
  });
});

test.describe('P1 — 汉堡菜单', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/stocks/pool/**', (route) =>
      route.fulfill({ status: 200, json: stockPoolMock })
    );
  });

  test('汉堡菜单 → 点击展开 Sidebar → 再点折叠', async ({ page }) => {
    await page.goto('http://localhost:5173');

    // 点击汉堡
    const hamburger = page.locator('[class*="hamburger"]');
    await expect(hamburger).toBeVisible();
    await hamburger.click();

    // Sidebar 展开
    await expect(page.getByText('龟龟策略')).toBeVisible({ timeout: 2000 });

    // 再点折叠
    await hamburger.click();
    await page.waitForTimeout(500);
  });
});
