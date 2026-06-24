import { useState, useEffect } from "react";
import { PersonStanding, Loader2, ExternalLink, RefreshCw } from "lucide-react";
import { api, type WatchlistMarket, type IndustryReport } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── sector definitions ──────────────────────────────────────────────────────

interface Stock {
  code: string;
  market: WatchlistMarket;
  note?: string;
}

interface Sector {
  key: string;
  label: string;
  stocks: Stock[];
}

const SECTORS: Sector[] = [
  {
    key: "overview",
    label: "总览",
    stocks: [
      { code: "TSLA", market: "us", note: "Optimus" },
      { code: "01810", market: "hk", note: "小米 CyberOne" },
      { code: "002527", market: "cn", note: "新世纪机器人" },
      { code: "300024", market: "cn", note: "机器人(沈阳)" },
      { code: "688276", market: "cn", note: "百利天恒" },
    ],
  },
  {
    key: "harmonic",
    label: "谐波减速器",
    stocks: [
      { code: "6324", market: "hk", note: "哈默纳科" },
      { code: "300159", market: "cn", note: "新研股份" },
      { code: "688507", market: "cn", note: "索辰科技" },
      { code: "603728", market: "cn", note: "鸣志电器" },
      { code: "002747", market: "cn", note: "埃斯顿" },
    ],
  },
  {
    key: "planetary",
    label: "行星滚柱丝杠",
    stocks: [
      { code: "002527", market: "cn", note: "新世纪机器人" },
      { code: "603728", market: "cn", note: "鸣志电器" },
      { code: "688017", market: "cn", note: "绿的谐波" },
      { code: "002747", market: "cn", note: "埃斯顿" },
    ],
  },
  {
    key: "torque_motor",
    label: "无框力矩电机",
    stocks: [
      { code: "002747", market: "cn", note: "埃斯顿" },
      { code: "603728", market: "cn", note: "鸣志电器" },
      { code: "688017", market: "cn", note: "绿的谐波" },
      { code: "300124", market: "cn", note: "汇川技术" },
    ],
  },
  {
    key: "force_sensor",
    label: "六维力传感器",
    stocks: [
      { code: "688100", market: "cn", note: "威胜信息" },
      { code: "300590", market: "cn", note: "移为通信" },
      { code: "688017", market: "cn", note: "绿的谐波" },
    ],
  },
  {
    key: "dexterous_hand",
    label: "灵巧手",
    stocks: [
      { code: "002527", market: "cn", note: "新世纪机器人" },
      { code: "300024", market: "cn", note: "机器人(沈阳)" },
      { code: "002747", market: "cn", note: "埃斯顿" },
    ],
  },
  {
    key: "ball_screw",
    label: "滚珠丝杠",
    stocks: [
      { code: "002527", market: "cn", note: "新世纪机器人" },
      { code: "002747", market: "cn", note: "埃斯顿" },
      { code: "603728", market: "cn", note: "鸣志电器" },
    ],
  },
];

// ── Placeholder card ────────────────────────────────────────────────────────

function PlaceholderCard({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-2xl border bg-card p-5">
      <h3 className="text-sm font-semibold text-foreground mb-3">{title}</h3>
      {children || (
        <div className="flex items-center justify-center py-8 text-sm text-muted-foreground/50">
          待补
        </div>
      )}
    </div>
  );
}

// ── OverviewPanel ───────────────────────────────────────────────────────────

const CORE_SECTORS = SECTORS.filter((s) => s.key !== "overview");

const UPSTREAM = [
  { name: "稀土永磁", desc: "钕铁硼永磁材料" },
  { name: "精密磨床", desc: "齿轮/丝杠加工设备" },
  { name: "特种材料", desc: "碳纤维、钛合金等" },
];

