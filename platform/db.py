"""平台数据库 schema v1
在爬虫已有的 tender/attachment 之上扩展:
rubric / rubric_item / case / injection / run / finding
GT 校验状态机落在 injection.gt_status: auto -> needs_review -> confirmed|rejected
"""
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "platform.db")

SCHEMA_V1 = """
ALTER TABLE attachment ADD COLUMN is_tender_doc INTEGER;  -- 1是 0否 NULL未审
"""

SCHEMA_V2 = """
ALTER TABLE tender ADD COLUMN category TEXT;          -- 工程/货物/服务
ALTER TABLE tender ADD COLUMN pinmu TEXT;             -- 财政部品目编码(后续LLM分类)
ALTER TABLE tender ADD COLUMN template_rubric_id TEXT; -- 绑定的模板rubric
ALTER TABLE rubric ADD COLUMN is_template INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS rubric_binding (           -- 模板rubric <-> 多项目绑定
    rubric_id TEXT NOT NULL,
    tdr_id TEXT NOT NULL,
    bound_by TEXT DEFAULT 'human',
    bound_at TEXT,
    UNIQUE(rubric_id, tdr_id)
);
"""

SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS review_check (             -- 生成审核: 按节点的校验项
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    node TEXT NOT NULL,                  -- N1输入解析/N2基线合规/N3偏差注入/N4成稿质量/EXP专家校验
    item TEXT NOT NULL,                  -- 校验项描述
    artifact TEXT,                       -- 展示给审核人的证据/文件片段
    result TEXT,                         -- NULL待审 / pass|fail / 专家区存verdict key
    note TEXT,
    reviewer TEXT,
    reviewed_at TEXT,
    UNIQUE(case_id, node, item)
);
"""

SCHEMA_V4 = """
ALTER TABLE review_check ADD COLUMN expert_area TEXT;  -- law法规/scheme矛盾/plaus合理带/inj注入可信度
"""

SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS env_file (                 -- 环境文件: agent 取证评测的噪声环境
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    role TEXT NOT NULL,                  -- tender招标/bid投标/cert证明/credit信用/clarify澄清/noise_old旧版/noise_misc无关
    path TEXT,
    is_noise INTEGER NOT NULL DEFAULT 0,
    has_evidence INTEGER NOT NULL DEFAULT 0,  -- 是否含注入偏差的证据(测agent取证召回)
    fb_type TEXT,                        -- 反馈: 缺失/内容错误/噪声不合理/版本不对/扫描件不真实/其他
    fb_note TEXT,
    fb_by TEXT,
    fb_at TEXT
);
"""

SCHEMA_V6 = """
ALTER TABLE env_file ADD COLUMN what_is_it TEXT;   -- 该文件是什么/用来干嘛(抄human_schema env.files)
ALTER TABLE env_file ADD COLUMN fb_page INTEGER;   -- 反馈定位页码(PDF)
ALTER TABLE env_file ADD COLUMN is_scan INTEGER NOT NULL DEFAULT 0;  -- 是否扫描件
"""

SCHEMA_V7 = """
ALTER TABLE review_check ADD COLUMN draft TEXT;    -- 专家区暂存的verdict(未提交)
"""

SCHEMA_V8 = """
ALTER TABLE rubric_item ADD COLUMN review_result TEXT;  -- NULL待审 / 保留|改写|删除
ALTER TABLE rubric_item ADD COLUMN draft TEXT;          -- 暂存的verdict(未提交)
ALTER TABLE rubric_item ADD COLUMN note TEXT;
"""

