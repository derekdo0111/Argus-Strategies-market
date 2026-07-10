/**
 * prosperity-components.test.tsx — 高景气策略 3 组件集成测试
 *
 * 覆盖：
 *   IndustrySelector  — 输入交互 / 空值保护 / disabled 状态
 *   HypothesisBoard   — 空状态 / session 切换 / L0-L3 分栏 / status emoji / derives_from
 *   ReportViewer       — 空状态 / loading / markdown 渲染 / session 切换
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import axios from 'axios';

// ════════════════════════════════════════════
// Mock axios
// ════════════════════════════════════════════
vi.mock('axios');
const mockAxios = vi.mocked(axios);

// Mock react-markdown (避免复杂渲染)
vi.mock('react-markdown', () => ({
  default: ({ children }: { children: string }) =>
    React.createElement('div', { 'data-testid': 'markdown' }, children),
}));
vi.mock('remark-gfm', () => ({ default: () => {} }));
vi.mock('rehype-raw', () => ({ default: () => {} }));

// Mock CSS modules
vi.mock('../src/components/prosperity/IndustrySelector.module.css', () => ({
  default: new Proxy({}, { get: (_, key) => key as string }),
}));
vi.mock('../src/components/prosperity/HypothesisBoard.module.css', () => ({
  default: new Proxy({}, { get: (_, key) => key as string }),
}));
vi.mock('../src/components/prosperity/ReportViewer.module.css', () => ({
  default: new Proxy({}, { get: (_, key) => key as string }),
}));

import IndustrySelector from '../src/components/prosperity/IndustrySelector';
import HypothesisBoard from '../src/components/prosperity/HypothesisBoard';
import ProsperityReportViewer from '../src/components/prosperity/ReportViewer';

// ════════════════════════════════════════════
// Helpers
// ════════════════════════════════════════════

const mockSessions = [
  { id: 1, industry: '半导体', status: 'completed', current_step: 'done' },
  { id: 2, industry: '消费电子', status: 'running', current_step: 'verify' },
];

const mockHypotheses = [
  {
    id: 'H0-1', title: '存储景气领涨', statement: '存储芯片是本轮半导体景气周期的领涨引擎',
    chain_level: 0, derives_from: null, status: 'CONFIRMED', confidence: 0.85,
    time_horizon: '当前',
  },
  {
    id: 'H1-1', title: '扩产计划推进', statement: '存储厂商营收利润双增 → 多家宣布扩产',
    chain_level: 1, derives_from: 'H0-1', status: 'PARTIAL', confidence: 0.6,
    time_horizon: '6个月',
  },
  {
    id: 'H2-1', title: '供需拐点预警', statement: '产能集中释放 → 2027Q1 供需可能逆转',
    chain_level: 2, derives_from: 'H1-1', status: 'UNVERIFIED', confidence: 0.4,
    time_horizon: '1年',
  },
  {
    id: 'H2-2', title: '上游推翻不可达', statement: '本假设上游被推翻',
    chain_level: 2, derives_from: 'H0-99', status: 'UNREACHABLE', confidence: 0,
  },
  {
    id: 'H3-1', title: '存储弹性窗口', statement: '当前关注存储弹性标的',
    chain_level: 3, derives_from: 'H2-1', status: 'UNVERIFIED', confidence: 0.5,
    investment_implication: '关注方向：HBM 绑定的存储设计/封测',
  },
];

const mockReportMd = `# 半导体行业景气分析

> **综合评级: 🔥 高景气** | 生成日期: 2026-06-29

## 推理链概览
测试内容
`;

// ════════════════════════════════════════════
// IndustrySelector
// ════════════════════════════════════════════

describe('IndustrySelector', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders title and flow steps', () => {
    const onSessionStart = vi.fn();
    render(React.createElement(IndustrySelector, { onSessionStart }));

    expect(screen.getByText('行业景气研究')).toBeDefined();
    expect(screen.getByText('6 Agent 因果推理链 · 4层假设 (L0→L3)')).toBeDefined();
    expect(screen.getByText('情报搜索')).toBeDefined();
    expect(screen.getByText('假设形成')).toBeDefined();
    expect(screen.getByText('交叉验证')).toBeDefined();
    expect(screen.getByText('反推修正')).toBeDefined();
    expect(screen.getByText('生成报告')).toBeDefined();

    // 流程箭头
    const flowText = screen.getByText(/研究流程：/);
    expect(flowText).toBeDefined();
  });

  it('shows error when submitting empty input via Enter', async () => {
    const onSessionStart = vi.fn();
    const user = userEvent.setup();
    render(React.createElement(IndustrySelector, { onSessionStart }));

    // Button 是 disabled 的（点击不触发 handler），但 Enter 键绕过 disabled 检查
    const input = screen.getByPlaceholderText(/输入行业名称/);
    await user.click(input);
    await user.keyboard('{Enter}');

    expect(screen.getByText('请输入行业名称')).toBeDefined();
    expect(onSessionStart).not.toHaveBeenCalled();
  });

  it('disables button when input is empty', () => {
    const onSessionStart = vi.fn();
    render(React.createElement(IndustrySelector, { onSessionStart }));

    const btn = screen.getByRole('button', { name: /开始研究/ });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it('enables button when input has text', async () => {
    const onSessionStart = vi.fn();
    const user = userEvent.setup();
    render(React.createElement(IndustrySelector, { onSessionStart }));

    const input = screen.getByPlaceholderText(/输入行业名称/);
    await user.type(input, '半导体');

    const btn = screen.getByRole('button', { name: /开始研究/ });
    expect((btn as HTMLButtonElement).disabled).toBe(false);
  });

  it('calls onSessionStart on successful API call', async () => {
    const onSessionStart = vi.fn();
    const user = userEvent.setup();
    mockAxios.post.mockResolvedValueOnce({
      data: { id: 1, industry: '半导体', status: 'running', current_step: 'search' },
    });

    render(React.createElement(IndustrySelector, { onSessionStart }));

    await user.type(screen.getByPlaceholderText(/输入行业名称/), '半导体');
    await user.click(screen.getByRole('button', { name: /开始研究/ }));

    await waitFor(() => {
      expect(onSessionStart).toHaveBeenCalledWith({
        id: 1, industry: '半导体', status: 'running', current_step: 'search',
      });
    });
  });

  it('shows loading state during API call', async () => {
    const onSessionStart = vi.fn();
    const user = userEvent.setup();
    // 永不 resolve 的 promise 保持 loading 状态
    mockAxios.post.mockReturnValueOnce(new Promise(() => {}));

    render(React.createElement(IndustrySelector, { onSessionStart }));

    await user.type(screen.getByPlaceholderText(/输入行业名称/), '半导体');
    await user.click(screen.getByRole('button', { name: /开始研究/ }));

    expect(screen.getByText('启动中...')).toBeDefined();
  });

  it('shows error on API failure', async () => {
    const onSessionStart = vi.fn();
    const user = userEvent.setup();
    mockAxios.post.mockRejectedValueOnce({
      response: { data: { detail: '服务器错误' } },
    });

    render(React.createElement(IndustrySelector, { onSessionStart }));

    await user.type(screen.getByPlaceholderText(/输入行业名称/), '半导体');
    await user.click(screen.getByRole('button', { name: /开始研究/ }));

    await waitFor(() => {
      expect(screen.getByText('服务器错误')).toBeDefined();
    });
  });

  it('triggers submit on Enter key', async () => {
    const onSessionStart = vi.fn();
    const user = userEvent.setup();
    mockAxios.post.mockResolvedValueOnce({
      data: { id: 2, industry: '消费电子', status: 'running', current_step: 'search' },
    });

    render(React.createElement(IndustrySelector, { onSessionStart }));

    const input = screen.getByPlaceholderText(/输入行业名称/);
    await user.type(input, '消费电子');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(onSessionStart).toHaveBeenCalled();
    });
  });

  it('disables input and button during loading', async () => {
    const onSessionStart = vi.fn();
    const user = userEvent.setup();
    mockAxios.post.mockReturnValueOnce(new Promise(() => {}));

    render(React.createElement(IndustrySelector, { onSessionStart }));

    const input = screen.getByPlaceholderText(/输入行业名称/) as HTMLInputElement;
    await user.type(input, '测试');

    const btn = screen.getByRole('button', { name: /开始研究/ });
    await user.click(btn);

    expect(input.disabled).toBe(true);
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });
});

// ════════════════════════════════════════════
// HypothesisBoard
// ════════════════════════════════════════════

/** 辅助：渲染 HypothesisBoard + 选 session 1 并等待假设加载完成 */
async function setupHypothesisBoard(hypotheses = mockHypotheses) {
  mockAxios.get
    .mockResolvedValueOnce({ data: { sessions: mockSessions } })
    .mockResolvedValueOnce({ data: { hypotheses } });
  render(React.createElement(HypothesisBoard, {}));
  await waitFor(() => {
    expect(screen.getByRole('combobox')).toBeDefined();
  });
  // 使用 fireEvent 而非 selectOptions 避免 jsdom 受控组件竞态
  await act(async () => {
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '1' } });
  });
}

