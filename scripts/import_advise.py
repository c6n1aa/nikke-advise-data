"""好感度对话（咨询）数据的三语言导入 / 更新工具。

目标文件：data/nikke_advises_i18n.json（唯一真源，db 由其重建）

────────────────────────────────────────────────────────────────────────
三个数据源的形态差异（决定了本脚本的用法）
────────────────────────────────────────────────────────────────────────
zh_CN  gamekee 单角色条目    https://www.gamekee.com/nikke/<内容id>
       按页抓取：/v1/content/detail/<id>（需 game-alias: nikke 头）-> content_cdn
       baseData 表格「好感度对话」段：问题N -> prompt，120好感度 -> good，100好感度 -> bad
       条目顺序 = i18n 的基准顺序（其它语言都要对齐到它）

en     nkas 全量 JSON         https://nkas.pages.dev/nk_data/advise-answers.json
       一次下载得到全部角色，advises[英文名] = 20 条 question/goodanswer/badanswer
       【顺序与 i18n 不同】，必须按 question 文本对齐，不能按索引覆盖

ja     gamewith 全量页        https://gamewith.jp/nikke/article/show/411638
       按企业分组，h3「XXXの面談」后接 div.nikke_mendan，每条一 table：
       th = Q 文，两个 td = 选项，第二个 td 为 ◯ 表示 +120
       【顺序与 i18n 不同】，但自带 ◯ 可直接判定 good/bad
       （单角色页 article/show/<id> 结构相同，但多数条目标「調査中」无 ◯，不建议使用）

────────────────────────────────────────────────────────────────────────
对齐策略
────────────────────────────────────────────────────────────────────────
i18n 的条目索引由 zh_CN 决定，五个语言共享同一组条目，故 en/ja 写入前必须对齐：
  1. 该角色该语言已有文本 -> 按 question 文本精确匹配源条目（实测 3260/3260 可对齐）
  2. 该角色该语言为空（新角色）-> 无法自动对齐，先 dry run 看对照，人工核对后 --map 指定
     en 形如 "1:4,2:8"（源序号:目标条目序号）
     ja 形如 "1:4A,2:8B"（再加 A/B 指定 good）
     注：ja 若已有文本，源该条无 ◯（标「調査中」）时会用本地 good/bad 文本自动反推，
     只有新角色且两边都无依据时才必须给 --map。
默认 dry run 只打印差异，确认无误后加 --apply 才写入。

────────────────────────────────────────────────────────────────────────
用法（纯标准库，任意 Python 3.12；路径锚定仓库根，任意工作目录可运行）
────────────────────────────────────────────────────────────────────────
先设变量，避免每条命令敲长路径（展示用正斜杠，避免 docstring 里反斜杠转义混乱）：
    $IMP = "scripts/import_advise.py"

# 简中：从 gamekee 建新角色（其条目顺序即基准顺序）
python $IMP zh_CN 719742             # 默认追加到末尾
python $IMP zh_CN 719742 --at 麦斯威尔：平凡技师  # 插到该角色后
#   gamekee 的 CDN 拦截脚本请求（HTTP 567）时，--file 从浏览器保存的内容 JSON 离线导入
python $IMP zh_CN 719742 --file saved.json

# 英文：nkas 全量源（按英文名；--all 批量刷新全部已有角色）
python $IMP en "Drake: Great Villain"
python $IMP en --all

# 日文：gamewith 全量页（也可 --all；命令行传日文易乱码，推荐用 --char 以英文名/序号定位）
python $IMP ja --char "Drake: Great Villain"

# 新角色且该语言为空时，人工核对后给映射
python $IMP en "Xxx" --map "1:4,2:8"
python $IMP ja "XXX" --map "1:4A,2:8B"

# 其它
--apply    真正写入（缺省 dry run）
--at <位置> 仅 zh_CN 新建：end / 数字索引 / 已存在角色名（默认 end）
--refresh  忽略 cache/ 下的源数据缓存重新下载
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import date

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/ 的上级即仓库根。

DST = os.path.join(_REPO_ROOT, "data", "nikke_advises_i18n.json")
CACHE = os.path.join(_REPO_ROOT, "cache")
LOCALES_NAME = ("zh_CN", "zh_TW", "en", "ja", "ko")
LOCALES_TEXT = ("zh_CN", "zh_TW", "ja", "ko", "en")
BASE_COUNT = 20

NKAS_URL = "https://nkas.pages.dev/nk_data/advise-answers.json"
GW_LIST_URL = "https://gamewith.jp/nikke/article/show/411638"
GK_DETAIL = "https://www.gamekee.com/v1/content/detail/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def _get(url, headers=None):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers or UA),
                                      timeout=120).read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        raise SystemExit("请求失败 %s（HTTP %s）。"
                         "gamekee 的 CDN 会对脚本请求返回 567，此时可稍后重试，"
                         "或从浏览器保存内容 JSON 后用 --file 离线导入。" % (url, e.code))


def _cached(name, url, refresh, parse, headers=None):
    """读缓存；缺失或 --refresh 时下载。parse 把原始文本转成结构化数据。"""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if refresh or not os.path.exists(path):
        raw = _get(url, headers)
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)
    else:
        raw = open(path, encoding="utf-8").read()
    return parse(raw)


def _norm(text):
    """zh_CN 去换行与空白：JSON 层不保留换行（见 build_advise_db.py 说明）。"""
    return re.sub(r"\s+", "", text).strip()


def _strip_html(text):
    """en/ja 源里的行内标签：<br> 视作换行，其余标签剥掉，实体还原为字符。"""
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


# ------------------------------------------------------------------ 抓取

def _rows_from_file(path):
    """离线通道：读浏览器/手动保存的 gamekee 内容 JSON（原始 {"content": ...} 或已解析）。"""
    raw = json.load(open(path, encoding="utf-8"))
    return raw["baseData"] if "baseData" in raw else json.loads(raw["content"])["baseData"]


def fetch_zh(content_id, refresh=False, path=None):
    """gamekee 单角色条目 -> (zh_CN 角色名, [{q, good, bad}])"""
    if path:
        rows = _rows_from_file(path)
    else:
        H = dict(UA, Referer="https://www.gamekee.com/nikke/", Origin="https://www.gamekee.com",
                 **{"game-alias": "nikke"})
        detail = json.loads(_get(GK_DETAIL + content_id, H))["data"]
        # content_cdn 指向的 JSON 里 content 又是一层 JSON 字符串。
        body = json.loads(_get("https:" + detail["content_cdn"], H))["content"]
        rows = json.loads(body)["baseData"]

    # 角色名取表格里的「角色名称」，离线与在线路径统一。
    name = ""
    for r in rows:
        if r and r[0].get("value") == "角色名称":
            name = (r[1].get("value") or "").strip() if len(r) > 1 else ""
            break
    if not name:
        raise SystemExit("未从表格中取到「角色名称」，请检查内容来源")

    start = next(i for i, r in enumerate(rows) if r and r[0].get("value") == "好感度对话")
    items, cur = [], None
    for r in rows[start + 1:]:
        label = (r[0].get("value") or "").strip()
        val = (r[1].get("value") or "").strip() if len(r) > 1 else ""
        if label.startswith("问题"):
            cur = {"q": val, "good": "", "bad": ""}
            items.append(cur)
        elif label == "120好感度" and cur is not None:
            cur["good"] = val
        elif label == "100好感度" and cur is not None:
            cur["bad"] = val
    return name, items


def fetch_en_all(refresh=False):
    """nkas 全量 -> {en 角色名: [{q, good, bad}]}"""
    def parse(raw):
        return {k: [{"q": i["question"], "good": i["goodanswer"], "bad": i["badanswer"]}
                    for i in v]
                for k, v in json.loads(raw)["advises"].items()}
    return _cached("nkas_advise_answers.json", NKAS_URL, refresh, parse)


def fetch_ja_all(refresh=False):
    """gamewith 全量页 -> {ja 角色名: [{q, a, b, mark}]}，mark 为 A/B/空（◯ 所在侧）"""
    def parse(html):
        out = {}
        for m in re.finditer(r'<h3 id="chara\d+">(.*?)の面談</h3>', html):
            blk = re.search(r'<div class="nikke_mendan">(.*?)</div>', html[m.end():], re.S)
            if not blk:
                continue
            items = []
            for t in re.findall(r"<table>(.*?)</table>", blk.group(1), re.S):
                q = re.search(r'<th colspan="2">Q\.(.*?)</th>', t, re.S)
                tds = [x.strip() for x in re.findall(r"<td>(.*?)</td>", t, re.S)]
                if not q or len(tds) != 4:
                    continue
                items.append({"q": _strip_html(q.group(1)).strip(),
                              "a": _strip_html(tds[0]), "b": _strip_html(tds[2]),
                              "mark": "A" if tds[1] == "◯" else ("B" if tds[3] == "◯" else "")})
            out[m.group(1).strip()] = items
        return out
    return _cached("gw_mendan_list.html", GW_LIST_URL, refresh, parse)


# ------------------------------------------------------------------ 对齐

def _parse_map(spec, src_count, need_side):
    """--map：en 用 "src:dst"，ja 用 "src:dstX"（X=A/B）。"""
    mapping = {}
    if not spec:
        return mapping
    for part in spec.split(","):
        m = re.fullmatch(r"(\d+):(\d+)([AB]?)", part.strip())
        if not m:
            raise SystemExit("--map 片段无法解析: %r（应形如 1:4 或 1:4A）" % part)
        s, d, side = int(m.group(1)), int(m.group(2)), m.group(3)
        if not 1 <= s <= src_count or not 1 <= d <= BASE_COUNT:
            raise SystemExit("--map 序号越界: %r" % part)
        if need_side and not side:
            raise SystemExit("--map 片段 %r 需指定 A/B（该条源无 ◯，无法判定 good）" % part)
        mapping[s] = (d, side)
    if sorted(d for d, _ in mapping.values()) != list(range(1, BASE_COUNT + 1)):
        raise SystemExit("--map 目标序号必须是 1-%d 的完整排列" % BASE_COUNT)
    return mapping


def _resolve(lang, src_items, advises, spec):
    """确定 {源序号: (目标序号, good 所在侧)}；返回 (mapping, 未对齐的源序号)。

    源与本地顺序不同，且存在大量「相同问题文本」（如两条都是 "What should I do?"）。
    故按信息量从多到少分三轮匹配，避免重复问题被全部对到同一条：
      1. (prompt, good, bad) 三元组精确；
      2. (good, bad) 精确（问题被改写、答案未变）；
      3. prompt 精确（答案被改写、问题未变），同题文本按出现顺序一一对应。
    """
    need_side = lang == "ja"
    manual = _parse_map(spec, len(src_items), need_side)
    if manual:
        return manual, []

    src_good, src_bad = [], []
    for it in src_items:
        if lang == "en":
            src_good.append(it["good"])
            src_bad.append(it["bad"])
        elif it.get("mark") == "A":
            src_good.append(it["a"])
            src_bad.append(it["b"])
        elif it.get("mark") == "B":
            src_good.append(it["b"])
            src_bad.append(it["a"])
        else:
            src_good.append(None)
            src_bad.append(None)

    loc = [{"i": i, "q": _key(a["prompt"][lang]),
            "g": _key(a["good"][lang]), "b": _key(a["bad"][lang])}
           for i, a in enumerate(advises, 1)]
    used = set()
    hits = {}

    def take(pred):
        for x in loc:
            if x["i"] not in used and pred(x):
                used.add(x["i"])
                return x["i"]
        return None

    for s in range(1, len(src_items) + 1):  # 1) 三元组
        g, b = src_good[s - 1], src_bad[s - 1]
        if g is None:
            continue
        q = _key(src_items[s - 1]["q"])
        d = take(lambda x, q=q, g=g, b=b:
                 x["q"] == q and x["g"] == _key(g) and x["b"] == _key(b))
        if d:
            hits[s] = d

    for s in range(1, len(src_items) + 1):  # 2) 答案对
        if s in hits:
            continue
        g, b = src_good[s - 1], src_bad[s - 1]
        if g is None:
            continue
        d = take(lambda x, g=g, b=b: x["g"] == _key(g) and x["b"] == _key(b))
        if d:
            hits[s] = d

    buckets = defaultdict(list)  # 3) 仅 prompt
    for x in loc:
        if x["i"] not in used:
            buckets[x["q"]].append(x["i"])
    for s in range(1, len(src_items) + 1):
        if s in hits:
            continue
        q = _key(src_items[s - 1]["q"])
        if buckets.get(q):
            d = buckets[q].pop(0)
            used.add(d)
            hits[s] = d

    miss = [s for s in range(1, len(src_items) + 1) if s not in hits]
    if miss:  # 未命中的用剩余空位补（仅当恰好一一对应时可接受）。
        free = [x["i"] for x in loc if x["i"] not in used]
        if len(free) == len(miss):
            hits.update(dict(zip(miss, free)))
            miss = []

    out, unresolved = {}, []
    for s, d in hits.items():
        it = src_items[s - 1]
        side = it.get("mark", "")
        if need_side and not side:
            # 源该条无 ◯（gamewith 很多条标「調査中」）：用本地已有的 good/bad 文本反推。
            side = _guess_side(it, advises[d - 1], lang)
        if need_side and not side:
            unresolved.append(s)
        out[s] = (d, side)
    if miss or unresolved:
        return None, sorted(set(miss) | set(unresolved))
    return out, []


def _key(text):
    """对齐用的比较键：忽略全部空白（同一条在源与本地可能一个有换行一个没有）。"""
    return re.sub(r"\s+", "", text or "")


def _guess_side(it, adv, lang):
    """源无 ◯ 时，用本地已有的 good/bad 文本判定 A/B；判定不了返回空串。"""
    a, b = _key(it["a"]), _key(it["b"])
    good, bad = _key(adv["good"][lang]), _key(adv["bad"][lang])
    if good:
        if a == good and b != good:
            return "A"
        if b == good and a != good:
            return "B"
    if bad:  # 反侧排除：命中 bad 则另一侧是 good。
        if a == bad and b != bad:
            return "B"
        if b == bad and a != bad:
            return "A"
    return ""


def _pairs(lang, it, side):
    """按语言与 good 所在侧取出 (good, bad) 文本。"""
    if lang == "en":
        return it["good"], it["bad"]
    return (it["a"], it["b"]) if side == "A" else (it["b"], it["a"])


# ------------------------------------------------------------------ 命令

def _resolve_pos(chars, at):
    names = [c["name"]["zh_CN"] for c in chars]
    if at == "end":
        return len(chars)
    if at.lstrip("-").isdigit():
        pos = int(at)
        if not 0 <= pos <= len(chars):
            raise SystemExit("插入位置越界: %d（有效范围 0-%d）" % (pos, len(chars)))
        return pos
    if at not in names:
        raise SystemExit("锚点角色不存在: %s" % at)
    return names.index(at) + 1


def cmd_add_zh(args):
    data = json.load(open(DST, encoding="utf-8"))
    chars = data["character"]
    pos = _resolve_pos(chars, args.at)  # 先解析位置：本地校验失败就不必联网。
    name, items = fetch_zh(args.locator, args.refresh, args.file)
    if len(items) != BASE_COUNT:
        print("条目数 %d，与基准 %d 不符，已中止" % (len(items), BASE_COUNT))
        return 1
    if name in [c["name"]["zh_CN"] for c in chars]:
        print("角色 %s 已存在，已中止（更新 zh_CN 请直接改 JSON）" % name)
        return 1

    print("将新建角色 %s（第 %d 位），%d 条：" % (name, pos, len(items)))
    for i, it in enumerate(items, 1):
        print("  [%02d] Q %s" % (i, _norm(it["q"])))
        print("       G %s" % _norm(it["good"]))
        print("       B %s" % _norm(it["bad"]))
    if not args.apply:
        print("\n（dry run，未写入。加 --apply 写入）")
        return 0

    chars.insert(pos, {
        "name": {l: (name if l == "zh_CN" else "") for l in LOCALES_NAME},
        "advises": [{f: {l: (_norm(it[k]) if l == "zh_CN" else "") for l in LOCALES_TEXT}
                     for f, k in (("prompt", "q"), ("good", "good"), ("bad", "bad"))}
                    for it in items],
    })
    data["last_update"] = date.today().isoformat()
    with open(DST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("\n已写入 %s（第 %d 位），角色总数 %d" % (name, pos, len(chars)))
    return 0


def _find_char(chars, value):
    """按 zh_CN 名 / en 名 / 1 起序号定位角色（避免命令行传非 ASCII）。"""
    if value.lstrip("-").isdigit():
        i = int(value)
        return chars[i - 1] if 1 <= i <= len(chars) else None
    for c in chars:
        if value in (c["name"]["zh_CN"], c["name"]["en"], c["name"]["ja"]):
            return c
    return None


def cmd_fill(args, lang):
    data = json.load(open(DST, encoding="utf-8"))
    chars = data["character"]
    table = fetch_en_all(args.refresh) if lang == "en" else fetch_ja_all(args.refresh)

    if args.all:
        targets = [(c, c["name"][lang]) for c in chars if c["name"][lang]]
        print("批量刷新 %s：%d 个角色（该语言名为空的跳过）" % (lang, len(targets)))
    elif args.char:
        char = _find_char(chars, args.char)
        if char is None:
            print("i18n 中找不到角色 %r（可用 zh_CN 名 / 英文名 / 1 起序号）" % args.char)
            return 1
        src_name = args.locator or char["name"][lang]  # 未给源名则取该角色该语言名。
        if not src_name:
            print("角色 %s 的 %s 名为空，需用 locator 显式给出源中的名字"
                  % (char["name"]["zh_CN"], lang))
            return 1
        targets = [(char, src_name)]
    else:
        if args.locator not in table:
            print("源中找不到 %r（可加 --refresh 重试）" % args.locator)
            return 1
        matched = [c for c in chars if c["name"][lang] == args.locator]
        if len(matched) != 1:
            print("i18n 中 %s 名为 %r 的角色有 %d 个，请用 --char 指定" % (lang, args.locator, len(matched)))
            return 1
        targets = [(matched[0], args.locator)]

    changed = skipped = 0
    for char, src_name in targets:
        src_items = table.get(src_name)
        if not src_items or len(src_items) != BASE_COUNT:
            print("  跳过 %s：源无数据或条目数非 %d" % (char["name"]["zh_CN"], BASE_COUNT))
            skipped += 1
            continue
        mapping, miss = _resolve(lang, src_items, char["advises"], args.map)
        if mapping is None:
            print("  跳过 %s：%d 条无法对齐（源序号 %s）；"
                  "需人工核对后 --map，或先补该语言文本以便按文本对齐"
                  % (char["name"]["zh_CN"], len(miss), miss[:10]))
            skipped += 1
            continue

        diffs = []
        for s, (d, side) in sorted(mapping.items()):
            it, adv = src_items[s - 1], char["advises"][d - 1]
            good, bad = _pairs(lang, it, side)
            for f, v in (("prompt", it["q"]), ("good", good), ("bad", bad)):
                if adv[f][lang] != v:
                    diffs.append((s, d, f, adv[f][lang], v, side))
        if not diffs:
            continue
        changed += 1
        print("\n== %s（%s）%d 处更新 ==" % (char["name"]["zh_CN"], src_name, len(diffs)))
        for s, d, f, old, new, side in diffs[:40]:
            tag = "" if lang == "en" else "  good=%s" % side
            print("  [源%02d -> 条目%02d]%s %s" % (s, d, tag, f))
            print("     旧: %s" % old)
            print("     新: %s" % new)
        if len(diffs) > 40:
            print("  ...另有 %d 处" % (len(diffs) - 40))
        if args.apply:  # 直接应用已收集的差异（diffs 已含新值）。
            for s, d, f, old, new, side in diffs:
                char["advises"][d - 1][f][lang] = new

    print("\n有更新的角色 %d，跳过 %d" % (changed, skipped))
    if not args.apply:
        print("（dry run，未写入。加 --apply 写入）")
        return 0
    if changed:
        data["last_update"] = date.today().isoformat()
        with open(DST, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("已写入 %s" % DST)
    return 0


def main():
    p = argparse.ArgumentParser(description="好感度对话三语言导入 / 更新")
    p.add_argument("lang", choices=("zh_CN", "en", "ja"), help="目标语言（决定数据源）")
    p.add_argument("locator", nargs="?",
                   help="zh_CN: gamekee 内容 id；en: 角色英文名；ja: 角色日文名")
    p.add_argument("--all", action="store_true", help="批量刷新该语言的全部角色")
    p.add_argument("--char", help="按 zh_CN 名 / 英文名 / 1 起序号定位角色（避免命令行传非 ASCII）")
    p.add_argument("--map", help="人工映射：en \"1:4,2:8\"；ja \"1:4A,2:8B\"")
    p.add_argument("--at", default="end", help="仅 zh_CN 新建：end / 数字索引 / 角色名")
    p.add_argument("--apply", action="store_true", help="真正写入（缺省 dry run）")
    p.add_argument("--refresh", action="store_true", help="忽略缓存重新下载源数据")
    p.add_argument("--file", help="仅 zh_CN：从本地内容 JSON 离线导入（CDN 被风控时用）")
    args = p.parse_args()

    if args.all:
        if args.lang == "zh_CN":
            print("--all 不支持 zh_CN（简中需按条目逐个从 gamekee 建）")
            return 1
        return cmd_fill(args, args.lang)
    if not args.locator and not args.char:
        print("缺少 locator（或改用 --all / --char）")
        return 1
    if args.lang == "zh_CN":
        return cmd_add_zh(args)
    return cmd_fill(args, args.lang)


if __name__ == "__main__":
    sys.exit(main())
