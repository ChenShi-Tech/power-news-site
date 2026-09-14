# -*- coding: utf-8 -*-
"""电力资讯站 - 数据构建脚本

数据源: /Users/xiaodongzheng/WorkBuddy/电力资料获取/
  - reports/*.md         每日采集日报（条目索引）
  - data/<机构>/<日期>/<栏目>/*.md   正文存档

产物: site/data/news.json  供静态站点消费

用法:
    python build_site.py                 # 全量重建
    python build_site.py --incremental   # 仅增量（同全量，保留已生成 body 缓存）
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta

SOURCE_ROOT = "/Users/xiaodongzheng/WorkBuddy/电力资料获取"
REPORT_DIR = os.path.join(SOURCE_ROOT, "reports")
DATA_DIR = os.path.join(SOURCE_ROOT, "data")

SITE_ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(SITE_ROOT, "site", "data", "news.json")

# 附件体积控制：站点是公开的，避免发布包失控
# （实测原始附件合计 108MB，含单个 18MB 的 zip，必须限制）
MAX_ATTACH_BYTES = 5 * 1024 * 1024           # 单个附件上限
MAX_ATTACH_TOTAL = 40 * 1024 * 1024          # 全站附件累计上限

# ---------------------------------------------------------------- 分类体系

# 主分类（用于首页 tab 筛选）
CATEGORIES = [
    "政策法规",
    "电力市场",
    "新能源",
    "电网建设",
    "安全生产",
    "资质监管",
    "企业动态",
    "数据统计",
]

# 关键词 → 主分类（按优先级从上到下匹配，仅作用于标题，避免正文泛词污染）
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("安全生产", ["安全生产", "安全运行", "安全检查", "安全风险", "安全大检查", "电力安全",
                  "应急", "隐患", "事故", "防汛", "防台", "防灾", "抢险", "覆冰", "台风",
                  "保供电", "迎峰度夏", "迎峰度冬", "风险管控", "大面积停电"]),
    ("电力市场", ["电力市场", "现货市场", "现货交易", "中长期", "电力交易", "交易中心",
                  "电价", "结算", "售电", "绿电交易", "市场化", "分时电价", "峰谷",
                  "代理购电", "辅助服务", "容量电价", "输配电价", "零售", "省间",
                  "需求响应", "虚拟电厂", "负电价", "报价", "出清", "绿证交易", "交易规则"]),
    ("新能源", ["新能源", "光伏", "风电", "储能", "氢能", "抽水蓄能", "消纳", "绿证",
                "可再生能源", "双碳", "清洁能源", "光热", "钠电", "动力电池", "零碳园区",
                "绿电直连", "充电设施", "充电桩", "新能源汽车", "海上风电", "核电"]),
    ("电网建设", ["特高压", "输配电", "西电东送", "配网", "微电网", "输电", "变电", "换流站",
                  "主网架", "跨省跨区", "并网", "电网建设", "工程投产", "输电线路", "电缆",
                  "变压器", "智能电网", "数字电网", "电网投资", "通道", "电网工程", "电鸿"]),
    ("资质监管", ["许可", "资质", "12398", "投诉举报", "行政处罚", "信用", "注册", "公示",
                  "注销", "市场注册", "垄断", "不正当竞争", "违规", "罚", "准入", "备案",
                  "专家库", "评标"]),
    ("数据统计", ["装机", "发电量", "用电量", "同比增长", "运行情况", "统计数据", "指数",
                  "解析", "月报", "年报", "半年报", "季度", "运行报告", "供需形势"]),
    ("政策法规", ["征求意见", "管理办法", "实施细则", "规划", "规则", "指导意见", "通知",
                  "公告", "办法", "细则", "实施方案", "条例", "政策", "标准", "立法",
                  "修订", "方案", "指引"]),
]

# 栏目 → 兜底分类
COLUMN_FALLBACK = {
    "公司要闻": "企业动态",
    "中电联动态": "企业动态",
    "工作动态": "企业动态",
    "新闻动态": "企业动态",
    "要闻": "企业动态",
    "监管动态": "资质监管",
    "通知公告": "政策法规",
    "通知": "政策法规",
    "公告": "政策法规",
    "市场动态": "电力市场",
    "名企动态": "企业动态",
}

# 细标签：主体实体
ENTITY_TAGS = [
    "国家能源局", "国家发改委", "国家发展改革委", "南方电网", "国家电网", "中电联",
    "中国电力企业联合会", "北京电力交易中心", "广州电力交易中心", "五大发电",
    "国家能源集团", "华能", "大唐", "华电", "国家电投", "三峡", "中广核", "中核",
    "国网", "南网", "APEC", "IRENA", "隆基", "宁德时代", "正泰", "华为", "比亚迪",
    "特变电工", "金风科技", "阳光电源", "通威", "晶科", "天合",
]
REGION_TAGS = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏",
    "新疆", "粤港澳", "长三角", "京津冀",
]
TOPIC_TAGS = [
    "新型电力系统", "现货市场", "绿电", "绿证", "储能", "虚拟电厂", "氢能", "充电桩",
    "数据中心", "算电协同", "人工智能", "大模型", "数字化转型", "乡村振兴", "一带一路",
    "十五五", "双碳", "碳排放", "新能源消纳", "电价机制",
]

# 来源机构 → 显示名 / 简写
ORG_META = {
    "国家能源局": ("国家能源局", "NEA"),
    "国家发改委": ("国家发改委", "NDRC"),
    "中电联": ("中电联", "CEC"),
    "南方电网": ("南方电网", "CSG"),
    "国家电网": ("国家电网", "SGCC"),
    "北极星电力网": ("北极星电力网", "BJX"),
    "区域能源监管局-华北": ("华北能源监管局", "HB"),
    "区域能源监管局-华东": ("华东能源监管局", "HD"),
    "区域能源监管局-华中": ("华中能源监管局", "HZ"),
    "区域能源监管局-东北": ("东北能源监管局", "DB"),
    "区域能源监管局-西北": ("西北能源监管局", "XB"),
    "区域能源监管局-南方": ("南方能源监管局", "NF"),
}

# ---------------------------------------------------------------- 文本清洗

# 政府/企业网站导航残留词（整段命中即丢弃）
NAV_NOISE = {
    "设为首页", "工作邮箱", "首页", "机构概览", "动态要闻", "信息公开", "在线办事",
    "互动回应", "专题专栏", "Aa", "字体：", "小 | 中 | 大", "打印", "关闭", "返回顶部",
    "分享到：", "扫一扫", "微信", "微博", "上一篇", "下一篇", "相关链接", "友情链接",
    "网站地图", "联系我们", "版权声明", "京ICP备", "主办单位", "承办单位", "技术支持",
    "南网报讯", "本报讯", "更多>", "更多 »", "最新推荐", "热点排行",
}


def _norm_text(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", s or "")


def _grams(s: str, n: int = 3) -> set:
    s = _norm_text(s)
    if len(s) < n:
        return set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def containment(a: str, b: str) -> float:
    """包含度：以较短一方为分母，用于识别"整段被重复"的情况。"""
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


def dedupe_within(text: str, threshold: float = 0.9, min_len: int = 20) -> str:
    """段内句子去重：处理"正文 A + 正文 A"挤在同一段落里的情况。

    只在段落内部比对本段已出现的句子，不做跨段落累积。
    跨段落的重复（多粒度存档）由 dedupe_piecewise 在行这一层处理 —— 若在此处
    跨段累积，会把"逐字段行"这种更可读的细粒度版本当成重复一并删掉。
    """
    sents = re.split(r"(?<=[。！？!?])", text)
    seen: list[set] = []
    out: list[str] = []
    for s in sents:
        if len(s) >= min_len:
            g = _grams(s)
            if g and any(len(g & sg) / min(len(g), len(sg)) >= threshold for sg in seen):
                continue
            seen.append(g)
        out.append(s)
    return "".join(out).strip()


# 行内导航词（TRS/政务站正文常与之挤在同一行）
NAV_INLINE_RE = re.compile(
    r"(设为首页|工作邮箱|机构概览|动态要闻|信息公开|在线办事|互动回应|专题专栏|"
    r"扫一扫在手机打开当前页|字体[:：])"
)

# 页脚起始标志 —— 这些词在正文中几乎不出现，命中即从该处截断。
# 注意不要放入"主办单位/联系我们"这类会出现在公文元信息块或正文里的词。
FOOTER_CUT_RE = re.compile(
    r"(扫一扫在手机打开当前页|网站地图|版权所有|ICP备|公网安备|"
    r"网站标识码|国家级政府网站|政府网站标识|无障碍浏览)"
)

# 页脚行特征 —— 短行命中即整行丢弃
FOOTER_LINE_RE = re.compile(
    r"(网站地图|联系我们|版权所有|主办单位|承办单位|技术支持|ICP备|公网安备|"
    r"网站标识码|邮编|邮政编码|值班电话|咨询电话|传真|扫一扫|关于我们|"
    r"广告服务|意见反馈|办公地址)"
)


def strip_inline_noise(text: str) -> str:
    """行内清洗：截断页脚、删除夹在正文中的导航词与元信息。"""
    m = FOOTER_CUT_RE.search(text)
    if m and m.start() >= 20:  # 只保护极短前缀，避免误截正文开头的正常表述
        text = text[: m.start()]
    text = NAV_INLINE_RE.sub(" ", text)
    # 政府站"目录项的基本信息"元信息块（国家能源局页面常见，且常与正文压在一行）
    text = re.sub(r"目录项的基本信息", " ", text)
    text = re.sub(r"公开事项名称[:：]", " ", text)
    text = re.sub(r"索引号[:：]\s*[\w\-/]{6,40}", " ", text)
    text = re.sub(r"制发日期[:：]\s*\d{4}[-年]\d{1,2}[-月]\d{1,2}日?", " ", text)
    # 孤立的小工具词
    text = re.sub(r"(?<![\u4e00-\u9fa5])首页(?![\u4e00-\u9fa5])", " ", text)
    text = re.sub(r"(?<![\u4e00-\u9fa5])Aa(?![\u4e00-\u9fa5])", " ", text)
    text = re.sub(r"小\s*[|｜]\s*中\s*[|｜]\s*大", " ", text)
    # 夹在行内的"2026-08-03 19:15 来源：国家能源局东北监管局"
    text = re.sub(
        r"\d{4}[-－/年]\d{1,2}[-－/月]\d{1,2}日?\s*\d{1,2}:\d{2}\s*来源[:：]\s*[\u4e00-\u9fa5A-Za-z]{2,22}",
        " ", text)
    return re.sub(r"[ \t\u3000]+", " ", text).strip()


def dedupe_piecewise(cands: list[str], cover_ratio: float = 0.80) -> list[str]:
    """丢弃"可由其他行拼凑出来"的长行。

    TRS 类政务站（区域能源监管局）的正文存档会把同一内容以三种粒度挤在一起，
    且用**单换行**分隔（不是空行），因此三遍内容落在同一个块里：①一段紧凑长文
    （导航+正文+页脚压在一行）②一份分段正文 ③一份逐字段行。

    判据：长行的内容若能被其他较短的行**按字符位置**基本覆盖（≥85%），说明它
    只是其他行的合并版，丢弃它、保留粒度更细（更可读）的版本。短行一律不参与
    丢弃判定，避免把"逐字段行"当成"长段落的子串"而误删。

    用字符位置覆盖而非 3-gram 覆盖率：字段被合并成长行时，字段衔接处会产生
    "司统一社会"这类跨界 n-gram，在拆分版里并不存在，用 n-gram 会低估覆盖率
    而漏判。
    """
    norm = [_norm_text(c) for c in cands]
    drop: set[int] = set()

    for i, a in enumerate(norm):
        if len(a) < 120:
            continue
        covered = bytearray(len(a))
        for j, b in enumerate(norm):
            if i == j or not b or len(b) >= len(a):
                continue
            start = 0
            while True:
                pos = a.find(b, start)
                if pos < 0:
                    break
                for k in range(pos, pos + len(b)):
                    covered[k] = 1
                start = pos + 1
        if sum(covered) / len(a) >= cover_ratio:
            drop.add(i)

    return [c for i, c in enumerate(cands) if i not in drop]


def is_nav_noise(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if t in NAV_NOISE:
        return True
    # markdown 图片行：图片单独作为画廊呈现，不混进正文段落
    if re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", t):
        return True
    # 页脚行
    if len(t) < 100 and FOOTER_LINE_RE.search(t):
        return True
    # 以页脚标志开头的行（整行都是页脚，只是被压成一行而已）
    if len(t) < 500 and re.match(
        r"^(网站地图|联系我们|主办单位|承办单位|版权所有|扫一扫在手机|办公地址|"
        r"邮编|邮政编码|值班电话|传真|ICP备|公网安备|网站标识码)", t):
        return True
    # "2026-08-03 19:15 来源：国家能源局东北监管局" 这类列表元信息行
    if re.match(r"^\d{4}[-－/]\d{1,2}[-－/]\d{1,2}\s+\d{1,2}:\d{2}\s*来源[:：]", t):
        return True
    # 纯符号 / 纯数字 / 极短且无中文语义
    if len(t) <= 6 and not re.search(r"[\u4e00-\u9fa5]{3,}", t):
        return True
    # 导航密集行：短行且含多个导航词
    hits = sum(1 for w in ("首页", "机构概览", "动态要闻", "信息公开", "在线办事", "互动回应", "专题专栏") if w in t)
    if len(t) < 150 and hits >= 4:
        return True
    if t.startswith("来源：") and len(t) < 20:
        return True
    return False


def clean_body(raw: str, title: str = "") -> tuple[str, list[str]]:
    """清洗正文存档 md，返回 (纯文本, 段落列表)。"""
    text = raw

    # 1. 剥离开头的元信息块（以 --- 分隔）
    parts = re.split(r"\n-{3,}\n", text, maxsplit=1)
    if len(parts) == 2:
        text = parts[1]

    # 2. 去掉元信息行（- **来源机构**: ... 等）
    lines = []
    for ln in text.split("\n"):
        s = ln.strip()
        if re.match(r"^[-*]\s*\*\*(来源机构|栏目|发布日期|原文链接|列表摘要|附件)\*\*", s):
            continue
        lines.append(ln)
    text = "\n".join(lines)

    # 3. 去掉 markdown 标题行标记 / 列表符号
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.M)

    # 4. 按空行分块；块内如果是"行式结构"则逐行处理，否则视为一个段落
    tnorm = _norm_text(title)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    cands: list[str] = []
    for b in blocks:
        sub = [x.strip() for x in b.split("\n") if x.strip()]
        if len(sub) >= 4:
            # 多行块：短行占比高 = 列表/字段流（TRS 存档、公告明细），逐行保留
            short_ratio = sum(1 for x in sub if len(x) < 50) / len(sub)
            pieces = sub if short_ratio >= 0.35 else [" ".join(sub)]
        else:
            pieces = sub

        for pc in pieces:
            s = strip_inline_noise(pc)
            if not s or len(s) < 12 or is_nav_noise(s):
                continue
            ns = _norm_text(s)
            if not ns:
                continue
            # 正文里重复的公文标题（页面 h1 已展示，无需再占一段）
            if tnorm and abs(len(ns) - len(tnorm)) < 12 and containment(ns, tnorm) > 0.85:
                continue
            cands.append(s)

    # 5. 行级去重：丢掉"由其他行拼出的长合并版"（多粒度存档的核心处理）
    cands = dedupe_piecewise(cands)

    # 6. 段内句子去重：处理"正文 A + 正文 A"挤在同一段里的情况
    kept: list[str] = []
    for p in cands:
        p = dedupe_within(p)
        if p and len(p) >= 12:
            kept.append(p)

    # 7. 超长段落按句读切分，提升可读性（政务站常把整篇压成一段）
    CLOSERS = "，。、；：）】」』》\"'’”"
    final: list[str] = []
    for p in kept:
        if len(p) <= 600:
            final.append(p)
            continue
        buf = ""
        for s in re.split(r"(?<=[。！？；])", p):
            # 若本片以闭合标点开头，说明上一处切分落在句子中间，续接回去
            if buf and re.match("^[" + re.escape(CLOSERS) + "]", s.strip()):
                buf += s
                continue
            buf += s
            if len(buf) >= 260:
                final.append(buf.strip())
                buf = ""
        if buf.strip():
            final.append(buf.strip())

    body = "\n\n".join(final)
    return body, final


def make_excerpt(body: str, limit: int = 150) -> str:
    """生成摘要片段（正文首段优先）。"""
    if not body:
        return ""
    paras = [p for p in body.split("\n\n") if p.strip()]
    if not paras:
        return ""
    # 找第一段"像正文"的（长度 > 30）
    for p in paras:
        if len(p) >= 30:
            return p[:limit] + ("…" if len(p) > limit else "")
    return paras[0][:limit]


RE_MD_IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


# ---------------------------------------------------------------- 归档扫描
# 直接从 data/ 全量扫描，而不是依赖 reports/*.md 索引 ——
# reports 是按天生成的文件，同一天多次采集（如分批跑 --only）会互相覆盖，
# 导致后跑的批次把先跑批次的条目从索引里冲掉。data/ 才是真正的归档。

RE_MD_META = re.compile(
    r"^-\s*\*\*(来源机构|栏目|发布日期|原文链接|摘要|附件)\*\*\s*[:：]\s*(.*)$"
)

# 归档 md 头部的中文键 → 内部英文键
_META_KEYS = {
    "来源机构": "org",
    "栏目": "column",
    "发布日期": "date",
    "原文链接": "url",
    "摘要": "summary",
    "附件": "attachments",
}


def parse_md_header(raw: str) -> dict:
    """解析正文存档 md 头部的元信息块，返回英文键的 dict。"""
    lines = (raw or "").split("\n")
    meta: dict = {}
    for ln in lines[:45]:
        m = RE_MD_META.match(ln.strip())
        if m:
            meta[_META_KEYS.get(m.group(1), m.group(1))] = m.group(2).strip()
    for ln in lines[:6]:
        tm = re.match(r"^#\s+(.+?)\s*$", ln.strip())
        if tm:
            title = tm.group(1).strip()
            dm = RE_DATE_SUFFIX.search(title)
            if dm:
                title = title[: dm.start()].strip()
            meta["title"] = title
            break
    return meta


def scan_data_dir() -> list[dict]:
    """扫描 data/<机构>/<日期>/<栏目>/*.md，返回全部归档条目。"""
    out: list[dict] = []
    if not os.path.isdir(DATA_DIR):
        return out
    for org in sorted(os.listdir(DATA_DIR)):
        org_path = os.path.join(DATA_DIR, org)
        # bjpx 是北京电力交易中心的批量归档，格式与日报体系不同，跳过
        if not os.path.isdir(org_path) or org == "bjpx":
            continue
        for day in sorted(os.listdir(org_path)):
            day_path = os.path.join(org_path, day)
            if not os.path.isdir(day_path):
                continue
            for cat in sorted(os.listdir(day_path)):
                cat_path = os.path.join(day_path, cat)
                if not os.path.isdir(cat_path):
                    continue
                for fn in sorted(os.listdir(cat_path)):
                    if not fn.endswith(".md") or fn.startswith("."):
                        continue
                    md_path = os.path.join(cat_path, fn)
                    try:
                        with open(md_path, encoding="utf-8") as f:
                            raw = f.read()
                    except Exception:
                        continue
                    meta = parse_md_header(raw)
                    if not meta.get("url"):
                        continue
                    # 附件：命名规则为 <md文件名去扩展名>-附件N.ext
                    atts = []
                    stem = fn[:-3]
                    try:
                        for f2 in sorted(os.listdir(cat_path)):
                            if f2.startswith(stem + "-附件"):
                                atts.append(os.path.join(cat_path, f2))
                    except Exception:
                        pass
                    out.append({
                        "org": meta.get("org") or org,
                        "column": meta.get("column") or cat,
                        "title": meta.get("title") or fn[:-3],
                        "url": meta["url"].strip(),
                        "date": meta.get("date") or day,
                        "list_summary": meta.get("summary", ""),
                        "archive": os.path.relpath(md_path, SOURCE_ROOT),
                        "raw": raw,
                        "attachments": atts,
                    })
    return out


def load_ai_summaries() -> dict:
    """回收 AI 摘要，按原文 URL 关联。

    两个来源：
    1. `reports/*.md` —— 每日采集自动化写入的 AI摘要字段
    2. `summaries.json` —— gen_summaries.py 用 LLM 补生成的（优先级更高）
    """
    out: dict = {}
    if os.path.isdir(REPORT_DIR):
        for rf in sorted(os.listdir(REPORT_DIR)):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", rf):
                continue
            try:
                for it in parse_report(os.path.join(REPORT_DIR, rf)):
                    if it.get("ai") and it.get("url"):
                        out[it["url"].strip().rstrip("/")] = it["ai"]
            except Exception:
                continue

    manual = os.path.join(SITE_ROOT, "summaries.json")
    if os.path.isfile(manual):
        try:
            with open(manual, encoding="utf-8") as f:
                for k, v in (json.load(f) or {}).items():
                    if v and str(v).strip():
                        out[str(k).strip().rstrip("/")] = str(v).strip()
        except Exception:
            pass
    return out


def file_md5(path: str) -> str:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def build_image_blacklist(by_url: dict, threshold: int = 3) -> set:
    """找出跨多篇文章重复出现的图片 —— 这类是站点推广素材/二维码，不是新闻配图。

    实测中国能源报每篇文章都挂同一套推广横幅与公众号二维码（"总书记的能源足迹"等），
    它们的 URL（img-rs CDN 的 imageDir 路径）不含 logo/qrcode/banner 等关键词，
    靠 URL 规则过滤不掉；但会在每篇文章里原样重复，用"出现篇数"判定最可靠。
    """
    from collections import Counter
    cnt: Counter = Counter()
    for url, it in by_url.items():
        raw = it.get("raw") or ""
        base = os.path.dirname(os.path.join(SOURCE_ROOT, it.get("archive", "")))
        seen = set()
        for rel in RE_MD_IMG.findall(raw):
            src = os.path.normpath(os.path.join(base, rel))
            if not os.path.isfile(src):
                continue
            h = file_md5(src)
            if h and h not in seen:
                seen.add(h)
                cnt[h] += 1
    return {h for h, n in cnt.items() if n >= threshold}


def collect_images(raw_md: str, md_path: str, iid: str, img_root: str,
                   limit: int = 6, blacklist: set = None) -> list[str]:
    """把正文 md 里引用的配图复制到站点 images/<id>/ 下。

    返回站点相对路径列表（如 images/<id>/1.jpg），供 news.json 与前端消费。
    原件由采集器下载在正文同目录的 images/<hash>/ 内。
    """
    refs = RE_MD_IMG.findall(raw_md or "")
    if not refs:
        return []
    base = os.path.dirname(md_path)
    out: list[str] = []
    for rel in refs:
        if len(out) >= limit:
            break
        src = os.path.normpath(os.path.join(base, rel))
        if not os.path.isfile(src):
            continue
        # 站点推广素材/二维码（多篇文章共用）不作为新闻配图
        if blacklist and file_md5(src) in blacklist:
            continue
        ext = os.path.splitext(src)[1].lower() or ".jpg"
        name = f"{len(out) + 1}{ext}"
        rel_out = f"images/{iid}/{name}"
        dest = os.path.join(img_root, iid, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            shutil.copy2(src, dest)
            out.append(rel_out)
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- 主题聚合
# 对应 aihot.news/topics：按「机构与主体 / 区域市场 / 主题方向」分组
# 结构为 (显示名, [匹配关键词], 描述)
TOPICS: list[tuple[str, list[tuple[str, list[str], str]]]] = [
    ("机构与主体", [
        ("国家能源局", ["国家能源局"], "国家级能源主管部门：政策文件、发展规划、监管通报与人事动态。"),
        ("国家发改委", ["发改委", "发展改革委"], "价格机制、产业政策与宏观调控相关的能源电力文件。"),
        ("中电联", ["中电联", "电力企业联合会"], "行业标准、统计信息、职业能力建设与人才动态。"),
        ("南方电网", ["南方电网", "南网"], "公司要闻、工程投产、数字电网与经营动态。"),
        ("国家电网", ["国家电网", "国网"], "公司动态与跨区输电、配网建设进展。"),
        ("电力交易中心", ["电力交易中心", "交易中心"], "各电力交易中心的市场公告、交易规则与组织动态。"),
        ("能源监管局", ["能源监管局", "能监局", "监管局", "监管办"], "区域能源监管机构的监管、许可与行政处罚信息。"),
        ("发电集团", ["华能", "大唐", "华电", "国家能源集团", "国家电投", "三峡", "中广核", "中核"],
         "主要发电集团的机组、项目与经营动态。"),
    ]),
    ("区域市场", [
        ("四川", ["四川"], "西南水电与现货市场的重点省份。"),
        ("云南", ["云南"], "水电富集、西电东送与绿电交易前沿。"),
        ("广东", ["广东"], "南方区域电力市场的核心省份。"),
        ("山东", ["山东"], "现货市场与新能源装机大省。"),
        ("山西", ["山西"], "全国首个转正式运行的现货市场试点省份。"),
        ("内蒙古", ["内蒙古", "蒙西", "蒙东"], "新能源交易与绿电直连的重点区域。"),
        ("甘肃", ["甘肃"], "西北新能源基地与外送通道关键节点。"),
        ("新疆", ["新疆"], "新能源大基地与跨区外送。"),
        ("青海", ["青海"], "清洁能源示范省与储能实践。"),
        ("浙江", ["浙江"], "现货市场转正式运行省份之一。"),
    ]),
    ("主题方向", [
        ("电力市场", ["电力市场"], "电力市场建设、运行与监管的全局动态。"),
        ("现货市场", ["现货"], "电力现货市场的规则、出清、结算与试点进展。"),
        ("绿电绿证", ["绿电", "绿证", "绿色电力"], "绿电交易、绿证核发与消纳责任机制。"),
        ("电价机制", ["电价", "价格机制", "峰谷", "分时"], "电价机制、分时电价与价格政策调整。"),
        ("新能源消纳", ["消纳", "新能源"], "新能源并网消纳、利用率与保障机制。"),
        ("储能", ["储能", "抽水蓄能"], "新型储能与抽水蓄能的政策、项目与调用。"),
        ("虚拟电厂", ["虚拟电厂", "负荷聚合"], "虚拟电厂、需求响应与负荷侧资源聚合。"),
        ("源网荷储", ["源网荷储", "绿电直连", "零碳园区"], "源网荷储一体化、绿电直连与零碳园区。"),
        ("新型电力系统", ["新型电力系统", "新型电网"], "新型电力系统与新型电网建设的顶层设计。"),
        ("安全生产", ["安全", "应急", "隐患", "保供", "迎峰度夏"], "电力安全生产、隐患排查与保供电。"),
        ("资质许可", ["许可", "资质", "注册", "公示", "处罚"], "承装（修、试）许可、市场注册与行政处罚。"),
        ("电网工程", ["工程", "投产", "并网", "输电", "特高压"], "输变电工程、设备投产与并网进度。"),
    ]),
]


def _topic_hit(it: dict, kws: list[str]) -> bool:
    """主题命中判定：只看标题与标签，避免长文本里的泛词污染。"""
    blob = f"{it.get('title','')} {' '.join(it.get('tags') or [])}"
    return any(k in blob for k in kws)


def build_topics(items: list[dict], min_count: int = 2) -> dict:
    groups = []
    for group_name, defs in TOPICS:
        cards = []
        for name, kws, blurb in defs:
            hit = [it for it in items if _topic_hit(it, kws)]
            if len(hit) < min_count:
                continue
            cards.append({
                "name": name,
                "blurb": blurb,
                "count": len(hit),
                "ids": [it["id"] for it in hit[:60]],
            })
        cards.sort(key=lambda c: -c["count"])
        if cards:
            groups.append({"name": group_name, "cards": cards})
    total = sum(len(g["cards"]) for g in groups)
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": total,
        "groups": groups,
    }


# ---------------------------------------------------------------- 周期报告


def _iso_week_range(key: str) -> list[str]:
    y, w = key.split("-W")
    monday = datetime.strptime(f"{y}-W{w}-1", "%G-W%V-%u")
    return [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in (0, 6)]


def _week_label(key: str) -> str:
    r = _iso_week_range(key)
    d = datetime.strptime(r[0], "%Y-%m-%d")
    return f"{d.month}月第{(d.day - 1) // 7 + 1}周"


def _month_range(key: str) -> list[str]:
    y, m = int(key[:4]), int(key[5:7])
    return [f"{y}-{m:02d}-01", f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"]


def build_reports(items: list[dict]) -> dict:
    """生成日报 / 周报 / 月报。三者结构一致，前端共用一个报告视图。"""
    buckets = {"daily": {}, "weekly": {}, "monthly": {}}

    for it in items:
        d = it.get("date") or ""
        if not d:
            continue
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            continue
        iso = dt.isocalendar()
        for kind, key in (
            ("daily", d),
            ("weekly", f"{iso[0]}-W{iso[1]:02d}"),
            ("monthly", d[:7]),
        ):
            b = buckets[kind].setdefault(key, {"ids": [], "cats": {}})
            b["ids"].append(it["id"])
            c = it.get("category", "")
            b["cats"][c] = b["cats"].get(c, 0) + 1

    def finalize(kind: str) -> list[dict]:
        out = []
        for key, v in sorted(buckets[kind].items(), reverse=True):
            n = len(v["ids"])
            rec = {
                "key": key,
                "count": n,
                "read_min": max(1, round(n * 0.33)),
                "by_category": dict(sorted(v["cats"].items(), key=lambda kv: -kv[1])),
                "ids": v["ids"],
            }
            if kind == "daily":
                dt = datetime.strptime(key, "%Y-%m-%d")
                rec["label"] = f"{dt.month}月{dt.day}日"
                rec["sub"] = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()]
                rec["range"] = [key, key]
            elif kind == "weekly":
                r = _iso_week_range(key)
                rec["label"] = _week_label(key)
                rec["sub"] = key
                rec["range"] = r
            else:
                rec["label"] = f"{int(key[5:7])} 月"
                rec["sub"] = key
                rec["range"] = _month_range(key)
            out.append(rec)
        return out

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "daily": finalize("daily"),
        "weekly": finalize("weekly"),
        "monthly": finalize("monthly"),
    }


# ---------------------------------------------------------------- 标签推导


def derive_tags(title: str, category: str, org: str, body: str, ai: str) -> list[str]:
    """推导细标签：最多 3 个。"""
    blob = f"{title} {body[:600]} {ai}"
    tags: list[str] = []

    # 机构类标签
    for e in ENTITY_TAGS:
        if e in title:
            tags.append(e)
            break
    if not tags and org in ("国家能源局", "国家发改委", "中电联", "南方电网", "国家电网"):
        tags.append(ORG_META.get(org, (org, ""))[0])

    # 主题类标签
    for t in TOPIC_TAGS:
        if t in blob and t not in tags:
            tags.append(t)
        if len(tags) >= 3:
            break

    # 地域类标签
    if len(tags) < 3:
        for r in REGION_TAGS:
            if r in title and r not in tags:
                tags.append(r)
                break

    # 保底：用主分类
    if not tags:
        tags.append(category)

    return tags[:3]


def org_short_name(org: str) -> str:
    """机构短名：用于时间轴在缺少发布时间时显示来源标识。"""
    if org in ORG_META and ORG_META[org][1]:
        return ORG_META[org][1]
    m = re.match(r"区域能源监管局-(.+)", org or "")
    if m:
        return m.group(1)          # 华北 / 东北 / 华东 …
    if org == "北极星电力市场网":
        return "北极星"
    if org == "中国能源报":
        return "能源报"
    return (org or "")[:3]


def derive_category(title: str, raw_cat: str, org: str, body: str, ai: str) -> str:
    """推导主分类：仅用标题判定，未命中则按栏目兜底。

    不使用正文/AI 摘要兜底 —— 长文本中的泛词会污染分类（如企业调研稿里
    提到"数字电网"就被判为电网建设）。标题最能反映文章主题。
    """
    for cat, kws in CATEGORY_RULES:
        for kw in kws:
            if kw in title:
                return cat
    for key, cat in COLUMN_FALLBACK.items():
        if key in raw_cat:
            return cat
    return "企业动态"


def make_short_title(title: str, limit: int = 46) -> str:
    """过长的标题按首个空格切分，取最能表意的前半段。"""
    t = title.strip()
    if len(t) <= limit:
        return t
    # 在空格 / 全角空格处切分
    parts = re.split(r"[\s\u3000]+", t)
    if len(parts) > 1 and len(parts[0]) >= 16:
        return parts[0]
    return t[:limit] + "…"


RE_TIME_INLINE = re.compile(
    r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})日?[\sT]+(\d{1,2})[:：](\d{2})"
)


def extract_pub_time(text: str) -> str:
    """从正文/摘录中提取 'YYYY-MM-DD HH:MM' 里的时间部分。"""
    if not text:
        return ""
    m = RE_TIME_INLINE.search(text)
    if m:
        return f"{int(m.group(4)):02d}:{int(m.group(5)):02d}"
    return ""


# ---------------------------------------------------------------- 报告解析

RE_ORG_HEAD = re.compile(r"^##\s+(.+?)（(\d+)\s*篇）\s*$")
RE_ITEM_HEAD = re.compile(r"^###\s+(?:\[([^\]]+)\]\s*)?(.+?)\s*$")
RE_FIELD = re.compile(r"^-\s*(原文|正文存档|列表摘要|附件)\s*[:：]\s*(.*)$")
RE_AI = re.compile(r"^-\s*\*\*AI摘要\*\*\s*[:：]\s*(.*)$")
RE_QUOTE = re.compile(r"^>\s*摘录\s*[:：]\s*(.*)$")
RE_DATE_SUFFIX = re.compile(r"\s+(\d{4}-\d{2}-\d{2})\s*$")


def parse_report(path: str) -> list[dict]:
    """解析单份日报，返回条目列表。"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    items: list[dict] = []
    cur_org = ""
    cur: dict | None = None

    def flush():
        nonlocal cur
        if cur and cur.get("title"):
            items.append(cur)
        cur = None

    for raw in lines:
        line = raw.rstrip()

        m = RE_ORG_HEAD.match(line)
        if m:
            flush()
            cur_org = m.group(1).strip()
            continue

        m = RE_ITEM_HEAD.match(line)
        if m:
            flush()
            cat = (m.group(1) or "").strip()
            title = m.group(2).strip()
            pub = ""
            dm = RE_DATE_SUFFIX.search(title)
            if dm:
                pub = dm.group(1)
                title = title[: dm.start()].strip()
            cur = {
                "title": title,
                "org": cur_org,
                "raw_category": cat,
                "pub_hint": pub,
                "url": "",
                "archive": "",
                "list_summary": "",
                "ai": "",
                "excerpt": "",
                "attachments": [],
            }
            continue

        if cur is None:
            continue

        m = RE_AI.match(line)
        if m:
            cur["ai"] = m.group(1).strip()
            continue

        m = RE_QUOTE.match(line)
        if m:
            cur["excerpt"] = m.group(1).strip()
            continue

        m = RE_FIELD.match(line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key == "原文":
                cur["url"] = val
            elif key == "正文存档":
                cur["archive"] = val.strip("`").strip()
            elif key == "列表摘要":
                cur["list_summary"] = val
            elif key == "附件":
                cur["has_attachment"] = True
            continue

        # 附件子项
        m = re.match(r"^\s*-\s*`(.+?)`\s*$", line)
        if m and cur.get("has_attachment"):
            cur["attachments"].append(m.group(1))
            continue

    flush()
    return items


# ---------------------------------------------------------------- 主流程


def build_trends(items: list[dict]) -> dict:
    """按日 / 按分类的时间序列，供"关于"页画趋势图。

    用途举例：现货市场相关新闻量突然放大，往往对应政策窗口期。
    """
    day_cat: dict[str, dict[str, int]] = {}
    for it in items:
        d = it.get("date") or ""
        if not d:
            continue
        slot = day_cat.setdefault(d, {})
        c = it.get("category") or "其他"
        slot[c] = slot.get(c, 0) + 1

    days = sorted(day_cat)
    cats = [c for c, _ in sorted(
        ((c, sum(v.get(c, 0) for v in day_cat.values())) for c in CATEGORIES),
        key=lambda kv: -kv[1])]

    return {
        "days": days,
        "categories": cats,
        "series": {c: [day_cat[d].get(c, 0) for d in days] for c in cats},
        "total": [len([1]) * sum(day_cat[d].values()) for d in days],
    }


def write_feed(items: list[dict], limit: int = 60) -> str:
    """生成 RSS 2.0 订阅源（site/feed.xml）。"""
    from email.utils import format_datetime
    from datetime import timezone

    base = "https://powhot-electric-news.app.workbuddy.host"
    seen_titles = set()
    picked = []
    for it in items:
        t = it.get("title") or ""
        if t in seen_titles:
            continue
        seen_titles.add(t)
        picked.append(it)
        if len(picked) >= limit:
            break

    def rfc822(d: str, hhmm: str = "") -> str:
        try:
            dt = datetime.strptime((d or "1970-01-01") + " " + (hhmm or "09:00"),
                                   "%Y-%m-%d %H:%M")
            return format_datetime(dt.replace(tzinfo=timezone(timedelta(hours=8))))
        except Exception:
            return format_datetime(datetime(1970, 1, 1, tzinfo=timezone.utc))

    def cdata(s: str) -> str:
        return "<![CDATA[" + str(s).replace("]]>", "]]]]><![CDATA[>") + "]]>"

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        "<title>电力动态 POWHOT</title>",
        f"<link>{base}/</link>",
        "<description>电力行业动态聚合 · 每日精选与 AI 摘要</description>",
        "<language>zh-CN</language>",
        f"<lastBuildDate>{rfc822(items[0].get('date', '') if items else '')}</lastBuildDate>",
        f'<atom:link href="{base}/feed.xml" rel="self" type="application/rss+xml" />',
    ]
    for it in picked:
        link = f"{base}/#/item/{it['id']}"
        desc = it.get("ai") or it.get("excerpt") or ""
        body = [f"<p>{desc}</p>"]
        if it.get("images"):
            body.append(f'<p><img src="{base}/{it["images"][0]}" alt="" /></p>')
        body.append(f'<p>来源：{it.get("org","")} ｜ '
                    f'<a href="{it.get("url","")}">原文</a> ｜ '
                    f'<a href="{link}">站内详情</a></p>')
        out += [
            "<item>",
            f"<title>{cdata(it.get('title',''))}</title>",
            f"<link>{link}</link>",
            f'<guid isPermaLink="false">powhot-{it["id"]}</guid>',
            f"<pubDate>{rfc822(it.get('date',''), it.get('time',''))}</pubDate>",
            f"<category>{cdata(it.get('category',''))}</category>",
            f"<description>{cdata(''.join(body))}</description>",
            "</item>",
        ]
    out += ["</channel>", "</rss>"]
    feed = "\n".join(out)

    path = os.path.join(SITE_ROOT, "site", "feed.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(feed)
    return path


def stamp_assets() -> str:
    """给 index.html 里的 CSS/JS 引用打上内容哈希，避免 CDN 与浏览器缓存旧版本。

    实测部署侧的静态服务会按 Accept-Encoding 分缓存条目：curl 已能取到新版 CSS，
    而浏览器仍拿到旧版（旧版含 aspect-ratio、缺 media-detail），导致改了样式却看不到效果。
    带 ?v=<内容哈希> 是绕过这类缓存的通用做法，且只在资源真变化时才改版本号。
    """
    idx = os.path.join(SITE_ROOT, "site", "index.html")
    if not os.path.isfile(idx):
        return ""
    parts = []
    for rel in ("assets/style.css", "assets/app.js"):
        fp = os.path.join(SITE_ROOT, "site", rel)
        if os.path.isfile(fp):
            parts.append(file_md5(fp))
    if not parts:
        return ""
    v = hashlib.md5("".join(parts).encode()).hexdigest()[:8]

    with open(idx, encoding="utf-8") as f:
        html = f.read()
    new = re.sub(
        r"assets/(style\.css|app\.js)(\?v=[0-9a-zA-Z]+)?",
        lambda m: f"assets/{m.group(1)}?v={v}",
        html,
    )
    if new != html:
        with open(idx, "w", encoding="utf-8") as f:
            f.write(new)
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--incremental", action="store_true", help="增量模式（保留 body 缓存）")
    args = ap.parse_args()

    if not os.path.isdir(DATA_DIR):
        print(f"❌ 归档目录不存在: {DATA_DIR}", file=sys.stderr)
        sys.exit(1)

    # 1. 全量扫描归档目录（不依赖 reports 索引 —— 同日多次采集会互相覆盖报告）
    records = scan_data_dir()
    print(f"📁 扫描 data/ 归档：{len(records)} 份")
    ai_map = load_ai_summaries()
    print(f"🧠 从 reports/ 回收 AI 摘要：{len(ai_map)} 条")

    # 2. 按 URL 去重（同一条可能被多次采集，保留正文更完整的）
    by_url: dict[str, dict] = {}
    for r in records:
        key = (r.get("url") or "").strip().rstrip("/")
        if not key:
            continue
        old = by_url.get(key)
        if old is None or len(r.get("raw") or "") > len(old.get("raw") or ""):
            by_url[key] = r
    print(f"🔗 URL 去重后 {len(by_url)} 条")

    # 2.5 标题重复合并：只合并"同一篇被抓两次"的真重复。
    #     ⚠️ 判据必须同时看标题与正文 —— 曾经只用标题相似度，把
    #     「华中/华北/西北能源监管局召开树立和践行正确政绩观学习教育总结会」
    #     这类**不同机构的独立新闻**当成重复合并了（标题仅差前两字）。
    def _body_head(it: dict) -> str:
        raw = it.get("raw") or ""
        seg = raw.split("\n---\n", 1)[-1]
        return _norm_text(re.sub(r"!\[[^\]]*\]\([^)]+\)", "", seg))[:300]

    deduped: dict[str, dict] = {}
    dropped_dup: list[tuple[str, str]] = []
    for key, it in by_url.items():
        tnorm = _norm_text(it.get("title") or "")
        if len(tnorm) < 15:
            deduped[key] = it
            continue
        body_head = _body_head(it)
        hit = None
        for k2, it2 in deduped.items():
            if _norm_text(it2.get("title") or "") != tnorm:
                continue          # 标题必须完全一致
            b2 = _body_head(it2)
            if body_head and b2 and containment(body_head, b2) >= 0.90:
                hit = k2           # 正文开头也几乎一致 → 同一篇
                break
        if hit is None:
            deduped[key] = it
        else:
            if len(it.get("raw") or "") > len(deduped[hit].get("raw") or ""):
                dropped_dup.append((deduped[hit]["title"], it["title"]))
                deduped[hit] = it
            else:
                dropped_dup.append((it["title"], deduped[hit]["title"]))
    if dropped_dup:
        print(f"🧹 标题重复合并：{len(dropped_dup)} 组（标题全同且正文开头一致）")
        for a, b in dropped_dup[:4]:
            print(f"   「{a[:30]}」")
    by_url = deduped

    # 3. 富化：清洗正文 + 提取配图
    items: list[dict] = []
    img_root = os.path.join(SITE_ROOT, "site", "images")
    if os.path.isdir(img_root):
        shutil.rmtree(img_root)
    os.makedirs(img_root, exist_ok=True)
    files_root = os.path.join(SITE_ROOT, "site", "files")
    if os.path.isdir(files_root):
        shutil.rmtree(files_root)
    os.makedirs(files_root, exist_ok=True)
    no_body = 0
    att_total = 0        # 已复制附件累计体积
    att_skipped = 0      # 因超限被跳过的附件数

    # 预处理：识别站点推广素材（跨文章重复出现），避免当成新闻配图
    img_blacklist = build_image_blacklist(by_url, threshold=2)
    if img_blacklist:
        print(f"🖼️  剔除 {len(img_blacklist)} 张站点推广素材（跨文章重复出现）")

    for url, it in by_url.items():
        iid = hashlib.sha1(url.encode("utf-8")).hexdigest()[:14]
        raw = it.get("raw") or ""
        apath = os.path.join(SOURCE_ROOT, it["archive"])
        title = it["title"]
        org = it["org"]
        column = it["column"]

        images = collect_images(raw, apath, iid, img_root, blacklist=img_blacklist)
        try:
            body, _ = clean_body(raw, title)
        except Exception as e:
            print(f"   ⚠️ 清洗失败 {it['archive']}: {e}")
            body = ""
        if not body:
            no_body += 1

        date = it.get("date") or ""
        ai = (ai_map.get(url) or "").strip()
        excerpt = make_excerpt(body)

        # 附件：复制到站点 files/<id>/，前端提供下载（受体积上限约束）
        att_out: list[dict] = []
        for idx, src in enumerate((it.get("attachments") or [])[:5], 1):
            try:
                size = os.path.getsize(src)
            except Exception:
                continue
            if size > MAX_ATTACH_BYTES or att_total + size > MAX_ATTACH_TOTAL:
                att_skipped += 1
                continue
            ext = os.path.splitext(src)[1] or ".bin"
            rel_out = f"files/{iid}/{idx}{ext}"
            dest = os.path.join(SITE_ROOT, "site", rel_out)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                shutil.copy2(src, dest)
                att_total += size
                att_out.append({
                    "name": os.path.basename(src),
                    "path": rel_out,
                    "size": size,
                })
            except Exception:
                pass

        cat = derive_category(title, column, org, body, ai)
        tags = derive_tags(title, cat, org, body, ai)
        # 发布时间要从**原始 md** 提取 —— 清洗后的正文里已经不含
        # "2026-08-03 19:15 来源：..." 这类时间戳了
        pub_time = extract_pub_time(raw) or extract_pub_time(body[:800])

        items.append({
            "id": iid,
            "title": title,
            "short_title": make_short_title(title),
            "org": org,
            "org_short": org_short_name(org),
            "column": column,
            "category": cat,
            "date": date,
            "time": pub_time,
            "url": url,
            "ai": ai,
            "excerpt": excerpt,
            "body_len": len(body),
            "images": images,
            "tags": tags,
            "has_attachment": bool(att_out),
            "attachment_count": len(att_out),
            "files": att_out,
            "list_summary": it.get("list_summary", ""),
            "_body": body,
            "_attachments": [],
        })

    if no_body:
        print(f"   ℹ️ {no_body} 条清洗后无正文（仅展示摘要与原文链接）")

    # 5. 排序：日期倒序 → 机构 → 标题
    items.sort(key=lambda x: (x["date"] or "0000-00-00", x["org"], x["title"]), reverse=True)

    # 6. 统计
    by_org: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    by_day: dict[str, int] = {}
    for it in items:
        by_org[it["org"]] = by_org.get(it["org"], 0) + 1
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
        if it["date"]:
            by_day[it["date"]] = by_day.get(it["date"], 0) + 1
    ai_covered = sum(1 for it in items if it["ai"])
    with_body = sum(1 for it in items if it["_body"])

    # 7. 拆分输出：列表数据 + 详情按需加载
    body_dir = os.path.join(os.path.dirname(OUT_JSON), "bodies")
    if os.path.isdir(body_dir):
        for old in os.listdir(body_dir):
            os.remove(os.path.join(body_dir, old))
    os.makedirs(body_dir, exist_ok=True)

    slim_items = []
    for it in items:
        body = it.pop("_body", "")
        atts = it.pop("_attachments", [])
        slim_items.append(it)
        if body or atts:
            with open(os.path.join(body_dir, f"{it['id']}.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "id": it["id"],
                        "body": body,
                        "paragraphs": [p for p in body.split("\n\n") if p.strip()],
                        "attachments": [os.path.basename(a) for a in atts],
                    },
                    f,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )

    # 7.5 主题聚合与周期报告（只引用条目 id，前端按需从 news.json 取细节）
    topics_data = build_topics(slim_items)
    reports_data = build_reports(slim_items)
    trends_data = build_trends(slim_items)
    data_dir = os.path.dirname(OUT_JSON)
    for name, data in (("topics.json", topics_data),
                       ("reports.json", reports_data),
                       ("trends.json", trends_data)):
        with open(os.path.join(data_dir, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    feed_path = write_feed(slim_items)
    print(f"📡 已生成 RSS 订阅源: {os.path.relpath(feed_path, SITE_ROOT)}")

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": {
            "total": len(slim_items),
            "ai_covered": ai_covered,
            "with_body": with_body,
            "by_org": dict(sorted(by_org.items(), key=lambda kv: -kv[1])),
            "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
            "by_day": dict(sorted(by_day.items(), reverse=True)),
            "days": len(by_day),
            "date_range": [
                min((it["date"] for it in slim_items if it["date"]), default=""),
                max((it["date"] for it in slim_items if it["date"]), default=""),
            ],
        },
        "items": slim_items,
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(OUT_JSON) / 1024
    print(f"\n✅ 已生成 {OUT_JSON}")
    print(f"   条目 {len(slim_items)} 条 | AI 摘要覆盖 {ai_covered} 条 | 有正文 {with_body} 条")
    print(f"   覆盖 {len(by_day)} 天 {payload['stats']['date_range'][0]} ~ {payload['stats']['date_range'][1]}")
    print(f"   分类分布: {payload['stats']['by_category']}")
    print(f"   机构分布: {payload['stats']['by_org']}")
    print(f"   列表数据: {size_kb:.0f} KB  详情数据: {len(os.listdir(body_dir))} 个文件")

    asset_v = stamp_assets()
    if asset_v:
        print(f"🔖 静态资源版本号: {asset_v}")


if __name__ == "__main__":
    main()