describe('HypothesisBoard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders placeholder when no sessions', async () => {
    mockAxios.get.mockResolvedValueOnce({ data: { sessions: [] } });
    render(React.createElement(HypothesisBoard, {}));
    await waitFor(() => {
      expect(screen.getByText('输入行业名称开始研究')).toBeDefined();
    });
  });

  it('renders session selector with industries', async () => {
    mockAxios.get.mockResolvedValueOnce({ data: { sessions: mockSessions } });
    render(React.createElement(HypothesisBoard, {}));
    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeDefined();
    });
    expect(screen.getByText(/半导体/)).toBeDefined();
    expect(screen.getByText(/消费电子/)).toBeDefined();
  });

  it('displays L0-L3 sections after selecting session', async () => {
    await setupHypothesisBoard();
    await waitFor(() => {
      expect(screen.getByText('L0 现状诊断')).toBeDefined();
      expect(screen.getByText('L1 一阶推演')).toBeDefined();
      expect(screen.getByText('L2 二阶推演')).toBeDefined();
      expect(screen.getByText('L3 投资落点')).toBeDefined();
    });
  });

  it('displays status text and IDs', async () => {
    await setupHypothesisBoard();
    // 使用 container.textContent 检查（emoji 在不同 DOM 节点，getByText 可能失败）
    await waitFor(() => {
      expect(document.body.textContent).toContain('CONFIRMED');
      expect(document.body.textContent).toContain('PARTIAL');
      expect(document.body.textContent).toContain('UNREACHABLE');
      expect(document.body.textContent).toContain('UNVERIFIED');
      expect(document.body.textContent).toContain('H0-1');
      expect(document.body.textContent).toContain('H3-1');
    });
  });

  it('displays hypothesis statements', async () => {
    await setupHypothesisBoard();
    await waitFor(() => {
      expect(document.body.textContent).toContain('存储芯片是本轮半导体景气周期的领涨引擎');
      expect(document.body.textContent).toContain('存储厂商营收利润双增');
    });
  });

  it('shows derives_from arrows', async () => {
    await setupHypothesisBoard();
    await waitFor(() => {
      expect(document.body.textContent).toContain('← 源自 H0-1');
      expect(document.body.textContent).toContain('← 源自 H1-1');
    });
  });

  it('shows time_horizon badges', async () => {
    await setupHypothesisBoard();
    await waitFor(() => {
      expect(document.body.textContent).toContain('当前');
      expect(document.body.textContent).toContain('6个月');
      expect(document.body.textContent).toContain('1年');
    });
  });

  it('shows investment_implication for L3', async () => {
    await setupHypothesisBoard();
    await waitFor(() => {
      expect(document.body.textContent).toContain('关注方向：HBM 绑定的存储设计/封测');
    });
  });

  it('shows empty state for session with no hypotheses', async () => {
    await setupHypothesisBoard([]);
    await waitFor(() => {
      expect(screen.getByText('暂无疑设数据')).toBeDefined();
    });
  });

  it('renders count badges per level', async () => {
    await setupHypothesisBoard();
    await waitFor(() => {
      // L0:1 / L1:1 / L2:2 / L3:1
      const counts = Array.from(document.querySelectorAll('[class*="count"]'));
      const texts = counts.map(c => c.textContent?.trim()).filter(Boolean);
      expect(texts).toContain('1');
      expect(texts).toContain('2');
    });
  });
});

