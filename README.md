# exam-prep-coach

理工科考前突击 skill。喂它往年真题或模拟卷，它反推考点、排可执行的复习计划，并产出知识点讲解、分层习题集和逐题详解。目标函数是分数，默认学生零基础、时间紧。

适用于数学、物理、化学、电路、数据结构等有计算/推导/操作步骤的科目；不适用于纯记忆、语言、纯论述类。

## 安装

```bash
git clone https://github.com/Molyuu/exam-prep-coach.git ~/.codex/skills/exam-prep-coach
```

其他支持 `SKILL.md` 的工具放到各自的 skills 目录即可。

## 使用

直接对它说，例如：

```text
我还有 7 天考高数期中，卷子发你，帮我划重点。
```

首次会问 4 个问题（科目与日期、有无真题、目标分、教材），随后自动执行全流程。产出在 `ai_study/` 下：复习路线、知识点讲解、习题集、逐题详解。

不装 skill、只在对话里用？直接贴这段提示词 → [PLAN_B.md](PLAN_B.md)

## 脚本

纯 Python 3 标准库；仅 `pdf_prepare.py` 需要 macOS + Xcode Command Line Tools。用法见 `scripts/README.md`，流程细节见 `SKILL.md`。

## License

[MIT](LICENSE)
