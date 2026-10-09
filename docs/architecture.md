# TradeOps 技术设计与数据合同

状态：建议架构，实施时根据已有仓库调整并锁定依赖版本。默认 React＋TypeScript 前端、Python FastAPI 服务、PostgreSQL 数据库、Docker Compose 本地环境。选择理由是同时覆盖表单、Python、API、SQL 和部署证据；不是声称这些库已验证或必须使用最新版本。

## 边界与数据流

浏览器 → API 身份与对象权限检查 → 业务规则／金额计算 → 数据库事务 → 响应。审计事件与业务变更同事务写入。可选 outbox 与后台 worker 在扩展阶段加入；MVP 不需要 Redis、Kubernetes、微服务或外部通知。

认证建议优先复用已有可信认证库／身份服务，不自己设计加密。开发模式预置角色必须显式标记 DEMO；服务端从已验证身份得到 user_id、组织与角色，不信任请求体传入的 role 或 organization_id。公开部署前检查 cookie／token、CSRF、CORS、TLS 与默认账号配置。

## 实体与约束

| 实体 | 关键字段 | 约束／用途 |
|---|---|---|
| organization | id, name | demo 单组织；另一个组织仅用于隔离测试 |
| user | id, organization_id, role, active | 禁用账号不能继续审批 |
| inquiry | id, organization_id, owner_id, customer_code, raw_text, destination, created_at | 关联报价；真实联系人不纳入合成数据 |
| quote | id, organization_id, inquiry_id, created_by, current_version | current_version 必须属于该 quote |
| quote_version | id, quote_id, version, status, currency, discount_pct, payment_days, fx_to_hkd, valid_until, submitted_at, lock_version | unique(quote_id, version)；状态受业务层及约束控制 |
| quote_line | id, quote_version_id, sku, qty, unit_price, unit_cost | qty > 0；金额非负；SKU 在演示目录中 |
| approval_decision | id, quote_version_id, actor_id, decision, reason, decided_at | unique(quote_version_id) 防重复终结决定 |
| audit_event | id, organization_id, actor_id, entity_id, version, action, reason, occurred_at, correlation_id | 追加；不存密码、token 或完整原始个人信息 |

所有金额 PostgreSQL numeric，不用二进制 float。单价／成本 numeric(18,2)，fx numeric(18,6)，百分比 numeric(5,2)；JSON 金额使用字符串。服务端使用 Decimal。时间保存 UTC；UI 明示 Asia/Hong_Kong；有效期为业务本地日期。

## 金额算法

line_gross = round_half_up(qty × unit_price, 2)

gross = sum(line_gross)

discount_amount = round_half_up(gross × discount_pct / 100, 2)

net = gross − discount_amount；cost = sum(round_half_up(qty × unit_cost, 2))；profit = net − cost。

margin = profit / net，仅在 net > 0 时计算。阈值用未四舍五入的比值比较，UI 百分数可显示两位。net_hkd = round_half_up(net × fx_snapshot, 2)。MVP 同一报价所有行使用同一币种。汇率和成本锁在版本快照中，历史报价不随配置更新而变化。

折扣按整张报价计，不是逐行折扣；报告和导出必须复用同一计算规则。未来加入税、运费、多币种成本时，需先版本化规则和回归样例，不允许悄悄改变旧报价。

## 状态与事务

Draft → Pending → Approved／Rejected。Pending → Withdrawn。Approved → Superseded。终态不回到 Draft；修订创建版本号递增的新记录。quote.current_version 指向可继续处理的版本。

submit 事务：读取当前版本并锁定 → 验证 actor、字段和金额 → 确认 lock_version 与客户端一致 → 写 Pending、submitted_at、不可变快照 → audit → commit。

approve 事务：读取并锁定 → 验证 Manager 与组织权限且 actor != quote.created_by → 状态必须 Pending 且仍为 current_version → 插入唯一 decision → 更新 Approved → audit → commit。失败整体回滚。界面隐藏按钮只是辅助，不能代替服务器授权。

## REST 合同

| 接口 | 请求要点 | 成功／失败 |
|---|---|---|
| POST /inquiries | raw_text, customer_code | 201；缺字段 422 |
| GET /inquiries | page, status, owner | 200 分页；越权对象不可见 |
| POST /inquiries/{id}/quotes | 行明细、币种、折扣、付款期、日期 | 201 Draft；无权 403 或统一 404 |
| PATCH /quotes/{id}/versions/{v} | expected_lock_version 与可编辑字段 | 200；旧版本 409；非 Draft 409 |
| POST /quotes/{id}/versions/{v}/submit | expected_lock_version | 200 Pending；校验 422 |
| POST /quotes/{id}/versions/{v}/decision | approve/reject, reason, expected_lock_version | 200；自批 403；重复／过期 409 |
| POST /quotes/{id}/versions/{v}/revise | reason | 201 新 Draft，旧版按规则撤回／作废 |
| GET /reports/approvals | as_of 固定时钟仅测试可注入 | 200 定义明确的统计 |
| GET /quotes/{id}/export | 当前已批准版本 | 200 demo 文件；未批准 409 |

错误体统一为 code、message、field_errors、correlation_id，不暴露 SQL 堆栈。事务失败不得返回成功。测试用固定时钟通过依赖注入实现，不在公开 API 任意修改系统时间。

## SQL 实操

请亲自解释下面查询为何排除旧版本，以及恰好 48 小时为何不算逾期。将查询结果与手工样例对账。

```sql
SELECT q.id, v.version, v.submitted_at,
       EXTRACT(EPOCH FROM (:as_of - v.submitted_at))/3600 AS age_hours
FROM quote q
JOIN quote_version v
  ON v.quote_id = q.id AND v.version = q.current_version
WHERE q.organization_id = :organization_id
  AND v.status = 'Pending'
  AND v.submitted_at < :as_of - INTERVAL '48 hours';
```

另外实现按 currency 分组的 Approved 净额和按固定 fx 快照换算的 net_hkd；不要 SUM 不同币种原金额。对组织、状态和常用查询字段设计索引，用 EXPLAIN 解释而非先盲目加索引。

## 测试与部署

单元测试覆盖金额边界；集成测试使用真实 PostgreSQL 验证事务、唯一约束与并发；E2E 验证角色操作。SQLite 的通过结果不能代替 PostgreSQL 并发验证。固定种子数据，使用可重建的测试库，重置命令明确只作用 demo 数据库。

备份恢复演练只对本地合成库进行：创建一个已批准报价 → 备份 → 在新库恢复 → 比对版本、决定与审计数量 → 记录时间和限制。不要把本地演练写成企业灾备能力。