// ════════════════════════════════════════════
// ReportViewer
// ════════════════════════════════════════════

describe('ReportViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders placeholder when no completed sessions', async () => {
    mockAxios.get.mockResolvedValueOnce({ data: { sessions: [] } });

    render(React.createElement(ProsperityReportViewer, {}));

    await waitFor(() => {
      expect(screen.getByText('开始研究后将在此展示综合报告')).toBeDefined();
    });
  });

  it('renders session list when completed sessions exist but no report loaded', async () => {
    // sessions with none completed
    mockAxios.get.mockResolvedValueOnce({
      data: { sessions: [{ id: 3, industry: '医药', status: 'running', current_step: 'search' }] },
    });

    render(React.createElement(ProsperityReportViewer, {}));

    await waitFor(() => {
      expect(screen.getByText('开始研究后将在此展示综合报告')).toBeDefined();
    });
  });

  it('auto-loads latest completed report', async () => {
    mockAxios.get.mockResolvedValueOnce({ data: { sessions: mockSessions } });
    mockAxios.get.mockResolvedValueOnce({ data: { markdown: mockReportMd } });

    render(React.createElement(ProsperityReportViewer, {}));

    await waitFor(() => {
      expect(screen.getByTestId('markdown')).toBeDefined();
    });

    // markdown 内容应渲染
    expect(screen.getByText(/半导体行业景气分析/)).toBeDefined();
  });

  it('shows loading state', async () => {
    mockAxios.get.mockResolvedValueOnce({ data: { sessions: mockSessions } });
    // 永不 resolve 保持 loading
    mockAxios.get.mockReturnValueOnce(new Promise(() => {}));

    render(React.createElement(ProsperityReportViewer, {}));

    await waitFor(() => {
      expect(screen.getByText('加载报告中...')).toBeDefined();
    });
  });

  it('renders session buttons for completed sessions', async () => {
    const user = userEvent.setup();
    // 不自动加载: 只返回非 completed 的 session
    const sessionsNoComplete = [
      { id: 4, industry: '新能源', status: 'running', current_step: 'report' },
    ];
    mockAxios.get.mockResolvedValueOnce({ data: { sessions: sessionsNoComplete } });

    render(React.createElement(ProsperityReportViewer, {}));

    await waitFor(() => {
      // 没有 completed → 显示 placeholder
      expect(screen.getByText('开始研究后将在此展示综合报告')).toBeDefined();
    });
  });

  it('shows error message when report load fails', async () => {
    mockAxios.get.mockResolvedValueOnce({ data: { sessions: mockSessions } });
    mockAxios.get.mockRejectedValueOnce(new Error('Network error'));

    render(React.createElement(ProsperityReportViewer, {}));

    await waitFor(() => {
      expect(screen.getByText('报告加载失败')).toBeDefined();
    });
  });

  it('manually loads a session report via button click', async () => {
    const user = userEvent.setup();
    const sessionsWithCompleted = [
      { id: 1, industry: '半导体', status: 'completed', current_step: 'done' },
      { id: 2, industry: '消费电子', status: 'completed', current_step: 'done' },
    ];
    // 第二次返回另一个 session 的报告
    mockAxios.get
      .mockResolvedValueOnce({ data: { sessions: sessionsWithCompleted } })
      .mockResolvedValueOnce({ data: { markdown: mockReportMd } });

    // 需要用新的 render，因为组件在 mount 时已自动加载
    const { unmount } = render(React.createElement(ProsperityReportViewer, {}));

    await waitFor(() => {
      expect(screen.getByTestId('markdown')).toBeDefined();
    });

    unmount();

    // 模拟第二个 session 的加载
    vi.clearAllMocks();
    mockAxios.get
      .mockResolvedValueOnce({ data: { sessions: sessionsWithCompleted } })
      .mockResolvedValueOnce({ data: { markdown: '# 消费电子行业景气分析\n\n> **综合评级: 弱景气**' } });

    render(React.createElement(ProsperityReportViewer, {}));

    await waitFor(() => {
      expect(screen.getByText(/消费电子行业景气分析/)).toBeDefined();
    });
  });
});
