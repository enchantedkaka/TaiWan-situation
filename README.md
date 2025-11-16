台海风险指数仪表盘 (Tension Index Dashboard) - V4

查看实时仪表盘

1. 项目简介

本项目是一个开源、自动化的地缘政治风险监测工具，旨在通过量化、透明、基于公开信息的模型，追踪台湾海峡的局势紧张程度。

我们相信，通过将模糊的“感觉”转变为可跟踪的“数据”，可以为关心此议题的和平主义者、研究者和普通民众提供一个更客观的参考。

2. 核心架构

本项目 100% 运行在免费的 GitHub 平台上：

前端 (Website): index.html 由 GitHub Pages 托管。

后端 (Automation): analyst-v4.py (V4 衰减模型) 由 GitHub Actions 按计划自动运行。

模型 (The "Brain"): indicators.json 是我们定义的所有“预警信号”及其基础权重。

数据 (The "Memory"): scores-v3.json 是由后端自动生成并推送回本仓库的最新风险状态。

3. V4 模型：累积衰减 (Cumulative Decay)

我们不再使用“无记忆”模型（V3），而是采用了一个有状态的、带衰减的模型。这更符合战争风险“逐渐累积”的特征。

模型逻辑：

记忆 (Memory): 脚本运行时，首先会读取上一次生成的 scores-v3.json，加载所有“已激活”的信号。

衰减 (Decay): 任何“已激活”但今天未被新闻再次触发的信号，其权重会按 DECAY_FACTOR (当前设为 0.75) 衰减。

例如： 权重 40 的信号，第二天变为 30，第三天变为 22.5...

刷新 (Refresh): 任何今天被新闻再次触发的信号，其权重会立刻“刷新”回 100% 的基础权重。

新增 (New): 今天新发现的信号会以 100% 的权重被添加到“激活列表”中。

总分 (Score): 总风险指数 = (Sum(所有“激活”信号的“当前权重”) / Sum(所有指标的“总基础权重”)) * 100

4. 如何贡献 (How to Contribute)

欢迎您通过 Pull Request 帮助改进这个模型！

A. 优化“模型” (最重要的)

您是否认为某个指标的权重 (weight) 不合理？或者您想到了一个新的“预警信号”？

Fork 本仓库。

编辑 indicators.json：

修改一个 weight。

或添加一个新指标 (请确保 id 唯一)。

提交 Pull Request (PR)，并详细说明您的理由。

B. 优化“引擎”

您是否想调整衰减因子 (DECAY_FACTOR)？

Fork 本仓库。

编辑 analyst-v4.py：

在文件顶部修改 DECAY_FACTOR = 0.75 的值。

提交 Pull Request (PR)。

5. 本地运行

git clone 本仓库。

安装依赖: pip install -r requirements.txt

在您的本地终端设置环境变量 (切勿将密钥写入代码)：

# (在 Mac/Linux)
export DEEPSEEK_API_KEY="sk-..."
export NEWS_API_KEY="..."

# (在 Windows CMD)
set DEEPSEEK_API_KEY="sk-..."
set NEWS_API_KEY="..."


运行脚本: python analyst-v4.py

6. 许可 (License)

本项目采用 MIT 许可证。详情请见 LICENSE 文件。
