"""FastAPI 人工工作台
三个人工队列:
  /queue/attachments  附件是否真招标文件 (爬虫产物过滤)
  /queue/gt           injection GT 校验 (成立/不成立/歧义, 计时)
  /queue/adjudication finding 裁决 (模型对/GT对/都对/都错)
运行: python platform/app.py  ->  http://127.0.0.1:8321
"""
import datetime as dt
import html
import os
import sqlite3

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "platform.db")

app = FastAPI(title="标书审查 Benchmark 工作台")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def esc(s):
    return html.escape(str(s or ""))


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title><style>
html{{scroll-behavior:smooth}}
body{{background:#fafafa;color:#333;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.7;font-size:14px;max-width:960px;margin:0 auto;padding:20px 24px 60px}}
nav{{border-bottom:1px solid #ececea;padding-bottom:10px;margin-bottom:18px}}
nav a{{margin-right:20px;color:#555;text-decoration:none;font-size:13px}}
nav a:hover{{color:#2e7d32}}
.card{{background:#fff;border:1px solid #ececea;border-radius:8px;padding:16px;margin:12px 0}}
.meta{{color:#8a8a85;font-size:12px}}
pre{{background:#f5f6f7;padding:12px;border-radius:6px;white-space:pre-wrap;font-size:13px}}
.btn{{display:inline-block;padding:6px 14px;margin:4px 6px 0 0;border:none;border-radius:6px;
font-size:13px;cursor:pointer;text-decoration:none}}
.y{{background:#2e7d32;color:#fff}} .n{{background:#d83931;color:#fff}}
.s{{background:#efefec;color:#555;border:1px solid #e2e2de}} .q{{background:#b76e00;color:#fff}}
kbd{{background:#f5f5f3;border:1px solid #ddd;border-radius:4px;padding:1px 6px;font-size:11px}}
.diff{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.diff>div{{border-radius:6px;padding:12px;font-size:13px;white-space:pre-wrap}}
.before{{background:#fff1f0;border:1px solid #ffccc7}} .after{{background:#f6ffed;border:1px solid #b7eb8f}}
.empty{{color:#57a05c;font-size:16px;padding:40px;text-align:center}}
table{{border-collapse:collapse;width:100%;font-size:13px;background:#fff}}
th,td{{border:1px solid #ececea;padding:6px 10px;text-align:left;vertical-align:top}}
th{{background:#f7f7f5;color:#555;font-weight:600}}
textarea{{width:100%;min-height:60px;font-size:13px}}
select,input[type=text],input[type=number]{{font-size:13px;padding:4px}}
.badge{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;background:#efefec;color:#8a8a84;text-decoration:none}}
.badge.g{{background:#eef7ee;color:#2e7d32;border:1px solid #cfe4cf}}
.badge.r{{background:#fde8e8;color:#c0392b;border:1px solid #f5c6c6}}
.guess{{color:#b76e00;font-size:12px}}
code,.tid{{font-family:Consolas,'SF Mono',monospace;font-size:12px;color:#8a8a85}}
</style></head><body>
<nav><a href="/tenders"><b>项目总览</b></a><a href="/case"><b>标注视图</b></a><a href="/rubrics"><b>规则编辑</b></a></nav>
{body}
<script>
document.addEventListener('keydown',e=>{{
const m={{'y':'btn-y','n':'btn-n','s':'btn-s','q':'btn-q'}};
const id=m[e.key]; if(id){{const b=document.getElementById(id); if(b)b.click();}}
}});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return RedirectResponse("/tenders", status_code=303)


@app.get("/case", response_class=HTMLResponse)
def case_entry():
    seed_rich()
    c = db()
    row = c.execute("""SELECT b.case_id, COUNT(r.id) n FROM bid_case b
                       LEFT JOIN review_check r ON r.case_id=b.case_id
                       GROUP BY b.case_id ORDER BY n DESC, b.case_id LIMIT 1""").fetchone()
    if not row:
        return RedirectResponse("/tenders", status_code=303)
    return RedirectResponse(f"/case/{row['case_id']}", status_code=303)


# ---------- 附件筛选 ----------
@app.get("/queue/attachments", response_class=HTMLResponse)
def attachment_queue():
    c = db()
    row = c.execute("""
        SELECT a.*, t.title ttitle, t.region, t.tdr_id
        FROM attachment a JOIN tender t ON a.tdr_id=t.tdr_id
        WHERE a.is_tender_doc IS NULL ORDER BY a.id LIMIT 1""").fetchone()
    if not row:
        return PAGE.format(title="附件筛选", body='<div class="empty">附件队列已清空</div>')
    detail_path = os.path.join(ROOT, "data", "raw", row["tdr_id"], "detail.txt")
    excerpt = ""
    if os.path.exists(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            excerpt = f.read()[:1200]
    body = f"""<h2>这个附件是招标文件吗？</h2>
<div class="card meta">{esc(row['tdr_id'])} ｜ {esc(row['region'])} ｜ {esc(row['ttitle'])}</div>
<div class="card">附件：<b>{esc(row['filename'])}</b>（{row['size']//1024} KB）
<a class="btn s" href="/file/{row['id']}" target="_blank">打开文件</a></div>
<div class="card"><div class="meta">公告正文摘录：</div><pre>{esc(excerpt)}</pre></div>
<form method="post" action="/queue/attachments/{row['id']}">
<button class="btn y" id="btn-y" name="v" value="1">是 <kbd>y</kbd></button>
<button class="btn n" id="btn-n" name="v" value="0">不是 <kbd>n</kbd></button>
<button class="btn s" id="btn-s" name="v" value="skip">跳过 <kbd>s</kbd></button>
</form>"""
    return PAGE.format(title="附件筛选", body=body)


@app.post("/queue/attachments/{att_id}")
def attachment_decide(att_id: int, v: str = Form(...)):
    if v != "skip":
        c = db()
        c.execute("UPDATE attachment SET is_tender_doc=? WHERE id=?", (int(v), att_id))
        c.commit()
    return RedirectResponse("/queue/attachments", status_code=303)


@app.get("/file/{att_id}")
def attachment_file(att_id: int):
    c = db()
    row = c.execute("SELECT path FROM attachment WHERE id=?", (att_id,)).fetchone()
    if row and os.path.exists(row["path"]):
        return FileResponse(row["path"])
    return HTMLResponse("文件不存在", status_code=404)


# ---------- GT 校验 ----------
GT_FORM = """<form method="post" action="/queue/gt/{inj_id}">
<input type="hidden" name="dur" id="dur">
<button class="btn y" id="btn-y" name="v" value="confirmed">偏差成立 <kbd>y</kbd></button>
<button class="btn n" id="btn-n" name="v" value="rejected">不成立 <kbd>n</kbd></button>
<button class="btn q" id="btn-q" name="v" value="ambiguous">歧义/待改写 <kbd>q</kbd></button>
<button class="btn s" id="btn-s" name="v" value="skip">跳过 <kbd>s</kbd></button><br><br>
<input name="note" placeholder="备注(不成立/歧义时填原因)" size="60">
</form>
<script>const t0=Date.now();
document.querySelector('form').addEventListener('submit',()=>{{
document.getElementById('dur').value=(Date.now()-t0)/1000;}});</script>"""


@app.get("/queue/gt", response_class=HTMLResponse)
def gt_queue():
    c = db()
    row = c.execute("""
        SELECT i.*, b.tdr_id FROM injection i JOIN bid_case b ON i.case_id=b.case_id
        WHERE i.gt_status='needs_review' ORDER BY i.inj_id LIMIT 1""").fetchone()
    if not row:
        return PAGE.format(title="GT校验", body='<div class="empty">GT 队列已清空</div>')
    body = f"""<h2>GT 校验：这个偏差真实成立吗？</h2>
<div class="card meta">{esc(row['inj_id'])} ｜ {esc(row['err_code'])} ｜
构造方式 {esc(row['method'])} / {esc(row['human_level'])} ｜ 位置 {esc(row['locator'])}</div>
<div class="diff"><div class="before"><b>注入前</b><br>{esc(row['before_text'])}</div>
<div class="after"><b>注入后</b><br>{esc(row['after_text'])}</div></div>
<div class="card"><b>期望检出：</b>{esc(row['expected_finding'])}</div>
""" + GT_FORM.format(inj_id=esc(row["inj_id"]))
    return PAGE.format(title="GT校验", body=body)


@app.post("/queue/gt/{inj_id}")
def gt_decide(inj_id: str, v: str = Form(...), dur: float = Form(0), note: str = Form("")):
    if v != "skip":
        status = {"confirmed": "confirmed", "rejected": "rejected",
                  "ambiguous": "needs_review"}.get(v, "needs_review")
        c = db()
        c.execute("""UPDATE injection SET gt_status=?, reviewed_by='human',
                     reviewed_at=?, review_duration_s=?, review_note=? WHERE inj_id=?""",
                  (status, dt.datetime.now().isoformat(timespec="seconds"), dur, note, inj_id))
        c.commit()
    return RedirectResponse("/queue/gt", status_code=303)


# ---------- 裁决台 ----------
@app.get("/queue/adjudication", response_class=HTMLResponse)
def adj_queue():
    c = db()
    row = c.execute("""
        SELECT f.*, i.err_code, i.expected_finding FROM finding f
        LEFT JOIN injection i ON f.inj_id=i.inj_id
        WHERE f.adj_status='pending' ORDER BY f.id LIMIT 1""").fetchone()
    if not row:
        return PAGE.format(title="裁决台", body='<div class="empty">裁决队列已清空</div>')
    gt = esc(row["expected_finding"]) if row["expected_finding"] else "（误报候选：GT 中无此条）"
    body = f"""<h2>裁决：模型 finding vs GT</h2>
<div class="card meta">finding #{row['id']} ｜ run {esc(row['run_id'])} ｜
{esc(row['case_id'])} ｜ {esc(row['err_code'])} ｜ 自动判定 {esc(row['verdict'])}</div>
<div class="diff"><div class="before"><b>模型检出</b><br>{esc(row['title'])}<br><br>
<span class="meta">证据：{esc(row['evidence'])}</span></div>
<div class="after"><b>GT 期望</b><br>{gt}</div></div>
<form method="post" action="/queue/adjudication/{row['id']}">
<button class="btn y" id="btn-y" name="v" value="model_right">模型对 <kbd>y</kbd></button>
<button class="btn n" id="btn-n" name="v" value="gt_right">GT 对 <kbd>n</kbd></button>
<button class="btn q" id="btn-q" name="v" value="both">都对/都错(备注) <kbd>q</kbd></button>
<button class="btn s" id="btn-s" name="v" value="skip">跳过 <kbd>s</kbd></button>
</form>"""
    return PAGE.format(title="裁决台", body=body)


@app.post("/queue/adjudication/{fid}")
def adj_decide(fid: int, v: str = Form(...)):
    if v != "skip":
        c = db()
        c.execute("""UPDATE finding SET adj_status='confirmed', adj_result=?,
                     adj_by='human', adj_at=? WHERE id=?""",
                  (v, dt.datetime.now().isoformat(timespec="seconds"), fid))
        c.commit()
    return RedirectResponse("/queue/adjudication", status_code=303)


# ---------- 项目总览(分类走规则, 不用人工) ----------
CAT_KEYWORDS = [
    ("工程", ["工程", "施工", "修缮", "改造", "养护", "装修", "市政", "绿化", "道路", "建设"]),
    ("服务", ["服务", "物业", "保洁", "运维", "咨询", "检测", "体检", "租赁", "保安", "餐饮", "培训", "评估", "测绘"]),
    ("货物", ["设备", "货物", "物资", "器材", "车辆", "家具", "耗材", "食品", "字典", "印刷", "办公用品"]),
]


def classify_tender(title):
    """只用标题分类: 剥掉代理机构前缀(「XX公司关于...」)防公司名里的工程/咨询污染。
    返回 (类别, 命中关键词), 无命中返回 ("", "")"""
    t = (title or "").split("关于", 1)[-1]
    best, best_score, best_kw = "", 0, ""
    for cat, kws in CAT_KEYWORDS:
        for k in kws:
            n = t.count(k)
            if k == "图书":
                n -= t.count("图书馆")
            if n > 0 and n > best_score:
                best, best_score, best_kw = cat, n, k
    return best, best_kw


@app.get("/tenders", response_class=HTMLResponse)
def tenders(cat: str = ""):
    c = db()
    rows = c.execute("""
        SELECT t.*, (SELECT COUNT(*) FROM attachment a WHERE a.tdr_id=t.tdr_id) n_att
        FROM tender t ORDER BY t.tdr_id DESC""").fetchall()
    # 规则重算(确定性, 每次都纠正与规则不一致的存量)
    dirty = False
    for r in rows:
        cat_, _ = classify_tender(r["title"])
        if cat_ and cat_ != r["category"]:
            c.execute("UPDATE tender SET category=? WHERE tdr_id=?", (cat_, r["tdr_id"]))
            dirty = True
    if dirty:
        c.commit()
        rows = c.execute("""
            SELECT t.*, (SELECT COUNT(*) FROM attachment a WHERE a.tdr_id=t.tdr_id) n_att
            FROM tender t ORDER BY t.tdr_id DESC""").fetchall()

    # 每个 case 的待审数(节点+环境 / 专家)
    case_pend = {}
    for r in c.execute("""
        SELECT b.case_id, b.tdr_id, b.variant, b.rubric_id,
        SUM(CASE WHEN r.node != 'EXP' AND r.result IS NULL THEN 1 ELSE 0 END) gen_p,
        SUM(CASE WHEN r.node = 'EXP' AND r.result IS NULL THEN 1 ELSE 0 END) exp_p
        FROM bid_case b LEFT JOIN review_check r ON r.case_id=b.case_id
        GROUP BY b.case_id""").fetchall():
        rbc_p = c.execute("SELECT COUNT(*) n FROM rubric_item WHERE rubric_id=? AND review_result IS NULL",
                          (r["rubric_id"],)).fetchone()["n"]
        case_pend.setdefault(r["tdr_id"], []).append(
            (r["case_id"], r["variant"], r["gen_p"] or 0, r["exp_p"] or 0, r["rubric_id"], rbc_p))

    counts = {}
    for r in rows:
        k = r["category"] or "未分类"
        counts[k] = counts.get(k, 0) + 1
    # 类别入口卡
    cat_cards = ""
    for k in ["工程", "货物", "服务", "未分类"]:
        if k not in counts:
            continue
        n_task = sum(len(case_pend.get(r["tdr_id"], [])) for r in rows if (r["category"] or "未分类") == k)
        cat_cards += f"""<a href="/tenders?cat={esc(k)}" style="text-decoration:none;color:inherit">
<div class="card" style="display:inline-block;width:180px;text-align:center">
<b style="font-size:16px">{esc(k)}</b><br>
<span class="meta">{counts[k]} 项目 ｜ {n_task} 个标注任务</span></div></a>"""

    trs = ""
    for r in rows:
        if cat and (r["category"] or "未分类") != cat:
            continue
        entries = ""
        for cid, var, gp, ep, rid, rp in case_pend.get(r["tdr_id"], []):
            g = f'<span class="badge r">待审{gp}</span>' if gp else '<span class="badge g">✓</span>'
            e = f'<span class="badge r">待审{ep}</span>' if ep else '<span class="badge g">✓</span>'
            b = f'<span class="badge r">待审{rp}</span>' if rp else '<span class="badge g">✓</span>'
            entries += f"""<div style="margin-top:4px"><span class="meta">{esc(var)}</span>
<a class="btn s" href="/case/{esc(cid)}">节点+环境 {g}</a>
<a class="btn s" href="/case/{esc(cid)}/expert">专家校验 {e}</a>
<a class="btn s" href="/rubrics/{esc(rid)}/annotate">规则标注 {b}</a></div>"""
        if not entries:
            entries = '<div class="meta" style="margin-top:4px">无标注任务（待生成 case）</div>'
        trs += f"""<div class="card"><b>{esc(r['title'])}</b>
<span class="badge g">{esc(r['category'] or '未分类')}</span><br>
<span class="meta">{esc(r['tdr_id'])} ｜ {esc(r['region'])} ｜ {esc(r['publish_date'])} ｜ 附件{r['n_att']}</span>
{entries}</div>"""
    body = f"""<h2>项目总览 · 标注入口</h2>
<div class="card meta">按类别进入标注任务。分类由关键词规则自动判定（只取标题，剥掉代理机构名），不进人工队列。</div>
<div>{cat_cards} <a href="/tenders" style="text-decoration:none;color:inherit">
<div class="card" style="display:inline-block;width:120px;text-align:center"><b>全部</b></div></a></div>
{trs or '<div class="empty">该类别暂无项目</div>'}"""
    return PAGE.format(title="项目总览", body=body)


# ---------- Rubric 规则编辑 ----------
@app.get("/rubrics", response_class=HTMLResponse)
def rubric_list():
    c = db()
    rows = c.execute("""
        SELECT r.*, (SELECT COUNT(*) FROM rubric_item i WHERE i.rubric_id=r.rubric_id) n_items,
        (SELECT COUNT(*) FROM rubric_binding b WHERE b.rubric_id=r.rubric_id) n_bound
        FROM rubric r ORDER BY r.is_template DESC, r.rubric_id""").fetchall()
    tenders_ = c.execute("SELECT tdr_id,title FROM tender ORDER BY tdr_id DESC").fetchall()
    trs = ""
    for r in rows:
        kind = '<span class="badge g">模板</span>' if r["is_template"] else f'专用:{esc(r["tdr_id"])}'
        pend = c.execute("SELECT COUNT(*) n FROM rubric_item WHERE rubric_id=? AND review_result IS NULL",
                         (r["rubric_id"],)).fetchone()["n"]
        ann = (f'<a href="/rubrics/{esc(r["rubric_id"])}/annotate">'
               f'{"<span class=\"badge r\">待审" + str(pend) + "</span>" if pend else "<span class=\"badge g\">✓</span>"}</a>')
        trs += f"""<tr><td><a href="/rubrics/{esc(r['rubric_id'])}">{esc(r['rubric_id'])}</a></td>
<td>{kind}</td><td>{esc(r['status'])}</td><td>{r['n_items']} 条</td>
<td>{r['n_bound'] if r['is_template'] else '—'}</td><td>{ann}</td></tr>"""
    topts = "".join(f'<option value="{esc(t["tdr_id"])}">{esc(t["tdr_id"])} {esc(t["title"][:25])}</option>'
                    for t in tenders_)
    body = f"""<h2>Rubric 规则库</h2>
<table><tr><th>rubric</th><th>类型</th><th>状态</th><th>条目</th><th>绑定项目数</th><th>标注</th></tr>{trs}</table>
<div class="card"><b>新建 rubric</b><form method="post" action="/rubrics/new">
<label><input type="radio" name="kind" value="template" checked> 模板（可绑多项目）</label>
<label><input type="radio" name="kind" value="dedicated"> 项目专用</label>
<select name="tdr_id">{topts}</select>
<button class="btn y">创建</button></form></div>"""
    return PAGE.format(title="Rubric规则", body=body)


@app.post("/rubrics/new")
def rubric_new(kind: str = Form(...), tdr_id: str = Form("")):
    c = db()
    if kind == "template":
        n = c.execute("SELECT COUNT(*) x FROM rubric WHERE is_template=1").fetchone()["x"] + 1
        rid = f"RBC-TPL-{n:03d}"
        c.execute("INSERT INTO rubric VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (rid, "", 1, "v1-18items", "human", "reviewed", None, None,
                   dt.datetime.now().isoformat(timespec="seconds"), 1))
    else:
        n = c.execute("SELECT COUNT(*) x FROM rubric WHERE tdr_id=?", (tdr_id,)).fetchone()["x"] + 1
        rid = f"RBC-{tdr_id}-v{n}"
        c.execute("INSERT INTO rubric VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (rid, tdr_id, n, "v1-18items", "human", "reviewed", None, None,
                   dt.datetime.now().isoformat(timespec="seconds"), 0))
    c.commit()
    return RedirectResponse(f"/rubrics/{rid}", status_code=303)


ITEM_CATS = ["qualification", "compliance", "rejection", "score", "other"]


def _item_row(i):
    cats = "".join(f'<option {"selected" if i["category"]==x else ""}>{x}</option>' for x in ITEM_CATS)
    layers = "".join(f'<option {"selected" if i["layer"]==x else ""}>{x}</option>'
                     for x in ["template", "delta"])
    return f"""<tr><td><form method="post" action="/rubrics/item/{i['id']}/save">
<select name="layer">{layers}</select></td>
<td><select name="category">{cats}</select></td>
<td><textarea name="requirement">{esc(i['requirement'])}</textarea></td>
<td><button class="btn y">存</button></form>
<form method="post" action="/rubrics/item/{i['id']}/del" onsubmit="return confirm('删除?')">
<button class="btn n">删</button></form></td></tr>"""


@app.get("/rubrics/{rubric_id}", response_class=HTMLResponse)
def rubric_detail(rubric_id: str):
    c = db()
    r = c.execute("SELECT * FROM rubric WHERE rubric_id=?", (rubric_id,)).fetchone()
    if not r:
        return HTMLResponse("rubric 不存在", status_code=404)
    items = c.execute("SELECT * FROM rubric_item WHERE rubric_id=? ORDER BY id",
                      (rubric_id,)).fetchall()
    rows = "".join(_item_row(i) for i in items)
    kind = "模板" if r["is_template"] else f"项目专用 → {esc(r['tdr_id'])}"
    bind_html = ""
    if r["is_template"]:
        bound = {b["tdr_id"] for b in c.execute(
            "SELECT tdr_id FROM rubric_binding WHERE rubric_id=?", (rubric_id,))}
        ts = c.execute("SELECT tdr_id,title,region FROM tender ORDER BY tdr_id DESC").fetchall()
        boxes = "".join(
            f'<label style="display:block"><input type="checkbox" name="tdr" value="{esc(t["tdr_id"])}" '
            f'{"checked" if t["tdr_id"] in bound else ""}> {esc(t["tdr_id"])} {esc(t["region"])} {esc(t["title"][:30])}</label>'
            for t in ts)
        bind_html = f"""<h3>绑定项目（{len(bound)}）</h3>
<form method="post" action="/rubrics/{esc(rubric_id)}/bind">
<div style="max-height:300px;overflow:auto" class="card">{boxes}</div>
<button class="btn y">保存绑定</button></form>"""
    body = f"""<h2>{esc(rubric_id)} <span class="badge">{kind}</span></h2>
<div class="card meta"><a href="/rubrics/{esc(rubric_id)}/annotate">→ 进入条目标注（保留/改写/删除）</a></div>
<h3>规则条目（{len(items)}）</h3>
<table><tr><th>层</th><th>类别</th><th>要求原文</th><th>操作</th></tr>{rows}</table>
<div class="card"><b>加条目</b><form method="post" action="/rubrics/{esc(rubric_id)}/item/new">
<select name="layer"><option>template</option><option selected>delta</option></select>
<select name="category">{"".join(f"<option>{x}</option>" for x in ITEM_CATS)}</select>
<textarea name="requirement" placeholder="审查要求原文"></textarea>
<button class="btn y">添加</button></form></div>
{bind_html}"""
    return PAGE.format(title=rubric_id, body=body)


@app.post("/rubrics/{rubric_id}/item/new")
def item_new(rubric_id: str, layer: str = Form(...), category: str = Form(...),
             requirement: str = Form(...)):
    c = db()
    c.execute("INSERT INTO rubric_item(rubric_id,layer,category,requirement) VALUES (?,?,?,?)",
              (rubric_id, layer, category, requirement))
    c.commit()
    return RedirectResponse(f"/rubrics/{rubric_id}", status_code=303)


@app.post("/rubrics/item/{item_id}/save")
def item_save(item_id: int, layer: str = Form(...), category: str = Form(...),
              requirement: str = Form(...)):
    c = db()
    c.execute("UPDATE rubric_item SET layer=?,category=?,requirement=? WHERE id=?",
              (layer, category, requirement, item_id))
    c.commit()
    ref = c.execute("SELECT rubric_id FROM rubric_item WHERE id=?", (item_id,)).fetchone()
    return RedirectResponse(f"/rubrics/{ref['rubric_id']}", status_code=303)


@app.post("/rubrics/item/{item_id}/del")
def item_del(item_id: int):
    c = db()
    ref = c.execute("SELECT rubric_id FROM rubric_item WHERE id=?", (item_id,)).fetchone()
    c.execute("DELETE FROM rubric_item WHERE id=?", (item_id,))
    c.commit()
    return RedirectResponse(f"/rubrics/{ref['rubric_id']}", status_code=303)


# ---------- 规则条目标注(解析产物的人工校验, 同专家区交互) ----------
ITEM_VERDICTS = ["保留", "改写", "删除"]


def _item_chip(i):
    r = i["review_result"]
    if r == "保留":
        return '<span class="chip g">保留</span>'
    if r == "改写":
        return '<span class="chip" style="background:#fdf3e0;color:#a8621b">改写</span>'
    if r == "删除":
        return '<span class="chip r">删除</span>'
    if i["draft"]:
        return '<span class="chip" style="background:#fdf3e0;color:#a8621b">暂存中</span>'
    return '<span class="chip">待审</span>'


@app.get("/rubrics/{rubric_id}/annotate", response_class=HTMLResponse)
def rubric_annotate(rubric_id: str):
    c = db()
    r = c.execute("SELECT * FROM rubric WHERE rubric_id=?", (rubric_id,)).fetchone()
    if not r:
        return HTMLResponse("rubric 不存在", status_code=404)
    items = c.execute("SELECT * FROM rubric_item WHERE rubric_id=? ORDER BY id", (rubric_id,)).fetchall()
    flat_ids = [i["id"] for i in items]
    pos = {iid: x for x, iid in enumerate(flat_ids)}
    groups, cards = {}, []
    for i in items:
        todo = 1 if not i["review_result"] else 0
        groups.setdefault(i["category"] or "other", []).append((f"item-{i['id']}", i["requirement"], todo))
        sel = i["review_result"] or i["draft"] or ""
        btns = " ".join(
            f'<button type="button" class="vbtn opt{" sel" if sel == v else ""}" data-v="{v}">{v}</button>'
            for v in ITEM_VERDICTS)
        x = pos[i["id"]]
        prev_a = (f'<a class="vbtn" href="#item-{flat_ids[x-1]}" style="text-decoration:none">← 上一条</a>'
                  if x > 0 else '<span class="vbtn" style="opacity:.4">← 上一条</span>')
        next_a = (f'<a class="vbtn" href="#item-{flat_ids[x+1]}" style="text-decoration:none">下一条 →</a>'
                  if x < len(flat_ids) - 1 else '<span class="vbtn" style="opacity:.4">下一条 →</span>')
        de = ""
        if i["note"]:
            de = f'<div class="de-card"><div class="de-desc">{esc(i["note"])}</div></div>'
        reset = ""
        if i["review_result"]:
            reset = (f'<form class="vrow" style="margin-top:-8px" method="post" action="/rubrics/item/{i["id"]}/reset">'
                     f'<input type="hidden" name="back" value="/rubrics/{esc(rubric_id)}/annotate#item-{i["id"]}">'
                     f'<button class="vbtn">↩ 撤销，回到待审</button></form>')
        cards.append(f"""<div class="stage-card" id="item-{i['id']}">
<div class="stage-header"><div class="stage-text"><span class="chip">{esc(i['layer'])}</span>
<span class="chip">{esc(i['category'] or 'other')}</span> {_item_chip(i)}</div></div>
<form class="expform" method="post" action="/rubrics/item/{i['id']}/annotate" style="margin:0 24px">
<input type="hidden" name="back" value="/rubrics/{esc(rubric_id)}/annotate#item-{i['id']}">
<input type="hidden" name="mode" value="submit">
<input type="hidden" name="v" value="{esc(sel)}">
<textarea class="reqtext" name="requirement">{esc(i['requirement'])}</textarea>
<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0 14px">{btns}
<input class="fnote" name="note" placeholder="备注" value="{esc(i['note'])}"></div></form>{de}
<div class="vrow" style="margin-top:-8px">{prev_a}
<button class="vbtn" data-act="draft">暂存</button>
<button class="vbtn pri" data-act="submit">提交</button>
{next_a}</div>{reset}</div>""")
    sidebar = _sb_node("规则条目", list(groups.items()))
    done = sum(1 for i in items if i["review_result"])
    main = f"""<h1>规则条目标注</h1>
<div class="sub">{esc(rubric_id)} ｜ 已审 {done}/{len(items)} ｜ <a href="/rubrics/{esc(rubric_id)}">条目编辑</a> · <a href="/rubrics">规则库</a></div>
{''.join(cards) or '<div class="node"><div class="node-title mid">暂无条目</div></div>'}"""
    return CASE_PAGE.format(title=f"{rubric_id} 标注", sb_title=rubric_id[-12:],
                            sidebar=sidebar, main=main)


@app.post("/rubrics/item/{item_id}/annotate")
def item_annotate(item_id: int, v: str = Form(""), note: str = Form(""),
                  requirement: str = Form(""), mode: str = Form("submit"),
                  back: str = Form("/rubrics")):
    c = db()
    if mode == "draft":
        c.execute("UPDATE rubric_item SET draft=?, note=? WHERE id=?", (v or None, note, item_id))
    else:
        if v == "改写" and requirement.strip():
            c.execute("UPDATE rubric_item SET requirement=? WHERE id=?", (requirement.strip(), item_id))
        c.execute("UPDATE rubric_item SET review_result=?, note=?, draft=NULL WHERE id=?",
                  (v, note, item_id))
    c.commit()
    return RedirectResponse(back, status_code=303)


@app.post("/rubrics/item/{item_id}/reset")
def item_annotate_reset(item_id: int, back: str = Form("/rubrics")):
    c = db()
    c.execute("UPDATE rubric_item SET review_result=NULL, note=NULL, draft=NULL WHERE id=?", (item_id,))
    c.commit()
    return RedirectResponse(back, status_code=303)


@app.post("/rubrics/{rubric_id}/bind")
def rubric_bind(rubric_id: str, tdr: list[str] = Form(default=[])):
    c = db()
    c.execute("DELETE FROM rubric_binding WHERE rubric_id=?", (rubric_id,))
    for t in tdr:
        c.execute("INSERT OR IGNORE INTO rubric_binding VALUES (?,?,?,?)",
                  (rubric_id, t, "human", dt.datetime.now().isoformat(timespec="seconds")))
    c.commit()
    return RedirectResponse(f"/rubrics/{rubric_id}", status_code=303)


# ---------- 主审配置 ----------
@app.get("/cases", response_class=HTMLResponse)
def case_list():
    c = db()
    rows = c.execute("""
        SELECT b.*, COUNT(i.inj_id) n_inj,
        SUM(CASE WHEN i.gt_status='needs_review' THEN 1 ELSE 0 END) n_review,
        SUM(CASE WHEN i.gt_status='confirmed' THEN 1 ELSE 0 END) n_confirmed
        FROM bid_case b LEFT JOIN injection i ON b.case_id=i.case_id
        GROUP BY b.case_id ORDER BY b.case_id DESC""").fetchall()
    trs = "".join(f"""<tr><td><a href="/cases/{esc(r['case_id'])}">{esc(r['case_id'])}</a></td>
<td>{esc(r['status'])}</td><td>{r['n_inj']}</td>
<td><span class="badge r">{r['n_review'] or 0} 待审</span>
<span class="badge g">{r['n_confirmed'] or 0} 已确认</span></td></tr>""" for r in rows)
    body = f"""<h2>主审配置（生成的标书，人工主审哪些值）</h2>
<div class="card meta">规则：L0 不进人工队列；L1 抽检；L2/L3 全量进 GT 校验队列。此处按注入项逐个调整。</div>
<table><tr><th>case</th><th>状态</th><th>注入项</th><th>主审</th></tr>{trs}</table>"""
    return PAGE.format(title="主审配置", body=body)


@app.get("/cases/{case_id}", response_class=HTMLResponse)
def case_detail(case_id: str):
    c = db()
    case = c.execute("SELECT * FROM bid_case WHERE case_id=?", (case_id,)).fetchone()
    if not case:
        return HTMLResponse("case 不存在", status_code=404)
    injs = c.execute("SELECT * FROM injection WHERE case_id=? ORDER BY inj_id", (case_id,)).fetchall()
    trs = ""
    for i in injs:
        lvls = "".join(f'<option {"selected" if i["human_level"]==x else ""}>{x}</option>'
                       for x in ["L0", "L1", "L2", "L3"])
        badge = {"auto": "badge g", "confirmed": "badge g",
                 "needs_review": "badge r", "rejected": "badge r"}.get(i["gt_status"], "badge")
        trs += f"""<tr><td class="meta">{esc(i['err_code'])}<br>{esc(i['method'])} ｜ {esc(i['locator'])}</td>
<td>{esc(i['expected_finding'])}</td>
<td><form method="post" action="/cases/injection/{esc(i['inj_id'])}/level">
<select name="level">{lvls}</select><button class="btn s">存</button></form></td>
<td><span class="{badge}">{esc(i['gt_status'])}</span></td></tr>"""
    body = f"""<h2>{esc(case_id)}</h2>
<div class="card meta">rubric {esc(case['rubric_id'])} ｜ 状态 {esc(case['status'])}<br>
基线关键值（报价/工期/有效期等）自动抽取器未上线，当前主审对象=注入项。</div>
<table><tr><th>错误/位置</th><th>期望检出</th><th>人力等级</th><th>GT状态</th></tr>{trs}</table>"""
    return PAGE.format(title=case_id, body=body)


@app.post("/cases/injection/{inj_id}/level")
def injection_set_level(inj_id: str, level: str = Form(...)):
    c = db()
    gt = "auto" if level == "L0" else "needs_review"
    c.execute("""UPDATE injection SET human_level=?, gt_status=CASE
                 WHEN gt_status='confirmed' THEN gt_status ELSE ? END
                 WHERE inj_id=?""", (level, gt, inj_id))
    c.commit()
    ref = c.execute("SELECT case_id FROM injection WHERE inj_id=?", (inj_id,)).fetchone()
    return RedirectResponse(f"/cases/{ref['case_id']}", status_code=303)


# ---------- 生成审核(按生成过程关键节点) ----------
NODES = [("N1", "输入解析"), ("N2", "基线合规"), ("N3", "偏差注入"), ("N4", "成稿质量")]


def node_status(c, case_id, node):
    r = c.execute("""SELECT SUM(CASE WHEN result='fail' THEN 1 ELSE 0 END) f,
                     SUM(CASE WHEN result='pass' THEN 1 ELSE 0 END) p, COUNT(*) n
                     FROM review_check WHERE case_id=? AND node=?""",
                  (case_id, node)).fetchone()
    if not r["n"]:
        return "none"
    if r["f"]:
        return "fail"
    if r["p"] == r["n"]:
        return "pass"
    return "pending"


STATUS_BADGE = {"pass": '<span class="badge g">通过</span>',
                "fail": '<span class="badge r">驳回</span>',
                "pending": '<span class="badge">待审</span>',
                "none": '<span class="badge">无数据</span>'}


def seed_demo():
    c = db()
    if c.execute("SELECT COUNT(*) n FROM review_check").fetchone()["n"]:
        return
    case = "CASE-TDR-CCGP-2026-00002-A01"
    demo = [
        ("N1", "资格要求抽取完整", "抽取到资格项 4 条：\n1. 政府采购法第22条（营业执照/承诺函）\n2. 信用中国无失信记录\n3. 不接受联合体\n4. 特定资格：无\n—— 原文位置：detail.txt 二、申请人的资格要求 第36行起"),
        ("N1", "★条款与实质性条款无遗漏", "本标未检测到 ★ 标记条款；\n已将'不接受联合体投标''合同履行期限3年'归入实质性响应项"),
        ("N2", "报价 ≤ 预算", "生成报价 ¥5,200,000.00\n预算金额 ¥5,350,000.00（detail.txt 第12行）\n→ 未超预算 ✓"),
        ("N2", "合同履行期限满足", "要求：3年（合同一年一签）\n生成承诺：服务期3年，按年度续签 ✓"),
        ("N2", "投标有效期 ≥ 要求", "要求：90 日历日\n生成：投标有效期 90 日历日 ✓"),
        ("N2", "资格材料齐全且真实有效", "营业执照复印件 ✓\n资格承诺函 ✓\n信用中国查询截图：仅占位符【此处插入信用截图】⚠️"),
        ("N4", "章节完整性", "目录 9 章 / 正文 9 章，齐全；\n资格证明文件、商务部分、技术部分均在"),
        ("N4", "全文一致性", "报价出现 3 处，金额一致 ✓\n项目名称出现 12 处，一致 ✓"),
        ("N4", "无占位符/模板残留", "检测到占位符 1 处：\n【此处插入信用截图】（第七章 资格证明文件）⚠️"),
    ]
    for node, item, artifact in demo:
        c.execute("INSERT OR IGNORE INTO review_check(case_id,node,item,artifact) VALUES (?,?,?,?)",
                  (case, node, item, artifact))
    c.commit()


@app.get("/review", response_class=HTMLResponse)
def review_list():
    seed_demo()
    c = db()
    cases = c.execute("SELECT * FROM bid_case ORDER BY case_id DESC").fetchall()
    trs = ""
    for case in cases:
        lights = " ".join(
            f'<a href="/review/{esc(case["case_id"])}/{n}">{n} {STATUS_BADGE[node_status(c, case["case_id"], n)]}</a>'
            for n, _ in NODES)
        trs += f"""<tr><td><a href="/review/{esc(case['case_id'])}">{esc(case['case_id'])}</a></td>
<td>{esc(case['status'])}</td><td>{lights}</td></tr>"""
    body = f"""<h2>生成审核：生成的标书是否符合要求</h2>
<div class="card meta">审核按生成过程关键节点组织：N1 输入解析 → N2 基线合规 → N3 偏差注入 → N4 成稿质量。
点节点灯跳转校验。任一节点驳回 → 回炉，四节点全通过才能进题库。</div>
<table><tr><th>case</th><th>状态</th><th>节点</th></tr>{trs}</table>"""
    return PAGE.format(title="生成审核", body=body)


@app.get("/review/{case_id}", response_class=HTMLResponse)
def review_case(case_id: str):
    c = db()
    case = c.execute("SELECT * FROM bid_case WHERE case_id=?", (case_id,)).fetchone()
    if not case:
        return HTMLResponse("case 不存在", status_code=404)
    cards = ""
    for n, name in NODES:
        st = node_status(c, case_id, n)
        cards += f"""<a href="/review/{esc(case_id)}/{n}" style="text-decoration:none;color:inherit">
<div class="card" style="display:inline-block;width:200px;text-align:center">
<b>{n} {name}</b><br>{STATUS_BADGE[st]}</div></a>"""
    body = f"""<h2>{esc(case_id)}</h2>
<div class="card meta">tender {esc(case['tdr_id'])} ｜ rubric {esc(case['rubric_id'])} ｜ 状态 {esc(case['status'])}</div>
{cards}"""
    return PAGE.format(title=case_id, body=body)


@app.get("/review/{case_id}/{node}", response_class=HTMLResponse)
def review_node(case_id: str, node: str):
    c = db()
    name = dict(NODES).get(node)
    if not name:
        return HTMLResponse("节点不存在", status_code=404)
    strip = " → ".join(
        f'<b><a href="/review/{esc(case_id)}/{n}">{n}</a></b>' if n == node
        else f'<a href="/review/{esc(case_id)}/{n}">{n}</a>' for n, _ in NODES)
    checks = c.execute("SELECT * FROM review_check WHERE case_id=? AND node=? ORDER BY id",
                       (case_id, node)).fetchall()
    if node == "N3":
        injs = c.execute("SELECT inj_id,err_code,gt_status FROM injection WHERE case_id=?",
                         (case_id,)).fetchall()
        lst = "".join(f'<li>{esc(i["inj_id"])} <span class="badge">{esc(i["gt_status"])}</span></li>'
                      for i in injs)
        body = f"""<h2>{esc(case_id)} ｜ N3 偏差注入</h2><div class="card meta">节点：{strip}</div>
<div class="card">本节点校验 = 注入偏差 GT 校验，在 GT 质检队列进行：<br><ul>{lst}</ul>
<a class="btn y" href="/queue/gt">跳转 GT 校验队列</a></div>"""
        return PAGE.format(title=f"{node} {name}", body=body)
    rows = ""
    for chk in checks:
        st = STATUS_BADGE.get(chk["result"] or "pending", "")
        rows += f"""<div class="card"><b>{esc(chk['item'])}</b> {st}
<pre>{esc(chk['artifact'])}</pre>
<form method="post" action="/review/check/{chk['id']}">
<input type="hidden" name="back" value="/review/{esc(case_id)}/{node}">
<button class="btn y" name="v" value="pass">通过</button>
<button class="btn n" name="v" value="fail">驳回</button>
<input name="note" placeholder="驳回原因/备注" size="50" value="{esc(chk['note'])}">
</form></div>"""
    body = f"""<h2>{esc(case_id)} ｜ {node} {name}</h2>
<div class="card meta">节点：{strip}</div>{rows}"""
    return PAGE.format(title=f"{node} {name}", body=body)


@app.post("/review/check/{check_id}")
def review_check_decide(check_id: int, v: str = Form(...), note: str = Form(""),
                        back: str = Form("/review")):
    c = db()
    c.execute("""UPDATE review_check SET result=?, note=?, reviewer='human', reviewed_at=?
                 WHERE id=?""",
              (v, note, dt.datetime.now().isoformat(timespec="seconds"), check_id))
    c.commit()
    return RedirectResponse(back, status_code=303)


@app.post("/review/reset/{check_id}")
def review_check_reset(check_id: int, back: str = Form("/case")):
    c = db()
    c.execute("""UPDATE review_check SET result=NULL, note=NULL, reviewer=NULL, reviewed_at=NULL
                 WHERE id=?""", (check_id,))
    c.commit()
    return RedirectResponse(back, status_code=303)


# ---------- 专家校验(四处机器替代不了的判断) ----------
EXPERT_AREAS = {
    "law":   ("法规引用真实性", ["存在且现行", "存在但已废止", "编造不存在", "场景不适用"]),
    "scheme": ("方案答非所问/矛盾", ["无矛盾", "应答表与方案矛盾", "答非所问", "漏项"]),
    "plaus": ("虚构事实合理带", ["合理", "偏假但可接受", "一眼假需回炉"]),
    "inj":   ("注入偏差领域可信度", ["自然", "可疑但可判", "不像真实偏差"]),
}


def seed_expert():
    c = db()
    if c.execute("SELECT COUNT(*) n FROM review_check WHERE node='EXP'").fetchone()["n"]:
        return
    demo = [
        ("CASE-TDR-CCGP-2026-00002-A01", "law", "引用法规核验 1/2",
         "标书第2章引用：《中华人民共和国政府采购法》第二十二条\n—— 该法真实存在，22条为供应商资格条件条款，现行有效"),
        ("CASE-TDR-CCGP-2026-00002-A01", "law", "引用法规核验 2/2",
         "标书第5章引用：《政府采购货物和服务招标投标管理办法》（财政部令第87号）第六十三条\n—— 87号令真实存在，但需核对63条内容是否为'低于成本价认定'"),
        ("CASE-TDR-CCGP-2026-00004-A01", "law", "引用标准核验",
         "灭菌器技术方案引用：GB 8599-2008《大型蒸汽灭菌器技术要求》\n—— 需核：该标准号是否真实、是否现行有效、是否适用于脉动真空灭菌器"),
        ("CASE-TDR-CCGP-2026-00004-A01", "scheme", "应答表 vs 方案矛盾检查",
         "参数应答表承诺：灭菌室容积 ≥ 600L【满足】\n方案正文第3.2节：'本公司主流机型容积覆盖 300~500L'\n—— 两处表述是否构成矛盾？"),
        ("CASE-TDR-CCGP-2026-00004-A01", "scheme", "需求回应度检查",
         "采购需求：'设备需具备双人双锁权限管理及追溯记录功能'\n方案对应章节仅写：'设备安全性高，权限管理完善'\n—— 是否构成答非所问？"),
        ("CASE-TDR-CCGP-2026-00004-A01", "plaus", "投标人规模合理性",
         "虚构投标人：成立 3 年，注册资本 500 万，员工 28 人\n投标内容：三甲医院灭菌设备（单价约 80 万）+ 全院 5 年维保\n—— 该规模承接此项目是否在合理带内？"),
        ("CASE-TDR-CCGP-2026-00010-A01", "plaus", "业绩合理性",
         "虚构业绩：近 3 年完成同类电子物证实验室项目 7 个，单个合同额均超 300 万\n投标人成立时间：4 年前\n—— 年均近 2 个同类大项目，对 4 年公司是否真实可信？"),
        ("CASE-TDR-CCGP-2026-00010-A01", "inj", "注入偏差：资质证书过期",
         "注入内容：ISO9001 证书有效期至 2025-12-30（投标截止 2026-09-15，已过期 9 个月）\n—— 过期 9 个月在真实投标中是否常见？还是通常过期 1~3 个月？"),
        ("CASE-TDR-CCGP-2026-00002-A01", "inj", "注入偏差：业绩数量不足",
         "注入内容：要求'近3年2个同类项目'，响应只提供 1 个（合同额达标）\n—— 真实废标案例中此类偏差是否以这种形态出现？"),
    ]
    for case, area, item, artifact in demo:
        c.execute("INSERT OR IGNORE INTO review_check(case_id,node,item,artifact,expert_area) VALUES (?,?,?,?,?)",
                  (case, "EXP", item, artifact, area))
    c.commit()


@app.get("/expert", response_class=HTMLResponse)
def expert_entry(cat: str = ""):
    seed_expert()
    seed_env()
    c = db()
    rows = c.execute("""
        SELECT b.case_id, t.category, t.title, t.region,
        SUM(CASE WHEN r.result IS NULL THEN 1 ELSE 0 END) pending, COUNT(r.id) total
        FROM bid_case b JOIN tender t ON b.tdr_id=t.tdr_id
        JOIN review_check r ON r.case_id=b.case_id AND r.node='EXP'
        GROUP BY b.case_id ORDER BY t.category, b.case_id""").fetchall()
    cats = {}
    for r in rows:
        k = r["category"] or "未分类"
        cats.setdefault(k, [0, 0])
        cats[k][0] += r["pending"]
        cats[k][1] += r["total"]
    chips = " ".join(f'<a class="badge" href="/expert?cat={esc(k)}">{esc(k)} 待审{v[0]}/{v[1]}</a>'
                     for k, v in sorted(cats.items()))
    trs = ""
    for r in rows:
        if cat and (r["category"] or "未分类") != cat:
            continue
        trs += f"""<tr><td><span class="badge">{esc(r['category'] or '未分类')}</span></td>
<td><a href="/expert/{esc(r['case_id'])}">{esc(r['case_id'])}</a><br>
<span class="meta">{esc(r['title'])}</span></td>
<td>{'<span class="badge r">待审 ' + str(r['pending']) + '</span>' if r['pending'] else '<span class="badge g">完成</span>'}</td></tr>"""
    body = f"""<h2>专家校验：四类机器替代不了的判断</h2>
<div class="card">{" ｜ ".join(f"<b>{v[0]}</b>" for v in EXPERT_AREAS.values())}<br>
{" ｜ ".join(v[0] for v in EXPERT_AREAS.values())}</div>
<div class="card">按项目类别进入：{chips} <a class="badge" href="/expert">全部</a></div>
<table><tr><th>类别</th><th>case / 项目</th><th>状态</th></tr>{trs}</table>"""
    return PAGE.format(title="专家校验", body=body)


@app.get("/expert/{case_id}", response_class=HTMLResponse)
def expert_case(case_id: str):
    c = db()
    cards = ""
    for area, (name, _) in EXPERT_AREAS.items():
        r = c.execute("""SELECT COUNT(*) n, SUM(CASE WHEN result IS NULL THEN 1 ELSE 0 END) p
                         FROM review_check WHERE case_id=? AND node='EXP' AND expert_area=?""",
                      (case_id, area)).fetchone()
        if not r["n"]:
            continue
        st = f'<span class="badge r">待审 {r["p"]}</span>' if r["p"] else '<span class="badge g">完成</span>'
        cards += f"""<a href="/expert/{esc(case_id)}/{area}" style="text-decoration:none;color:inherit">
<div class="card" style="display:inline-block;width:200px;text-align:center">
<b>{name}</b><br>{st} <span class="meta">共{r['n']}条</span></div></a>"""
    body = f"""<h2>{esc(case_id)}</h2>
<div class="card meta"><a href="/expert">← 返回类别入口</a></div>{cards or '<div class="empty">无专家校验项</div>'}
{env_section(case_id)}"""
    return PAGE.format(title=case_id, body=body)


@app.get("/expert/{case_id}/{area}", response_class=HTMLResponse)
def expert_area_page(case_id: str, area: str):
    c = db()
    name, verdicts = EXPERT_AREAS.get(area, (None, None))
    if not name:
        return HTMLResponse("校验区不存在", status_code=404)
    checks = c.execute("""SELECT * FROM review_check WHERE case_id=? AND node='EXP' AND expert_area=?
                          ORDER BY (result IS NOT NULL), id""", (case_id, area)).fetchall()
    rows = ""
    for chk in checks:
        cur = f'<span class="badge g">已标：{esc(chk["result"])}</span>' if chk["result"] else ""
        note = f'<div class="meta">备注：{esc(chk["note"])}</div>' if chk["note"] else ""
        btns = " ".join(f'<button class="btn {"y" if i == 0 else "s"}" name="v" value="{esc(v)}">{esc(v)}</button>'
                        for i, v in enumerate(verdicts))
        rows += f"""<div class="card"><b>{esc(chk['item'])}</b> {cur}
<pre>{esc(chk['artifact'])}</pre>{note}
<form method="post" action="/expert/check/{chk['id']}">
<input type="hidden" name="back" value="/expert/{esc(case_id)}/{area}">
{btns}<br><br><input name="note" placeholder="备注(依据/链接/复核建议)" size="60">
</form></div>"""
    body = f"""<h2>{esc(case_id)} ｜ {name}</h2>
<div class="card meta"><a href="/expert/{esc(case_id)}">← 返回四个校验区</a></div>{rows}"""
    return PAGE.format(title=name, body=body)


@app.post("/expert/check/{check_id}")
def expert_decide(check_id: int, v: str = Form(""), note: str = Form(""),
                  mode: str = Form("submit"), back: str = Form("/expert")):
    c = db()
    if mode == "draft":
        c.execute("UPDATE review_check SET draft=?, note=? WHERE id=?", (v or None, note, check_id))
    else:
        c.execute("""UPDATE review_check SET result=?, note=?, draft=NULL,
                     reviewer='expert', reviewed_at=? WHERE id=?""",
                  (v, note, dt.datetime.now().isoformat(timespec="seconds"), check_id))
    c.commit()
    return RedirectResponse(back, status_code=303)


# ---------- 环境文件(取证评测的噪声环境, 非主审, 只留反馈入口) ----------
ENV_ROLES = {"tender": "招标文件", "bid": "投标文件", "cert": "证明材料",
             "credit": "信用查询", "clarify": "澄清函",
             "noise_old": "噪声·旧版本", "noise_misc": "噪声·无关文件"}
ENV_FB_TYPES = ["文件缺失", "内容错误", "噪声不合理", "版本不对", "扫描件不真实", "其他"]


def seed_env():
    c = db()
    if c.execute("SELECT COUNT(*) n FROM env_file").fetchone()["n"]:
        return
    demo = [
        ("CASE-TDR-CCGP-2026-00004-A01", "招标文件（灭菌器采购）.pdf", "tender", 0, 0),
        ("CASE-TDR-CCGP-2026-00004-A01", "投标文件_正本_v3.docx", "bid", 0, 1),
        ("CASE-TDR-CCGP-2026-00004-A01", "ISO9001质量管理体系证书.pdf", "cert", 0, 1),
        ("CASE-TDR-CCGP-2026-00004-A01", "同类业绩合同_3份.pdf", "cert", 0, 0),
        ("CASE-TDR-CCGP-2026-00004-A01", "信用中国查询截图.png", "credit", 0, 0),
        ("CASE-TDR-CCGP-2026-00004-A01", "澄清答疑函_第1号.pdf", "clarify", 0, 0),
        ("CASE-TDR-CCGP-2026-00004-A01", "投标文件_v2_旧版勿用.docx", "noise_old", 1, 0),
        ("CASE-TDR-CCGP-2026-00004-A01", "公司员工手册2025.pdf", "noise_misc", 1, 0),
        ("CASE-TDR-CCGP-2026-00002-A01", "招标文件（企业出海服务）.zip", "tender", 0, 0),
        ("CASE-TDR-CCGP-2026-00002-A01", "投标文件_正本.docx", "bid", 0, 1),
        ("CASE-TDR-CCGP-2026-00002-A01", "资格承诺函.docx", "cert", 0, 0),
        ("CASE-TDR-CCGP-2026-00002-A01", "上一年度财务报表.pdf", "cert", 0, 0),
        ("CASE-TDR-CCGP-2026-00002-A01", "投标文件_草稿_未审.docx", "noise_old", 1, 0),
    ]
    for case, fn, role, noise, ev in demo:
        c.execute("INSERT INTO env_file(case_id,filename,role,is_noise,has_evidence) VALUES (?,?,?,?,?)",
                  (case, fn, role, noise, ev))
    c.commit()


# ---------- 丰富种子数据(幂等, 原型演示用) ----------
def seed_rich():
    c = db()
    now = dt.datetime.now().isoformat(timespec="seconds")

    # 1. 补齐 case 引用的 rubric 行 + 新 case
    for rid, tdr in [("RBC-TDR-CCGP-2026-00002-v1", "TDR-CCGP-2026-00002"),
                     ("RBC-TDR-CCGP-2026-00004-v1", "TDR-CCGP-2026-00004"),
                     ("RBC-TDR-CCGP-2026-00005-v1", "TDR-CCGP-2026-00005"),
                     ("RBC-TDR-CCGP-2026-00010-v1", "TDR-CCGP-2026-00010")]:
        c.execute("""INSERT OR IGNORE INTO rubric(rubric_id,tdr_id,version,source,status,created_at)
                     VALUES (?,?,1,'llm','extracted',?)""", (rid, tdr, now))
    for cid, tdr, rid, var in [
            ("CASE-TDR-CCGP-2026-00002-A02", "TDR-CCGP-2026-00002", "RBC-TDR-CCGP-2026-00002-v1", "A02"),
            ("CASE-TDR-CCGP-2026-00005-A01", "TDR-CCGP-2026-00005", "RBC-TDR-CCGP-2026-00005-v1", "A01")]:
        c.execute("""INSERT OR IGNORE INTO bid_case(case_id,tdr_id,rubric_id,variant,status,created_at)
                     VALUES (?,?,?,?,'injected',?)""", (cid, tdr, rid, var, now))

    # 2. 生成节点校验项 (UNIQUE(case_id,node,item) 幂等)
    checks = [
        # --- 00004 灭菌器(货物): 此前完全没有 N 节点 ---
        ("CASE-TDR-CCGP-2026-00004-A01", "N1", "资格要求抽取完整",
         "抽取到资格项 3 条：\n1. 政府采购法第22条（营业执照扫描件/财务状况报告/纳税社保证明）\n2. 不接受联合体\n3. 特定资格：无\n—— 原文位置：detail.txt 二、申请人的资格要求"),
        ("CASE-TDR-CCGP-2026-00004-A01", "N1", "交付期与履约条款抽取",
         "抽取：合同生效后 30 日内交付、安装、调试完毕并投入使用\n项目编号 JSZC-320300-ZJZB-G2026-0109 ｜ 数量 3 台"),
        ("CASE-TDR-CCGP-2026-00004-A01", "N2", "报价 ≤ 预算",
         "生成报价 ¥1,458,000.00\n预算金额 ¥1,500,000.00（detail.txt 预算金额）\n→ 未超预算 ✓"),
        ("CASE-TDR-CCGP-2026-00004-A01", "N2", "交付期响应",
         "要求：合同生效后 30 日内交付并投入使用\n生成承诺：合同生效后 28 日内完成交付安装调试 ✓"),
        ("CASE-TDR-CCGP-2026-00004-A01", "N2", "财务证明材料时效",
         "要求：投标截止前 6 个月内任一时点资产负债表/损益表，或 2025 年度经审计财报\n生成：附 2024 年度审计报告 ⚠️ 年度是否符合'或'条款需人工确认"),
        ("CASE-TDR-CCGP-2026-00004-A01", "N4", "章节完整性",
         "目录 8 章 / 正文 8 章；资格证明、商务应答、技术方案、售后服务均在"),
        ("CASE-TDR-CCGP-2026-00004-A01", "N4", "参数应答表与方案一致性",
         "容积应答 ≥600L【满足】，方案正文写'300~500L 主流机型' ⚠️ 不一致（转专家 scheme 区复核）"),
        # --- 00010 电子物证实验室(货物): 此前无 N 节点 ---
        ("CASE-TDR-CCGP-2026-00010-A01", "N1", "资格要求抽取完整",
         "抽取到资格项 3 条：\n1. 政府采购法第22条\n2. 非专门面向中小企业\n3. 特定资格：无\n—— 原文位置：detail.txt 二、申请人的资格要求"),
        ("CASE-TDR-CCGP-2026-00010-A01", "N1", "商务条款抽取",
         "预算/最高限价 ¥2,560,684（同额，即不得高于预算）\n履约期：20 日历天 ｜ 不接受联合体 ｜ 质疑需一次性提出"),
        ("CASE-TDR-CCGP-2026-00010-A01", "N2", "报价 ≤ 最高限价",
         "生成报价 ¥2,560,684.00\n最高限价 ¥2,560,684.00\n→ 等于限价 ⚠️ 贴线报价，策略风险（不违规）"),
        ("CASE-TDR-CCGP-2026-00010-A01", "N2", "履约期响应",
         "要求：20 日历天\n生成承诺：18 日历天 ✓"),
        ("CASE-TDR-CCGP-2026-00010-A01", "N4", "无占位符/模板残留",
         "检测到占位符 2 处：【此处插入检测设备清单照片】【XXX公司】（第 4 章）⚠️"),
        ("CASE-TDR-CCGP-2026-00010-A01", "N4", "全文一致性",
         "项目名称出现 9 处一致 ✓\n报价大写与小写一致 ✓\n法定代表人姓名前后一致 ✓"),
        # --- 00005 一体杆电灯(货物, 新case) ---
        ("CASE-TDR-CCGP-2026-00005-A01", "N1", "资格要求抽取完整",
         "抽取到资格项 3 条：\n1. 政府采购法第22条\n2. 专门面向中小企业（含监狱企业、残疾人福利性单位）\n3. 不接受联合体\n—— 原文位置：detail.txt 二、申请人的资格要求"),
        ("CASE-TDR-CCGP-2026-00005-A01", "N1", "中小企业政策条款抽取",
         "本项目专门面向中小企业：须出具有效《中小企业声明函》\n划型行业：工业（须与采购标的所属行业一致）"),
        ("CASE-TDR-CCGP-2026-00005-A01", "N2", "报价 ≤ 预算/限价",
         "生成报价 ¥2,498,000.00\n预算 ¥2,558,800.00 ｜ 最高限价 ¥2,530,000.00/批\n→ 低于限价 ✓"),
        ("CASE-TDR-CCGP-2026-00005-A01", "N2", "中小企业声明函",
         "要求：专门面向中小企业，声明函必填且划型真实\n生成：已附声明函，声明为小型企业 ⚠️ 划型依据需人工抽查"),
        ("CASE-TDR-CCGP-2026-00005-A01", "N2", "合同期限响应",
         "要求：合同签订之日起 2 年，每年履约验收\n生成承诺：服务期 2 年，接受年度履约验收 ✓"),
        ("CASE-TDR-CCGP-2026-00005-A01", "N4", "章节完整性",
         "目录 10 章 / 正文 10 章；含产品彩页、检测报告索引、售后网点表"),
        ("CASE-TDR-CCGP-2026-00005-A01", "N4", "检测报告有效性",
         "LED 灯具检测报告落款日期 2023-05 ⚠️ 超过 3 年，是否需复检报告需人工判断"),
        # --- 00002 企业出海服务(服务): A02 变体 ---
        ("CASE-TDR-CCGP-2026-00002-A02", "N1", "资格要求抽取完整",
         "抽取到资格项 4 条：\n1. 政府采购法第22条（营业执照/承诺函）\n2. 信用中国无失信记录\n3. 不接受联合体\n4. 不接受分公司投标\n—— 原文位置：detail.txt 二、申请人的资格要求"),
        ("CASE-TDR-CCGP-2026-00002-A02", "N1", "采购需求要点抽取",
         "预算 ¥5,350,000 ｜ 服务期 3 年（一年一签）\n采购人：中国国际贸易促进委员会东莞市委员会"),
        ("CASE-TDR-CCGP-2026-00002-A02", "N2", "报价 ≤ 预算",
         "生成报价 ¥5,480,000.00\n预算金额 ¥5,350,000.00\n→ 超预算 ¥130,000 ✗（应废标，基线生成错误）"),
        ("CASE-TDR-CCGP-2026-00002-A02", "N2", "服务期响应",
         "要求：3 年（合同一年一签）\n生成承诺：一次性签订 3 年合同 ⚠️ 与'一年一签'不一致"),
        ("CASE-TDR-CCGP-2026-00002-A02", "N4", "章节完整性",
         "目录 9 章 / 正文 8 章：缺'项目实施方案'整章 ⚠️"),
        ("CASE-TDR-CCGP-2026-00002-A02", "N4", "全文一致性",
         "报价出现 3 处：摘要 ¥5,480,000 / 报价表 ¥5,480,000 / 服务承诺章 ¥5,350,000 ⚠️ 不一致"),
        # --- 00002 A01 补充 ---
        ("CASE-TDR-CCGP-2026-00002-A01", "N1", "商务条款抽取",
         "预算 ¥5,350,000 ｜ 截止 2026-09-22 09:30 ｜ 远程电子开标\n保证金：可走智慧云平台金融服务中心担保函"),
        ("CASE-TDR-CCGP-2026-00002-A01", "N2", "联合体/分公司限制响应",
         "要求：不接受联合体、不接受分公司投标\n生成：以独立法人名义投标，无联合体声明遗漏 ✓"),
    ]
    for case, node, item, artifact in checks:
        c.execute("INSERT OR IGNORE INTO review_check(case_id,node,item,artifact) VALUES (?,?,?,?)",
                  (case, node, item, artifact))

    # 3. 专家校验项补齐(每个主打 case 四区都有)
    exp = [
        ("CASE-TDR-CCGP-2026-00002-A01", "scheme", "服务方案 vs 采购需求回应度",
         "采购需求：企业出海合规咨询 + 海外仓对接 + 年度不少于 12 场对接活动\n方案对应章节仅写：'提供全方位出海服务，活动丰富'\n—— 是否构成答非所问/漏项？"),
        ("CASE-TDR-CCGP-2026-00002-A01", "plaus", "服务团队规模合理性",
         "虚构服务团队：核心顾问 5 人，承诺 3 年服务期 + 每年 12 场活动 + 驻场响应 2 小时\n投标人成立 2 年，社保缴纳人数 9 人\n—— 该配置承接 535 万/3年项目是否在合理带内？"),
        ("CASE-TDR-CCGP-2026-00002-A02", "law", "引用法规核验",
         "标书引用：《中华人民共和国政府采购法》第七十七条（虚假材料罚则）\n—— 法条真实存在，引用场景为'声明函真实性承诺'，是否适用？"),
        ("CASE-TDR-CCGP-2026-00002-A02", "inj", "注入偏差：报价超预算",
         "注入内容：报价 ¥5,480,000 超预算 ¥5,350,000\n—— 超预算注入在真实废标案例中是否以整额超出的形态出现？还是多为分项漏价？"),
        ("CASE-TDR-CCGP-2026-00002-A02", "scheme", "服务期承诺矛盾",
         "商务应答：服务期 3 年【满足】\n合同条款响应章：'一次性签订 3 年合同'\n招标要求：一年一签\n—— 应答表与合同响应是否矛盾？"),
        ("CASE-TDR-CCGP-2026-00002-A02", "plaus", "报价超预算的合理性",
         "A02 变体基线即超预算 13 万\n—— 真实投标中是否存在'明知超预算仍报价'？多因什么产生（漏看限价/分项加总错误）？"),
        ("CASE-TDR-CCGP-2026-00005-A01", "law", "中小企业划型标准引用核验",
         "标书引用：《中小企业划型标准规定》（工信部联企业〔2011〕300号）工业划型\n—— 该文是否现行有效？是否有更新版本（2021 修订征求意见稿）？"),
        ("CASE-TDR-CCGP-2026-00005-A01", "scheme", "技术参数应答 vs 检测报告",
         "应答表：LED 模组光效 ≥160 lm/W【满足，见检测报告】\n检测报告实测：152 lm/W\n—— 应答与证据矛盾，是否构成虚假应答？"),
        ("CASE-TDR-CCGP-2026-00005-A01", "plaus", "产能合理性",
         "虚构投标人：年产 LED 路灯 8 万套，员工 45 人，成立 4 年\n本次投标 2 年供 13 批次一体杆电灯\n—— 产能规模与供货承诺是否匹配？"),
        ("CASE-TDR-CCGP-2026-00005-A01", "inj", "注入偏差：检测报告过期",
         "注入内容：检测报告落款 2023-05，距投标截止超 3 年\n—— 真实案例中'报告过期'偏差的常见年限分布？3 年是否一眼假？"),
        ("CASE-TDR-CCGP-2026-00010-A01", "law", "引用标准核验",
         "取证设备方案引用：GA/T 754-2008《电子数据存储介质复制工具要求及检测方法》\n—— 该行业标准号是否真实、是否现行有效？"),
        ("CASE-TDR-CCGP-2026-00010-A01", "scheme", "20 天履约承诺 vs 实施方案",
         "商务应答：20 日历天完成供货安装【满足】\n实施方案：'设备定制生产周期约 45 天'\n—— 两处是否构成矛盾？定制周期是否暴露应答不实？"),
        ("CASE-TDR-CCGP-2026-00010-A01", "inj", "注入偏差：贴线报价",
         "注入内容：报价 = 最高限价 ¥2,560,684（分毫不差）\n—— 贴线报价在真实项目中出现频率？作为偏差注入是否太明显？"),
    ]
    for case, area, item, artifact in exp:
        c.execute("INSERT OR IGNORE INTO review_check(case_id,node,item,artifact,expert_area) VALUES (?,?,?,?,?)",
                  (case, "EXP", item, artifact, area))

    # 4. 环境文件(按 (case_id,filename) 判重)
    env = [
        ("CASE-TDR-CCGP-2026-00010-A01", "招标文件(电子物证实验室设备).docx", "tender", 0, 0, 0, "采购人发布的招标文件正文"),
        ("CASE-TDR-CCGP-2026-00010-A01", "投标文件_正本_v5.docx", "bid", 0, 1, 0, "被测标书正本，含注入偏差"),
        ("CASE-TDR-CCGP-2026-00010-A01", "营业执照扫描件.pdf", "cert", 0, 0, 1, "资格证明，扫描件"),
        ("CASE-TDR-CCGP-2026-00010-A01", "同类业绩合同_7份.pdf", "cert", 0, 1, 0, "业绩证明，注入偏差的证据载体"),
        ("CASE-TDR-CCGP-2026-00010-A01", "法定代表人授权书.pdf", "cert", 0, 0, 1, "授权书扫描件"),
        ("CASE-TDR-CCGP-2026-00010-A01", "投标文件_v4_作废.docx", "noise_old", 1, 0, 0, "旧版投标稿，干扰 agent 取证"),
        ("CASE-TDR-CCGP-2026-00010-A01", "会议室预订确认邮件.eml", "noise_misc", 1, 0, 0, "无关邮件"),
        ("CASE-TDR-CCGP-2026-00005-A01", "招标文件(一体杆电灯).pdf", "tender", 0, 0, 0, "采购人发布的招标文件"),
        ("CASE-TDR-CCGP-2026-00005-A01", "投标文件_正本.docx", "bid", 0, 1, 0, "被测标书正本，含注入偏差"),
        ("CASE-TDR-CCGP-2026-00005-A01", "中小企业声明函.docx", "cert", 0, 1, 0, "声明函，划型真实性证据"),
        ("CASE-TDR-CCGP-2026-00005-A01", "LED灯具检测报告.pdf", "cert", 0, 1, 1, "检测报告扫描件，落款日期是证据"),
        ("CASE-TDR-CCGP-2026-00005-A01", "产品彩页_2026.pdf", "cert", 0, 0, 0, "产品资料"),
        ("CASE-TDR-CCGP-2026-00005-A01", "检测报告_旧版2021.pdf", "noise_old", 1, 0, 1, "旧报告，易与现行报告混淆"),
        ("CASE-TDR-CCGP-2026-00005-A01", "团建活动通知.docx", "noise_misc", 1, 0, 0, "无关文件"),
        ("CASE-TDR-CCGP-2026-00002-A02", "招标文件（企业出海服务）.zip", "tender", 0, 0, 0, "同 A01 招标文件"),
        ("CASE-TDR-CCGP-2026-00002-A02", "投标文件_A02变体.docx", "bid", 0, 1, 0, "A02 变体标书，基线即超预算"),
        ("CASE-TDR-CCGP-2026-00002-A02", "资格条件承诺函.docx", "cert", 0, 0, 0, "承诺函"),
        ("CASE-TDR-CCGP-2026-00002-A02", "出海服务案例集.pdf", "cert", 0, 0, 0, "服务案例"),
        ("CASE-TDR-CCGP-2026-00002-A02", "报价单_内部测算版.xlsx", "noise_old", 1, 0, 0, "内部测算稿，价格与正本不同"),
        ("CASE-TDR-CCGP-2026-00002-A01", "信用中国查询截图.png", "credit", 0, 0, 0, "信用查询截图"),
        ("CASE-TDR-CCGP-2026-00002-A01", "澄清答疑函_第1号.pdf", "clarify", 0, 0, 0, "采购人澄清，影响条款解读"),
    ]
    for case, fn, role, noise, evd, scan, what in env:
        if not c.execute("SELECT 1 FROM env_file WHERE case_id=? AND filename=?",
                         (case, fn)).fetchone():
            c.execute("""INSERT INTO env_file(case_id,filename,role,is_noise,has_evidence,is_scan,what_is_it)
                         VALUES (?,?,?,?,?,?,?)""", (case, fn, role, noise, evd, scan, what))

    # 5. 注入记录(GT 队列演示)
    inj = [
        ("INJ-CASE-TDR-CCGP-2026-00004-A01-ERR-QUA-003-01", "CASE-TDR-CCGP-2026-00004-A01",
         "ERR-QUA-003", "P", "第3章 资格证明",
         "财务状况报告：2025年度经审计财报", "财务状况报告：2024年度经审计财报",
         "应检出：财报年度不满足'投标截止前6个月内或2025年度'要求"),
        ("INJ-CASE-TDR-CCGP-2026-00010-A01-ERR-PRC-001-01", "CASE-TDR-CCGP-2026-00010-A01",
         "ERR-PRC-001", "P", "报价一览表",
         "总报价：¥2,486,000.00", "总报价：¥2,560,684.00（=最高限价）",
         "应检出：报价贴线，且大写金额需复核一致性"),
        ("INJ-CASE-TDR-CCGP-2026-00005-A01-ERR-DOC-002-01", "CASE-TDR-CCGP-2026-00005-A01",
         "ERR-DOC-002", "G", "第6章 检测报告",
         "检测报告落款：2025-06", "检测报告落款：2023-05",
         "应检出：检测报告超过3年有效期，需复检报告"),
    ]
    for iid, case, code, method, loc, before, after, expect in inj:
        c.execute("""INSERT OR IGNORE INTO injection
                     (inj_id,case_id,err_code,method,locator,before_text,after_text,expected_finding,gt_status)
                     VALUES (?,?,?,?,?,?,?,?,'needs_review')""",
                  (iid, case, code, method, loc, before, after, expect))

    # 6. 项目类别: 由 /tenders 的规则自动判定, 此处不再手工设置

    # 7. rubric 条目(解析需求文档生成的打分/审查项, 原型手工种子)
    tpl_items = [
        ("template", "qualification", "营业执照（或法人登记证）复印件有效"),
        ("template", "qualification", "信用中国/中国政府采购网无失信记录"),
        ("template", "qualification", "依法缴纳税收和社保的证明或承诺"),
        ("template", "compliance", "投标报价未超预算/最高限价"),
        ("template", "compliance", "投标有效期满足招标要求"),
        ("template", "compliance", "投标文件签章齐全"),
        ("template", "rejection", "串通投标/弄虚作假 → 废标"),
        ("template", "rejection", "资格证明文件造假 → 废标并追责"),
    ]
    rbc_items = {
        "RBC-TDR-CCGP-2026-00002-v1": [
            ("delta", "qualification", "在境内注册的法人/组织/自然人，提交有效营业执照复印件"),
            ("delta", "qualification", "参照公告附件格式提供资格条件承诺函（税收/社保/商业信誉/履约能力）"),
            ("delta", "qualification", "前3年内无重大违法记录（较大数额罚款≥200万元）"),
            ("delta", "qualification", "信用中国无失信被执行人/重大税收违法/政府采购严重违法记录"),
            ("delta", "rejection", "单位负责人为同一人或存在控股管理关系的不同供应商不得同时投标"),
            ("delta", "rejection", "不接受分公司投标"),
            ("delta", "rejection", "不接受联合体投标"),
            ("delta", "compliance", "报价 ≤ 预算 ¥5,350,000"),
            ("delta", "compliance", "合同履行期限：3年（合同一年一签）"),
            ("delta", "compliance", "电子投标：提前办理CA和电子签章，网上提交"),
            ("delta", "score", "技术方案：出海服务实施计划与资源投入（分值占比待评分办法确认）"),
            ("delta", "score", "商务：同类服务业绩与团队资历"),
        ],
        "RBC-TDR-CCGP-2026-00004-v1": [
            ("delta", "qualification", "法人营业执照等证明文件/自然人身份证明，提供原件扫描件"),
            ("delta", "qualification", "财务状况报告：投标截止前6个月内任一时点资产负债表/损益表，或2025年度经审计财报"),
            ("delta", "qualification", "投标截止前6个月内任一月份依法缴纳税收和社保材料"),
            ("delta", "compliance", "报价 ≤ 预算 ¥1,500,000（3台脉动真空灭菌器）"),
            ("delta", "compliance", "合同生效后30日内交付、安装、调试完毕并投入使用"),
            ("delta", "rejection", "不接受联合体投标"),
            ("delta", "score", "技术参数应答：灭菌室容积/真空度/灭菌温度等指标逐项应答"),
            ("delta", "score", "售后服务：维保响应时间与备件保障"),
        ],
        "RBC-TDR-CCGP-2026-00005-v1": [
            ("delta", "qualification", "专门面向中小企业：须出具有效《中小企业声明函》（含监狱企业/残疾人福利单位）"),
            ("delta", "qualification", "声明函划型行业须与采购标的所属行业一致，划型须真实"),
            ("delta", "compliance", "报价 ≤ 预算 ¥2,558,800 且 ≤ 最高限价 ¥2,530,000/批"),
            ("delta", "compliance", "合同期2年：每年开展履约验收，合格续约"),
            ("delta", "rejection", "声明函划型不实 = 提供虚假材料谋取中标（政府采购法第77条）"),
            ("delta", "rejection", "不接受联合体投标"),
            ("delta", "score", "产品：LED光效/防护等级/检测报告有效性"),
            ("delta", "score", "供货组织：13批次交付计划与售后网点"),
        ],
        "RBC-TDR-CCGP-2026-00010-v1": [
            ("delta", "qualification", "满足政府采购法第22条规定"),
            ("delta", "qualification", "非专门面向中小企业"),
            ("delta", "compliance", "报价 ≤ 最高限价 ¥2,560,684（与预算同额）"),
            ("delta", "compliance", "合同履约期限：20日历天"),
            ("delta", "rejection", "不接受联合体投标"),
            ("delta", "rejection", "质疑需一次性提出，多次提出不予受理"),
            ("delta", "score", "技术：电子物证取证设备功能指标逐项应答"),
            ("delta", "score", "实施：20日历天交付的供货安装方案可行性"),
        ],
    }
    for rid, items in [("RBC-TPL-001", tpl_items)] + list(rbc_items.items()):
        for layer, catg, req in items:
            if not c.execute("SELECT 1 FROM rubric_item WHERE rubric_id=? AND requirement=?",
                             (rid, req)).fetchone():
                c.execute("INSERT INTO rubric_item(rubric_id,layer,category,requirement) VALUES (?,?,?,?)",
                          (rid, layer, catg, req))

    c.commit()


def env_section(case_id):
    c = db()
    files = c.execute("SELECT * FROM env_file WHERE case_id=? ORDER BY is_noise, id",
                      (case_id,)).fetchall()
    if not files:
        return ""
    rows = ""
    for f in files:
        role = f'<span class="badge{" r" if f["is_noise"] else ""}">{ENV_ROLES.get(f["role"], f["role"])}</span>'
        ev = ' <span class="badge g">含证据</span>' if f["has_evidence"] else ""
        fb = (f'<div class="meta">反馈[{esc(f["fb_type"])}] {esc(f["fb_note"])} — {esc(f["fb_by"])}</div>'
              if f["fb_type"] else "")
        opts = "".join(f"<option>{esc(t)}</option>" for t in ENV_FB_TYPES)
        rows += f"""<tr><td>{esc(f['filename'])}</td><td>{role}{ev}</td>
<td>{fb}<form method="post" action="/env/feedback/{f['id']}" style="display:inline">
<input type="hidden" name="back" value="/expert/{esc(case_id)}">
<select name="fb_type">{opts}</select>
<input name="fb_note" placeholder="问题描述" size="30">
<button class="btn s">反馈</button></form></td></tr>"""
    return f"""<h3>环境文件（辅助参考，非主审内容）</h3>
<div class="card meta">agent 取证评测环境：含噪声文件，被测 agent 需自行甄别取证。
「含证据」= 该文件含注入偏差的证据（日后测取证召回）。发现文件问题随手反馈，不占主审流程。</div>
<table><tr><th>文件</th><th>角色</th><th>反馈入口</th></tr>{rows}</table>"""


@app.post("/env/feedback/{file_id}")
def env_feedback(file_id: int, fb_type: str = Form(...), fb_note: str = Form(""),
                 fb_page: int = Form(None), back: str = Form("/expert")):
    c = db()
    c.execute("UPDATE env_file SET fb_type=?, fb_note=?, fb_page=?, fb_by='human', fb_at=? WHERE id=?",
              (fb_type, fb_note, fb_page, dt.datetime.now().isoformat(timespec="seconds"), file_id))
    c.commit()
    return RedirectResponse(back, status_code=303)


@app.post("/env/feedback/reset/{file_id}")
def env_feedback_reset(file_id: int, back: str = Form("/case")):
    c = db()
    c.execute("""UPDATE env_file SET fb_type=NULL, fb_note=NULL, fb_page=NULL, fb_by=NULL, fb_at=NULL
                 WHERE id=?""", (file_id,))
    c.commit()
    return RedirectResponse(back, status_code=303)


# ---------- 统一标注视图(复刻 human_view: sidebar目录树+锚点高亮+stage-card+ios-browser) ----------
CASE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>
html{{scroll-behavior:smooth}}
body{{background:#fafafa;color:#333;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
     margin:0;line-height:1.7;font-size:14px}}
.anchor-row:target,.de-card:target,.ab-card:target{{
  background:#eef7ee!important;box-shadow:inset 3px 0 0 #57a05c}}
.node:target{{outline:2px solid #cfe4cf;outline-offset:2px}}
.layout{{display:flex;align-items:flex-start}}
.sidebar{{position:sticky;top:0;width:264px;flex:0 0 264px;height:100vh;overflow-y:auto;
         background:linear-gradient(180deg,#fbfbfa,#f7f7f5);border-right:1px solid #e6e6e2;
         padding:10px 8px 48px;scrollbar-width:thin;scrollbar-color:#ddd transparent;font-size:12px}}
.sb-head{{display:flex;align-items:center;justify-content:space-between;
         padding:4px 8px 10px;border-bottom:1px solid #ececea;margin-bottom:8px}}
.sb-title{{font-size:12px;font-weight:700;color:#555;letter-spacing:.5px}}
.sb-tools{{display:flex;gap:4px}}
.sb-btn{{font-size:10px;color:#888;background:#fff;border:1px solid #e2e2de;border-radius:4px;
        padding:1px 7px;cursor:pointer;user-select:none;text-decoration:none}}
.sb-btn:hover{{color:#333;border-color:#ccc}}
details.sb-nd{{margin:1px 0;border-radius:8px}}
details.sb-nd[open]{{background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.05);
                    border:1px solid #ececea;margin:3px 0;padding-bottom:5px}}
details.sb-nd>summary{{list-style:none;cursor:pointer;display:flex;align-items:center;gap:7px;
        padding:6px 9px;border-radius:8px;user-select:none}}
details.sb-nd>summary::-webkit-details-marker{{display:none}}
details.sb-nd>summary:hover{{background:#f1f1ee}}
details.sb-nd[open]>summary{{border-bottom:1px dashed #f0f0ec;border-radius:8px 8px 0 0}}
.sb-caret{{width:0;height:0;border-left:4px solid #b5b5b0;border-top:3.5px solid transparent;
          border-bottom:3.5px solid transparent;transition:transform .15s;flex:0 0 auto}}
details.sb-nd[open]>summary .sb-caret{{transform:rotate(90deg)}}
.sb-nm{{flex:1;min-width:0;font-size:12px;color:#3a3a36;font-weight:600;
       white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.sb-pill{{font-size:9.5px;min-width:16px;text-align:center;padding:0 6px;border-radius:8px;
         font-weight:600;background:#efefec;color:#8a8a84}}
.sb-pill.todo{{background:#fde8e8;color:#c0392b}}
details.sb-nd[open]>summary .sb-pill{{display:none}}
.sb-group{{font-size:9px;color:#b8b8b2;letter-spacing:1.4px;font-weight:700;
          padding:6px 10px 2px 24px}}
.sb-item{{display:flex;align-items:center;padding:2px 10px 2px 24px;color:#4a4a46;text-decoration:none;
         font-size:11px;border-left:2px solid transparent}}
.sb-item .sb-txt{{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0}}
.sb-item:hover{{background:#f2f2ef;border-left-color:#9dbf9f;color:#222}}
.wrap{{flex:1;min-width:0;max-width:1080px;margin:0 auto;padding:20px 24px 80px}}
.de-card{{background:#fdfaf6;border:1px solid #f0e2d0;border-left:3px solid #a8621b;
         border-radius:8px;padding:11px 14px;margin:0 24px 12px;scroll-margin-top:14px}}
.de-desc{{font-size:12.5px;color:#5a4632}}
h1{{font-size:22px;margin:14px 0 4px}}
.sub{{color:#888;font-size:12.5px;margin-bottom:20px}}
.node{{margin:30px 0 10px;padding:12px 18px;background:#fff;border-radius:12px;
      box-shadow:0 2px 12px rgba(0,0,0,.06);scroll-margin-top:52px}}
.node-title{{font-size:17px;font-weight:600;margin:2px 0;line-height:1.42;word-break:break-word;max-width:60em}}
.node-title.mid{{font-size:15px;font-weight:600}}
.chips{{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0}}
.chip{{font-size:10.5px;padding:1.5px 8px;border-radius:3px;background:#f0f0f0;color:#666}}
.chip.g{{background:#eef4ee;color:#2e7d32}} .chip.r{{background:#fde8e8;color:#c0392b}}
.instr{{background:#fcfcfc;border:1px solid #ececec;border-radius:8px;padding:11px 14px;
       font-size:12.5px;color:#444;margin:10px 0;white-space:pre-wrap;max-height:190px;overflow:auto}}
.stage-card{{background:#fff;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.06);
            overflow:hidden;margin-bottom:16px;scroll-margin-top:30px}}
.stage-card:target{{box-shadow:0 2px 12px rgba(0,0,0,.06),inset 4px 0 0 #57a05c}}
.stage-card:target>.stage-header{{background:#f4faf4}}
.stage-header{{padding:15px 24px 4px}}
.stage-text{{font-size:13px;color:#444}}
.item{{padding:9px 16px;border-bottom:1px solid #f0f0f0;scroll-margin-top:14px;background:#fff;
      border-radius:8px;margin-bottom:8px}}
.item:target{{box-shadow:inset 3px 0 0 #57a05c}}
.item.truth{{background:#f6fbf6;border-left:3px solid #2e7d32}}
.item.distractor{{background:#fef8f8;border-left:3px solid #c62828}}
.item.bulk{{background:#fbfbfb;border-left:3px solid #dcdcdc}}
.i-name{{font-size:11.5px;font-weight:600;color:#333;margin-bottom:2px}}
.i-what{{font-size:10px;color:#888;line-height:1.5}}
.i-carries{{font-size:10px;color:#2e7d32}}
details.cnt>summary{{cursor:pointer;color:#7799bb;font-size:10px;margin-top:3px;outline:none;
                    list-style:none;user-select:none}}
details.cnt>summary::before{{content:'▸ 展开反馈';}}
details.cnt[open]>summary::before{{content:'▾ 收起';}}
.vrow{{margin:0 24px 14px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
.vbtn{{font-size:11.5px;padding:3px 12px;border-radius:6px;border:1px solid #d8dcd0;background:#fff;
      color:#4a4a46;cursor:pointer}}
.vbtn:hover{{border-color:#9dbf9f;color:#1d4d21;background:#f6faf6}}
.vbtn.pri{{background:#eef4ee;border-color:#cfe0cf;color:#1d4d21;font-weight:600}}
.vbtn.sel{{background:#e3efe3;border-color:#57a05c;color:#1d4d21;font-weight:600;box-shadow:inset 0 0 0 1px #57a05c}}
.vbtn.danger{{border-color:#ecc;color:#a33}}
.vbtn.danger:hover{{background:#fef5f5;border-color:#d9a0a0}}
.fnote{{flex:1;min-width:160px;font-size:11.5px;padding:3px 8px;border:1px solid #e2e2de;border-radius:6px}}
.reqtext{{width:100%;min-height:56px;font-size:12.5px;padding:8px 10px;border:1px solid #e2e2de;border-radius:6px;
         font-family:inherit;line-height:1.6;box-sizing:border-box;background:#fcfcfc}}
select,.fpage{{font-size:11.5px;padding:3px 6px;border:1px solid #e2e2de;border-radius:6px}}
.fpage{{width:56px}}
</style></head><body><div class="layout">
<div class="sidebar"><div class="sb-head"><span class="sb-title">{sb_title}</span>
<span class="sb-tools"><a class="sb-btn" href="/tenders">总览</a><a class="sb-btn" href="/rubrics">规则</a></span></div>
{sidebar}</div>
<div class="wrap">{main}</div></div>
<script>
document.addEventListener('click',e=>{{
const opt=e.target.closest('.vbtn.opt');
if(opt){{const card=opt.closest('.stage-card');
card.querySelectorAll('.vbtn.opt').forEach(x=>x.classList.remove('sel'));
opt.classList.add('sel');
card.querySelector('input[name=v]').value=opt.dataset.v;return;}}
const act=e.target.closest('[data-act]');
if(act){{const card=act.closest('.stage-card');const f=card.querySelector('form.expform');
if(act.dataset.act==='submit'&&!f.v.value){{alert('请先点选一个判定');return;}}
f.mode.value=act.dataset.act;f.requestSubmit();}}
}});
</script></body></html>"""


def _sb_node(name, groups, open_=True):
    """groups: [(分组名, [(anchor, label, todo)])]"""
    inner = ""
    total_todo = 0
    for gname, items in groups:
        inner += f'<div class="sb-group">{esc(gname)}</div>'
        for anchor, label, todo in items:
            total_todo += todo
            inner += (f'<a class="sb-item" href="#{anchor}" title="{esc(label)}">'
                      f'<span class="sb-txt">{esc(label)}</span></a>')
    op = " open" if open_ else ""
    pill = f'<span class="sb-pill{" todo" if total_todo else ""}">{total_todo or "✓"}</span>'
    return f"""<details class="sb-nd"{op}><summary><span class="sb-caret"></span>
<span class="sb-nm">{esc(name)}</span>{pill}</summary>{inner}</details>"""


def _status_chip(result):
    if result == "pass":
        return '<span class="chip g">通过</span>'
    if result == "fail":
        return '<span class="chip r">驳回</span>'
    if result:
        return f'<span class="chip g">已标：{esc(result)}</span>'
    return '<span class="chip">待审</span>'


def _reset_form(back_url, chk_id):
    return (f'<form class="vrow" style="margin-top:-8px" method="post" '
            f'action="/review/reset/{chk_id}">'
            f'<input type="hidden" name="back" value="{esc(back_url)}">'
            f'<button class="vbtn">↩ 撤销，回到待审</button></form>')


def _case_header(case, case_id, active):
    gen = f'<a href="/case/{esc(case_id)}">节点+环境</a>'
    exp = f'<a href="/case/{esc(case_id)}/expert">专家校验</a>'
    if active == "gen":
        gen = f'<b style="color:#2e7d32">节点+环境</b>'
    else:
        exp = f'<b style="color:#2e7d32">专家校验</b>'
    return (f'<h1>{esc(case["title"])}</h1>\n<div class="sub">{esc(case_id)} ｜ '
            f'{esc(case["category"] or "未分类")} ｜ rubric {esc(case["rubric_id"])} ｜ {gen} · {exp}</div>')


@app.get("/case/{case_id}", response_class=HTMLResponse)
def case_gen_view(case_id: str):
    c = db()
    case = c.execute("SELECT b.*, t.title, t.category FROM bid_case b JOIN tender t ON b.tdr_id=t.tdr_id WHERE case_id=?",
                     (case_id,)).fetchone()
    if not case:
        return HTMLResponse("case 不存在", status_code=404)

    # --- 生成节点审核 ---
    node_groups, node_cards = [], []
    for n, nname in NODES:
        checks = c.execute("SELECT * FROM review_check WHERE case_id=? AND node=? ORDER BY id",
                           (case_id, n)).fetchall()
        if not checks:
            continue
        items, cards = [], []
        for chk in checks:
            todo = 1 if not chk["result"] else 0
            items.append((f"chk-{chk['id']}", chk["item"], todo))
            de = ""
            if chk["note"]:
                de = f'<div class="de-card"><div class="de-desc">{esc(chk["note"])}</div></div>'
            reset = _reset_form(f"/case/{case_id}#chk-{chk['id']}", chk["id"]) if chk["result"] else ""
            cards.append(f"""<div class="stage-card" id="chk-{chk['id']}">
<div class="stage-header"><div class="stage-text"><b>{esc(chk['item'])}</b> {_status_chip(chk['result'])}</div></div>
<div class="instr">{esc(chk['artifact'])}</div>{de}
<form class="vrow" method="post" action="/review/check/{chk['id']}">
<input type="hidden" name="back" value="/case/{esc(case_id)}#chk-{chk['id']}">
<button class="vbtn pri" name="v" value="pass">通过</button>
<button class="vbtn danger" name="v" value="fail">驳回</button>
<input class="fnote" name="note" placeholder="驳回原因/备注"></form>{reset}</div>""")
        node_groups.append((nname, items))
        node_cards.append(f'<div class="node" id="node-{n}"><div class="node-title mid">{n} {nname}</div></div>'
                          + "".join(cards))
    node_cards.append("""<div class="node"><div class="node-title mid">N3 偏差注入</div></div>
<div class="stage-card"><div class="stage-header"><div class="stage-text">
N3 = GT 校验，在 <a href="/queue/gt">GT 质检队列</a> 进行。</div></div></div>""")

    # --- 环境文件(非主审, 反馈入口+阅读器) ---
    efiles = c.execute("SELECT * FROM env_file WHERE case_id=? ORDER BY is_noise, id", (case_id,)).fetchall()
    env_items, env_rows = [], []
    for f in efiles:
        env_items.append((f"env-{f['id']}", f["filename"], 0))
        cls = "distractor" if f["is_noise"] else ("truth" if f["has_evidence"] else "bulk")
        role = esc(ENV_ROLES.get(f["role"], f["role"]))
        ev = ' · <span class="i-carries">含注入证据</span>' if f["has_evidence"] else ""
        scan = " · 扫描件" if f["is_scan"] else ""
        wit = f'<div class="i-what">{esc(f["what_is_it"])}</div>' if f["what_is_it"] else ""
        viewer = (f'<a class="vbtn" href="/viewer/{f["id"]}" target="_blank" '
                  f'style="text-decoration:none">打开阅读器</a>') if f["path"] else ""
        fb = ""
        if f["fb_type"]:
            fb = (f'<div class="i-what" style="color:#a8621b">已反馈[{esc(f["fb_type"])}'
                  + (f' 第{f["fb_page"]}页' if f["fb_page"] else "")
                  + f'] {esc(f["fb_note"])}</div>'
                  + f'<form method="post" action="/env/feedback/reset/{f["id"]}" style="display:inline">'
                  + f'<input type="hidden" name="back" value="/case/{esc(case_id)}#env-{f["id"]}">'
                  + '<button class="vbtn">清除反馈</button></form>')
        opts = "".join(f"<option>{esc(t)}</option>" for t in ENV_FB_TYPES)
        env_rows.append(f"""<div class="item {cls}" id="env-{f['id']}">
<div class="i-name">{esc(f['filename'])}</div>
<div class="i-what">{role}{scan}{ev}</div>{wit}{fb}
<div style="margin-top:4px">{viewer}</div>
<details class="cnt"><summary></summary>
<form method="post" action="/env/feedback/{f['id']}" style="margin-top:6px">
<input type="hidden" name="back" value="/case/{esc(case_id)}#env-{f['id']}">
<select name="fb_type">{opts}</select>
<input class="fpage" name="fb_page" placeholder="页码" type="number" min="1">
<input class="fnote" name="fb_note" placeholder="问题描述" style="min-width:120px">
<button class="vbtn">反馈</button></form></details></div>""")
    if efiles:
        env_groups = [("环境文件 · 非主审", env_items)]
        env_sec = ('<div class="node" id="env"><div class="node-title mid">环境文件（辅助参考，非主审）</div>'
                   '<div class="chips"><span class="chip g">绿=含证据</span><span class="chip r">红=噪声</span>'
                   '<span class="chip">灰=普通</span></div></div>' + "".join(env_rows))
    else:
        env_groups, env_sec = [], ""

    sidebar = (_sb_node("生成节点审核", node_groups) +
               (_sb_node("环境文件", env_groups, open_=False) if env_groups else ""))
    main = _case_header(case, case_id, "gen") + "".join(node_cards) + env_sec
    return CASE_PAGE.format(title=case_id, sb_title=case_id[-8:],
                            sidebar=sidebar, main=main)


@app.get("/case/{case_id}/expert", response_class=HTMLResponse)
def case_exp_view(case_id: str):
    c = db()
    case = c.execute("SELECT b.*, t.title, t.category FROM bid_case b JOIN tender t ON b.tdr_id=t.tdr_id WHERE case_id=?",
                     (case_id,)).fetchone()
    if not case:
        return HTMLResponse("case 不存在", status_code=404)
    exp_groups, exp_cards = [], []
    flat_ids = [chk["id"] for area in EXPERT_AREAS
                for chk in c.execute("""SELECT id FROM review_check WHERE case_id=? AND node='EXP' AND expert_area=?
                                        ORDER BY (result IS NOT NULL), id""", (case_id, area)).fetchall()]
    pos = {cid: i for i, cid in enumerate(flat_ids)}
    for area, (aname, verdicts) in EXPERT_AREAS.items():
        checks = c.execute("""SELECT * FROM review_check WHERE case_id=? AND node='EXP' AND expert_area=?
                              ORDER BY (result IS NOT NULL), id""", (case_id, area)).fetchall()
        if not checks:
            continue
        items, cards = [], []
        for chk in checks:
            todo = 1 if not chk["result"] else 0
            items.append((f"chk-{chk['id']}", chk["item"], todo))
            sel = chk["result"] or chk["draft"] or ""
            btns = " ".join(
                f'<button type="button" class="vbtn opt{" sel" if sel == v else ""}" data-v="{esc(v)}">{esc(v)}</button>'
                for v in verdicts)
            st = _status_chip(chk["result"]) if chk["result"] else (
                '<span class="chip" style="background:#fdf3e0;color:#a8621b">暂存中</span>' if chk["draft"]
                else '<span class="chip">待审</span>')
            de = ""
            if chk["note"]:
                de = f'<div class="de-card"><div class="de-desc">{esc(chk["note"])}</div></div>'
            reset = _reset_form(f"/case/{case_id}/expert#chk-{chk['id']}", chk["id"]) if chk["result"] else ""
            i = pos[chk["id"]]
            prev_a = (f'<a class="vbtn" href="#chk-{flat_ids[i-1]}" style="text-decoration:none">← 上一条</a>'
                      if i > 0 else '<span class="vbtn" style="opacity:.4">← 上一条</span>')
            next_a = (f'<a class="vbtn" href="#chk-{flat_ids[i+1]}" style="text-decoration:none">下一条 →</a>'
                      if i < len(flat_ids) - 1 else '<span class="vbtn" style="opacity:.4">下一条 →</span>')
            cards.append(f"""<div class="stage-card" id="chk-{chk['id']}">
<div class="stage-header"><div class="stage-text"><b>{esc(chk['item'])}</b> {st}</div></div>
<div class="instr">{esc(chk['artifact'])}</div>{de}
<form class="vrow expform" method="post" action="/expert/check/{chk['id']}">
<input type="hidden" name="back" value="/case/{esc(case_id)}/expert#chk-{chk['id']}">
<input type="hidden" name="mode" value="submit">
<input type="hidden" name="v" value="{esc(sel)}">{btns}
<input class="fnote" name="note" placeholder="备注(依据/链接/复核建议)" value="{esc(chk['note'])}"></form>
<div class="vrow" style="margin-top:-8px">{prev_a}
<button class="vbtn" data-act="draft">暂存</button>
<button class="vbtn pri" data-act="submit">提交</button>
{next_a}</div>{reset}</div>""")
        exp_groups.append((aname, items))
        exp_cards.append(f'<div class="node" id="exp-{area}"><div class="node-title mid">{aname}</div></div>'
                         + "".join(cards))
    sidebar = _sb_node("专家校验", exp_groups)
    main = _case_header(case, case_id, "exp") + "".join(exp_cards)
    return CASE_PAGE.format(title=f"{case_id} 专家校验", sb_title=case_id[-8:],
                            sidebar=sidebar, main=main)


# ---------- PDF 阅读器(原生渲染, 兼容扫描件; 右侧页码级反馈) ----------
@app.get("/envfile/{file_id}")
def env_file_raw(file_id: int):
    c = db()
    row = c.execute("SELECT path FROM env_file WHERE id=?", (file_id,)).fetchone()
    if row and row["path"] and os.path.exists(row["path"]):
        return FileResponse(row["path"], media_type="application/pdf")
    return HTMLResponse("文件不存在或未接线", status_code=404)


VIEWER_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>
body{{margin:0;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#fafafa;
     color:#333;line-height:1.7;font-size:14px}}
.layout{{display:flex;align-items:flex-start}}
.sidebar{{position:sticky;top:0;flex:0 0 300px;width:300px;height:100vh;overflow-y:auto;
         background:linear-gradient(180deg,#fbfbfa,#f7f7f5);border-right:1px solid #e6e6e2;
         scrollbar-width:thin;scrollbar-color:#ddd transparent;font-size:12px}}
.sb-head{{display:flex;align-items:center;justify-content:space-between;
         padding:10px 12px;border-bottom:1px solid #ececea}}
.sb-title{{font-size:12px;font-weight:700;color:#555;letter-spacing:.5px}}
.sb-btn{{font-size:10px;color:#888;background:#fff;border:1px solid #e2e2de;border-radius:4px;
        padding:1px 7px;cursor:pointer;user-select:none;text-decoration:none}}
.sb-btn:hover{{color:#333;border-color:#ccc}}
.sb-group{{font-size:9px;color:#b8b8b2;letter-spacing:1.4px;font-weight:700;padding:12px 12px 2px}}
.meta{{color:#8a8a85;font-size:12px}}
.de-card{{background:#fdfaf6;border:1px solid #f0e2d0;border-left:3px solid #a8621b;
         border-radius:8px;padding:9px 12px;margin:8px 12px;font-size:11.5px;color:#5a4632}}
.vbtn{{font-size:11.5px;padding:3px 12px;border-radius:6px;border:1px solid #d8dcd0;background:#fff;
      color:#4a4a46;cursor:pointer;text-decoration:none;display:inline-block;margin:2px 4px 2px 0}}
.vbtn:hover{{border-color:#9dbf9f;color:#1d4d21;background:#f6faf6}}
.vbtn.pri{{background:#eef4ee;border-color:#cfe0cf;color:#1d4d21;font-weight:600}}
input,select{{font-size:11.5px;padding:3px 6px;border:1px solid #e2e2de;border-radius:6px;
             width:100%;box-sizing:border-box;margin-bottom:4px}}
.main{{flex:1;min-width:0;padding:16px 18px}}
.docbar{{background:#fff;border:1px solid #e6e6e2;border-radius:8px 8px 0 0;padding:8px 14px;
        font-size:12px;color:#666;border-bottom:none}}
.docframe{{background:#fff;border:1px solid #e6e6e2;border-radius:0 0 8px 8px;overflow:hidden}}
</style></head><body>{body}</body></html>"""


@app.get("/viewer/{file_id}", response_class=HTMLResponse)
def pdf_viewer(file_id: int, page: int = 1):
    c = db()
    f = c.execute("SELECT * FROM env_file WHERE id=?", (file_id,)).fetchone()
    if not f:
        return HTMLResponse("文件不存在", status_code=404)
    others = c.execute("SELECT id,filename FROM env_file WHERE case_id=? AND path IS NOT NULL AND id!=?",
                       (f["case_id"], file_id)).fetchall()
    other_links = " ".join(f'<a class="vbtn" href="/viewer/{o["id"]}">{esc(o["filename"][:14])}</a>' for o in others)
    fb = ""
    if f["fb_type"]:
        fb = (f'<div class="de-card">最近反馈[{esc(f["fb_type"])}'
              + (f' 第{f["fb_page"]}页' if f["fb_page"] else "")
              + f'] {esc(f["fb_note"])}</div>')
    opts = "".join(f"<option>{esc(t)}</option>" for t in ENV_FB_TYPES)
    body = f"""<div class="layout">
<div class="sidebar">
<div class="sb-head"><span class="sb-title">{esc(f['filename'][:20])}</span>
<a class="sb-btn" href="/case/{esc(f['case_id'])}#env-{f['id']}">返回case</a></div>
<div style="padding:8px 12px">
<div class="meta">{ENV_ROLES.get(f['role'], f['role'])}</div>
<p class="meta">{esc(f['what_is_it'])}</p></div>
{fb}
<div class="sb-group">对此文件反馈</div>
<div style="padding:0 12px">
<form method="post" action="/env/feedback/{f['id']}">
<input type="hidden" name="back" value="/viewer/{f['id']}">
<select name="fb_type">{opts}</select>
<input name="fb_page" type="number" min="1" placeholder="页码" value="{page}">
<input name="fb_note" placeholder="问题描述">
<button class="vbtn pri">提交反馈</button></form></div>
<div class="sb-group">同 case 其他文件</div>
<div style="padding:0 12px">{other_links or '<span class="meta">无</span>'}</div>
</div>
<div class="main"><div class="docbar">{esc(f['filename'])} · 第 {page} 页</div>
<div class="docframe">
<iframe src="/envfile/{f['id']}#page={page}" style="width:100%;height:calc(100vh - 76px);border:0;display:block"></iframe>
</div></div>
</div>"""
    return VIEWER_PAGE.format(title=f["filename"], body=body)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8321)
