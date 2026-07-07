<p align="center">
  <img src="frontend/public/logo.png" width="96" alt="Alpha Mind logo"/>
</p>

<h1 align="center">Alpha Mind · 量化之心</h1>

<p align="center">AI 驱动的个人量化研究与交易助手 — 自然语言回测、多市场行情、机会扫描与走势预测。</p>

---

## 项目结构

```
agent/        Python 后端
  api_server.py   FastAPI 服务(REST API,端口 8899)
  mcp_server.py   MCP 服务
  cli/            命令行入口(vibe-trading serve / run ...)
  src/            功能模块(scanner 机会扫描、forecast 走势预测、
                  paper_trading 模拟盘、news_center 新闻中心、
                  factors 因子库、market_data 行情等)
  backtest/       回测引擎与数据加载器
  tests/          pytest 测试
frontend/     React + Vite 前端(Alpha Mind UI,端口 5899)
scripts/      定时任务与运维脚本(daily_scan.py 等)
```

## 本地运行

需要 Python ≥ 3.11、Node.js,以及 `.venv`(仓库根目录)。

**后端**(REST API,端口 8899):

```bash
.venv/bin/python -c 'import cli, sys; raise SystemExit(cli.main(sys.argv[1:]))' \
  serve --host 127.0.0.1 --port 8899
```

**前端**(Vite,端口 5899,已开启 `host: true` 供局域网/手机访问):

```bash
cd frontend
npm install      # 首次
npm run dev
```

浏览器打开 http://localhost:5899 ;同一 Wi-Fi 下手机用 `http://<本机IP>:5899`。

## 主要功能

- **总览** — A股 / 港股 / 美股大盘指数与自选股实时行情
- **模拟盘** — 30+ 策略的历史回测与稳健性优化
- **走势预测** — TimesFM 不确定性锥与多时间段策略信号
- **机会扫描** — 因子 / 异常 / 事件多源打分,前瞻收益自我验证(每日定时扫描 + 回填)
- **新闻中心** — 自选股、指数与重点行业的每日投资简报
- **投研分析** — 自然语言驱动的智能体研究

## 测试

```bash
cd agent && ../.venv/bin/pytest        # 后端
cd frontend && npm run test:run        # 前端
```

## 致谢与许可

本项目基于开源项目 [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) 二次开发,并按个人需求(Alpha Mind)大幅定制。许可信息见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。
