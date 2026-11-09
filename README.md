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

首次会问 4 个问题（科目与日期、有无真题与教材、目标分、每天能学几小时），随后先交复习路线 + Day 1 的讲解/习题/详解；你做完、记好错题再要下一天，计划会按你的错题调整。只剩 ≤ 3 天时一次给全。产出在 `ai_study/` 下。

不装 skill、只在对话里用？直接贴这段提示词 → [PLAN_B.md](PLAN_B.md)

## 脚本

只有一个：`scripts/pdf_prepare.py`，把 PDF 卷子逐页渲染成图片供读图转写。纯 Python 3 标准库 + 任一渲染器：macOS 用自带 Swift（Xcode Command Line Tools），其他系统装 poppler（`pdftoppm`）或 mupdf（`mutool`）。交付前的检查由模型按 `SKILL.md` §6 的清单逐条自检。

## License

[MIT](LICENSE)
