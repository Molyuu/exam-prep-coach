# AGENTS.md

## Markdown / LaTeX 语法约定

本目录是 Obsidian vault。生成或修改 `.md` 文件时，数学公式必须遵守：

- 行内公式用 `$...$`（**禁止** `\(...\)`，Obsidian 不渲染）；
- 行间公式用 `$$...$$`（**禁止** `\[...\]`）；
- 不要在公式块前加 `+`、`-` 等列表符号；
- `$$` 块独立成行，前后留空行。

示例：

```md
行内：$f'(x_0)=\lim_{x\to x_0}\frac{f(x)-f(x_0)}{x-x_0}$

行间：
$$
\frac{d^2y}{dx^2}=\frac{d}{dt}\left(\frac{dy}{dx}\right)\Big/\frac{dx}{dt}
$$
```
