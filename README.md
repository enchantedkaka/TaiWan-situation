台海风险指数仪表盘 (Tension Index Dashboard) - 开源项目

查看实时仪表盘
(请将上方链接替换为您 GitHub Pages 的真实网址)

1. 项目简介

本项目是一个开源、自动化的地缘政治风险监测工具，旨在通过量化、透明、基于公开信息的模型，追踪台湾海峡的局势紧张程度。

我们相信，通过将模糊的“感觉”转变为可跟踪的“数据”，可以为关心此议题的和平主义者、研究者和普通民众提供一个更客观的参考。

2. 核心架构

本项目 100% 运行在免费的 GitHub 平台上：

前端 (Website): index-v3.html 由 GitHub Pages 托管。

后端 (Automation): analyst-v3.py 由 GitHub Actions 每日自动运行。

模型 (The "Brain"): indicators.json 是我们定义的所有“预警信号”及其权重。

数据 (Data): scores-v3.json 是由后端自动生成并推送回本仓库的最新风险数据。

3. “数学模型” (indicators.json)

本项目的核心是 indicators.json 文件。

我们不依赖 LLM 的主观打分，而是将 LLM 用作“信息扫描仪”，在每日新闻中查找是否明确触发了此文件中定义的“预警信号”。

总风险指数 = (Sum(所有被触发指标的权重) / Sum(所有指标的总权重)) * 100

4. 如何贡献 (How to Contribute)

这是本项目的核心目标！ 欢迎任何人提交 Pull Request 来改进这个模型。

A. 优化“模型” (最重要的)

您是否认为某个指标的权重 (weight) 不合理？或者您想到了一个新的“预警信号”？

Fork 本仓库。

编辑 indicators.json：

修改一个 weight。

或添加一个新指标 (请确保 id 唯一)。

提交 Pull Request (PR)，并详细说明您的理由。

B. 优化“引擎”

您是否精通 Python 和 API？

Fork 本仓库。

编辑 analyst-v3.py：

改进 NewsAPI 的搜索关键词 (query)？

改进给 LLM 的 system_prompt？

提交 Pull Request (PR)。

5. 本地运行

Clone 本仓库。

安装依赖: pip install -r requirements.txt

创建您自己的 analyst-v3.py 副本，并填入您的 API 密钥 (请勿提交此文件)。

运行: python analyst-v3.py

6. 许可 (License)

本项目采用 MIT 许可证。这意味着您可以自由地使用、修改和分发本项目的代码，但请保留原始许可声明。# TaiWan-situation
