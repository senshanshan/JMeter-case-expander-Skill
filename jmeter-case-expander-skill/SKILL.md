---
name: jmeter-case-expander-skill
description: 基于正向模板用例和字段必填/选填规则，在现有 JMeter `.jmx` 线程组中保守地扩展测试用例，并审查或收紧直接相关的 JDBC 清理逻辑。当 Codex 拿到 JMeter 文件、目标线程组、至少一个正向 API 用例和字段规则，并且需要在不重构无关线程组的前提下补充高价值的反向或边界用例时使用。
---

# JMeter 线程组用例扩展器

## 概述

使用这个 skill 安全地扩展单个现有线程组。优先做最小化、局部性的修改，而不是重写整个文件。如果信息缺失，只生成高置信度用例，并明确指出缺口。

## 工作流

1. 阅读 `references/input-contract.md`，并确认请求中包含：
   - 一个 `.jmx` 文件
   - 一个目标线程组
   - 至少一个正向模板用例
   - 必填与选填字段规则
2. 在做任何修改之前，先运行 `scripts/inspect_jmx.py`，盘点目标线程组内容。
3. 阅读相关参考资料：
   - 用 `references/coverage-rules.md` 确定用例扩展顺序
   - 在修改清理 SQL 前阅读 `references/jdbc-safety-rules.md`
   - 在修改断言或评估审查风险前阅读 `references/jmeter-assertion-rules.md`
4. 使用 `scripts/patch_jmx.py` 克隆目标 HTTP sampler，并追加保守的“每次只改一个字段”的变体用例。
5. 对输出文件运行 `scripts/review_jmx.py`，并在最终给用户的总结中带上它的审查结果。

## 操作规则

- 每次运行只处理一个目标线程组。
- 默认采用增量式修改，不要重构无关线程组。
- 除非用户明确提出，否则不要改写登录、token 或共享初始化流程。
- 复用正向模板请求结构。每个变体只修改最少必要字段。
- 每个测试用例优先只做一次变异，避免组合爆炸。
- 如果没有提供字段边界、枚举值或唯一性规则，就跳过推测性用例，并说明原因。
- 如果 JDBC 清理意图不明确，应给出警告，而不是扩大删除范围。

## 先检查

运行：

```powershell
python scripts/inspect_jmx.py --input path\to\case.jmx --thread-group "Target Thread Group"
```

根据输出识别：

- 精确的线程组名称
- 基础 HTTP sampler 名称
- 请求方法、路径、编码和请求体样式
- 同级关联的断言、提取器、脚本和 JDBC 请求

如果 `.jmx` 中包含多个线程组，必须明确只处理其中一个，其余部分保持不动。

## 保守打补丁

先准备一个符合 `references/input-contract.md` 的 JSON 规格文件，然后运行：

```powershell
python scripts/patch_jmx.py --input path\to\case.jmx --output path\to\case-patched.jmx --spec path\to\spec.json
```

补丁策略：

- 优先使用命名的 `base_sampler`；否则使用目标线程组中的第一个 HTTP sampler。
- 按照 `references/coverage-rules.md` 中的顺序生成高价值变体。
- 如果规格中提供了 `case_plan`，优先使用其中明确指定的顺序和命名，而不是自动生成英文标签。
- sampler 名称优先使用带清晰编号的中文，例如 `1. 全必填正常情况`、`2. 必填编号缺失`。
- 复制基础 sampler 时，连同它的子级 `hashTree` 一起复制，确保本地断言和提取器仍然挂在对应节点下。
- 除非确实需要做最小修正，否则保留原有 sampler 风格、请求方法、路径、请求头和编码。
- 只有当规格中提供了明确且安全的指导，如 `full_sql` 或 `where_clause`，才收紧 JDBC 清理逻辑。

## 交付前审查

运行：

```powershell
python scripts/review_jmx.py --input path\to\case-patched.jmx --thread-group "Target Thread Group"
```

至少需要指出：

- 新增或修改过的 sampler 名称
- JDBC SQL 是否发生变化
- 成功或失败断言是否存在薄弱点
- 编码或路径是否存在不一致
- 清理范围是否存在风险，或是否有未解决的审查项

## 资源

- `scripts/inspect_jmx.py`：检查线程组、sampler、断言、提取器和 JDBC 请求
- `scripts/patch_jmx.py`：添加保守的用例变体，并可选地收紧清理 SQL
- `scripts/review_jmx.py`：检测空白 sampler、无效 JSON 请求体、断言缺口、编码漂移和高风险 JDBC SQL
- `references/coverage-rules.md`：默认的用例扩展顺序与边界规则
- `references/jdbc-safety-rules.md`：清理 SQL 的硬性安全护栏
- `references/jmeter-assertion-rules.md`：断言与编码的审查清单
- `references/input-contract.md`：必需输入项与补丁规格 schema
