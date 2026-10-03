# Robot Workflow

[English](README.md)

Robot Workflow 是面向机器人团队的开源工程工作流工具。登记机器人模型、参考数据、训练、感知和部署之间的关系，对比带版本的源码快照，查看下游影响，以及采用新版本所需的验证证据。

0.5.0 版本提供本地 CLI、本机网页工作台和离线交互报告。运行依赖为 Python 3.11+；记录 Git checkout 溯源时需要 Git。无需 AI 服务、ROS 安装或仿真器。

## 目录

- [本地网页工作台](#本地网页工作台)
- [引导式设置](#引导式设置)
- [功能](#功能)
- [创建并监测自己的工作流](#创建并监测自己的工作流)
- [快速开始](#快速开始)
- [接入自己的工作流](#接入自己的工作流)
- [命令与状态](#命令与状态)
- [边界与后续方向](#边界与后续方向)
- [契约、命令检查与变更处理](#契约命令检查与变更处理)
- [端口与精确重测](#端口与精确重测)
- [开发与许可证](#开发与许可证)

完整操作流程见[用户说明书](docs/user-guide.zh-CN.md)，包括初始化、依赖审查、监测、负责人 Webhook 和故障排查。

## 本地网页工作台

准备已有仓库的父目录，以及独立的状态目录，然后启动：

```bash
robot-workflow serve --root /tmp/my-robot-repos --state-dir /tmp/my-robot-workflow --port 8780
```

打开 `http://127.0.0.1:8780`。审查发现的仓库、编辑组件负责人、保留/删除/反向推断依赖，再保存已审阅配置。也可以显式克隆 GitHub HTTPS 仓库到一个不存在的相对目录。刷新会采集源码并生成报告；页面支持认领事项、填写说明后关闭，以及重新打开。命令检查按钮显式执行已声明命令；普通刷新不会执行命令。控制台是本地单用户服务，不是带身份认证的团队共享服务器。 保存变更后的配置会建立该配置的新基线，并保留此前状态；这不构成跨配置兼容性结论。添加仓库后的重新发现会保留人工登记，只追加新发现。

离线报告继续可用。网页工作台增加操作入口，不改变验证证据范围，也不证明机器人行为成功。

## 引导式设置

安装后，在交互终端运行一个命令：

```bash
robot-workflow setup
```

向导依次询问已有 Git checkout 的父目录、根目录之外的状态目录、工作流名称及组件负责人。对于推断关系，可选择保留（`k`）、删除（`d`）或反向（`r`）。随后检查覆盖、生成第一份本地报告，并调用系统浏览器打开。设置期间不拉取源码；已有保存配置会复用，不会覆盖。

无人值守生成首份报告时，明确指定根目录。默认保留的推断关系仍待审查，`--yes` 不证明依赖正确。

```bash
robot-workflow setup --root /tmp/my-robot-repos --owner robotics --yes --no-open
robot-workflow doctor --config /tmp/my-robot-repos-workflow/workflow.json --root /tmp/my-robot-repos
robot-workflow open --state-dir /tmp/my-robot-repos-workflow
```

默认状态目录位于根目录同级，名称为 `<root-name>-workflow`。`setup --lang en` 使用英文提示，默认中文。检查涵盖源码覆盖、未指定负责人、本地 Git 问题和待审查推断依赖。`doctor` 对 error 问题返回 2，warning 仍需审查。纯文档仓库存在实际文档时登记该文档，只覆盖文档，不证明运行时行为。浏览器不可用时仍提供报告路径。

设置完成会打印持续观察本地变化的命令；去掉 `--no-update` 即可启用 Git 拉取与快进同步。通知路由仍通过 `init` 或 JSON 配置；此向导不配置 Webhook 密钥、不补全遗漏依赖，也不提供图形编辑。

## 功能

| 功能 | 行为 |
|---|---|
| 工程依赖图 | 组件、仓库、带类型的依赖类别、维护归属、实现状态和需求 |
| 源码快照 | Git commit、dirty 状态、文件 SHA-256、登记源码覆盖及契约之外的 Git 文件清单 |
| 语义变化 | URDF 运动学/动力学/visual、Python AST、JSON、TOML、保守 YAML、ROS schema、文本及二进制哈希 |
| 影响分析 | 有向传递传播，附来源、代表性路径、依据和所需验证 |
| 验证证据 | 声明检查绑定相关输入/检查签名；旧证据仍绑定精确快照；明确显示过期 |
| 交互报告 | 工作流画布、场景选择、组件检查面板、搜索、状态过滤、缩放、变更、需求和版本组合 |
| 离线使用 | 独立 HTML，支持中英文控件及 JSON 导入/导出，不发起网络请求 |
| 集成门禁 | 可选的非零退出码，提示源码变化、覆盖缺失或未登记变化 |

## 创建并监测自己的工作流

将已有 Git checkout 放在同一目录下。配置、报告和监测状态必须放在这些 checkout 之外。默认发现与监测不会执行被检查项目的代码。

1. 启动工作流，自动发现仓库与依赖：

   ```bash
   robot-workflow start --root /tmp/my-robot-repos \
     --state-dir /tmp/my-robot-workflow --owner robotics \
     --webhook-env ROBOT_WORKFLOW_WEBHOOK_URL --interval 30
   ```

2. 首次启动生成 `/tmp/my-robot-workflow/workflow.json`。审查推断依赖及其源码依据，编辑组件负责人，并按需补充显式契约。编辑配置前先按 Ctrl+C 停止监测，重启后加载已审查配置。
3. 在环境中设置 `ROBOT_WORKFLOW_WEBHOOK_URL` 即可向自己的通知服务投递。不要把 Webhook 密钥写入配置或版本控制。未配置通知目标时，事件仅记录在本地；已指定环境变量但缺少 URL 时，投递保留为待重试。
4. 初始化新工作流时，可为每位负责人配置独立路由：

   ```bash
   robot-workflow init --root /tmp/my-robot-repos \
     --output /tmp/workflow.json --owner robotics \
     --route robotics=ROBOTICS_WEBHOOK_URL
   robot-workflow watch --config /tmp/workflow.json \
     --root /tmp/my-robot-repos --state-dir /tmp/my-robot-monitor \
     --interval 30
   ```

监测按指定间隔轮询，不是 GitHub push Webhook 接收器。它获取并 fast-forward 更新干净的现有分支，报告跳过或失败的同步，比较源码快照，生成影响 HTML/JSON，并按负责人路由事件。首份源码快照建立基线。使用 `--once` 执行一轮，或使用 `--no-update` 只观察本地变化、不拉取。

自动发现利用明确的仓库/软件包引用，并将其记录为推断关系，不是已经证明的行为依赖。需要审查生成的图：隐藏的运行时、硬件和数据依赖仍需手工契约。新增仓库或刷新推断关系时，重新运行 `init` 输出到新文件；初始化拒绝覆盖已审查配置。

## 快速开始

在项目根目录执行。最小示例包含两个小型源码契约，无需外部仓库。

1. 安装到隔离环境：

   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   python -m pip install .
   ```

2. 采集并验证示例：

   ```bash
   robot-workflow snapshot --config examples/minimal/workflow.json \
     --root examples/minimal/repositories --output /tmp/robot-baseline.json
   robot-workflow verify --snapshot /tmp/robot-baseline.json \
     --output /tmp/robot-evidence.json
   robot-workflow compare --before /tmp/robot-baseline.json \
     --after /tmp/robot-baseline.json --evidence /tmp/robot-evidence.json \
     --output /tmp/robot-report.json --html /tmp/robot-workflow.html
   ```

3. 用浏览器打开 `/tmp/robot-workflow.html`。关节顺序需求应显示已验证，源码影响应为空。
4. 如需试验变更，修改示例机器人 `model.json` 中的 `joint_order`，将新快照写入 `/tmp/robot-candidate.json`，然后对比基线与候选。重新运行 `verify` 检查新关节顺序关系。试验后恢复示例修改。

生成的报告、源码快照和日志必须放在仓库之外。

## 接入自己的工作流

从[最小配置](examples/minimal/workflow.json)开始。每个节点拥有声明的源码 glob；每条边声明关注哪些上游类别，以及哪些下游类别可能需要重新验证。

```json
{
  "from": "robot",
  "to": "policy",
  "watch": ["kinematics", "joint_order"],
  "emits": ["data"],
  "reason": "Policy FK and joint mapping consume the robot model"
}
```

1. 添加仓库，路径相对于 checkout 根目录。
2. 使用支持的解析器添加组件与源码 glob。
3. 声明依赖边并审查依据。关系由团队显式登记和维护。
4. 对适合确定性相等检查的需求添加源文件断言。
5. 使用同一依赖图采集基线/候选快照；对比并审查候选后，再更新版本组合。

解析类别、断言、覆盖和证据语义见[架构与配置](docs/architecture.zh-CN.md)。依赖图配置变更需要独立审查：工具拒绝对比不同图配置的两个快照，以免悄然丢失依赖。

## 命令与状态

| 命令 | 用途 |
|---|---|
| `serve --root DIR --state-dir DIR [--config FILE] [--port 8780]` | 启动本机网页工作台；配置默认位于 STATE_DIR/workflow.json |
| `setup [--root DIR] [--state-dir DIR] [--yes] [--no-open]` | 引导本地设置、审查依赖并生成首份报告 |
| `doctor --config FILE --root DIR` | 解释本地设置与覆盖问题 |
| `open --state-dir DIR` | 打开最新监测报告 |
| `init --root DIR --output FILE [--owner NAME] [--webhook-env ENV] [--route OWNER=ENV]` | 发现已有 checkout 并生成新的可编辑配置 |
| `start --root DIR --state-dir DIR [--interval 30] [--once] [--no-update]` | 首次初始化，然后使用已保存配置监测 |
| `sync --config FILE --root DIR` | 获取并快进更新符合条件的现有 checkout |
| `watch --config FILE --root DIR --state-dir DIR [--interval 30] [--once] [--no-update]` | 保存影响报告并按负责人路由变更事件 |
| `fetch --config FILE --root DIR` | 按声明的源码 glob 新建稀疏 GitHub clone；不会替换已有目录 |
| `snapshot --config FILE --root DIR --output FILE [--label NAME]` | 记录实际本地源码状态与溯源 |
| `verify --snapshot FILE --output FILE [--run-checks --root DIR] [--evidence FILE]` | 执行声明的相等断言并记录绑定证据 |
| `compare --before FILE --after FILE --output FILE [--evidence FILE] [--html FILE] [--fail-on-impact]` | 分析候选变化，可选生成 HTML / CI 门禁 |
| `cases sync/list/update --state FILE` | 同步、查看、认领或处理绑定候选快照的变更项 |
| `report --input FILE --output FILE` | 将已有影响报告 JSON 渲染为独立 HTML |

退出码：`0` 表示完成；`1` 表示输入错误或操作失败；`2` 表示断言失败、影响门禁触发或保护性跳过同步。影响门禁采用保守策略：源码语义变化、覆盖未知和未登记变化均需要审查。它不是不兼容分类器。

| 状态 | 含义 |
|---|---|
| `changed` | 登记源码的语义发生变化 |
| `potential_impact` | 声明的依赖路径将候选变化连接到该组件 |
| `no_registered_impact` | 当前图中没有匹配路径；兼容性仍未证明 |
| `unknown` | 所需源码缺失/无效，或变化位于登记契约之外 |
| `verified` / `failed` | 声明检查在当前依赖绑定下通过/失败 |
| `stale` | 相关输入、检查定义或支持的绑定发生变化 |
| `unverified` | 没有记录当前证据 |

## 边界与后续方向

- 默认的发现、监测和源码验证不执行被检查代码。`verify --run-checks --root DIR` 显式执行配置的命令；运行器不是沙箱，不会自动调度 ROS、训练或真机任务。
- 图由声明构建。Python AST 变化是保守的语义变化信号，不能证明行为变化。YAML 使用词法提取器，而非完整 YAML 解析器。
- H5、checkpoint tensor layout、外部校准、时序行为和真实执行器映射需要额外提取器或外部验证。源码 manifest 建立声明的源码契约；物理需求需要外部证据。
- 0.5.0 提供依赖发现、轮询、安全同步与通用出站 Webhook；网页工作台可编辑负责人和发现的依赖；尚未包含通用图编辑器、GitHub Webhook 接收器、CAD/PLM 集成或 AI agent。
- 证据记录声明检查的实际范围，包括源码断言、接口相等和显式命令结果；不是签名证明，不能自动推断仿真、真机安全或 Sim2Real 成功。报告可能包含源码片段，外部分享前应审查。
- 固定版本的现有部署不会改变。报告分析沿声明的工程关系采用候选版本的影响，其中也包含规划中的接口。
- 当前提供端口声明、按依赖范围绑定的证据和本地网页操作；领域提取器、团队认证与 PR 集成仍是后续工作。

## 契约、命令检查与变更处理

0.5.0 的接口检查和处理状态继续使用配置 schema 1；原有配置无需新增字段即可使用。`interface_contracts` 对比提供者与消费者的显式字段；`validation_checks` 定义需要显式执行的命令。未执行的命令显示 unknown，不能被其他通过的源码检查覆盖。

`cases sync/list/update` 管理待处理、已认领、已处理、已排除状态；关闭需要说明。监测自动生成本地处理项，报告可嵌入处理状态。认领或关闭通过 CLI 或本地控制台完成，离线页面仅展示；已处理不等于兼容性验证通过。配置示例和完整命令见[用户说明书](docs/user-guide.zh-CN.md#契约命令检查与变更处理)。

## 端口与精确重测

声明节点的 `kind` 和可选 `ports`，再用 `from_port`/`to_port` 连接输出/输入端口 ID。接口视图比较配置声明，不产生运行证据。字段格式见[架构说明](docs/architecture.zh-CN.md#工程对象与端口)。

传入旧证据，可复用声明依赖和定义仍有效的检查：

```bash
robot-workflow verify --snapshot /tmp/robot-candidate.json \
  --evidence /tmp/robot-evidence.json --output /tmp/robot-candidate-evidence.json
```

报告逐需求列出 `reuse`、`run` 或 `not_configured`，以及检查 ID 和原因。相关字段或命令输入改变使证据过期；无关源码变化可以保留证据。命令复用保守检查所选仓库全部跟踪、未跟踪和忽略文件、工具实现、环境变量摘要以及命令程序身份；稀疏或不可读输入显示 unknown。它不覆盖所有外部服务、系统依赖或硬件状态。`--run-checks --root DIR` 显式执行无法复用的检查；强制重测时省略 `--evidence`。没有范围字段的旧证据仍绑定其精确快照。

## 开发与许可证

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/check_docs.py
```

参见[贡献规范](CONTRIBUTING.zh-CN.md)和[实现范围](docs/spec.zh-CN.md)。工具采用 [Apache-2.0](LICENSE)。上游仓库仍分别遵循其许可证；本项目不重新分发其源码、模型、截图、训练日志或历史备份。

工程记录方向参考 [Flow Systems Graph](https://www.flowengineering.com/product/systems-graph)。这是独立实现，与 Flow Engineering 无关联。

下一步建议和验收标准见 [Flow 产品对照与改进优先级](docs/flow-comparison.zh-CN.md)。这些建议属于计划方向，尚未实现。
