# GDPVal BidReview — Human-in-the-loop 与专家标注 UI Spec

版本：v0.1（MVP）  
目标：用尽可能少的专家时间，产出可追溯、可复核、无答案泄漏的 benchmark 数据。

## 1. 人工 Gate

| Gate | 审核对象 | 默认人力 | 通过条件 | 失败去向 |
|---|---|---:|---|---|
| G1 规则真实性 | TenderIR 的强制规则、例外和证据 span | 1 名标注员；高风险规则 2 名专家 | 原文、结构化表达和证据定位一致 | 回到规则抽取 |
| G2 clean 有效性 | clean bid 与全部 mandatory rules | 1 名主审 + 20% 专家抽检；MVP 100% 专家复核 | 无已知强制违规、内部事实一致 | 回到 clean 生成 |
| G3 mutation 有效性 | clean/injected 配对与 mutation manifest | 2 名独立专家 | 目标违规成立、单点、自然、无第二违规 | 回到 mutation |
| G4 成稿与泄漏 | 文档结构、元数据、语言痕迹、无关扰动 | 自动检查 + 10–20% 抽检 | 无标签/文件名/文风泄漏，渲染正常 | 回到 renderer |
| G5 争议仲裁 | 专家分歧、模型发现的额外问题 | 第三名高级专家 | 给出最终 verdict 与书面依据 | 修 GT 或剔除样本 |
| G6 发布冻结 | family split、版本、许可、统计 | 数据负责人 | family 无跨 split 泄漏；审计完整 | 不得发布 |

`G2/G3` 在 MVP 阶段不得抽样；规模化后，只有通过历史一致性校准的低风险模板才允许抽检。

## 2. 审核状态机

```text
generated → auto_validated → review_pending
                               ├─ agreed → accepted
                               ├─ conflict → adjudicated → accepted|rework|retired
                               └─ insufficient → review_pending
```

- 每位专家写独立的 `expert_review`，禁止覆盖另一位专家。
- 达到 `required_reviews` 后才计算 resolution。
- verdict 全同为 `agreed`；不同为 `conflict`；第三方仲裁后为 `adjudicated`。
- 所有暂存、提交、改判和仲裁写入 `audit_event`。
- 正式数据集只读取 `expert_resolution.final_verdict`，不读取旧版 `review_check.result`。

## 3. 角色与权限

| 角色 | 能看 | 能做 | 不能做 |
|---|---|---|---|
| Annotator | tender 规则与证据 | G1 初标、修订结构化字段 | 冻结数据集 |
| Expert reviewer | 自己被分配的盲样本 | 暂存、独立提交 | 看 clean/injected 标签、预期答案、他人结论 |
| Adjudicator | 冲突样本、匿名专家理由 | 最终裁决、退回重做 | 修改专家原始记录 |
| Data steward | 统计、审计、版本 | 分配、冻结、退役 | 代替专家作专业判断 |

MVP 的 `reviewer` query 参数仅用于演示；生产必须由 SSO/session 注入，后端忽略客户端传入身份。

## 4. 专家工作台信息架构

### 4.1 队列页 `/expert/work`

- 顶部：审核人、已完成/总数、进度条、预计剩余时间。
- 筛选：专家领域、tender family、语言、风险级别、任务类型。
- 列表只显示稳定的盲样本 alias，例如 `SAMPLE-37AF921C`。
- 不显示 case ID、variant、clean/injected、注入类型、预期 finding、其他专家进度。
- 默认按高风险优先，其次按分配时间；不允许专家挑选“容易题”。

### 4.2 单题页 `/expert/task/{id}`

两栏布局：

- 左栏证据：任务问题、tender 原文、bid 原文、必要上下文；支持页码/段落锚点。
- 右栏决策：互斥 verdict、置信度 1–5、必填理由、证据引用、暂存、提交。
- G3 配对审查应以 A/B 呈现，不说明哪份是 clean；专家判断“A/B 是否各自合规、差异是否仅一个语义事实”。
- 提交前校验：必须选 verdict、理由非空、置信度合法；低置信度自动进入额外复核。
- 提交后锁定；改判通过单独 revision 操作，保留旧记录。

### 4.3 冲突页 `/expert/conflicts`

- 只有 `conflict` 任务进入。
- 展示原始材料、匿名的专家 A/B verdict、置信度、证据与理由。
- 仲裁人必须写明采纳/推翻的证据；可选择最终 verdict、退回数据构造、退役样本。
- 仲裁完成后不可静默重开。

## 5. 四种任务模板

1. `rule_validity`：规则是否被正确抽取，是否含例外，证据定位是否充分。
2. `clean_validity`：该 bid 是否在给定规则下合规；若否，列出非预期违规。
3. `mutation_validity`：目标变化是否造成单一违规，是否自然，是否出现连带违规。
4. `finding_adjudication`：模型 finding 与 GT 谁正确，证据是否足够。

现有 `law/scheme/plaus/inj` 是专业领域标签，不应替代上述任务类型；两者需正交存储。

## 6. 数据契约

`expert_review` 保存单个专家的不可合并判断：`check_id, reviewer_id, round, verdict, confidence, rationale, evidence_refs, status, timestamps`。

`expert_resolution` 保存聚合/仲裁结果：`status, final_verdict, adjudicator_id, rationale, resolved_at`。

`audit_event` 保存状态变化，不保存密钥和完整文档内容。所有 benchmark 导出必须包含 schema version、case-set version、family split 和 resolution revision。

## 7. 质量指标与发布门槛

- 专家原始一致率与 Cohen's kappa（分类不平衡时同时报 Gwet's AC1）。
- 每种 task/family/error type 的冲突率。
- 单题中位耗时与 P90；过快提交作为质量告警，不自动判错。
- 低置信度比例、退回率、改判率和专家漂移。
- 发布要求：G1–G3 完整、冲突全部仲裁、关键字段无空值、family split 无泄漏、audit chain 完整。

## 8. 隐私与安全

- 原始投标资料默认最小权限；专家只见完成当前任务所需片段。
- UI 不把答案标签写进 DOM、URL、文件名或下载元数据。
- reviewer identity 来自认证层；POST 需 CSRF 防护；所有文档下载使用短期授权 URL。
- 研究导出使用盲 alias，内部映射单独加密保存。

## 9. MVP 验收标准

- 两位不同 reviewer 可以对同一任务独立提交且互不可见。
- 相同 verdict 自动进入 `agreed`；不同 verdict 自动进入 `conflict`。
- 只有 adjudicator 能结束 conflict，且理由必填。
- 页面不泄漏 case ID 或 clean/injected 标签。
- 暂存/提交/仲裁都有审计事件。
- 自动测试覆盖 migration、agreement、conflict 和 adjudication。

