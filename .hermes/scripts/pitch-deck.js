const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

// Icon imports
const {
  FaBrain, FaChartLine, FaGlobeAmericas, FaRobot, FaShieldAlt,
  FaCode, FaLightbulb, FaUsers, FaRocket, FaDatabase,
  FaCogs, FaChartBar, FaLayerGroup, FaLock, FaBullseye,
  FaCheckCircle, FaArrowRight, FaStar, FaMoneyBillWave,
} = require("react-icons/fa");

// ── Color Palette (Midnight Executive) ──
const C = {
  navy: "0C1E3F",
  darkNavy: "07132E",
  iceBlue: "D6E4F0",
  white: "FFFFFF",
  accent: "00B4D8",
  accentGold: "F4A261",
  lightGray: "F0F4F8",
  midGray: "94A3B8",
  darkText: "1E293B",
  bodyText: "334155",
  green: "10B981",
  red: "EF4444",
  teal: "0D9488",
  highlight: "E0F2FE",
};

// ── Icon helper ──
function renderIconSvg(IconComponent, color = "#000000", size = 256) {
  return ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, { color, size: String(size) })
  );
}

async function iconToBase64(IconComponent, color, size = 256) {
  const svg = renderIconSvg(IconComponent, color, size);
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

// ── Helpers ──
const ICON_SIZE = 0.45;
const makeShadow = () => ({ type: "outer", color: "000000", blur: 8, offset: 2, angle: 135, opacity: 0.12 });
const labelStyle = (slideIndex, total) => ({ x: 0.4, y: 5.2, w: 3, h: 0.3, fontSize: 8, color: C.midGray, fontFace: "Calibri" });

async function main() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "Liang Huang";
  pres.title = "Alpha Mind — AI-Native Quant Trading Platform";

  // ────────────────────────────────────────────
  // SLIDE 1: TITLE
  // ────────────────────────────────────────────
  let s1 = pres.addSlide();
  s1.background = { color: C.darkNavy };

  // Big brand name
  s1.addText("ALPHA MIND", {
    x: 1, y: 1.2, w: 8, h: 1.2,
    fontSize: 48, fontFace: "Georgia", color: C.white, bold: true,
    charSpacing: 6, align: "center",
  });
  // Subtitle
  s1.addText("AI-Native Quantitative Trading Platform", {
    x: 1, y: 2.3, w: 8, h: 0.6,
    fontSize: 20, fontFace: "Calibri", color: C.accent, align: "center",
  });
  // Tagline
  s1.addText("Institutional-Grade Quant Research. Personal Ownership.", {
    x: 1.5, y: 3.0, w: 7, h: 0.5,
    fontSize: 13, fontFace: "Calibri Light", color: C.iceBlue, align: "center",
  });
  // Decorative line
  s1.addShape(pres.shapes.RECTANGLE, {
    x: 3.5, y: 3.6, w: 3, h: 0.03, fill: { color: C.accent },
  });
  // Stats row
  s1.addText([
    { text: "100+", options: { fontSize: 22, bold: true, color: C.accentGold, breakLine: true } },
    { text: "API Routes", options: { fontSize: 10, color: C.iceBlue } },
  ], { x: 0.8, y: 4.0, w: 2.5, h: 0.7, align: "center" });
  s1.addText([
    { text: "30+", options: { fontSize: 22, bold: true, color: C.accentGold, breakLine: true } },
    { text: "Strategies", options: { fontSize: 10, color: C.iceBlue } },
  ], { x: 3.8, y: 4.0, w: 2.5, h: 0.7, align: "center" });
  s1.addText([
    { text: "3,700+", options: { fontSize: 22, bold: true, color: C.accentGold, breakLine: true } },
    { text: "Tests", options: { fontSize: 10, color: C.iceBlue } },
  ], { x: 6.8, y: 4.0, w: 2.5, h: 0.7, align: "center" });

  // ────────────────────────────────────────────
  // SLIDE 2: THE PROBLEM
  // ────────────────────────────────────────────
  let s2 = pres.addSlide();
  s2.background = { color: C.white };

  s2.addText("The Gap in Retail Quant Investing", {
    x: 0.7, y: 0.4, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Georgia", color: C.darkText, bold: true,
  });
  s2.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.0, w: 1.2, h: 0.04, fill: { color: C.accent },
  });

  const problems = [
    { icon: FaLock, title: "Wall Street Moat", desc: "Institutional tools cost $10K+/mo — locked behind Bloomberg terminals and prime broker APIs" },
    { icon: FaCode, title: "Fragmented Tooling", desc: "Python scripts + Excel + web dashboards. No unified workflow from research to execution" },
    { icon: FaBrain, title: "AI Gap", desc: "LLMs can write code but can't reason about markets. No agent bridges the gap" },
    { icon: FaMoneyBillWave, title: "Capital Asymmetry", desc: "Retail traders face data delays, no co-location, and inferior execution — the edge gap is widening" },
  ];

  for (let i = 0; i < problems.length; i++) {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const bx = 0.7 + col * 4.6;
    const by = 1.4 + row * 1.8;

    const iconData = await iconToBase64(problems[i].icon, "#" + C.accent);
    s2.addImage({ data: iconData, x: bx, y: by + 0.05, w: ICON_SIZE, h: ICON_SIZE });
    s2.addText(problems[i].title, {
      x: bx + 0.6, y: by, w: 3.8, h: 0.35,
      fontSize: 15, fontFace: "Calibri", color: C.darkText, bold: true, margin: 0,
    });
    s2.addText(problems[i].desc, {
      x: bx + 0.6, y: by + 0.35, w: 3.8, h: 0.85,
      fontSize: 11, fontFace: "Calibri Light", color: C.bodyText, margin: 0,
    });
  }

  // ────────────────────────────────────────────
  // SLIDE 3: THE SOLUTION — Alpha Mind Overview
  // ────────────────────────────────────────────
  let s3 = pres.addSlide();
  s3.background = { color: C.navy };

  s3.addText("Alpha Mind: One Platform, All Markets", {
    x: 0.7, y: 0.4, w: 8.6, h: 0.6,
    fontSize: 28, fontFace: "Georgia", color: C.white, bold: true,
  });
  s3.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.0, w: 1.2, h: 0.04, fill: { color: C.accent },
  });

  const features = [
    { icon: FaGlobeAmericas, title: "Multi-Market Data", desc: "US, HK, China A-shares, Crypto — unified via akshare, yfinance, CCXT, IBKR" },
    { icon: FaChartLine, title: "TimesFM Forecast", desc: "Google's TimesFM foundation model for 3-month price forecasts with confidence intervals" },
    { icon: FaRobot, title: "LLM Agent + Swarm", desc: "LangGraph-powered ReAct agents with multi-agent swarm for research & execution" },
    { icon: FaCogs, title: "30+ Backtest Strategies", desc: "Grid, momentum, risk-parity, DCA, defensive momentum — with robust comparison engine" },
    { icon: FaLayerGroup, title: "Factor Zoo", desc: "Qlib158, Alpha101, GTJA191, academic factors — 300+ alpha signals off the shelf" },
    { icon: FaChartBar, title: "Opportunity Scanner", desc: "Factor + anomaly + event tri-signal ranking with forward-return validation" },
  ];

  for (let i = 0; i < features.length; i++) {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const bx = 0.7 + col * 3.1;
    const by = 1.4 + row * 1.8;

    // Card background
    s3.addShape(pres.shapes.RECTANGLE, {
      x: bx, y: by, w: 2.8, h: 1.5,
      fill: { color: "152B52" }, shadow: makeShadow(),
    });
    // Left accent bar
    s3.addShape(pres.shapes.RECTANGLE, {
      x: bx, y: by, w: 0.06, h: 1.5, fill: { color: C.accent },
    });
    const iconData = await iconToBase64(features[i].icon, "#" + C.accent);
    s3.addImage({ data: iconData, x: bx + 0.25, y: by + 0.2, w: 0.35, h: 0.35 });
    s3.addText(features[i].title, {
      x: bx + 0.7, y: by + 0.15, w: 1.9, h: 0.35,
      fontSize: 13, fontFace: "Calibri", color: C.white, bold: true, margin: 0,
    });
    s3.addText(features[i].desc, {
      x: bx + 0.25, y: by + 0.65, w: 2.35, h: 0.7,
      fontSize: 9.5, fontFace: "Calibri Light", color: C.iceBlue, margin: 0,
    });
  }

  // ────────────────────────────────────────────
  // SLIDE 4: AI-NATIVE ARCHITECTURE
  // ────────────────────────────────────────────
  let s4 = pres.addSlide();
  s4.background = { color: C.white };

  s4.addText("AI-Native Architecture", {
    x: 0.7, y: 0.4, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Georgia", color: C.darkText, bold: true,
  });
  s4.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.0, w: 1.2, h: 0.04, fill: { color: C.accent },
  });

  // Architecture layers (left side)
  const layers = [
    { title: "LLM Agent Loop", desc: "LangGraph ReAct — context builder, tool router, skill engine, memory manager", icon: FaRobot },
    { title: "Multi-Agent Swarm", desc: "Task decomposition, parallel workers, trust model, output contracts", icon: FaUsers },
    { title: "MCP Server", desc: "Model Context Protocol — tools as composable services for any LLM", icon: FaCogs },
    { title: "Security Layer", desc: "Mandate system, audit trail, read-only sandbox, consent-based execution", icon: FaShieldAlt },
  ];

  for (let i = 0; i < layers.length; i++) {
    const by = 1.3 + i * 1.0;
    s4.addShape(pres.shapes.RECTANGLE, {
      x: 0.7, y: by, w: 4.3, h: 0.85,
      fill: { color: C.lightGray },
    });
    s4.addShape(pres.shapes.RECTANGLE, {
      x: 0.7, y: by, w: 0.06, h: 0.85, fill: { color: C.accent },
    });
    const iconData = await iconToBase64(layers[i].icon, "#" + C.navy);
    s4.addImage({ data: iconData, x: 0.85, y: by + 0.2, w: 0.35, h: 0.35 });
    s4.addText(layers[i].title, {
      x: 1.35, y: by + 0.05, w: 3.5, h: 0.3,
      fontSize: 13, fontFace: "Calibri", color: C.darkText, bold: true, margin: 0,
    });
    s4.addText(layers[i].desc, {
      x: 1.35, y: by + 0.35, w: 3.5, h: 0.4,
      fontSize: 10, fontFace: "Calibri Light", color: C.bodyText, margin: 0,
    });
  }

  // Right side — tech stack callouts
  s4.addShape(pres.shapes.RECTANGLE, {
    x: 5.5, y: 1.3, w: 4.0, h: 3.8,
    fill: { color: C.navy }, shadow: makeShadow(),
  });
  s4.addText("TECH STACK", {
    x: 5.7, y: 1.4, w: 3.6, h: 0.4,
    fontSize: 12, fontFace: "Calibri", color: C.accent, bold: true, charSpacing: 4,
  });

  const techItems = [
    "Python 3.11+ / FastAPI",
    "React 19 + TypeScript + Vite",
    "LangGraph / LangChain",
    "Google TimesFM (Forecast)",
    "Pydantic v2 / DuckDB",
    "Docker + GitHub CI",
    "Ollama / OpenAI / DeepSeek",
    "MCP Protocol (FastMCP)",
  ];
  for (let i = 0; i < techItems.length; i++) {
    const iconData = await iconToBase64(FaCheckCircle, "#" + C.teal);
    s4.addImage({ data: iconData, x: 5.8, y: 2.0 + i * 0.38, w: 0.2, h: 0.2 });
    s4.addText(techItems[i], {
      x: 6.15, y: 2.0 + i * 0.38, w: 3.0, h: 0.25,
      fontSize: 10, fontFace: "Calibri", color: C.white, margin: 0,
    });
  }

  // ────────────────────────────────────────────
  // SLIDE 5: MARKET COVERAGE
  // ────────────────────────────────────────────
  let s5 = pres.addSlide();
  s5.background = { color: C.white };

  s5.addText("Market Coverage", {
    x: 0.7, y: 0.4, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Georgia", color: C.darkText, bold: true,
  });
  s5.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.0, w: 1.2, h: 0.04, fill: { color: C.accent },
  });

  const markets = [
    { name: "US Equities", desc: "S&P 500, NASDAQ — yfinance, Alpaca. Full stock, ETF, options coverage", stat: "10K+", statLabel: "Tickers" },
    { name: "China A-Shares", desc: "Shanghai/Shenzhen — akshare, tushare. 30+ data connectors", stat: "5K+", statLabel: "Tickers" },
    { name: "Hong Kong", desc: "HKEX equities — akshare, futu. Real-time and historical", stat: "2.5K+", statLabel: "Tickers" },
    { name: "Crypto", desc: "Binance, OKX, Bybit — CCXT. Spot + futures across 20+ exchanges", stat: "500+", statLabel: "Pairs" },
  ];

  for (let i = 0; i < markets.length; i++) {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const bx = 0.7 + col * 4.6;
    const by = 1.4 + row * 1.7;

    s5.addShape(pres.shapes.RECTANGLE, {
      x: bx, y: by, w: 4.2, h: 1.4,
      fill: { color: C.lightGray },
    });
    s5.addShape(pres.shapes.RECTANGLE, {
      x: bx, y: by, w: 4.2, h: 0.04, fill: { color: C.accent },
    });
    s5.addText(markets[i].name, {
      x: bx + 0.2, y: by + 0.15, w: 2.5, h: 0.3,
      fontSize: 16, fontFace: "Calibri", color: C.darkText, bold: true, margin: 0,
    });
    s5.addText(markets[i].desc, {
      x: bx + 0.2, y: by + 0.5, w: 2.5, h: 0.7,
      fontSize: 10, fontFace: "Calibri Light", color: C.bodyText, margin: 0,
    });
    // Stat callout
    s5.addText(markets[i].stat, {
      x: bx + 3.0, y: by + 0.15, w: 1.0, h: 0.4,
      fontSize: 24, fontFace: "Georgia", color: C.accent, bold: true, align: "right", margin: 0,
    });
    s5.addText(markets[i].statLabel, {
      x: bx + 2.8, y: by + 0.6, w: 1.2, h: 0.3,
      fontSize: 9, fontFace: "Calibri", color: C.midGray, align: "right", margin: 0,
    });
  }

  // ────────────────────────────────────────────
  // SLIDE 6: TRACTION & DEVELOPMENT
  // ────────────────────────────────────────────
  let s6 = pres.addSlide();
  s6.background = { color: C.navy };

  s6.addText("Traction & Development", {
    x: 0.7, y: 0.4, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Georgia", color: C.white, bold: true,
  });
  s6.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.0, w: 1.2, h: 0.04, fill: { color: C.accent },
  });

  // Big stat boxes
  const stats = [
    { num: "531", label: "Git Commits", desc: "18 months of active development" },
    { num: "3,700+", label: "Test Suite", desc: "238 test files, CI-gated on every push" },
    { num: "180K", label: "Lines of Python", desc: "25+ backend modules, clean architecture" },
    { num: "2", label: "Months to v1", desc: "From fork to production-ready release" },
  ];

  for (let i = 0; i < stats.length; i++) {
    const bx = 0.7 + (i % 4) * 2.3;
    const by = 1.3;

    s6.addShape(pres.shapes.RECTANGLE, {
      x: bx, y: by, w: 2.0, h: 1.6,
      fill: { color: "152B52" },
    });
    s6.addText(stats[i].num, {
      x: bx, y: by + 0.15, w: 2.0, h: 0.55,
      fontSize: 28, fontFace: "Georgia", color: C.accentGold, bold: true, align: "center",
    });
    s6.addText(stats[i].label, {
      x: bx, y: by + 0.65, w: 2.0, h: 0.3,
      fontSize: 11, fontFace: "Calibri", color: C.white, bold: true, align: "center",
    });
    s6.addText(stats[i].desc, {
      x: bx, y: by + 0.95, w: 2.0, h: 0.5,
      fontSize: 8.5, fontFace: "Calibri Light", color: C.iceBlue, align: "center", margin: 0,
    });
  }

  // Progress timeline
  s6.addText("DEVELOPMENT TIMELINE", {
    x: 0.7, y: 3.2, w: 3, h: 0.3,
    fontSize: 10, fontFace: "Calibri", color: C.accent, bold: true, charSpacing: 3,
  });

  const milestones = [
    { date: "Jan 2025", event: "Fork from Vibe-Trading" },
    { date: "Mar 2025", event: "Multi-market data + scanner" },
    { date: "May 2025", event: "TimesFM forecast engine" },
    { date: "Jul 2025", event: "30+ strategy backtest engine" },
    { date: "Sep 2025", event: "LLM agent + swarm system" },
    { date: "Present", event: "v5.0 — production ready" },
  ];

  // Timeline line
  s6.addShape(pres.shapes.LINE, {
    x: 1.0, y: 3.8, w: 8.2, h: 0, line: { color: C.accent, width: 2 },
  });

  for (let i = 0; i < milestones.length; i++) {
    const bx = 1.0 + i * 1.5;
    s6.addShape(pres.shapes.OVAL, {
      x: bx + 0.15, y: 3.65, w: 0.25, h: 0.25, fill: { color: C.accent },
    });
    s6.addText(milestones[i].date, {
      x: bx - 0.2, y: 3.95, w: 1.4, h: 0.2,
      fontSize: 8, fontFace: "Calibri", color: C.accentGold, align: "center", margin: 0,
    });
    s6.addText(milestones[i].event, {
      x: bx - 0.2, y: 4.15, w: 1.4, h: 0.6,
      fontSize: 8, fontFace: "Calibri Light", color: C.iceBlue, align: "center", margin: 0,
    });
  }

  // ────────────────────────────────────────────
  // SLIDE 7: TECHNOLOGY MOAT
  // ────────────────────────────────────────────
  let s7 = pres.addSlide();
  s7.background = { color: C.white };

  s7.addText("Technology Moat", {
    x: 0.7, y: 0.4, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Georgia", color: C.darkText, bold: true,
  });
  s7.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.0, w: 1.2, h: 0.04, fill: { color: C.accent },
  });

  const moats = [
    { icon: FaBrain, title: "LLM-Native Design", desc: "Not a chatbot bolted onto a trading app. The agent IS the operating system — LangGraph orchestrates every tool, skill, and data source." },
    { icon: FaLayerGroup, title: "Factor Research Engine", desc: "300+ alpha factors from 4 major libraries (Qlib, Alpha101, GTJA191, academic). Custom factor authoring in YAML." },
    { icon: FaRocket, title: "TimesFM Foundation Model", desc: "Google's TimesFM for probabilistic forecasts with 80% confidence cones. Multi-timeframe strategy overlay." },
    { icon: FaUsers, title: "Swarm Intelligence", desc: "Decompose complex research tasks across specialized agents. Each agent runs in a sandboxed context with its own tools." },
  ];

  for (let i = 0; i < moats.length; i++) {
    const by = 1.3 + i * 1.0;
    const iconData = await iconToBase64(moats[i].icon, "#" + C.navy);
    s7.addImage({ data: iconData, x: 0.7, y: by + 0.1, w: 0.4, h: 0.4 });
    s7.addText(moats[i].title, {
      x: 1.25, y: by, w: 3.5, h: 0.3,
      fontSize: 14, fontFace: "Calibri", color: C.darkText, bold: true, margin: 0,
    });
    s7.addText(moats[i].desc, {
      x: 1.25, y: by + 0.3, w: 8, h: 0.55,
      fontSize: 10.5, fontFace: "Calibri Light", color: C.bodyText, margin: 0,
    });
  }

  // ────────────────────────────────────────────
  // SLIDE 8: BUSINESS MODEL
  // ────────────────────────────────────────────
  let s8 = pres.addSlide();
  s8.background = { color: C.darkNavy };

  s8.addText("Business Model", {
    x: 0.7, y: 0.4, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Georgia", color: C.white, bold: true,
  });
  s8.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.0, w: 1.2, h: 0.04, fill: { color: C.accent },
  });

  const models = [
    { icon: FaStar, title: "SaaS Tier (Coming Soon)", desc: "Cloud-hosted Alpha Mind: managed data feeds, automated daily scans, portfolio alerts. $49-99/mo." },
    { icon: FaDatabase, title: "Premium Data & Factors", desc: "Proprietary factor packs, alternative data integrations, institutional-grade risk models." },
    { icon: FaRobot, title: "API / MCP Licensing", desc: "License the agent backend + MCP server as infrastructure for fintech startups building AI-trading products." },
    { icon: FaGlobeAmericas, title: "Strategy Marketplace", desc: "Community strategy sharing + verified signal marketplace. Revenue share on top-performing strategies." },
  ];

  for (let i = 0; i < models.length; i++) {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const bx = 0.7 + col * 4.6;
    const by = 1.4 + row * 1.7;

    s8.addShape(pres.shapes.RECTANGLE, {
      x: bx, y: by, w: 4.2, h: 1.4,
      fill: { color: "152B52" },
    });
    const iconData = await iconToBase64(models[i].icon, "#" + C.accent);
    s8.addImage({ data: iconData, x: bx + 0.2, y: by + 0.2, w: 0.35, h: 0.35 });
    s8.addText(models[i].title, {
      x: bx + 0.65, y: by + 0.15, w: 3.3, h: 0.3,
      fontSize: 14, fontFace: "Calibri", color: C.white, bold: true, margin: 0,
    });
    s8.addText(models[i].desc, {
      x: bx + 0.2, y: by + 0.55, w: 3.8, h: 0.7,
      fontSize: 10, fontFace: "Calibri Light", color: C.iceBlue, margin: 0,
    });
  }

  // ────────────────────────────────────────────
  // SLIDE 9: COMPETITIVE LANDSCAPE
  // ────────────────────────────────────────────
  let s9 = pres.addSlide();
  s9.background = { color: C.white };

  s9.addText("Competitive Landscape", {
    x: 0.7, y: 0.4, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Georgia", color: C.darkText, bold: true,
  });
  s9.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.0, w: 1.2, h: 0.04, fill: { color: C.accent },
  });

  // Comparison table header
  s9.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.3, w: 8.6, h: 0.4,
    fill: { color: C.navy },
  });
  s9.addText("Feature", { x: 0.9, y: 1.3, w: 3, h: 0.4, fontSize: 11, fontFace: "Calibri", color: C.white, bold: true, margin: 0 });
  s9.addText("Alpha Mind", { x: 4.2, y: 1.3, w: 1.8, h: 0.4, fontSize: 11, fontFace: "Calibri", color: C.accentGold, bold: true, align: "center", margin: 0 });
  s9.addText("QuantConnect", { x: 6.0, y: 1.3, w: 1.5, h: 0.4, fontSize: 11, fontFace: "Calibri", color: C.midGray, align: "center", margin: 0 });
  s9.addText("TradingView", { x: 7.5, y: 1.3, w: 1.5, h: 0.4, fontSize: 11, fontFace: "Calibri", color: C.midGray, align: "center", margin: 0 });

  const rows = [
    ["LLM Agent + Swarm", "✅ Native", "❌", "❌"],
    ["Multi-Market (US/HK/CN)", "✅ Built-in", "✅", "✅"],
    ["Local-First / Privacy", "✅ Yes", "❌ Cloud-only", "❌ Cloud-only"],
    ["TimesFM AI Forecast", "✅ Integrated", "❌", "❌"],
    ["300+ Factors", "✅ Built-in", "✅ Build your own", "❌ Limited"],
    ["Open Source (MIT)", "✅ Yes", "❌ Proprietary", "❌ Proprietary"],
    ["MCP Protocol", "✅ Native", "❌", "❌"],
    ["30+ Strategies (Grid/DCA/RP)", "✅ Included", "❌ Write your own", "❌ Limited"],
  ];

  for (let i = 0; i < rows.length; i++) {
    const by = 1.7 + i * 0.4;
    const bg = i % 2 === 0 ? C.lightGray : C.white;
    s9.addShape(pres.shapes.RECTANGLE, { x: 0.7, y: by, w: 8.6, h: 0.4, fill: { color: bg } });
    s9.addText(rows[i][0], { x: 0.9, y: by, w: 3.2, h: 0.4, fontSize: 9.5, fontFace: "Calibri", color: C.darkText, margin: 0 });
    s9.addText(rows[i][1], { x: 4.2, y: by, w: 1.8, h: 0.4, fontSize: 9.5, fontFace: "Calibri", color: C.teal, bold: true, align: "center", margin: 0 });
    s9.addText(rows[i][2], { x: 6.0, y: by, w: 1.5, h: 0.4, fontSize: 9.5, fontFace: "Calibri", color: C.midGray, align: "center", margin: 0 });
    s9.addText(rows[i][3], { x: 7.5, y: by, w: 1.5, h: 0.4, fontSize: 9.5, fontFace: "Calibri", color: C.midGray, align: "center", margin: 0 });
  }

  // ────────────────────────────────────────────
  // SLIDE 10: TEAM & ASK
  // ────────────────────────────────────────────
  let s10 = pres.addSlide();
  s10.background = { color: C.navy };

  s10.addText("Team & Opportunity", {
    x: 0.7, y: 0.4, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Georgia", color: C.white, bold: true,
  });
  s10.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.0, w: 1.2, h: 0.04, fill: { color: C.accent },
  });

  // Founder card
  s10.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.4, w: 4.0, h: 2.0,
    fill: { color: "152B52" },
  });
  s10.addText("Liang Huang", {
    x: 1.0, y: 1.6, w: 3.5, h: 0.35,
    fontSize: 18, fontFace: "Calibri", color: C.white, bold: true,
  });
  s10.addText("Founder & Lead Developer", {
    x: 1.0, y: 1.95, w: 3.5, h: 0.25,
    fontSize: 11, fontFace: "Calibri", color: C.accent,
  });
  s10.addText([
    { text: "• Full-stack developer & quant researcher", options: { breakLine: true } },
    { text: "• Built Alpha Mind from zero to production v5.0", options: { breakLine: true } },
    { text: "• Deep expertise in LLM agents, fintech infrastructure, and quantitative trading systems", options: {} },
  ], {
    x: 1.0, y: 2.3, w: 3.5, h: 0.9,
    fontSize: 9.5, fontFace: "Calibri Light", color: C.iceBlue, margin: 0,
  });

  // Ask card
  s10.addShape(pres.shapes.RECTANGLE, {
    x: 5.2, y: 1.4, w: 4.2, h: 2.0,
    fill: { color: "152B52" },
  });
  s10.addText("We're Seeking", {
    x: 5.5, y: 1.6, w: 3.7, h: 0.35,
    fontSize: 18, fontFace: "Calibri", color: C.accentGold, bold: true,
  });
  s10.addText([
    { text: "💰 $500K Seed Round", options: { bold: true, breakLine: true } },
    { text: "To scale engineering, build cloud infrastructure, and launch SaaS", options: {} },
  ], {
    x: 5.5, y: 2.0, w: 3.7, h: 0.5,
    fontSize: 11, fontFace: "Calibri Light", color: C.white, margin: 0,
  });
  s10.addText([
    { text: "🎯 Strategic Partners", options: { bold: true, breakLine: true } },
    { text: "Broker-dealers, data vendors, and fintech platforms for distribution", options: {} },
  ], {
    x: 5.5, y: 2.5, w: 3.7, h: 0.5,
    fontSize: 11, fontFace: "Calibri Light", color: C.white, margin: 0,
  });

  // Contact
  s10.addText("github.com/Huangliang0826/Vibe-Trading", {
    x: 0.7, y: 3.7, w: 8.6, h: 0.3,
    fontSize: 10, fontFace: "Consolas", color: C.accent, align: "center",
  });
  s10.addText("huangliang19950826@gmail.com", {
    x: 0.7, y: 4.0, w: 8.6, h: 0.3,
    fontSize: 10, fontFace: "Calibri", color: C.iceBlue, align: "center",
  });

  // Footer
  s10.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 4.8, w: 10, h: 0.825,
    fill: { color: "07132E" },
  });
  s10.addText("Alpha Mind · AI-Native Quantitative Trading · MIT Licensed", {
    x: 1, y: 4.9, w: 8, h: 0.4,
    fontSize: 9, fontFace: "Calibri Light", color: C.midGray, align: "center",
    margin: 0,
  });

  // ────────────────────────────────────────────
  // WRITE FILE
  // ────────────────────────────────────────────
  await pres.writeFile({ fileName: "/Users/lianghuang/Desktop/Alpha_Mind_Pitch_Deck.pptx" });
  console.log("✅ Pitch deck saved to /Users/lianghuang/Desktop/Alpha_Mind_Pitch_Deck.pptx");
}

main().catch(console.error);
