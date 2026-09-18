---
name: nikke-advise-import
description: Add a new character or update existing characters in the NIKKE advise/conversation database for the repository, filling zh_CN/en/ja from gamekee, nkas, and gamewith. Use when the user wants to add or refresh a character's advise/conversation options or a specific language for advise data, e.g. 新增角色咨询选项, 更新xx的好感度对话, 导入xx的咨询数据, fill/update the advise answers for a character, sync en/ja advise data.
---

# Nikke Advise Data Import

## Overview

Keeps `data/nikke_advises_i18n.json` (the single source of truth for in-game
advise/conversation answers, versioned in this repository) in sync with three external
sources. Each advise entry holds all five locales together and shares one row index whose
baseline order comes from zh_CN.

The runtime DB `dist/advise.db` is a derived artifact built by `scripts/build_advise_db.py`;
the importer is `scripts/import_advise.py`. Both are repo-level tools (pure stdlib, any
Python 3.12, paths anchored to the repo root). Download dumps land in gitignored `cache/`.
Publishing means copying `dist/advise.db` over ok-nikke's `assets/db/advise.db` (sibling
checkout `../ok-nikke`) and committing it there — ok-nikke only consumes the DB.

## Sources (order and structure differ per source)

| Locale | Source | Type | Lookup | Good/bad |
|---|---|---|---|---|
| zh_CN | gamekee 角色条目 `https://www.gamekee.com/nikke/<内容id>` | single page | content id | 表格明确分 120好感度(good)/100好感度(bad)，顺序=基准 |
| en | nkas 全量 JSON `https://nkas.pages.dev/nk_data/advise-answers.json` | full dump | English char name | 源已分 goodanswer/badanswer |
| ja | gamewith 全量页 `https://gamewith.jp/nikke/article/show/411638` | full dump | Japanese char name | 每条自带 ◯ 可选；标「調査中」时回退本地文本反推 |

zh_TW has no external source here (recent characters keep it empty); ko has none at all.

## When to use / ask first

Before importing, confirm (or infer with a stated assumption):
- **Action**: add a brand-new character vs. update/fill an existing character's language.
- **Character**: best given as the zh_CN name, English name, or 1-based index (`--char`).
- **Locales**: zh_CN and/or en and/or ja. zh_TW/ko are not covered by this skill.

If the character is new: first create it with zh_CN (gamekee), then optionally fill en and ja.
If only a language is stale: refresh that locale (single character or `--all`).

## Workflow

All scripts anchor their paths to the repo root, so they run from any working directory.
The importer defaults to dry run; nothing is written until `--apply`.

### 1. Add a new character (zh_CN baseline)

```powershell
python scripts\import_advise.py zh_CN 719742 [--at 麦斯威尔：平凡技师]
```

The `--at` anchor is optional; characters default to the end.

If gamekee's CDN blocks the script (HTTP 567), fetch the content JSON with `curl.exe`
(sends different TLS fingerprint than Python's urllib) and import it offline:

```powershell
# detail API 给出 content_cdn（api-cdn.gamekee.com/wiki2.0/pro/1253/content/<id>.json）
curl.exe -s -o cache\<id>.json "<content_cdn URL>" -H "User-Agent: Mozilla/5.0 ... Chrome/120 Safari/537.36" -H "Referer: https://www.gamekee.com/"
python scripts\import_advise.py zh_CN 719742 --file cache\<id>.json
```

Only if curl also fails, ask the user to save the content JSON from the browser and use `--file`.

### 2. Fill / refresh English

```powershell
python scripts\import_advise.py en "Drake: Great Villain"
python scripts\import_advise.py en --all
```

### 3. Fill / refresh Japanese

```powershell
# 日文直接传参在 Windows 控制台易乱码，优先用英文名/序号定位：
python scripts\import_advise.py ja --char "Drake: Great Villain"
python scripts\import_advise.py ja --all
```

### 4. Cross-validate before applying

- Inspect the dry-run output (`[源NN -> 条目NN]` diffs plus the good side for ja).
- The three sources use different internal orders; alignment is by text, never by index.
  Many entries share an identical question text (e.g. two `"What should I do?"`), so the
  importer matches on (prompt, good, bad) → (good, bad) → prompt, in that order.
- Verify semantics rather than trusting position: some en questions are fragments (only the
  trailing half-sentence), ja good/bad may be inferred from the local text when the source lacks ◯.
  gamewith uses `<br>`/`<span>` inline markup; the importer normalizes it (tags stripped, `<br>`→newline).
- If a brand-new character has empty target-locale text and cannot align automatically, run once
  to see the对照 (prompt/options in source vs. the target entry), then give the mapping:
  en `--map "1:4,2:8"`；ja `--map "1:4A,2:8B"` (A/B = which option is good).
- Then write with `--apply`.

### 5. Validate and rebuild the runtime DB

```powershell
python scripts\build_advise_db.py
```

This validates (all 5 locale keys present, uniform 20-entry count, zh_CN names unique) and
atomically regenerates `dist/advise.db`. Skip only if the user asked for the JSON alone, and
say so explicitly.

### 6. Publish to ok-nikke

```powershell
Copy-Item dist\advise.db ..\ok-nikke\assets\db\advise.db
```

Then commit the DB in ok-nikke (its tests query the real file, and the app ships it).

### 7. Report

List which characters changed and which locales are still empty. Optionally refresh the derived
name table with `python scripts\gen_name_table.py` (regenerates `data/character_names.md`).

## Rules

- The i18n JSON is the source of truth; build the DB from it, never edit the DB directly.
- Copy source text verbatim: do not translate, paraphrase, or "complete" fragmentary prompts.
  Keep original punctuation (⋯、～、…、newlines in en/ja). zh_CN text is de-newlined on import.
- Align by text only; en/ja orders differ from zh_CN, and duplicate question texts exist, so
  index-based fills corrupt data.
- Cross-verify good/bad for ja when the source lacks ◯; if uncertain, ask or require `--map`.
- Default is dry run; do not `--apply` without reviewing the diff (user may also ask to review).
- Prefer `--char` (English name or index) over typing Chinese/Japanese in the console.
- Newly written characters must have 20 entries; the importer aborts otherwise.
- `last_update` is stamped automatically; no need to edit manually.
- Commit `data/` (source JSON and the generated name table); keep download dumps in gitignored
  `cache/` and never commit them; `dist/` is not committed either (rebuildable on demand).
