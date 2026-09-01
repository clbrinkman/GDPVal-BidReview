# 标书审查 Benchmark 数据治理平台（prototype）

对标 OpenAI GDPval 的思路，做一个**审查类** benchmark：让模型审查投标文件，检出其中被注入的偏差。
由于真实标书不公开，采用**注入式合成**：抓取真实招标文件 → 程序化/生成式构造合规基线标书 → 注入已知偏差 →
偏差自带 ground truth（before/after/位置/期望检出结论），评测检出率与误报率。

本仓库是其中的**数据治理 + 后期人工工作台** prototype，覆盖 选题（爬虫）→ 构造（注入）→ 质检（人工校验）闭环中
"人"的那一环，设计目标是**尽可能少的人工**：能走规则的不进人工队列，必须人工的做成 <30 秒可判的自描述卡片。

运行：`python platform/app.py` → http://127.0.0.1:8321 （Python 3.13，依赖 fastapi / uvicorn / requests / bs4 / lxml）

## 已实现功能

- **爬虫选题**：ccgp 公开招标频道抓取（48 项目/26 附件），URL 去重幂等，TDR 统一编号
- **项目总览（标注入口）**：类别卡（工程/货物/服务）→ 项目 → 三类标注任务，实时待审数；
  分类走关键词规则（剥代理机构名前缀，命中词可溯源），不设人工
- **生成节点审核**：N1 输入解析 → N2 基线合规 → N3 偏差注入 → N4 成稿质量，任一驳回即回炉
- **专家校验**：law/scheme/plaus/inj 四区，点选绿色高亮 + 上一条/暂存(draft)/提交/下一条
- **规则标注**：rubric 条目保留/改写（文本直接写回）/删除，同款暂存/提交交互
- **规则编辑**：rubric 库、条目编辑、模板绑定多项目
- **环境文件**：噪声环境展示（含证据绿/噪声红/普通灰）+ PDF 阅读器（原生渲染兼容扫描件，按页反馈）
- **辅助队列**：GT 校验（gt_status 状态机）、finding 裁决、附件校准
- **治理**：六前缀编号、五类错误法典、全部判定可撤销回退、暂存/提交两态、schema 迁移 V1-V8
- **演示数据**：5 case / 59 校验项 / 34 环境文件 / 44 rubric 条目 / 4 注入 GT，开箱即用

## 未来待实现功能

- **rubric 自动抽取器**：用 OpenBidKit 18 解析项 schema 从真实招标 DOCX 抽取 delta 条目
  （其三轮废标检查 prompt 定为第一个评测基线）
- **基线标书生成器**：按 rubric 逐条生成合规响应，产出 baseline case
- **程序化注入器**：按 err_taxonomy 的 P 方式批量注入偏差并自动生成自描述 GT
- **扫描件构造**：参数化做旧（DPI/倾斜/阴影/压缩痕迹）vs 真实打印扫描，
  用"扫描件不真实"专家反馈通道收敛方案
- **评测 run**：模型跑 case_set，finding 自动对 GT（hit/miss/false_positive），
  逐条检出率/误报率按 错误类型 × 项目类别 宏平均切片，case_set 版本化
- **agent 取证评测**：噪声环境中的工具面（shell vs 检索 API），按 has_evidence 测取证召回
- **dynamic_events**：澄清函发布等动态事件进环境（二期）

## 设计理念

1. **GT 免费**：偏差是我们注入的，所以每个 GT 自描述（注入位置、改前、改后、期望模型结论）。
   人工不"找答案"，只"验答案"——校验一条 GT 是否成立应在 30 秒内完成。
2. **后期人工，不是采集人工**：人工出现在三个位置——
   ① 审核生成的标书是否符合要求（按生成关键节点跳转校验，任一节点驳回即回炉）
   ② 修改调整规则（rubric 条目标注与编辑）
   ③ 质检（机器替代不了的专家判断）
   项目分类、招标文件识别这类确定性工作全部走规则，不设人工队列。
3. **两层 rubric**：`template`（官方示范文本/通用审查项）+ `delta`（每个项目从需求文档解析出的专用项）。
   评分永远**逐条**，不跨 rubric 合总分；指标只在同版本 case_set 上比较。
4. **噪声环境评测取证**：把被测 agent 放进含噪声（旧版文件、无关文件）的文件环境里自行取证审查，
   `has_evidence` 标记哪些文件含注入偏差的证据，用于测取证召回。
5. **状态机治理**：GT 校验 `auto → needs_review → confirmed|rejected`；标注全部可撤销回退，
   判定分"暂存"（draft）与"提交"两态，runs 永不覆盖。