function OverviewPanel() {
  return (
    <div className="space-y-6">
      {/* ── 产业链结构图 ── */}
      <PlaceholderCard title="产业链结构">
        <div className="space-y-4">
          {/* 需求端 */}
          <div>
            <p className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">需求端</p>
            <div className="rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 text-center">
              <span className="text-sm font-semibold text-primary">本体机器人</span>
              <span className="text-xs text-muted-foreground ml-2">Tesla Optimus · 小米 CyberOne · Figure · 1X</span>
            </div>
          </div>

          {/* 箭头 */}
          <div className="flex justify-center text-muted-foreground/40 text-lg">↓</div>

          {/* 中游：六个核心环节 */}
          <div>
            <p className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">核心零部件（中游）</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {CORE_SECTORS.map((s) => (
                <div key={s.key} className="rounded-xl border px-3 py-2.5 text-center bg-muted/20 hover:bg-muted/40 transition-colors">
                  <p className="text-sm font-medium text-foreground">{s.label}</p>
                  <p className="text-[11px] text-muted-foreground">{s.stocks.length} 只标的</p>
                </div>
              ))}
            </div>
          </div>

          {/* 箭头 */}
          <div className="flex justify-center text-muted-foreground/40 text-lg">↓</div>

          {/* 上游 */}
          <div>
            <p className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">上游材料与设备</p>
            <div className="grid grid-cols-3 gap-2">
              {UPSTREAM.map((u) => (
                <div key={u.name} className="rounded-xl border px-3 py-2.5 text-center bg-muted/10">
                  <p className="text-sm font-medium text-foreground">{u.name}</p>
                  <p className="text-[11px] text-muted-foreground">{u.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </PlaceholderCard>

      {/* ── 板块评分总览 ── */}
      <PlaceholderCard title="板块评分总览" />

      {/* ── 核心标的池 ── */}
      <PlaceholderCard title="核心标的池" />

      {/* ── 整机成本构成 ── */}
      <PlaceholderCard title="整机成本构成" />

      {/* ── 量产时间轴 ── */}
      <PlaceholderCard title="量产时间轴" />

      {/* ── 板块结论 ── */}
      <PlaceholderCard title="板块结论" />
    </div>
  );
}

// ── SegmentTemplate (每个环节子页统一模板) ────────────────────────────────────
// 内容综合自最近收集的东财/问财行业研报（人形机器人核心零部件），产业级口径，
// 个股层暂不展开。评分维度列出该环节研判各维度的关注点，非具体个股打分。

interface ScoreDim { dim: string; note: string }
interface SegmentResearch {
  positioning: string;
  barriers: { tech: string; capacity: string };
  landscape: { overseas: string; domestic: string };
  scoring: ScoreDim[];
}

const SEGMENT_RESEARCH: Record<string, SegmentResearch> = {
  harmonic: {
    positioning:
      "旋转关节减速核心。体积小、重量轻、传动比大、回转精度高，是人形机器人旋转关节（尤其上肢）的主流减速方案，单台用量约 14 个。减速器约占工业机器人成本 35%，盈利水平居核心零部件最高一档。目前下游以工业机器人为主（占比约 75%），2024 全球市场约 86 亿元；人形量产放量后，2029 年增量市场有望再添约 84 亿元，总规模翻倍。",
    barriers: {
      tech: "柔轮/刚轮齿形设计、波发生器、柔性轴承为核心技术；柔轮材料（40Cr 合金钢）与热处理工艺仍部分依赖进口；齿形与加工精度直接决定传动误差、背隙与寿命，专利护城河集中在总体结构、波发生器、柔轮与加工制造。",
      capacity: "海外龙头哈默纳科缓速扩产，下游需求缺口大；批量一致性与扩产节奏是国产替代窗口的关键。柔轮材料、轴承等上游自主化程度影响成本与交付。",
    },
    landscape: {
      overseas: "日本哈默纳科一家独大，全球产能占比约 40%（历史市占率口径高达 35%~85%），齿形设计、柔轮材料与工艺设备长期领先；新宝（日）亦占一定份额。",
      domestic: "绿的谐波为国产龙头，国内销量市占约 21%~26%，仅次于哈默纳科，已打破外资垄断并进入 UR、埃斯顿等供应链；来福、中技克美等跟进。国产替代受益于交期、政策与降本三重逻辑。",
    },
    scoring: [
      { dim: "不可替代性", note: "旋转关节主流减速方案，齿形/材料/工艺壁垒高，替代难度大。" },
      { dim: "估值", note: "板块高景气，谐波环节估值溢价显著，需警惕预期透支。" },
      { dim: "业绩", note: "当前工业机器人需求承压、人形未放量，业绩弹性待量产兑现。" },
      { dim: "客户", note: "能否进入特斯拉及国内本体厂旋转执行器供应链是关键。" },
      { dim: "管理层", note: "长期研发投入、齿形/柔轮材料自主化与扩产节奏的把握能力。" },
    ],
  },
  planetary: {
    positioning:
      "线性关节核心传动，将旋转运动转为直线运动。相比滚珠丝杠具高承载、高工况适应、小体积、高精度、长寿命，是综合性能最优的丝杠品种，为人形机器人线性执行器主选方案（特斯拉 Optimus 采用反向式），单台约 14 个，约占整机价值量 19%（关节价值占比可达 15%~25%）。叠加灵巧手微型丝杠，2030 年市场有望超 450 亿元。",
    barriers: {
      tech: "螺纹牙型与行星齿轮设计决定服役性能；内螺纹加工是最大难点（高精度以磨削为主，大长径比、大螺旋角磨削存在砂轮颤振难题），设计 know-how 壁垒高。",
      capacity: "高端磨床依赖进口（近千万元/台、采购周期 1 年以上），国产磨床精度不足、出品不稳定；面向远期百万台需求的一致性批量生产能力是核心产能壁垒。",
    },
    landscape: {
      overseas: "欧美日垄断，CR5 超 80%。瑞士 Rollvis/GSA、瑞典 SKF（Ewellix）、德国 Rexroth（舍弗勒）、美国 CMC 等凭借材料、设计、热处理与精密加工全流程领先。",
      domestic: "起步晚，处于国产替代第一阶段，国产化率约 19%；汽车零部件、齿轮、轴承等工艺相通的厂商加速切入送样，磨床与内螺纹加工工艺突破是胜负手。",
    },
    scoring: [
      { dim: "不可替代性", note: "线性关节高价值量、高确定性方案，工艺壁垒为零部件之最。" },
      { dim: "估值", note: "稀缺高弹性赛道，估值溢价高，对量产兑现敏感。" },
      { dim: "业绩", note: "多处于送样/小批量阶段，业绩尚未兑现。" },
      { dim: "客户", note: "进入主机厂线性执行器供应链、通过批量验证是核心看点。" },
      { dim: "管理层", note: "磨床等设备投入、内螺纹工艺与热处理储备的前瞻布局。" },
    ],
  },
  torque_motor: {
    positioning:
      "关节驱动动力源。无框力矩电机小体积、大扭矩、低速高力矩、高功率密度，是人形机器人旋转关节的主流驱动电机（特斯拉 Optimus 28 个关节均搭载），约占整机 BOM 成本 8%。预计 2029 年全球市场约 308 亿元，其中人形机器人占比约 73%（约 224 亿元），CAGR 极高。",
    barriers: {
      tech: "磁路与工艺设计为核心（需在低压供电下输出高功率）；绕组工艺（如无框灌封）、高性能永磁体、转矩/功率密度与温升控制决定性能。",
      capacity: "需定制化设计并集成进关节内部；高端永磁材料、硅钢等上游，以及批量降本与一致性能力构成产能壁垒。",
    },
    landscape: {
      overseas: "第一梯队为德国 TQ Robodrive、美国 Kollmorgen、Allied Motion、Aerotech、Parker，深耕数十年，高端参数领先。",
      domestic: "第二梯队加速追赶。步科股份为国产龙头（2016 首代、2022 第三代首创无框灌封工艺，性能比肩国际一流，已获人形小批量订单）；雷赛智能、昊志机电、禾川、汇川等切入，差距在快速缩小。",
    },
    scoring: [
      { dim: "不可替代性", note: "关节主流驱动方案，但电机相对成熟、竞争者较多。" },
      { dim: "估值", note: "人形增量大、CAGR 高，估值随订单催化波动。" },
      { dim: "业绩", note: "协作机器人为基本盘，人形处小批量起量阶段。" },
      { dim: "客户", note: "能否拿到人形本体厂关节/电机订单决定弹性。" },
      { dim: "管理层", note: "磁路/绕组工艺积累与下一代降本预研能力。" },
    ],
  },
  force_sensor: {
    positioning:
      "力感知高端核心器件。六维力传感器同时测量 Fx/Fy/Fz 三力与 Mx/My/Mz 三力矩，用于踝、膝、髋关节及末端执行器，为步态规划、平衡控制与柔顺操作提供数据，单台人形至少 4 个，技术难度为各类传感器之最。市场基数小（2023 中国约 2.35 亿元、出货不足万台），人形放量打开远期空间（2030 预测出货约 120 万台、规模约 143 亿元）。",
    barriers: {
      tech: "结构耦合设计、六维联合标定/校准、解耦算法是核心；需抑制温漂、蠕变、维间串扰并优化动态性能，高精度六维测量偏差需控制在量程 0.3%FS 以内。",
      capacity: "贴片工艺、加工精度与一致性，以及标定设备与流程构成壁垒；当前价格高，降本依赖工艺成熟与规模化。",
    },
    landscape: {
      overseas: "欧美日领跑。美国 ATI 为龙头（中国市占约 22.4%），德国 SCHUNK、加拿大 Robotiq、丹麦 OnRobot、日韩 Robotous/Epson 等在灵敏度、串扰等指标上领先。",
      domestic: "市场集中度较高，宇立仪器（SRI）市占约 12.2% 居第二，坤维科技、蓝点触控、海伯森、鑫精诚、柯力传感等崛起；准度可对标国际，灵敏度/串扰/维间耦合仍有差距，国产替代推进中。",
    },
    scoring: [
      { dim: "不可替代性", note: "力控核心、技术最难，高端供给稀缺，替代性低。" },
      { dim: "估值", note: "稀缺标的，估值高，对人形上量节奏敏感。" },
      { dim: "业绩", note: "市场规模小、尚未上量，业绩贡献有限。" },
      { dim: "客户", note: "进入人形本体感知方案、获得量产验证是关键。" },
      { dim: "管理层", note: "标定/解耦算法与贴片工艺的长期积累深度。" },
    ],
  },
  dexterous_hand: {
    positioning:
      "人形机器人末端执行器、通用化的“最后一公里”，直接决定精细操作能力，约占整机成本 14%~18%，价值量高。由驱动（空心杯/无刷有齿槽电机）、传动（腱绳/连杆/丝杠）、感知（触觉/六维力/电子皮肤）与控制四系统构成。全球市场 2024 约 17 亿美元、2030 约 30 亿美元，远期（2035 中性测算）国内约 967 亿元；当前面临成本高、可靠性不足、控制泛化弱三大瓶颈。",
    barriers: {
      tech: "系统集成（多自由度运动、多模态感知与精密控制融合）是核心；驱动-传动-感知技术路线尚未收敛（腱绳 vs 连杆、空心杯 vs 无刷有齿槽），触觉感知与控制算法泛化能力是难点。",
      capacity: "微型电机、微型丝杠、触觉传感器等核心器件成熟度不足；零件多、未量产致 BOM 成本高（约 5 万元），降本空间大（测算约 80%），量产一致性待突破。",
    },
    landscape: {
      overseas: "特斯拉引领方案迭代（二代加入触觉、三代提升自由度并以无刷有齿槽电机替换部分空心杯电机），国际巨头卡位关键器件。",
      domestic: "国内多点突破（因时机器人等），产业从实验室向规模化工业品跨越；技术路线收敛中，具备灵巧手本体设计与生产能力的厂商话语权与盈利水平领先。",
    },
    scoring: [
      { dim: "不可替代性", note: "末端执行器“唯一解”，本体设计能力者话语权高。" },
      { dim: "估值", note: "高价值量、高弹性主题，估值溢价与波动均大。" },
      { dim: "业绩", note: "未量产、成本高，短期业绩贡献小。" },
      { dim: "客户", note: "进入人形本体厂或数据采集体系是核心看点。" },
      { dim: "管理层", note: "本体设计 + 核心器件协同创新与降本路径能力。" },
    ],
  },
  ball_screw: {
    positioning:
      "成熟线性传动部件，以滚动摩擦替代滑动，传动效率 90%+、精度高（C3/C5）、轴向刚度高。主下游为数控机床（占比 50%+）、汽车（线控制动/转向/驻车/主动悬架）与工业自动化；在人形机器人中用于部分线性环节，并作为行星滚柱丝杠的成熟对照/过渡方案。国内市场约 31 亿元（2023），供需缺口明显（2023 缺口约 566 万套）。",
    barriers: {
      tech: "原材料、工艺流程（磨削、淬硬处理）与精度等级控制为关键，整体壁垒低于行星滚柱丝杠，但高端精度/刚性/寿命仍待突破。",
      capacity: "高精度磨床等设备瓶颈突出；高端国产化率低（整体 < 30%、高端 < 5%），热处理工艺与先进设备产能决定突破节奏。",
    },
    landscape: {
      overseas: "日本 NSK/THK、德国力士乐（Rexroth）、瑞典 SKF 为主，日欧合计约占全球 70% 份额；中国台湾上银、银泰在中端强势，中高端国内市场超 70% 由外资/台资占据。",
      domestic: "南京工艺、贝斯特、秦川机床等为国产替代中坚，以中低端为主，高端待突破；机床更新周期与机器人需求共同拉动国产替代。",
    },
    scoring: [
      { dim: "不可替代性", note: "成熟通用、技术壁垒相对低，可被行星滚柱丝杠替代，稀缺性弱。" },
      { dim: "估值", note: "偏传统功能件，弹性弱于行星滚柱丝杠。" },
      { dim: "业绩", note: "机床/汽车基本盘稳健，业绩相对扎实。" },
      { dim: "客户", note: "机床、汽车、机器人多下游，客户结构分散。" },
      { dim: "管理层", note: "磨床/热处理工艺与高端产品突破的推进力。" },
    ],
  },
};

function ResearchCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border bg-card p-5">
      <h3 className="text-sm font-semibold text-foreground mb-3">{title}</h3>
      {children}
    </div>
  );
}

