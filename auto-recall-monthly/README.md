
# Auto Recall Monthly (SAMR)

一个**一键自动化**的“汽车召回月度数据”抓取与可视化仓库：
- 每月自动从**国家市场监督管理总局召回专栏**抓取“×年×月汽车召回月度汇总”；如失败，自动从**中国汽车质量网**备份抓取；
- 将结构化数据（CSV/JSON）写入 `docs/data/`；
- GitHub Actions 按计划任务运行，自动更新 GitHub Pages 静态看板（ECharts）。

> 数据源：
> - SAMR 召回专栏目录（含“2026年1月汽车召回月度汇总”等）：https://www.samr.gov.cn/zlfzj/qxcpzh/index.html  citeturn1search3
> - SAMR 召回历史分页（用于校验）：https://qxzh.samr.gov.cn/qxzh/qxxxcx/web.jsp  citeturn1search5
> - 备份源：中国汽车质量网“召回信息/×月召回汇总”：https://www.aqsiqauto.com/recall/index/13.html  citeturn1search4

## 一键使用（推荐）

1. **创建仓库**：把本项目上传到你的 GitHub（建议仓库名：`auto-recall-monthly`）。
2. **启用 GitHub Pages**：Repository → Settings → Pages → Build and deployment → Source 选择 `Deploy from a branch`，Branch 选择 `main`，`/docs` 文件夹。
3. **等待首次工作流运行**：首次运行可能在每月计划前不会自动触发，你可以在 `Actions` 页面手动 `Run workflow`。
4. **访问看板链接**：`https://<你的GitHub用户名>.github.io/auto-recall-monthly`。

> 如需更改仓库名/用户名，页面链接相应变化。

## 本地开发
```bash
pip install -r crawler/requirements.txt
python crawler/monthly_crawler.py  # 生成 docs/data/latest.json & 当月CSV
# 用浏览器打开 docs/index.html 查看
```

## 声明
- 本项目仅做信息聚合与可视化，**以官方发布为准**。请遵守目标站点使用条款与 robots.txt。
- 若 DOM 结构变更导致解析失败，需要适配更新。

