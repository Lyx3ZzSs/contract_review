# 审查结果复刻校准 v2 · 2026-11-12

本次验收替代上一版只用不同文案、不同状态比对的视觉结论。

## 依据与画面

- Source visual truth: `/Users/liyuanxin/.codex/generated_images/01a1bfc4-badb-7e43-87d2-fa370cd99d44/exec-fe9a884a-2793-4d76-af41-90e3482ef14e.png`
- 校准页：`/tests/visual/review-panel.html`，仅测试目录；复用生产的 Heading/Footer/Notice/ReviewResultsList/ReviewFindingCard 和样式，不复制一份界面实现。
- Source dimensions: 1024×1536，按 2x 图归一为 512×768。
- Calibration viewport / screenshot: 512×768 CSS px / 512×768 px。
- 首轮同图对照：`../design-references/results-fidelity-v2/03-comparison.png`。
- 最终同图对照：`../design-references/results-fidelity-v2/05-refined-comparison.png`；右侧为浏览器截图 `04-calibration-refined.png`。
- 真实业务页：`08-real-desktop-final.jpg`，1630×832 CSS px；按 DOM bounds (1105.125,42,514.875,768) 裁为 `09-real-panel.png`。
- 窄屏：`07-real-mobile.jpg`，390×844。
- State：待处理 9，首项展开、依据关闭、筛选关闭。校准页使用图中同文案；真实页保留后端原始顺序、内容及“复审失败，保留上一轮结果”状态。两种证据明确分开。

## 差异与修复循环

- [P1 已修复] 上版保留双标题导航与额外底部说明。结果页隐藏旧导航/说明，修订与批注迁移到更多菜单，切换后仍可返回审查结果。
- [P2 已修复] 标题偏细、按钮和底栏比例偏小。调整标题字重、意见字号、动作内边距和图标。
- [P2 已修复] 第一轮同文案比较：卡片 y≈171、高≈319，收起行高≈96，第四项无法完整显示。按实际 DOM 测量与源图对齐：最终卡片 y=163.48、高=309.80；后续行 y=485.28/563.08/640.88，高均为77.80。完整第四项与固定底栏可见。
- [P2 已修复] 多条失败/历史提示挤占结果空间。失败状态常驻紧凑提示，展开仍显示完整错误原因与阶段；进行中仍展示进度。

## 五项视觉检查

- Fonts：PingFang SC / Microsoft YaHei，标题22px/700，意见17px/700，正文14px、修改方向13.5px；三级层级与源图一致。生成图的字形栅格差异保留为 P3。
- Spacing：编号、选中卡片、分隔线、摘要、操作行与固定底栏同尺寸测量；主要纵向边界误差约1px。
- Colors：蓝色强调、浅蓝选中态、灰蓝建议区、浅琥珀提示和弱边框；按钮禁用色只由真实状态决定。
- Assets：沿用 Lucide 图标；历史入口改成 FileText，与图中纸张图标对应。无截图贴图或新装饰资产。
- Copy：校准文案仅存在 tests/visual；业务页原有审查意见、身份、计数和锁定逻辑保留。校准页阻断 /api 请求，生产单入口构建不包含测试页。
- 同图可清楚阅读文本与间距，另有真实页与窄屏截图，因此无需额外放大区域。

## 验证结果及边界

- npm test: 61 passed, 0 failed。
- npm run build: passed；原有 >500KB bundle 提示仍存在。
- 实际浏览器：更多菜单 → 修订与批注 → 返回审查结果通过；失败提示展开后仍可见“审查口径版本校验失败，未执行”；仅一个可见结果标题。
- 390px：clientWidth=scrollWidth=390，底栏 bottom=816，小于viewport 844；无横向溢出。
- 浏览器 error/warn 为空。临时校准标签页已关闭，默认视口已恢复，真实结果页保留。
- 未发起新审查或保存法务结论；后端复审失败不是本次 UI 修复范围，也未被隐藏或宣称修复。

## 完成清单

- [x] 同文案、同尺寸对照并修正。
- [x] 真实业务页面复核。
- [x] 窄屏与导航验证。
- [x] 运行测试、生产构建，明确测试页隔离。

final result: passed