function SegmentTemplate({ sectorKey }: { sectorKey: string }) {
  const r = SEGMENT_RESEARCH[sectorKey];
  if (!r) {
    return (
      <div className="space-y-6">
        <PlaceholderCard title="环节定位" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <PlaceholderCard title="国际竞争格局" />
          <PlaceholderCard title="国内竞争格局" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 环节定位 */}
      <ResearchCard title="环节定位">
        <p className="text-sm text-foreground/90 leading-relaxed">{r.positioning}</p>
      </ResearchCard>

      {/* 竞争格局（产业级） */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ResearchCard title="国际竞争格局">
          <p className="text-sm text-foreground/90 leading-relaxed">{r.landscape.overseas}</p>
        </ResearchCard>
        <ResearchCard title="国内竞争格局">
          <p className="text-sm text-foreground/90 leading-relaxed">{r.landscape.domestic}</p>
        </ResearchCard>
      </div>

      {/* 壁垒类型 */}
      <div className="rounded-2xl border bg-card p-5">
        <h3 className="text-sm font-semibold text-foreground mb-3">壁垒类型</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="rounded-xl border px-4 py-3 bg-blue-500/[0.04]">
            <p className="text-sm font-medium text-blue-600 dark:text-blue-400 mb-1.5">科技壁垒</p>
            <p className="text-xs text-foreground/80 leading-relaxed">{r.barriers.tech}</p>
          </div>
          <div className="rounded-xl border px-4 py-3 bg-orange-500/[0.04]">
            <p className="text-sm font-medium text-orange-600 dark:text-orange-400 mb-1.5">产能壁垒</p>
            <p className="text-xs text-foreground/80 leading-relaxed">{r.barriers.capacity}</p>
          </div>
        </div>
      </div>

      {/* 评分维度（产业研判关注点，个股层不展开） */}
      <div className="rounded-2xl border bg-card p-5">
        <h3 className="text-sm font-semibold text-foreground mb-1">评分维度</h3>
        <p className="text-[11px] text-muted-foreground mb-4">各维度的研判关注点（个股打分暂不展开）</p>
        <div className="space-y-2.5">
          {r.scoring.map((s) => (
            <div key={s.dim} className="flex gap-3">
              <span className="text-xs font-medium text-foreground w-20 shrink-0 pt-0.5">{s.dim}</span>
              <span className="text-xs text-muted-foreground leading-relaxed flex-1">{s.note}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 核心标的（个股层先不展开） */}
      <div className="rounded-2xl border bg-card p-5">
        <h3 className="text-sm font-semibold text-foreground mb-1">核心标的</h3>
        <p className="text-[11px] text-muted-foreground mb-3">个股层暂不展开，后续补充</p>
        <div className="flex items-center justify-center py-6 text-sm text-muted-foreground/50">待补</div>
      </div>
    </div>
  );
}

// ── ReportLibraryPanel (研报库) ───────────────────────────────────────────────

const SEGMENT_COLORS: Record<string, string> = {
  机器人: "bg-primary/10 text-primary",
  减速器: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  丝杠: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  执行器: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  灵巧手: "bg-purple-500/10 text-purple-600 dark:text-purple-400",
};

function ReportLibraryPanel() {
  const [reports, setReports] = useState<IndustryReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<{ begin: string; end: string } | null>(null);
  const [filter, setFilter] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api.getIndustryReports()
      .then((res) => {
        setReports(res.reports || []);
        setRange({ begin: res.begin, end: res.end });
        if (res.error) setError(res.error);
      })
      .catch((e) => setError(e?.message || "获取研报失败"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const segments = Array.from(new Set(reports.map((r) => r.segment)));
  const shown = filter ? reports.filter((r) => r.segment === filter) : reports;

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setFilter(null)}
            className={cn(
              "text-xs px-2.5 py-1 rounded-full border transition-colors",
              !filter ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:text-foreground"
            )}
          >
            全部 ({reports.length})
          </button>
          {segments.map((seg) => {
            const count = reports.filter((r) => r.segment === seg).length;
            return (
              <button
                key={seg}
                onClick={() => setFilter(filter === seg ? null : seg)}
                className={cn(
                  "text-xs px-2.5 py-1 rounded-full border transition-colors",
                  filter === seg ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:text-foreground"
                )}
              >
                {seg} ({count})
              </button>
            );
          })}
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded border border-border hover:border-foreground/20 disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          刷新
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 px-4 py-2 text-xs text-yellow-600 dark:text-yellow-400">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-2xl border bg-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/30 text-left text-muted-foreground">
              <th className="px-4 py-3 font-medium w-28">日期</th>
              <th className="px-4 py-3 font-medium w-28">机构</th>
              <th className="px-4 py-3 font-medium">标题</th>
              <th className="px-4 py-3 font-medium w-24">所属环节</th>
              <th className="px-4 py-3 font-medium w-16">来源</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin inline mr-2" />
                拉取行业研报中…（首次较慢）
              </td></tr>
            ) : shown.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-muted-foreground text-sm">
                暂无研报
              </td></tr>
            ) : (
              shown.map((r, i) => (
                <tr key={`${r.date}-${i}`} className="border-b last:border-b-0 hover:bg-muted/20 transition-colors">
                  <td className="px-4 py-3 tabular-nums text-muted-foreground whitespace-nowrap">{r.date}</td>
                  <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">{r.org}</td>
                  <td className="px-4 py-3">
                    {r.url ? (
                      <a href={r.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:text-primary transition-colors">
                        {r.title}
                        <ExternalLink className="h-3 w-3 shrink-0 opacity-50" />
                      </a>
                    ) : r.title}
                  </td>
                  <td className="px-4 py-3">
                    <span className={cn("text-[10px] px-2 py-0.5 rounded-full font-medium", SEGMENT_COLORS[r.segment] || "bg-muted text-muted-foreground")}>
                      {r.segment}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[11px] text-muted-foreground whitespace-nowrap">{r.source || "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted-foreground/60">
        数据源: 东方财富行业研报 (qType=1) + 同花顺问财研报搜索
        {range && ` · ${range.begin} ~ ${range.end}`}
        {` · 共 ${reports.length} 篇`}
      </p>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────────────

export function HumanoidRobot() {
  const [activeKey, setActiveKey] = useState("overview");
  const activeSector = SECTORS.find((s) => s.key === activeKey) || SECTORS[0];

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <PersonStanding className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-xl font-bold">人形机器人</h1>
          <p className="text-xs text-muted-foreground">核心零部件板块追踪</p>
        </div>
      </div>

      {/* Sector tabs */}
      <div className="flex flex-wrap gap-1.5 mb-6 border-b pb-3">
        {[...SECTORS.map((s) => ({ key: s.key, label: s.label })), { key: "reports", label: "研报库" }].map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveKey(t.key)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
              t.key === activeKey
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-muted"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Active sector content */}
      {activeKey === "overview" ? (
        <OverviewPanel />
      ) : activeKey === "reports" ? (
        <ReportLibraryPanel />
      ) : (
        <SegmentTemplate key={activeSector.key} sectorKey={activeSector.key} />
      )}
    </div>
  );
}
