# 架构与配置

[English](architecture.md)

本文规定 0.4.0 的工程依赖图、快照、影响与证据边界。配置采用 JSON；运行依赖为 Python 3.11+，记录 Git 溯源时需要 Git。

## 目录

- [数据流](#数据流)
- [配置](#配置)
- [提取器](#提取器)
- [影响与版本语义](#影响与版本语义)
- [证据与覆盖](#证据与覆盖)
- [集成与扩展](#集成与扩展)

- [依赖发现与监测](#依赖发现与监测)

## 数据流

```text
workflow.json + local checkouts
              │
           snapshot
              │
      baseline / candidate JSON
              │
     compare ← source assertions (verify)
              │
     impact JSON → offline HTML
```

源码按数据解析，不导入 Python 文件，不执行机器人代码、训练入口或 ROS 节点。只有 `fetch` 创建 checkout；snapshot/compare/report 命令不修改输入仓库。

## 配置

| 字段 | 含义 |
|---|---|
| `schema_version` | 必须为 `1` |
| `project` | 报告标题 |
| `repositories[]` | 唯一 `id`、相对 `path`，可选 GitHub HTTPS `.git` URL 与 branch/tag `ref` |
| `nodes[]` | 唯一 `id`、`repository`、`label`，可选 `label_zh`、`description`、`description_zh`、`stage`、`position`、`owner`、`readiness`、`checks` |
| `nodes[].artifacts[]` | 仓库相对 `glob`、支持的 `parser`，可选 `facet` 覆盖与 `max_bytes`（默认 4,000,000） |
| `edges[]` | `from`、`to`、非空 `watch` 与 `emits` 数组、解释用 `reason`，可选关系 `basis` |
| `requirements[]` | 唯一 `id`、`title`、涉及的 `nodes`，可选源码相等 `assertions` |

`readiness` 是包含 `state`（`implemented`、`partial`、`planned`、`unknown`）、`summary`、可选 `summary_zh`，以及源码审查绑定 `reviewed_commit` / `reviewed_fingerprint` 的记录。没有绑定时显示 `unverified`，绑定变化时显示 `stale`。它是维护者的源码审查，与执行证据分开。

仓库路径与 artifact glob 不能使用绝对路径或 `..`。源码符号链接不能越出仓库或指向 `.git`。glob 无匹配、文件超限、语法无效和未解析的 LFS pointer 都会造成覆盖未知。

同一个文件可以登记在不同组件中。避免在同一组件内使用解析器不同的重叠 glob；当前由最后匹配的声明决定其表示。

## 提取器

| 解析器 | 类别 | 说明 |
|---|---|---|
| `urdf` | `joint_order`、`kinematics`、`dynamics`、`visuals`、`extensions` | 关节/link 定义、限位、惯性/碰撞元素和根级扩展；保守处理 XML 值 |
| `python` | `implementation`、`symbols` | 去除 module/class/function docstring 的 AST；忽略注释与格式，不导入代码 |
| `json` | `data` | 解析结构；忽略对象键顺序，保留列表顺序 |
| `toml` | `config` | 标准库 TOML 解析器 |
| `yaml` | `config` | 保守的行提取；忽略空行和独立注释，保留缩进与行内内容 |
| `ros` | `interface` | `.msg` / `.srv` / `.action` 字段行、分隔符和常量；忽略注释 |
| `markdown` | `documentation` | 标准化换行；只有关注该类别的依赖才会传播变化 |
| `text` | `content` | 标准化换行 |
| `binary` | `artifact` | 只计算 SHA-256，不解释结构或 tensor |

artifact 的 `facet` 覆盖会将提取值嵌套在指定类别下。例如可将架构 README 登记为 `interface`，但随后其所有修改都保守地需要接口审查。这适用于规划契约，精度低于结构化 schema。

原始文件 SHA-256 与语义类别哈希分别记录。契约之外超过 4,000,000 字节的工作文件使用 size/mtime 元数据，并明确标记为 `unhashed_large_file`；如需内容覆盖，登记该文件并提高 `max_bytes`。URDF 中数值文本的不同写法即使物理等价，也可能触发审查。通用 AST 差异不能证明行为回归。

## 影响与版本语义

1. 使用相同配置对比登记产物。
2. 为每个变化的语义类别建立传播起点。
3. 当边的 `watch` 包含该类别或 `*` 时沿边传播。
4. 在消费者处，以其 `emits` 类别继续沿后续边传播。
5. 记录代表性路径和依据；通过已访问 node/facet 集合限制遍历，环路会终止。
6. 将源码覆盖缺失沿声明的下游依赖传播为 unknown。
7. 将登记产物之外的已跟踪和未忽略的未跟踪 Git/文件清单变化列为未分类变化，不会悄然视为兼容。

工具分析候选版本升级。依赖描述工程关系，不意味着运行中的部署跟随上游默认分支。现有固定版本组合不会改变。Vendored policy 有独立溯源，不能假设它采用每个上游训练 commit。

`potential_impact` 表示需要审查或重新验证。相等断言失败表示确认的源码契约不一致，不自动等于物理任务失败。`no_registered_impact` 的结论受依赖图覆盖范围限制。界面不会声称枚举了所有可能路径。

## 证据与覆盖

需求可以用源节点、产物路径和指向提取类别的 JSON Pointer 声明相等断言：

```json
{
  "id": "actor-input",
  "source": {
    "node": "policy",
    "path": "models/manifest.json",
    "pointer": "/data/actor/layers/0"
  },
  "equals": 134
}
```

使用 `equals_source` 替代 `equals` 可与另一提取源对比。JSON Pointer 支持列表索引和 `~0` / `~1` 转义。

`verify` 输出需求 ID、结果、检查详情、精确快照 ID，以及需求涉及的全部组件指纹。`compare --evidence` 仅在绑定均匹配时将记录作为当前证据。候选快照任何位置发生变化，都会保守地让旧记录过期。没有声明检查的需求保留为未验证；源码覆盖缺失时，即使断言通过也显示 unknown。

快照 ID 对依赖图、仓库溯源和采集源码状态进行哈希，可发现意外修改，但不是签名或可信证明。证据 JSON 可以由外部编写，因此使用前必须审查。

### 显式契约、命令与处理项

`interface_contracts` 在需求涉及的组件间对比提取字段，返回 pass/fail/unknown。`validation_checks` 的 argv 通过 `shell=False` 在指定仓库运行；默认跳过并记录 unknown。`verify --run-checks --root DIR` 核对执行前后完整快照身份；超时、执行器缺失、源码变动或覆盖缺失均为 unknown。输出截取为每流 4000 字节；默认超时 60 秒，上限 3600 秒。POSIX 超时终止本次进程组，Windows 仅终止本次主进程。

同一需求的检查合并：任何 fail 保留 fail，否则任何 unknown 保留 unknown，全部 pass 才通过。当前绑定仍以完整快照为粒度。变更处理状态单独存放在源码根目录外，通过文件锁和原子替换更新；报告只显示候选身份匹配的处理项。

## 集成与扩展

CI 可执行 `snapshot`、`verify` 和 `compare --fail-on-impact`，并附上 JSON/HTML 供人工审查。0.4.0 提供轮询和出站通知，尚未实现入站 GitHub Webhook 接收器。

新增解析器时，在 `contracts.py` 实现并登记名称，添加面向行为的测试，记录其类别。领域无关的图传播保留在 `engine.py`。外部仿真或真机证据需要后续适配器，明确输入/版本绑定和验证范围；工具不会从源文件断言推断外部执行结果。

HTML 渲染器转义嵌入 JSON，用 DOM 文本节点插入源码值，将来源链接限制为 HTTPS GitHub URL，并用内容策略禁止网络连接。报告会包含所选源码差异；内容允许分享之前应保留在本地。

## 依赖发现与监测

`init` 发现已有本地 Git checkout；`start` 首次保存配置并启动轮询。仓库/软件包引用生成带文件依据、从提供者到消费者的保守推断边。这是依赖辅助，不是完整静态分析。作为发布门禁前，应编辑负责人、审查图并补充精确契约。新增仓库需要生成并审查新配置，并使用新的监测状态目录。

`sync` 不 stash、不 reset、不合并分叉分支。`watch` 观察本地源码状态，按需同步，比较快照，并在源码根目录之外生成报告。默认轮询间隔为 30 秒；网络操作与分析会增加延迟。状态目录锁支持 Unix 和 Windows；监测自动测试目前在 Linux 上运行。

通知通过 `notifications.webhook_env` 配置默认目标，通过 `notifications.recipients` 配置负责人到环境变量的路由。环境保存 URL，配置只保存变量名。JSON POST 包含事件身份、负责人、影响、源码 commit 和本地报告路径。接收端应按 `event_id` 去重：持久重试提供至少一次投递，不保证跨进程崩溃的恰好一次投递。拒绝重定向。本地状态含报告与事件历史；源码私有时状态也必须保持私有。
