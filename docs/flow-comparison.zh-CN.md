# Flow Systems Graph 与 Robot Workflow 对比

截至 2026-10-03，本文对比 Flow Engineering 公开介绍的 Systems Graph 与 Robot Workflow 0.5.0，并提出开源项目可落地的改进方向。下文对 Flow 的描述均来自厂商公开发布的产品资料，并非对其私有产品行为的独立验证；Robot Workflow 的现状则依据仓库中的 0.5.0 README 和架构文档核对。

[English](flow-comparison.md)

## 目录

- [范围与证据](#范围与证据)
- [Flow 公开介绍的能力](#flow-公开介绍的能力)
- [Robot Workflow 当前状态](#robot-workflow-当前状态)
- [改进优先级](#改进优先级)
- [边界与验收标准](#边界与验收标准)
- [参考资料](#参考资料)

## 范围与证据

本对比依据 Flow Systems Graph 产品页、Flow 官方集成页和客户 API 文档，以及 Robot Workflow 仓库中已核对的 0.5.0 README 与架构说明。Flow 网站介绍了一个共享且持续更新的工程模型，连接需求、接口、测试、CAD 和合规数据，并提供来源链接、变更影响、分支审查、参数引用和集成能力。这些内容是 Flow 的公开陈述；本次研究没有访问经过身份验证的 Flow 工作区，也未在实时 UI 中验证所述工作流。[Flow Systems Graph](https://www.flowengineering.com/product/systems-graph) [Flow 集成目录](https://www.flowengineering.com/integrations)

## Flow 公开介绍的能力

| 产品领域 | 公开介绍的行为 | 证据边界 |
|---|---|---|
| 连通图谱 | 工程制品作为节点并显式关联；可追溯到来源文档和条款 | 产品页介绍；未检查实时图谱 |
| 变更与审查 | 提出变更、分析影响、标记下游可疑/过期项、在分支上重跑、通知并审查/批准 | 产品页中的示例场景；未独立验证 |
| 需求与参数 | 跨项目关联需求；通过 API 提供需求中引用的实时参数 | 产品页陈述 |
| 集成 | 列出 GitHub、GitLab、Python、Onshape、表格、问题跟踪、文档存储和协作工具；各条目说明不同读写能力 | 官方集成目录；部分条目明确标注“即将推出” |
| API 与自动化 | 经过身份验证的 REST API 可访问项目、实体、关系和自动化；API 文档还介绍 MCP 连接 | 官方 API 概览 |
| API 控制 | API 支持分支范围读写；API key 继承创建者的权限，包括只读角色和分支限制；Webhook 自动化会启动异步运行 | 官方 API 文档；Webhook 响应表示已接受，不表示已完成 |

官方集成目录区分已列出的集成与标注“即将推出”的集成；例如，页面介绍了 Python、GitHub、Onshape、Excel 和 SharePoint，而查询时 Ansys 和 SimScale 标记为“即将推出”。目录中的条目不能证明某个具体部署已启用相应访问或权限。API 文档进一步说明分支范围操作、权限继承、只读/分支限制和异步 Webhook 运行；202 响应表示已接受而非已完成。[Flow 集成目录](https://www.flowengineering.com/integrations) [API 约定](https://docs.flowengineering.com/api/conventions) [API 身份验证](https://docs.flowengineering.com/api/authentication) [Webhook 自动化](https://docs.flowengineering.com/api/automations/webhooks)

## Robot Workflow 当前状态

Robot Workflow 0.5.0 已具备本地声明式工程图谱，包含仓库、组件、类型化依赖维度、需求、就绪状态、负责人和端口。它可以采集 Git/文件快照、计算下游影响、检查源码断言和接口声明、记录带范围的证据、显式运行命令检查、轮询并通过负责人 Webhook 通知，还能生成本地/离线报告。引导式初始化会发现仓库和推断边，供人员审阅。[Robot Workflow README](../README.zh-CN.md) [架构与配置](architecture.zh-CN.md)

关键边界是：它目前是本地单用户工作流工具，并非持续同步的共享系统模型。配置和关系由团队维护，自动发现只是保守辅助。它没有通用图谱编辑器、带身份验证的多人服务器、GitHub 入站 Webhook、CAD/PLM 连接器、参数计算引擎、审查/批准分支，也没有针对 HDF5 数据集、策略 checkpoint、标定或仿真/硬件证据的机器人领域提取器。源码证据不能证明物理行为、安全性或 Sim2Real 成功。[Robot Workflow README](../README.zh-CN.md) [架构与配置](architecture.zh-CN.md)

## 改进优先级

| 优先级 | 改进方向 | 具体机器人示例 | 验收标准 |
|---|---|---|---|
| P0 | 建立已接受基线到候选版本的多仓库流程 | 将 URDF、策略、标定和部署仓库绑定到一个已批准基线；提出修改腕部相机坐标系的候选版本 | 主流程为：已接受基线 → 不可变候选版本 → 影响报告 → 必需检查 → 指定人员审查 → 明确接受为新基线。候选不会自动批准；记录每仓库 commit、脏状态、图谱版本和覆盖情况；相关变更会使检查和批准失效 |
| P0 | 增加有来源依据的机器人契约和提取器 | 在已有 URDF/ROS 解析基础上，将提取字段绑定到端口，并扩展 checkpoint、数据集、标定身份及策略维度提取 | 每个值绑定准确来源路径和指纹；不支持/缺失字段为未知；差异显示变更值；元数据检查不会宣称完成物理验证 |
| P1 | 增加领域化初始化模板 | 引导新团队映射机器人模型、传感器、手、数据集、训练、评估和部署 | 模板生成可编辑提案及来源证据；推断边保持未验证；初始化以覆盖和负责人审查及可复现初始基线结束 |
| P1 | 集成实测仿真和硬件证据 | 将仿真运行或台架测试绑定到准确模型、控制器、固件、标定和测试设置版本 | 适配器记录结果来源、输入指纹、环境、测试条件和范围；输入变化/缺失会使证据过期/未知；证据不能自动接受候选或认证安全 |
| P1 | 增加团队身份、角色和审查记录 | 模型、感知和控制负责人审查相机坐标系变更 | 身份角色检查限制读写权限；审查绑定不可变候选及字段级差异；决定和证据 ID 可审计；批准与检查结果分开 |
| P1 | 集成 GitHub PR、检查和入站事件 | URDF/策略 PR 收到影响报告及检查状态；仓库事件触发刷新 | PR 显示通过/失败/未知及证据链接；配置的检查可阻止合并；入站/出站事件认证、去重并记录重试；不会隐式运行机器人命令 |
| P2 | 增加层级视图和实时参数传播 | 关节限制值从机器人模型传播到控制器限制和策略契约，并按 arm/wrist 子系统展示 | 公式引用绑定来源字段、单位、表达式版本和结果；变更会重算下游值并分析影响；单位无效时为未知；树/筛选视图保留稳定图谱身份 |
| P3 | 增加辅助式变更与影响建议 | 传感器坐标系或关节映射变化时建议相关检查 | 建议引用来源对象/路径，保持为提案并要求人工接受，绝不自动改变基线、批准或证据 |

建议顺序：先建立已接受基线/候选版本关卡和有来源依据的机器人契约；再增加领域初始化和实测证据；之后加入共享审查、CI 和集成；待图谱身份和来源稳定后再加层级及参数传播。辅助 AI 最后引入。以上均是 Robot Workflow 的改进建议，不代表当前已有能力。Flow 官方产品页启发了共享基线、影响审查、参数引用和集成这些方向；其官方 API 文档另行说明分支范围访问、权限继承和自动化触发。这些来源用于支持对比，不用于推断未验证的内部行为。[Flow Systems Graph](https://www.flowengineering.com/product/systems-graph) [API 约定](https://docs.flowengineering.com/api/conventions) [API 身份验证](https://docs.flowengineering.com/api/authentication) [Webhook 自动化](https://docs.flowengineering.com/api/automations/webhooks)

## 边界与验收标准

改进应保留本地优先能力，默认将源码作为数据检查，并在运行命令或连接机器人硬件前要求明确操作。新增证据记录应声明覆盖的输入和环境；输入变化或缺失时必须使结果失效或降级。集成应先支持只读导入/导出和机器可读格式；凭据和写入权限应由用户选择并限定范围。图谱经过审查、源码契约通过或仿真报告成功，都不能证明部署安全或真实机器人操作成功。

本文的 Flow 依据仅来自公开产品页和 API 页面。本地 Robot Workflow 改进建议不表示已测试实时 Flow 租户或 UI。

## 参考资料

- [Flow Systems Graph 产品页](https://www.flowengineering.com/product/systems-graph) — 公开介绍的图谱、影响分析、参数、集成和审查能力。
- [Flow 集成目录](https://www.flowengineering.com/integrations) — 集成说明及“即将推出”标记。
- [Flow API 概览](https://docs.flowengineering.com/api) — REST API 范围以及 MCP/自动化文档入口。
- [Flow API 约定](https://docs.flowengineering.com/api/conventions) — API 分支范围读写、分页和错误处理。
- [Flow API 身份验证](https://docs.flowengineering.com/api/authentication) — API key 权限、只读角色和分支限制。
- [Flow Webhook 自动化](https://docs.flowengineering.com/api/automations/webhooks) — 触发方式和异步运行行为。
- [Robot Workflow README](../README.zh-CN.md) — 当前 0.5.0 的用户可见范围和限制。
- [Robot Workflow 架构说明](architecture.zh-CN.md) — 配置、数据维度、证据、影响分析和扩展边界。
