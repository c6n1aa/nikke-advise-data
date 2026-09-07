"""从 nikke_advises_i18n.json 生成各语言角色名称参照表（Markdown）。

用法（纯标准库，默认路径锚定到仓库根，任意工作目录均可运行）：
    python scripts\\gen_name_table.py

输出：data/character_names.md
顺序与源数据 character[] 一致，便于按序号定位；某语言无该角色名则留空。
"""

import json
import os
from datetime import date

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/ 的上级即仓库根。

SRC = os.path.join(_REPO_ROOT, "data", "nikke_advises_i18n.json")
DST = os.path.join(_REPO_ROOT, "data", "character_names.md")
LOCALES = ("zh_CN", "zh_TW", "en", "ja", "ko")  # 列顺序：与 JSON 的 name 键序一致
LABEL = {"zh_CN": "简体中文", "zh_TW": "繁体中文", "en": "English", "ja": "日本語", "ko": "한국어"}


def main():
    data = json.load(open(SRC, encoding="utf-8"))
    chars = data["character"]

    # 名称里若含竖线会撑破 Markdown 表格，先兜底转义。
    def cell(text):
        return (text or "").replace("|", "\\|")

    lines = [
        "# 各语言角色名称参照表",
        "",
        "由 `data/nikke_advises_i18n.json` 生成"
        "（角色 %d 个，顺序与源数据 `character[]` 一致，便于按序号定位）。" % len(chars),
        "",
        "空白表示该语言暂无此角色名（按 `build_advise_db.py` 规则，角色名为空则该语言整条不入库）。",
        "",
        "生成日期：%s　源数据 `last_update`：%s" % (date.today().isoformat(), data.get("last_update", "")),
        "",
        "| # | " + " | ".join("%s (%s)" % (l, LABEL[l]) for l in LOCALES) + " |",
        "|" + "---|" * (len(LOCALES) + 1),
    ]
    for i, c in enumerate(chars, 1):
        lines.append("| %d | " % i + " | ".join(cell(c["name"].get(l, "")) for l in LOCALES) + " |")

    # 缺失统计：定位待补翻译的角色。
    lines += ["", "## 缺失统计", "", "| 语言 | 已填 | 缺失 |", "|---|---|---|"]
    for l in LOCALES:
        missing = [c["name"]["zh_CN"] for c in chars if not c["name"].get(l)]
        lines.append("| %s | %d | %d |" % (l, len(chars) - len(missing), len(missing)))
    lines.append("")
    for l in LOCALES:
        missing = [c["name"]["zh_CN"] for c in chars if not c["name"].get(l)]
        if not missing:
            continue
        if len(missing) == len(chars):  # 整列为空无需罗列。
            lines.append("- **%s**：全部 %d 个角色均无名称，该语言暂无数据" % (l, len(missing)))
        elif len(missing) <= 10:
            lines.append("- **%s 缺失 %d 个**：%s" % (l, len(missing), "、".join(missing)))
        else:
            lines.append("- **%s 缺失 %d 个**：%s 等"
                         % (l, len(missing), "、".join(missing[:10])))

    with open(DST, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("已生成: %s（%d 个角色）" % (DST, len(chars)))


if __name__ == "__main__":
    main()