SCHEMA_V1_REST = """
CREATE TABLE IF NOT EXISTS rubric (
    rubric_id TEXT PRIMARY KEY,          -- RBC-{tdr_id}-v{n}
    tdr_id TEXT NOT NULL REFERENCES tender(tdr_id),
    version INTEGER NOT NULL,
    schema_ver TEXT NOT NULL DEFAULT 'v1-18items',
    source TEXT NOT NULL,                -- template / llm / human
    status TEXT NOT NULL DEFAULT 'extracted',  -- extracted/reviewed/approved
    content_json TEXT,                   -- 18解析项结构化结果
    confidence REAL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS rubric_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rubric_id TEXT NOT NULL REFERENCES rubric(rubric_id),
    layer TEXT NOT NULL,                 -- template / delta
    category TEXT,                       -- qualification/compliance/rejection/score...
    item_no TEXT,
    requirement TEXT NOT NULL,           -- 审查要求原文
    check_hint TEXT                      -- 判定提示
);

CREATE TABLE IF NOT EXISTS bid_case (
    case_id TEXT PRIMARY KEY,            -- CASE-{tdr_id}-{variant}
    tdr_id TEXT NOT NULL,
    rubric_id TEXT NOT NULL,
    variant TEXT NOT NULL,
    baseline_path TEXT,
    injected_path TEXT,
    status TEXT NOT NULL DEFAULT 'baseline',  -- baseline/injected/evaluable/retired
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS injection (
    inj_id TEXT PRIMARY KEY,             -- INJ-{case_id}-{err_code}-{seq}
    case_id TEXT NOT NULL REFERENCES bid_case(case_id),
    err_code TEXT NOT NULL,              -- ERR-XXX-NNN
    method TEXT NOT NULL,                -- P程序化/G生成式/R真实案例
    locator TEXT,                        -- 注入位置(章节/表格行)
    before_text TEXT,
    after_text TEXT,
    expected_finding TEXT NOT NULL,      -- 期望模型检出的结论
    gt_status TEXT NOT NULL DEFAULT 'auto',   -- auto/needs_review/confirmed/rejected
    human_level TEXT NOT NULL DEFAULT 'L0',   -- L0~L3
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_duration_s REAL,
    review_note TEXT
);

CREATE TABLE IF NOT EXISTS run (
    run_id TEXT PRIMARY KEY,             -- RUN-{date}-{model}-{caseset}
    case_set TEXT NOT NULL,              -- case_set 版本, 指标只在同版本上比
    model TEXT NOT NULL,
    config_json TEXT,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS finding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES run(run_id),
    case_id TEXT NOT NULL,
    inj_id TEXT,                         -- NULL=模型多报的(误报候选)
    title TEXT,
    evidence TEXT,
    verdict TEXT,                        -- hit/miss/false_positive (自动对GT)
    adj_status TEXT NOT NULL DEFAULT 'none',  -- none/pending/confirmed/overturned
    adj_result TEXT,                     -- model_right/gt_right/both/neither
    adj_by TEXT,
    adj_at TEXT
);
"""

# taxonomy 版本表: code 只增不改
TAXONOMY = """
CREATE TABLE IF NOT EXISTS err_taxonomy (
    err_code TEXT PRIMARY KEY,           -- ERR-QUA-001
    category TEXT NOT NULL,              -- QUA/FMT/SUB/PRC/DOC
    name TEXT NOT NULL,
    description TEXT,
    method TEXT NOT NULL DEFAULT 'P',    -- 默认构造方式 P/G/R
    human_level TEXT NOT NULL DEFAULT 'L1',
    active INTEGER NOT NULL DEFAULT 1,   -- 0=停用(不删)
    created_at TEXT
);
"""


def _has_col(conn, table, col):
    return col in [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _run(conn, script):
    for raw in script.split(";"):
        lines = [l for l in raw.splitlines() if not l.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if not stmt:
            continue
        if stmt.startswith("ALTER TABLE"):
            parts = stmt.split()
            table, col = parts[2], parts[5]
            if _has_col(conn, table, col):
                continue
        conn.execute(stmt)


def migrate():
    conn = sqlite3.connect(DB_PATH)
    _run(conn, SCHEMA_V1)
    _run(conn, SCHEMA_V1_REST)
    _run(conn, SCHEMA_V2)
    _run(conn, SCHEMA_V3)
    _run(conn, SCHEMA_V4)
    _run(conn, SCHEMA_V5)
    _run(conn, SCHEMA_V6)
    _run(conn, SCHEMA_V7)
    _run(conn, SCHEMA_V8)
    conn.executescript(TAXONOMY)
    conn.commit()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    conn.close()
    return tables


if __name__ == "__main__":
    print("tables:", migrate())
