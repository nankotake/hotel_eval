# hotel_eval —— 酒店推荐评测框架（去 prompt 化 + 分层评测）

一套用于评测"酒店推荐 LLM 输出质量"的框架。核心思路是 **"能不问模型，就不要问模型"**：
优先用**确定性信号 / 真值比对 / 语义指标**打分，而不是让一个本身有偏的 LLM 当裁判；
只在开放式语义判断（如画像贴合）才回退到 LLM-as-judge，并用 confidence 把模糊样本筛出来转人工。

## 数据三分类（理解本框架的关键）

评测始终围绕三类数据：

| 分类 | 含义 | 存放 | 谁提供 |
|---|---|---|---|
| **入参（用户输入）** | 勾选的酒店 + 日期/人数/晚数 | `input` 字段 | 被测 LLM 收到的请求 |
| **参考信息（基准/真值）** | 酒店事实库 + 用户画像 | `reference` 字段 | 评测方，用于比对 |
| **评测对象** | LLM 原始输出 + 客观声称 | `llm_outputs.json` | 被测系统输出 |

评测就是：**拿"评测对象"去和"参考信息"比对，看是否忠于"入参"**。
注意别把 LLM 输出里复述的"需求理解"当成真值——真值只有参考信息（事实库 + 画像）。

## 分层评测（按维度，每个维度一个模块）

```
评测对象
 ├─ 一致性 consistency —— 回显 / 自洽 / 事实查库 / 勾选覆盖（确定性 floor，gate 硬门禁）
 ├─ 安全性 safety       —— 规则层 + judge（隐私/承诺/违规）
 ├─ 语义   semantics    —— BERTScore（有参考时）+ judge（开放时）
 ├─ 相关性 relevance    —— 规则层 + 受众匹配 + judge（画像贴合，语义判断）
 └─ LLM-as-judge        —— 多维度结构化打分 + 引用依据 + confidence
```

分层报、不混成一个总分：**硬门禁(gate)失败即整单 fail**，安全/质量层单独列。

## 目录结构

```
hotel_eval/
├─ __init__.py       导出公共类型/函数
├─ schema.py         数据结构（HotelInput/EvalReference/HotelFact/Claim/Issue...）
├─ casefile.py       评测数据加载/构建（eval_cases + llm_outputs）
├─ extractor.py      把 LLM 原始输出解析成结构化字段 + 自动抽声称
├─ consistency.py    维度①一致性（确定性层）
├─ safety.py         维度②安全性
├─ semantics.py      维度③语义
├─ relevance.py      维度④相关性
├─ judge.py          LLM-as-judge 引擎
├─ prompts.py        judge 的 rubric（评分锚点）+ 提示词模板
├─ online.py         在线层：全量确定性检查 + 行为校准
├─ report.py         分层汇总报告（文本渲染）
├─ engine.py         结构化评测引擎（CLI 与 Web 共用，返回可序列化结果）
├─ store.py          JSON 持久化（cases/outputs/eval_sets/records/config）
├─ data/             数据文件（见下）
└─ webapp/           FastAPI 后端 + 前端页面（可视化界面）
```

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> **依赖说明**：`requirements.txt` 写明了各依赖的用途。
> - `bert-score` 会自动拉起 `torch` + `transformers` 作为底层，因此这两个大件**不用手动写进 requirements**（pip 会自动装）。torch 建议用 CPU wheel 减小体积：`pip install torch --index-url https://download.pytorch.org/whl/cpu`。
> - `bert-score` 首次计算会联网下载默认模型（`distilbert-base-uncased`），离线环境需提前缓存或换本地模型。

## 运行

### 1) CLI 评测（打印分层报告）

```bash
python run_hotel_eval.py
```

无 API key 时只跑确定性层，judge 层跳过；配置 key 后自动启用。

### 2) 可视化界面（FastAPI + 前端）

```bash
python run_webapp.py
# 打开 http://127.0.0.1:8000
# 可选环境变量：WEBAPP_HOST / WEBAPP_PORT
```

界面功能（左侧导航）：

- **单case 管理**：列出/新建/编辑/删除评测 case（入参 + 事实库 + 画像），并在详情里增删改 LLM 输出。
- **评测集管理**：把一组 case 打包成评测集（如回归集），支持勾选 case、批量跑。
- **触发评测**：单次跑一个 case 的一份输出；或按评测集 / 多选 case 批量跑（可只跑每 case 第一份输出）。
- **评测记录**：每次运行自动落库，按记录查看完整报告详情。
- **配置**：配置 LLM-as-judge 的 API key / base_url / model；配置后运行自动带 judge 层。

## 数据文件（hotel_eval/data/）

- `eval_cases.json`   评测用例（入参 + 参考信息）—— 源数据，入库
- `llm_outputs.json`  评测对象（LLM 输出）—— 源数据，入库
- `eval_sets.json`    评测集定义（运行时生成，已 gitignore）
- `eval_records.json` 评测记录（运行时生成，含完整报告，已 gitignore）
- `config.json`       judge 配置（含 API key，已 gitignore）

## 配置 judge

`judge.py` 读取环境变量或 `data/config.json`：

- `JUDGE_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY`
- `JUDGE_BASE_URL`（DeepSeek 等 OpenAI 兼容端点）
- `JUDGE_MODEL`（默认 `gpt-4o-mini`）

也可直接在 Web 界面「配置」页填写并测试连接。

## 关键设计点

- **去 prompt 化**：一致性/安全性/相关性规则是确定性 floor，不问模型；语义用 BERTScore；只有画像贴合这类开放式判断才交 judge。
- **结构化引擎**：`engine.run_case_eval()` 返回可序列化的 `RunResult`，CLI 打印与 Web 渲染共用同一份计算逻辑，避免两套行为不一致。
- **judge 工程化**：单次调用、多维度分别调；不暴力多次采样，靠 confidence 把模糊样本筛出来转人工。

## 部署 / 推送 GitHub

仓库已就绪（默认分支 `main`，历史完整），可在你自己的机器上推到 GitHub。

### 方式 A：用 GitHub CLI（`gh`，最简单）

```bash
cd D:\hotel_eval
gh auth login                                   # 登录一次
gh repo create hotel_eval --public --source=. --remote=origin --push
```

### 方式 B：网页建空仓库 + git（无 `gh`）

1. 到 https://github.com/new 新建**公开**空仓库，命名为 `hotel_eval`。
   > 注意：**不要**勾选 "Add a README / .gitignore / license"（留空），避免和现有历史冲突。
2. 本地推送：

```bash
cd D:\hotel_eval
git remote add origin https://github.com/<你的用户名>/hotel_eval.git
git push -u origin main
```

> Windows 也可直接运行脚本 `push_to_github.ps1`（按提示输入 GitHub 用户名）。

### ⚠️ 公开仓库前的安全检查（已在本仓库执行）

- 已确认**已跟踪文件不含任何 `sk-` 密钥 / 邮箱 / 用户名**。
- `config.json`（含 judge 的 API key）、`eval_records.json`、`eval_sets.json` 均为**运行时文件，已在 `.gitignore` 中忽略**，不会被推送。
- 若你在本机改过 `.gitignore` 或新增了敏感文件，推送前请再跑一次：
  ```bash
  git grep -n -i -E "sk-[A-Za-z0-9]{10,}|[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}" 
  git check-ignore hotel_eval/data/config.json
  ```