## 专业词表

| 词 | 含义 |
|---|---|
| **tender / TDR** | 招标项目（爬虫抓取的公告+附件），平台一切实体的根 |
| **rubric / RBC** | 审查规则集。模板 rubric 可绑多个项目；项目 rubric 从需求文档解析生成 |
| **rubric_item** | 单条审查/打分项，分 `template`/`delta` 两层，类别：qualification 资质 / compliance 符合性 / rejection 废标条款 / score 打分项 |
| **case / CASE** | 一份构造的投标标书案例，属于某 tender 的某变体（如 A01/A02） |
| **injection / INJ** | 注入的偏差，自带 GT。构造方式 `P` 程序化 / `G` 生成式 / `R` 真实案例 |
| **err_taxonomy / ERR** | 错误类型法典：`QUA` 资质 / `FMT` 格式 / `SUB` 实质响应 / `PRC` 报价 / `DOC` 文档，code 只增不改 |
| **生成节点 N1-N4** | 标书生成的关键审核点：N1 输入解析 → N2 基线合规 → N3 偏差注入 → N4 成稿质量 |
| **专家四区** | 机器替代不了的判断：law 法规引用真实性 / scheme 方案矛盾 / plaus 虚构合理带 / inj 注入可信度 |
| **review_check** | 一条人工校验项（节点审核或专家校验），可暂存/提交/撤销 |
| **env_file** | 环境文件：agent 取证评测的噪声环境，角色 tender/bid/cert/credit/clarify/noise_old/noise_misc |
| **GT** | ground truth。`gt_status` 状态机：auto → needs_review → confirmed / rejected |
| **检出率 / 误报率** | 评测指标：hit/miss/false_positive，争议走 adjudication（model_right/gt_right/both/neither） |
| **暂存 / 提交** | 标注两态：暂存写 draft 可反悔，提交才落 result |
| **合理带** | 虚构投标人/业绩/规模"像不像真的"的可接受区间，由专家判断（plaus 区） |

## 编号系统

所有实体统一编号，编号只增不改、不复用。

| 前缀 | 格式 | 实体 |
|---|---|---|
| `TDR` | `TDR-CCGP-{YYYY}-{NNNNN}` | tender 招标项目（爬虫按年递增分配） |
| `RBC` | `RBC-{tdr_id}-v{n}` / `RBC-TPL-{NNN}` | rubric（项目版 / 模板版） |
| `CASE` | `CASE-{tdr_id}-{variant}` | bid_case 标书案例 |
| `INJ` | `INJ-{case_id}-{err_code}-{seq}` | injection 注入偏差 |
| `ERR` | `ERR-{类目}-{NNN}` | err_taxonomy 错误类型 |
| `RUN` | `RUN-{date}-{model}-{caseset}` | run 评测批次 |

状态机：`injection.gt_status` auto→needs_review→confirmed|rejected；
`bid_case.status` baseline→injected→evaluable|retired；
`review_check.result` NULL→pass|fail（专家区存 verdict 文案）；
`finding.verdict` hit|miss|false_positive，争议走 adj_status。

## 平台结构

- **项目总览** `/tenders` — 标注入口：类别卡（工程/货物/服务，规则自动分类）→ 项目 → 三类标注任务（节点+环境 / 专家校验 / 规则标注），实时待审数
- **标注视图** `/case/{id}` — 生成节点 N1-N4 审核卡 + 环境文件（含证据绿/噪声红/普通灰，PDF 阅读器按页反馈）
- **专家校验** `/case/{id}/expert` — 四区判定：点选高亮 → 上一条/暂存/提交/下一条
- **规则标注** `/rubrics/{id}/annotate` — rubric 条目同款标注：保留/改写（文本直接写回）/删除
- **规则编辑** `/rubrics` — rubric 库、条目编辑、模板绑定项目
- 辅助队列：GT 校验 `/queue/gt`、裁决 `/queue/adjudication`、附件校准 `/queue/attachments`

## 目录

- `scraper/ccgp.py` — 中国政府采购网爬虫（频道列表→详情→附件），产物 `data/raw/{tdr_id}/`
- `platform/db.py` — SQLite schema 迁移（V1-V8，`data/platform.db`）
- `platform/app.py` — FastAPI 人工工作台（单文件，无构建步骤）
- `项目讨论纪要.md` — 设计文档（持续更新）
- `agent交互记录.md` — 与 agent 协作的完整记录（数据构造→质检全流程 + 关键决策点）
- `data/` — 爬取的 48 个真实招标项目 + 平台库（含种子演示数据，开箱即用）
