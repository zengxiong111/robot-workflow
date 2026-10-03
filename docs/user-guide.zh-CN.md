# Robot Workflow 用户说明书

[English](user-guide.md)

适用版本 0.5.0。用于搭建、审查和监测团队工程工作流的操作指南。

## 目录

- [用途与团队协作](#用途与团队协作)
- [安装与目录准备](#安装与目录准备)
- [本地网页工作台](#本地网页工作台)
- [引导式设置](#引导式设置)
- [首次运行内置示例](#首次运行内置示例)
- [创建自己的工作流](#创建自己的工作流)
- [审查依赖与源码契约](#审查依赖与源码契约)
- [监测与同步仓库](#监测与同步仓库)
- [配置负责人 Webhook](#配置负责人-webhook)
- [通知内容与投递行为](#通知内容与投递行为)
- [阅读报告与状态文件](#阅读报告与状态文件)
- [新增仓库与修改配置](#新增仓库与修改配置)
- [固定基线对比与 CI](#固定基线对比与-ci)
- [契约、命令检查与变更处理](#契约命令检查与变更处理)
- [端口与精确重测](#端口与精确重测)
- [故障排查与能力边界](#故障排查与能力边界)
- [相关文档](#相关文档)

## 用途与团队协作

Robot Workflow v0.5.0 是以 Git 记录版本、同步源码的工程依赖与变更影响工具。通过经过审查的依赖图连接机器人模型、数据、训练、感知和部署；读取本地源码、记录指纹、比较版本，并指出需要复核的组件。Git 提供提交与同步，JSON 依赖图提供工程关系。

它帮助团队回答谁需要复核、为什么可能受影响，以及哪些源码检查已有证据。默认发现和监测不执行被检查代码；显式命令检查需要 `--run-checks`。源码断言通过不代表物理任务成功。

| 角色 | 职责 |
| --- | --- |
| 工作流维护者 | 审查依赖、文件覆盖和配置变更 |
| 组件负责人 | 维护源码契约、负责人名称和待验证项 |
| 集成负责人 | 审阅报告，安排仿真与硬件验证 |
| 通知服务负责人 | 接收 JSON 事件、去重并转发消息 |

## 安装与目录准备

需要 Python 3.11+；发现仓库与同步时需要 Git。无需 AI 服务、ROS 或仿真器。以下命令使用 POSIX shell；可替换 `$HOME/robot-workflow-lab`，但后续路径必须保持一致。

工具源码、被检查仓库和工作流状态分开放置。状态目录必须位于整个 `repos` 根目录之外，不能只放在某一个 checkout 之外。私有仓库认证沿用已有 Git 配置。

1. 克隆工具，安装至仓库外的虚拟环境。
2. 本说明书描述 `0.5.0`。安装后检查版本；默认分支未来可能更新。
3. 后续命令继续使用已激活环境。

```bash
mkdir -p "$HOME/robot-workflow-lab"
cd "$HOME/robot-workflow-lab"
git clone https://github.com/zengxiong111/robot-workflow.git tool
python3 -m venv env
. env/bin/activate
python -m pip install ./tool
python -c 'import robot_workflow; print(robot_workflow.__version__)'
robot-workflow --help
```

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

## 首次运行内置示例

在 `$HOME/robot-workflow-lab` 下采集快照、验证声明的关节顺序相等关系，并生成报告。输出位于工具仓库之外，无需外部仓库或通知地址。

使用浏览器打开 `demo/workflow.html`。预期无源码变化，关节顺序需求为 verified。此结果只验证声明的 JSON 源码关系，不验证机器人行为。

```bash
mkdir -p demo
robot-workflow snapshot --config tool/examples/minimal/workflow.json   --root tool/examples/minimal/repositories --output demo/baseline.json
robot-workflow verify --snapshot demo/baseline.json --output demo/evidence.json
robot-workflow compare --before demo/baseline.json --after demo/baseline.json   --evidence demo/evidence.json --output demo/report.json --html demo/workflow.html
```

## 创建自己的工作流

工作目录为 `$HOME/robot-workflow-lab`。将已有 Git checkout 放到 `repos` 下，例如 `repos/robot-description` 和 `repos/policy-runtime`。可以嵌套；`--root` 指向父目录，不是单个 checkout。开始监测前用 Git 选择各仓库分支。使用你真实的仓库即可，无需执行包含虚构远端的 clone 命令。

1. 生成配置，此步骤不更新源码。
2. 审查 `state/workflow.json` 的负责人、artifact、推断边方向及 `discovery.notes`。
3. 用 `--no-update` 执行一轮本地观察。
4. 阅读生成的 JSON/HTML，再启用同步。

首次观察建立基线。`init` 拒绝覆盖已有输出文件。目前默认每仓库生成一个节点；需要时编辑配置，将同一仓库拆成多个组件。

```bash
mkdir -p repos state
robot-workflow init --root "$PWD/repos" --output "$PWD/state/workflow.json"   --project "My Robot Workflow" --owner robotics
robot-workflow watch --config "$PWD/state/workflow.json"   --root "$PWD/repos" --state-dir "$PWD/state" --once --no-update
```

## 审查依赖与源码契约

### 理解配置

| 字段 | 含义 |
| --- | --- |
| `repositories[].id` / `path` | 稳定标识 / 相对 `--root` 的 checkout 路径 |
| `nodes[].repository` / `owner` | 仓库标识 / 负责团队的通知路由名称 |
| `nodes[].artifacts[]` | 相对该仓库的文件 glob 与解析器 |
| `edges[].from` / `to` | 提供者 → 消费者；上游变化可能影响下游 |
| `edges[].watch` / `emits` | 关注的输入语义类别 / 继续向下游传播的类别 |
| `edges[].reason` / `basis` | 工程原因 / 证据或推断关系依据 |
| `nodes[].checks` | 复核提醒，不会自动执行这些命令 |
| `requirements[]` | 命名需求，可含确定性的相等断言 |

自动发现考虑明确的 GitHub 身份、本地路径、软件包声明和 submodule。README 链接可能产生相反或过度推断的工程关系。应与组件负责人逐条审查。

### 明确选择覆盖范围

自动发现每仓库最多选 80 个受支持 artifact，每 checkout 最多扫描 20,000 个文件，跳过超过 1,000,000 字节的文件；排除部分生成目录、测试和 vendor 目录。这些限制不同于快照 artifact 的 `max_bytes`，后者默认 4,000,000。

登记真正定义契约的文件。手工支持的解析器为 `urdf`、`python`、`json`、`toml`、`yaml`、`ros`、`markdown`、`text`、`binary`。YAML 是保守词法分析，binary 仅记录哈希。纯文档仓库存在实际文档时现会登记文档；无受支持源码或文档时可能得到缺失占位文件：应换成实际文档，使用 `markdown` 并选择预期 facet。缺失文件在修正前应保持 unknown。

下方完整示例描述两个组件和一个相等需求。可另存配置，配合内置示例的仓库根目录运行；也可按自己的源码路径调整。两个断言路径都必须登记为 artifact。

```json
{
  "schema_version": 1,
  "project": "Joint mapping workflow",
  "repositories": [
    {"id": "robot", "path": "robot"},
    {"id": "policy", "path": "policy"}
  ],
  "nodes": [
    {"id": "robot", "label": "Robot model", "repository": "robot", "owner": "model-team",
     "artifacts": [{"glob": "model.json", "parser": "json"}]},
    {"id": "policy", "label": "Policy runtime", "repository": "policy", "owner": "policy-team",
     "artifacts": [{"glob": "input.json", "parser": "json"}],
     "checks": ["Validate named actuator mapping"]}
  ],
  "edges": [
    {"from": "robot", "to": "policy", "watch": ["data"], "emits": ["data"],
     "reason": "Policy input consumes robot joint order"}
  ],
  "requirements": [
    {"id": "joint-order", "title": "Joint orders match", "nodes": ["robot", "policy"],
     "assertions": [
       {"id": "order", "source": {"node": "robot", "path": "model.json", "pointer": "/data/joint_order"},
        "equals_source": {"node": "policy", "path": "input.json", "pointer": "/data/joint_order"}}
     ]}
  ]
}
```

## 监测与同步仓库

配置审查后，在 lab 目录启动连续监测。Ctrl+C 停止前台进程；恢复时使用相同根目录、配置和状态目录重新运行。默认间隔 30 秒，网络和分析耗时会增加延迟。本版本没有后台服务或 GitHub push 接收器。

`watch` 采集源码，按需 fetch 并快进符合条件的 checkout，比较、验证源码断言、写入报告和事件，然后更新基线。每轮对比上一轮，不会始终对比首次批准的发布版本。需要固定发布基线时应保留显式快照。

`--once` 运行一轮；`--no-update` 只观察本地变化，不拉取。`start` 是快捷入口，仅在不存在时创建 `state-dir/workflow.json`，然后监测；已有配置会复用，初始化参数不会替换其中的负责人或路由。

| 同步状态 | 操作 |
| --- | --- |
| `current` / `updated` | 远端无新提交 / 已完成快进 |
| `dirty` | 有本地修改；工具不 stash 或 reset |
| `detached` | 无活动分支，手动选择预期分支 |
| `diverged` | 本地历史不是远端祖先，按正常 Git 审查流程解决 |
| `no_upstream` | 配置预期 tracking branch；声明 `ref` 仅在存在分支 remote 时可帮助同步 |
| `error` | 检查远端认证、网络或 checkout 可用性 |

存在 upstream 时同步沿当前分支 upstream 执行；配置 `ref` 不会强制切换或固定分支。同步跳过或失败会让相关覆盖变成 unknown。仅需更新结果时，单独运行 `sync`。

```bash
robot-workflow watch --config "$PWD/state/workflow.json"   --root "$PWD/repos" --state-dir "$PWD/state" --interval 30

robot-workflow sync --config "$PWD/state/workflow.json" --root "$PWD/repos"
```

## 配置负责人 Webhook

编辑配置前停止监测。在顶层加入下方 `notifications` 对象，为节点 `owner` 填写对应名称。审查配置变更后使用新状态目录。URL 密钥只放环境变量，不写入 JSON。

默认地址接收事件全部负责人，负责人路由接收映射到该地址的负责人；相同 URL 合并投递。通用 Webhook 是 HTTP JSON 接收接口，Slack、飞书等专用格式需要自己的适配服务。本版本没有内置自定义认证 header 或 payload 模板。

启动进程前设置环境。将 `https://notify.example.org/...` 替换为自己的接收地址；它们是占位符，不是可用服务。没有配置目标时事件保留本地；配置了环境变量名称但没有赋值时，事件保留队列重试。

```json
{
  "notifications": {
    "webhook_env": "WORKFLOW_WEBHOOK_URL",
    "recipients": {
      "model-team": "MODEL_TEAM_WEBHOOK_URL",
      "policy-team": "POLICY_TEAM_WEBHOOK_URL"
    }
  }
}
```

```bash
export WORKFLOW_WEBHOOK_URL='https://notify.example.org/workflow'
export MODEL_TEAM_WEBHOOK_URL='https://notify.example.org/model'
export POLICY_TEAM_WEBHOOK_URL='https://notify.example.org/policy'
robot-workflow watch --config "$PWD/state/workflow.json"   --root "$PWD/repos" --state-dir "$PWD/state-notify" --interval 30
```

## 通知内容与投递行为

| Payload 字段 | 含义 |
| --- | --- |
| `event_id` / `created_at` | 去重标识 / UTC 创建时间 |
| `owners` / `impacts` | 路由负责人 / 组件状态及代表性路径 |
| `source_commits` | 实际采集的仓库 commit |
| `baseline` / `candidate` | 对比的快照身份 |
| `summary` | 变化、未知和未登记变化计数 |
| `sync_errors` / `sync_warnings` | 同步失败或跳过 |
| `report` | 本地 JSON 报告路径，不是远端下载 URL |

语义变化、覆盖未知、未登记变化或同步警告会触发事件。仅修改被忽略格式的 commit 可能不产生事件。单独的需求失败不是独立通知触发条件；通知之外仍需查看报告需求。

接收器应返回 HTTP 2xx，并按 `event_id` 去重。重定向被拒绝，请求超时为 8 秒，失败投递在后续轮询重试。跨崩溃投递语义为至少一次，不保证恰好一次；相同状态事件在本地去重。

`pending_notifications=0` 可能仅表示本地处理，不表示外部服务收到。验证接收器时，在可丢弃 checkout 中做经过审查的可恢复变更，确认接收端 event ID，再恢复。不要通过修改运行中机器人的源码测试。

## 阅读报告与状态文件

打开最新 `report-*.json` 对应的 HTML。每轮产生新报告；已经打开的报告不会实时刷新。用浏览器打开下一份报告，或导入更新后的报告 JSON。离线 UI 提供图选择、搜索/过滤、缩放、组件检查面板、变化、需求和版本信息，不编辑工作流配置。

| 状态 | 解读 |
| --- | --- |
| `changed` | 已登记源码语义发生变化 |
| `potential_impact` | 声明的路径需要复核或重新验证 |
| `no_registered_impact` | 当前图没有匹配路径，不证明兼容 |
| `unknown` | 无法确认必要覆盖或远端新鲜度 |
| `verified` / `failed` | 此快照上的源码相等断言通过 / 失败 |
| `stale` | 提供的证据与当前身份不再匹配 |
| `unverified` | 未记录有效证据 |

| 状态文件 | 用途 |
| --- | --- |
| `baseline.json` | 最近一轮采集结果，报告/事件持久写入后更新 |
| `root-identity.json` | 被检查根目录绑定 |
| `report-*.json` / `.html` | 每轮分析 / 离线视图 |
| `events.jsonl` | 本地有意义事件，无事件时可能不存在 |
| `notification-queue.json` | 待投递状态 |
| `.watch.lock` | 状态目录进程锁 |
| `workflow.json` | 由 `start` 创建，或由自己的 `init` 命令放在此处 |

报告可能包含选定源码差异，私有报告应保持私有。监测输出随轮询增长：停止监测后，将必要证据保留在仓库外，按团队保留策略管理存储。不要删除活动基线或队列来清除警告。

画布根据节点位置自动调整边界，默认显示选中组件的相关连线；用连线视图切换本次影响路径或全部依赖。点击组件，先查看路径和待验证项，再展开“源码与登记文件”查看文件清单。报告提供的分区只是展示分组，不证明实际运行顺序。 连线区分输入和输出依赖；放大的箭头指向接收依赖的组件。长连线采用分开的通道，并用白色描边区分交叉处。
输入和输出视图以选中组件为基准：蓝色连线表示上游输入依赖，橙色表示下游输出依赖，灰色虚线表示其他关系；粗线表示本次变更涉及的路径。方向选项可以同时显示两侧，或只看输入、输出。详情面板分开列出直接输入依赖和输出影响，可展开的路径清单来自既有分析结果。登记依赖表示潜在影响关系，不代表接口已失败或已通过。在循环依赖中，一条关系可能同时属于两侧；间接关系的颜色优先按输入显示。

## 新增仓库与修改配置

1. Ctrl+C 停止运行中的监测。
2. 将新 checkout 放在相同根目录下，选择预期分支/upstream。
3. 用新文件名运行 `init`，将发现结果与已审查图整合，保留手工负责人、依赖、断言和契约。
4. 与负责人审查方向、artifact 是否存在及覆盖范围。
5. 用修订配置和新状态目录启动 `watch`。

修改负责人/路由、artifact 或依赖也采用此流程：配置身份属于快照绑定。已有状态在同步前拒绝配置变化。新状态建立新基线，不会自动比较新旧依赖图。处理待投递事件和必要证据前，不要删除旧状态。

```bash
robot-workflow init --root "$PWD/repos" --output "$PWD/workflow-proposed.json"   --project "My Robot Workflow" --owner robotics
# Review and reconcile workflow-proposed.json before running the next command.
robot-workflow watch --config "$PWD/workflow-proposed.json"   --root "$PWD/repos" --state-dir "$PWD/state-revised" --once --no-update
```

## 固定基线对比与 CI

发布审查时，用完全相同的已审查配置采集显式基线和候选。先采集批准基线，再单独实施或 checkout 预期源码变化，采集候选并验证。下方假设已审查配置在 `state/workflow.json`；命令不负责实施源码变更。

`--fail-on-impact` 对语义变化、覆盖未知或未登记变化返回 2，是保守审查门禁，不是兼容性分类器。`verify` 单独对相等断言失败返回 2；`compare --fail-on-impact` 不是通用断言失败门禁。CI 应分别记录并检查两者。

| 退出码 | 含义 |
| --- | --- |
| 0 | 命令完成，仍需检查报告状态 |
| 1 | 输入或操作错误 |
| 2 | `verify` 断言失败、`compare` 影响门禁或 `sync` 保护性跳过 |

`watch` 可能在一轮包含同步警告时仍以 0 结束；应查看打印的 `sync` 和报告。

```bash
mkdir -p release-review
robot-workflow snapshot --config state/workflow.json --root "$PWD/repos"   --output release-review/baseline.json --label approved
# Apply or check out the intended source change separately before continuing.
robot-workflow snapshot --config state/workflow.json --root "$PWD/repos"   --output release-review/candidate.json --label candidate
robot-workflow verify --snapshot release-review/candidate.json   --output release-review/evidence.json
robot-workflow compare --before release-review/baseline.json   --after release-review/candidate.json --evidence release-review/evidence.json   --output release-review/report.json --html release-review/report.html --fail-on-impact
```

## 契约、命令检查与变更处理

为已有图增加契约和检查。下面是配置片段：先登记 `camera`、`pose` 组件和 `pose` 仓库，增加涉及这两个组件的 `pose-contract` 需求，并将两个实际 `contract.json` 文件作为 `json` 产物登记。`/data` 是 JSON 解析器的提取根，字段 pointer 相对于该根；名字不隐含单位转换或坐标变换。

```json
{
  "interface_contracts": [{
    "id": "pose-fields", "requirement": "pose-contract",
    "producer": {"node": "camera", "path": "contract.json", "pointer": "/data"},
    "consumer": {"node": "pose", "path": "contract.json", "pointer": "/data"},
    "fields": [{"name": "frame", "pointer": "/frame"}, {"name": "units", "pointer": "/units"}]
  }],
  "validation_checks": [{
    "id": "pose-tests", "requirement": "pose-contract", "repository": "pose",
    "argv": ["python3", "-B", "-m", "unittest", "discover", "-s", "tests"],
    "timeout_seconds": 60
  }]
}
```

1. 源码断言和契约比较默认执行；缺失字段为 unknown，不匹配为 fail。
2. 命令只在 `--run-checks` 下执行，并要求 `--root`。配置中的测试必须事先存在；运行器不是沙箱，只配置已审查的检查命令。默认超时 60 秒，上限 3600 秒；每个输出流最多展示 4000 字节。外部命令退出码非零为 fail，超时、执行器缺失、源码变动或覆盖缺失为 unknown。
3. 同一需求所有声明检查合并，任何 fail 保留 fail，否则任何 unknown 保留 unknown。未执行的命令不能因为源码断言通过而变成 verified。`verify` 遇到 fail 或 unknown 返回 2，配置/调用错误返回 1。
4. 监测自动维护源码根之外的 `cases.json`；也可手工同步已有影响报告。处理项 ID 绑定候选快照和组件，重复同步保留负责人、状态、说明和带操作者/时间的转换记录。
5. 用 CLI 认领或处理；`CASE_ID` 取自 list 输出，`OWNER` 替换为实际操作者。关闭必须有说明；重新打开用 `--status open`。`resolved` 是人工处理结论，不会修改验证状态；`dismissed` 同样需要理由。离线报告显示状态，不能直接写回状态文件。

```bash
robot-workflow snapshot --config "$HOME/robot-workflow-lab/state/workflow.json" \
  --root "$HOME/robot-workflow-lab/repos" --output /tmp/candidate.json
robot-workflow verify --snapshot /tmp/candidate.json \
  --root "$HOME/robot-workflow-lab/repos" --run-checks --output /tmp/evidence.json
robot-workflow compare --before /tmp/candidate.json --after /tmp/candidate.json \
  --evidence /tmp/evidence.json --output /tmp/verified-report.json
robot-workflow cases sync --input /tmp/verified-report.json \
  --state "$HOME/robot-workflow-lab/state/cases.json"
robot-workflow cases list --state "$HOME/robot-workflow-lab/state/cases.json"
robot-workflow cases update --state "$HOME/robot-workflow-lab/state/cases.json" \
  --id CASE_ID --status claimed --actor OWNER
robot-workflow cases update --state "$HOME/robot-workflow-lab/state/cases.json" \
  --id CASE_ID --status resolved --actor OWNER --note "Reviewed evidence and recorded disposition"
robot-workflow report --input /tmp/verified-report.json \
  --cases "$HOME/robot-workflow-lab/state/cases.json" --output /tmp/verified-report.html
```

上述 compare 对比同一快照，只展示该候选的检查结果；变更分析应改用真正的基线。没有变更/未知组件的报告不会生成处理项。报告展示的状态是生成时快照，CLI 更新后需重新生成报告。

需要从本地 checkout 安装时，使用下面命令；路径为工具源码占位符。既有 schema 1 配置仍可使用，不添加 `validation_checks` 就不会声明命令检查。

```bash
python -m pip install /path/to/local/robot-workflow
python -c 'import robot_workflow; print(robot_workflow.__version__)'
```

## 端口与精确重测

声明节点的 `kind` 和可选 `ports`，再用 `from_port`/`to_port` 连接输出/输入端口 ID。接口视图比较配置声明，不产生运行证据。字段格式见[架构说明](architecture.zh-CN.md#工程对象与端口)。

传入旧证据，可复用声明依赖和定义仍有效的检查：

```bash
robot-workflow verify --snapshot /tmp/robot-candidate.json \
  --evidence /tmp/robot-evidence.json --output /tmp/robot-candidate-evidence.json
```

报告逐需求列出 `reuse`、`run` 或 `not_configured`，以及检查 ID 和原因。相关字段或命令输入改变使证据过期；无关源码变化可以保留证据。命令复用保守检查所选仓库全部跟踪、未跟踪和忽略文件、工具实现、环境变量摘要以及命令程序身份；稀疏或不可读输入显示 unknown。它不覆盖所有外部服务、系统依赖或硬件状态。`--run-checks --root DIR` 显式执行无法复用的检查；强制重测时省略 `--evidence`。没有范围字段的旧证据仍绑定其精确快照。

## 故障排查与能力边界

| 现象 | 处理 |
| --- | --- |
| 未发现 Git checkout | 使用父目录根；确保其下有实际 checkout，而非仅有 URL |
| 配置已存在 | 初始化到新文件名，保留已审查配置 |
| 配置与基线不一致 | 审查新图，然后使用新状态目录 |
| 状态绑定其他根目录 | 每个源码根使用独立状态目录 |
| 状态目录被拒绝 | 放到整个源码根之外 |
| artifact 覆盖未知 | 检查 glob、解析器、大小、语法、稀疏检出和未解析 LFS pointer |
| 纯文档仓库未知 | 将占位 glob 换成实际 `markdown`/`text` 契约 |
| commit 更新但无事件 | 检查语义变化及未登记文件，仅格式变化可能不触发 |
| 通知待投递 | 检查配置环境变量名称、进程环境、HTTP 接收器与队列错误 |
| 无通知且 pending=0 | 确认发生事件并配置了真实目标 |
| 旧 HTML 仍显示以前状态 | 打开新生成的 HTML；报告是静态文件 |

工具不能完整发现运行时/数据/硬件依赖、解释 checkpoint tensor 或 H5 语义、批准部署，或证明 Sim2Real 安全。二进制哈希能检测身份变化，不能证明行为。此类决策需要源码契约和明确的外部测试。

目前发现结果需要审查，尤其 artifact 上限、纯文档覆盖和引用方向。先维护关键依赖、精确契约及约定负责人，再扩展覆盖。报告结论受已知依赖图限制。

## 相关文档

- [快速开始与命令参考](../README.zh-CN.md)。
- [架构、解析器与断言语义](architecture.zh-CN.md)。
- [内置完整最小配置](../examples/minimal/workflow.json)。
- [贡献规范](../CONTRIBUTING.zh-CN.md)。

本说明书为通用指南，不包含机器人团队私有仓库配置或验证输出。未另行授权分享时，此类案例应留在本地工作目录。
