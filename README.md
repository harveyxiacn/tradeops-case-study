# TradeOps Case Study

A synthetic trade quotation and approval case study with versioned rules, role checks and acceptance plans.

**Status: planning scaffold. No runnable application or completed benchmark is claimed.** Created 2026-10-09. Documents describe intended behavior; synthetic fixtures and NOT_RUN templates are not execution evidence.

## 从这里开始

在本项目目录打开新 session，发送：

> 请先读取 AGENTS.md、README.md 和 START_HERE.md，按 START_HERE 的第一阶段执行。保留已有修改，完成适当验证并报告实际结果与未完成项。

第一阶段：先做 T01–T07：询盘草稿、Decimal 金额计算和提交校验；之后再做审批与报表。

## 文档

- [新 session 启动说明](START_HERE.md)
- [acceptance](docs/acceptance.md)
- [architecture](docs/architecture.md)
- [business-case](docs/business-case.md)
- [prd](docs/prd.md)

## 项目关系

独立业务后端与最小 UI；其他仓库只通过有版本的 HTTP 合同接入，不共享或复制数据库。

## 使用边界

本仓库使用个人实验或虚构业务样本，不代表真实客户交付。模型、第三方组件、素材与运行工具遵循各自许可；本仓库不附带模型权重，不预先授权重新分发第三方材料。

本阶段没有统一启动应用命令，因为尚未开发。实施 session 应补充依赖版本、安装、运行、测试与已知限制，并明确真实后端测试与 mock 测试。

[完整文档索引](docs/index.md)
