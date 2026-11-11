"""Build the offline DreamerV3 deck from the supplied arXiv v2 and approved ReAct deck.

Run: python scripts/build_dreamerv3.py
Requires PyMuPDF. No network requests or changes to other decks are made.
"""

import argparse
import hashlib
import html
import json
import re
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
BASELINE_SHA256 = "1504ee550c84e3303dc824929dfe531105325f8f6669f46efae6aa9990f77b6d"
PAPER_TITLE = "Mastering Diverse Domains through World Models"
CROPS = {
    "summary": (1, (64, 432, 552, 625), "Figure 1 · 跨领域结果与 Minecraft 进展"),
    "training": (3, (70, 56, 542, 253), "Figure 3 · 世界模型学习与想象中的 Actor–Critic 学习"),
    "predictions": (4, (64, 42, 542, 261), "Figure 4 · DMLab 与四足机器人开环预测"),
    "discover": (8, (64, 55, 542, 174), "Figure 5 · 训练中曾发现物品的 Agent 比例"),
    "robust": (9, (64, 54, 331, 174), "Figure 6a · 鲁棒性机制消融"),
    "signals": (9, (64, 191, 331, 308), "Figure 6b · 表征的学习信号消融"),
    "scaling": (9, (335, 56, 542, 326), "Figure 6c–d · 模型规模与 Replay Ratio"),
    "minecraft-predictions": (23, (64, 122, 542, 636), "Figure 7 · Minecraft 开环视频预测"),
    "episode-diamond": (24, (430, 455, 545, 572), "Figure 9 · 单局 Diamond 成功率"),
    "minecraft-table": (24, (92, 106, 265, 203), "Table 5 · Minecraft Diamond 平均回报"),
    "all-items": (24, (64, 259, 545, 598), "Figure 9 · 十二种物品的单局成功率"),
}
SLIDES = []


def tex(text):
    return re.sub(
        r"\$([^$]+)\$",
        lambda m: '<span class="latex-source" data-display="false" data-latex="'
        + html.escape(m[1], quote=True) + '"></span>',
        text,
    )


def equation(expression, focus=""):
    return (
        f'<div class="math-block" {target(focus)}><span class="latex-source" '
        f'data-display="true" data-latex="{html.escape(expression, quote=True)}"></span></div>'
    )


def target(name):
    return f'data-focus="{name}"' if name else ""


def card(title, text, tone="", focus=""):
    return (
        f'<div class="card {tone}" {target(focus)}><h3 class="card-title">{tex(title)}</h3>'
        f'<p>{tex(text)}</p></div>'
    )


def grid(*items):
    return f'<div class="grid-{len(items)}">' + "".join(items) + "</div>"


def stack(*items):
    return '<div class="dreamer-stack">' + "".join(items) + "</div>"


def note(text):
    return '<div class="takeaway">' + tex(text) + "</div>"


def diagram_card(heading, sub, svg_html, caption):
    return (
        f'<div class="dreamer-diagram" role="group" aria-label="{heading} · {sub}">'
        f'{svg_html}'
        f'<div class="dreamer-diagram-cap">{tex(caption)}</div></div>'
    )


def table(headers, rows, focus=()):
    body = "".join(
        f'<tr {target(focus[i] if i < len(focus) else "")}>'
        + "".join(f"<td>{tex(value)}</td>" for value in row) + "</tr>"
        for i, row in enumerate(rows)
    )
    return (
        '<table class="data-table"><thead><tr>'
        + "".join(f"<th>{tex(value)}</th>" for value in headers)
        + f"</tr></thead><tbody>{body}</tbody></table>"
    )


def figure(name, height=350, regions=()):
    _, coords, label = CROPS[name]
    ratio = (coords[2] - coords[0]) / (coords[3] - coords[1])
    boxes = "".join(
        f'<span class="paper-region image-step-focus" {target(key)} aria-hidden="true" '
        f'style="left:{x}%;top:{y}%;width:{w}%;height:{h}%;"></span>'
        for key, x, y, w, h in regions
    )
    return (
        f'<figure class="fig-box"><div class="dreamer-figure" '
        f'style="--figure-ratio:{ratio};--figure-height:{height}px">'
        f'<img data-figure-ref="{name}" alt="{label}" draggable="false"/>{boxes}</div>'
        f'<figcaption class="fig-cap">{label} · 原论文矢量裁图，点击放大</figcaption></figure>'
    )


def walk(visual, steps, summary="", interval=0):
    mappings = {}
    authored_targets = set(re.findall(r'data-focus="([^"]+)"', visual))
    for i, (_, _, keys) in enumerate(steps, 1):
        for key in keys.split(","):
            assert key.strip() in authored_targets, f"Missing visual target: {key}"
            mappings.setdefault(key.strip(), []).append(str(i))
    visual = re.sub(
        r'data-focus="([^"]+)"',
        lambda m: f'data-visual-step="{",".join(mappings.get(m[1], []))}"',
        visual,
    )
    assert 'data-visual-step=""' not in visual, "Every visual focus needs a matching explanation."
    for i, (_, _, keys) in enumerate(steps, 1):
        assert keys and any(i in [int(x) for x in mappings[k.strip()]] for k in keys.split(","))
    explanations = "".join(
        f'<div class="dreamer-step explanation-step" data-visual-step="{i}" tabindex="0" role="button">'
        f'<span class="dreamer-step-number">{i:02}</span><div><strong>{tex(title)}</strong>'
        f'<p>{tex(text)}</p></div></div>'
        for i, (title, text, _) in enumerate(steps, 1)
    )
    summary_html = f'<div class="dreamer-takeaway">{tex(summary)}</div>' if summary else ""
    notes = html.escape(json.dumps([t for t, _, _ in steps], ensure_ascii=False), quote=True)
    pacing = f' data-interval="{interval}"' if interval else ""
    return (
        f'<div class="visual-sequence dreamer-walk" data-sequence-notes="{notes}"{pacing}>'
        f'<div class="dreamer-visual">{visual}</div><div class="dreamer-explanations">'
        f'{explanations}</div>{summary_html}</div>'
    )


def box(title, text, focus="", tone=""):
    return (
        f'<div class="dreamer-node {tone}" {target(focus)}>'
        f'<strong>{tex(title)}</strong><p>{tex(text)}</p></div>'
    )


def flow(*nodes):
    return '<div class="dreamer-flow">' + '<span class="dreamer-arrow">→</span>'.join(nodes) + "</div>"


def case(stage="start", focus=""):
    captions = {
        "start": ("真实起点", "面前一棵树；空背包；目标是最终获得钻石"),
        "memory": ("真实历史", "刚执行朝树移动；记忆结合新画面与背包信息"),
        "imagine": ("想象起点", "Replay 中的树前状态；此后不再读取新画面"),
        "predict": ("模型预测", "执行采集动作后，模型预测获得原木与里程碑奖励"),
        "correct": ("真实校正", "动作已执行；环境未给原木，模型必须接受新观测"),
    }
    label, detail = captions[stage]
    return (
        f'<div class="dreamer-case" {target(focus)}><svg viewBox="0 0 700 210" '
        'role="img" aria-label="教学重绘：Minecraft 树前采集场景，不是作者运行截图">'
        '<rect width="700" height="210" rx="12" fill="#eef2ff"/>'
        '<path d="M0 135 170 112 340 140 520 102 700 130V210H0Z" fill="#d1fae5"/>'
        '<path d="M0 171H700V210H0Z" fill="#a7f3d0"/>'
        '<rect x="368" y="60" width="38" height="112" fill="#92400e"/>'
        '<rect x="311" y="20" width="155" height="64" fill="#059669"/>'
        '<rect x="333" y="6" width="112" height="53" fill="#10b981"/>'
        '<path d="M340 102H360M350 92V112" stroke="#4f46e5" stroke-width="3"/>'
        '<path d="M570 176 590 134 610 158 624 138 639 174" fill="#4f46e5"/>'
        '<rect x="18" y="17" width="184" height="33" rx="8" fill="white"/>'
        f'<text x="32" y="39" font-size="18" fill="#334155">{label}</text>'
        '<text x="20" y="196" font-size="16" fill="#334155">原木 → 工具 → 铁镐 → 钻石</text>'
        '</svg><p>' + tex(detail) + ' · <strong>教学重绘 / 假设状态</strong></p></div>'
    )


def art_label(x, y, width, text, height=28, cls=""):
    # HTML labels allow the bundled KaTeX renderer to typeset math inside SVG.
    return (
        f'<foreignObject x="{x}" y="{y}" width="{width}" height="{height}">'
        f'<div xmlns="http://www.w3.org/1999/xhtml" class="opening-label {cls}">'
        f'{tex(text)}</div></foreignObject>'
    )


def art_panel(x, y, width, height, heading, detail="", focus="", tone="plain"):
    colors = {"plain": ("#fff", "#e2e8f0"), "real": ("#ecfdf5", "#a7f3d0"),
              "model": ("#eef2ff", "#c7d2fe"), "warm": ("#fffbeb", "#fde68a")}
    fill, stroke = colors[tone]
    return (
        f'<g class="opening-node" {target(focus)}>'
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        + art_label(x+15, y+12, width-30, heading, 32, "heading")
        + (art_label(x+15, y+49, width-30, detail, height-53) if detail else "")
        + "</g>"
    )


def art_edge(path, focus="", color="#94a3b8", dashed=False):
    dash = 'stroke-dasharray=".07 .07"' if dashed else ""
    cls = "opening-edge opening-uncertain" if dashed else "opening-edge"
    return (
        f'<path class="{cls}" {target(focus)} d="{path}" fill="none" '
        f'stroke="{color}" stroke-width="2.5" stroke-linecap="round" '
        f'{dash} '
        'marker-end="url(#opening-arrow)" pathLength="1"/>'
    )


def art_svg(content, label):
    markup = (
        f'<svg class="opening-art" viewBox="0 0 820 440" role="img" aria-label="{label}">'
        '<defs><marker id="opening-arrow" viewBox="0 0 10 10" refX="8" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M1 1L9 5L1 9" fill="none" stroke="#64748b" stroke-width="1.8"/>'
        '</marker></defs>' + content + "</svg>"
    )
    return markup.replace("opening-arrow", "opening-arrow-" + hashlib.sha256(label.encode()).hexdigest()[:8])


def tree_scene(x=20, y=48, width=386, height=208, focus=""):
    return (
        f'<g class="opening-node" {target(focus)}>'
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" '
        'fill="#eef2ff" stroke="#c7d2fe" stroke-width="1.5"/>'
        f'<svg x="{x+2}" y="{y+2}" width="{width-4}" height="{height-4}" viewBox="0 0 386 208">'
        '<path d="M0 132L81 112L180 130L274 102L386 125V208H0Z" fill="#d1fae5"/>'
        '<path d="M0 174L386 148V208H0Z" fill="#a7f3d0"/>'
        '<path d="M150 208L246 156" stroke="#059669" stroke-width="2" stroke-dasharray="6 6"/>'
        '<rect x="246" y="64" width="26" height="106" fill="#92400e"/>'
        '<rect x="202" y="30" width="112" height="57" fill="#059669"/>'
        '<rect x="219" y="17" width="79" height="48" fill="#10b981"/>'
        '<path d="M249 101H269M259 91V111" stroke="#fff" stroke-width="2"/>'
        '<g class="opening-player"><rect x="99" y="134" width="22" height="22" rx="3" fill="#6366f1"/>'
        '<path d="M110 158V185M94 168H126M110 185L99 201M110 185L122 201" '
        'stroke="#4f46e5" stroke-width="7" stroke-linecap="round"/></g>'
        '<rect x="14" y="13" width="166" height="31" rx="7" fill="#fff"/>'
        '<text x="26" y="35" font-size="17" fill="#334155">树前 · 尚未开始采集</text>'
        '<path class="opening-approach" data-focus="approach" d="M146 170L214 145" fill="none" '
        'stroke="#4f46e5" stroke-width="3" stroke-dasharray="7 6"/>'
        '</svg></g>'
    )


def opening_task():
    slots = "".join(
        f'<rect x="{457+i*51}" y="123" width="42" height="40" rx="5" fill="#f8fafc" stroke="#cbd5e1"/>'
        for i in range(6)
    )
    content = (
        art_label(20, 7, 780, "先确认眼前有什么，再决定下一步做什么", 30, "heading")
        + tree_scene(focus="start")
        + art_panel(434, 48, 366, 124, "当前背包：空", "没有原木，也没有工具", "start", "real")
        + slots
        + '<g class="opening-reveal" data-from="2">'
        + art_panel(434, 188, 366, 68, "目标：把钻石收进背包", focus="wood", tone="model")
        + '<path d="M738 209L754 202L770 209L754 238Z" fill="#4f46e5"/>'
        + art_label(20, 274, 780, "依赖链：后一步需要前一步提供材料与工具", 28)
        + art_edge("M186 352H218", "wood")
        + art_edge("M392 352H424", "wood")
        + art_edge("M598 352H630", "wood")
        + art_panel(20, 312, 166, 82, "原木", "采集基础材料", "wood", "real")
        + art_panel(224, 312, 168, 82, "工作台 / 木镐", "再进入石器阶段", "wood")
        + art_panel(430, 312, 168, 82, "石器 / 铁镐", "采集与烧炼", "wood")
        + art_panel(636, 312, 164, 82, "钻石", "地下探索后收集", "wood", "model")
        + '</g><g class="opening-reveal opening-node" data-from="3" data-focus="approach">'
        '<rect x="20" y="408" width="780" height="30" '
        'rx="7" fill="#f1f5f9" stroke="#e2e8f0"/>'
        + art_label(33, 411, 754, "先只做这一步：朝树移动；此时还没有采到原木", 26)
        + "</g>"
    )
    return diagram_card("先明确起点、依赖与成功标准", "Minecraft Diamond",
                        art_svg(content, "空背包、树前起点及原木到钻石的技术依赖链"),
                        "教学重绘：起点为假设；技术链压缩展示，不是作者的执行日志。")


def opening_choices():
    content = (
        art_panel(20, 10, 780, 78, "共同起点：树前、空背包", "只看眼前分数，能判断该往哪走吗？", "same")
        + art_edge("M410 88V108H203V133", "same")
        + art_edge("M410 108H617V133", "same")
        + art_panel(20, 139, 366, 93, "A · 朝树移动", "更接近可采集的位置", "same", "real")
        + art_panel(434, 139, 366, 93, "B · 离开树游走", "离开眼前的采集位置", "same")
        + art_label(243, 154, 127, "$r=0$", 36, "score")
        + art_label(657, 154, 127, "$r=0$", 36, "score")
        + '<g aria-hidden="true">'
        '<rect x="345" y="196" width="7" height="28" fill="#92400e"/>'
        '<path d="M336 187H361V204H336Z" fill="#059669"/>'
        '<circle cx="305" cy="202" r="5" fill="#6366f1"/>'
        '<path d="M305 209V219M298 214H312M305 219L300 226M305 219L310 226" '
        'stroke="#6366f1" stroke-width="3" stroke-linecap="round"/>'
        '<path d="M318 211H335M331 207L335 211L331 215" fill="none" stroke="#4f46e5" stroke-width="2"/>'
        '<rect x="694" y="196" width="7" height="28" fill="#92400e"/>'
        '<path d="M685 187H710V204H685Z" fill="#059669"/>'
        '<circle cx="752" cy="202" r="5" fill="#6366f1"/>'
        '<path d="M752 209V219M745 214H759M752 219L747 226M752 219L757 226" '
        'stroke="#6366f1" stroke-width="3" stroke-linecap="round"/>'
        '<path d="M717 211H737M733 207L737 211L733 215" fill="none" stroke="#4f46e5" stroke-width="2"/>'
        '</g>'
        + '<g class="opening-reveal" data-from="2">'
        + art_edge("M203 232V270", "later", "#4f46e5")
        + art_edge("M617 232V270", "later", dashed=True)
        + art_panel(20, 278, 366, 85, "随后还要采集、拾取", "靠近只是准备，不等于已经采到", "later", "real")
        + art_panel(434, 278, 366, 85, "随后会遇到什么？", "取决于后续行动，不能只凭零分断言", "later")
        + '</g><g class="opening-reveal opening-node" data-from="3" data-focus="credit">'
        '<rect x="20" y="386" width="780" height="52" rx="10" fill="#fffbeb" stroke="#fde68a"/>'
        + art_label(34, 397, 750,
                    "现在：移动，$r=0$　→　以后：首次获得原木，$+1$", 32)
        + "</g>"
    )
    return diagram_card("即时奖励相同，不代表未来机会相同", "教学对照 · 不是搜索树",
                        art_svg(content, "两个零即时奖励动作，以及后续采集与首次奖励的区别"),
                        "教学对照，非搜索树。12 种里程碑物品每局首次各得 $+1$；重复采集仍可能有用，但无新增里程碑奖励。")


def opening_loop():
    content = (
        '<rect x="8" y="8" width="804" height="176" rx="14" fill="#f8fafc" stroke="#e2e8f0"/>'
        + art_label(22, 16, 770, "先学世界：真实结果提供训练依据", 28, "heading")
        + art_edge("M252 112H286", "real")
        + art_edge("M524 112H560", "real")
        + art_panel(22, 61, 230, 108, "真实环境", "移动后返回观测与奖励", "real", "real")
        + art_panel(294, 61, 230, 108, "回放经验 Replay", "保存观测、动作与奖励", "real", "real")
        + art_panel(568, 61, 230, 108, "世界模型", "学习动作之后发生什么", "real", "model")
        + '<g class="opening-reveal" data-from="2">'
        + art_edge("M409 184V226", "imagine", "#4f46e5")
        + '<rect x="8" y="235" width="804" height="125" rx="14" fill="#eef2ff" stroke="#c7d2fe"/>'
        + art_label(22, 241, 770, "再练行动：从真实起点出发，用已学模型预测后续", 28, "heading")
        + art_panel(22, 283, 170, 61, "真实起点", focus="imagine", tone="real")
        + art_panel(242, 283, 229, 61, "Actor + 世界模型", focus="imagine", tone="model")
        + art_panel(522, 283, 276, 61, "预测状态 / 奖励 / 继续", focus="imagine", tone="model")
        + art_edge("M194 313H234", "imagine", "#4f46e5")
        + art_edge("M473 313H514", "imagine", "#4f46e5")
        + '</g><g class="opening-reveal" data-from="3">'
        + art_edge("M660 360V386H423", "learn", "#4f46e5")
        + art_panel(202, 376, 214, 62, "Critic 估计未来收益", focus="learn", tone="model")
        + art_panel(22, 376, 166, 62, "改进 Actor", focus="learn", tone="model")
        + art_edge("M200 407H190", "learn", "#4f46e5")
        + art_edge("M18 399H3V202H137V174", "learn", "#4f46e5")
        + art_label(456, 389, 340, "改好策略，再回环境行动", 44)
        + "</g>"
    )
    return diagram_card("把后续收益变成策略的学习信号", "训练与行动分两条线",
                        art_svg(content, "真实经验训练世界模型，想象轨迹与Critic帮助改进Actor，再回到环境行动"),
                        "流程为教学抽象：三类网络交替更新；想象训练时冻结世界模型参数。")


def opening_state():
    content = (
        art_panel(20, 12, 354, 150, "当前真实输入 $x_t$", focus="input", tone="real")
        + art_label(37, 61, 322, "图像：$64\\times64\\times3$<br>背包计数、历史最大计数<br>装备、生命、饥饿与呼吸", 100)
        + art_panel(448, 12, 352, 150, "此前发生过什么？", focus="history")
        + art_label(465, 61, 318, "上一记忆、上一离散表示<br>以及刚执行的移动动作<br>不能只看一张图就丢掉历史", 100)
        + '<g class="opening-reveal" data-from="2">'
        + art_edge("M624 162V203", "history", "#4f46e5")
        + art_panel(448, 212, 352, 105, "递归记忆 $h_t$", "网络中的历史摘要，不是文字日志", "history", "model")
        + '</g><g class="opening-reveal" data-from="3">'
        + art_edge("M197 162V263H392V348", "state", "#059669")
        + art_edge("M448 264H420V322H350V332", "state", "#4f46e5")
        + art_panel(20, 338, 386, 99, "当前离散表示 $z_t$", "结合新输入与记忆，形成后验表示", "state", "model")
        + art_panel(448, 338, 352, 99, "策略使用模型状态", "$s_t=\\{h_t,z_t\\}$ → Actor / Critic", "state", "model")
        + art_edge("M406 388H440", "state", "#4f46e5")
        + art_edge("M710 317V332", "state", "#4f46e5")
        + '</g>'
        + art_label(34, 205, 343, "新输入提供当前证据<br>记忆保留此前线索", 65)
    )
    return diagram_card("把可观测输入与历史线索接起来", "RSSM · 循环状态空间模型",
                        art_svg(content, "多模态真实输入和历史递归记忆共同形成当前离散表示以及策略状态"),
                        "原木、装备等是输入语义；潜在表示并没有人工指定的“原木格”。")


def add(chapter, title, lead, body, source, appendix=False, cls=""):
    SLIDES.append(dict(chapter=chapter, title=title, lead=lead, body=body, source=source,
                       appendix=appendix, cls=cls))


def code_line(line):
    pattern = r"""#[^\n]*|"[^"]*"|\b(?:def|for|in|return|if|else|while|not|with)\b|\b\d+(?:\.\d+)?\b|\b[A-Za-z_]\w*(?=\s*\()"""
    parts, end = [], 0
    for match in re.finditer(pattern, line):
        value = match[0]
        category = (
            "c-cm" if value.startswith("#") else "c-str" if value.startswith('"')
            else "c-kw" if value in {"def", "for", "in", "return", "if", "else", "while", "not", "with"}
            else "c-num" if value[0].isdigit() else "c-fn"
        )
        parts.extend([html.escape(line[end:match.start()]),
                      f'<span class="{category}">{html.escape(value)}</span>'])
        end = match.end()
    parts.append(html.escape(line[end:]))
    return '<div class="algo-line">' + "".join(parts) + "</div>"


def algorithm(lines, steps, title):
    explanations = "".join(
        f'<div class="algo-step" data-lines="{ids}"><h4>{i}. {tex(heading)}</h4>'
        f'<p>{tex(description)}</p><div class="dreamer-algo-visual">'
        f'{flow(box("输入", before), box("本步输出", after, tone="emerald"))}</div>'
        f'<div class="algo-state">{tex(state)}</div></div>'
        for i, (ids, heading, description, before, after, state) in enumerate(steps, 1)
    )
    summary = (
        '<div class="dreamer-print-summary"><h4>教学控制流摘要</h4>'
        + "".join(f'<p><strong>{i}. {tex(heading)}</strong><br>{tex(state)}</p>'
                  for i, (_, heading, _, _, _, state) in enumerate(steps, 1))
        + "</div>"
    )
    return (
        f'<div class="algo-walkthrough dreamer-algorithm" style="height:475px" '
        f'data-algo-title="{html.escape(title)}"><div class="algo-code">'
        + "".join(code_line(line) for line in lines)
        + f'</div><div class="algo-steps">{explanations}{summary}</div></div>'
    )


def make_slides():
    add("论文精读 · arXiv v2 / 2024", PAPER_TITLE,
        "同一学习配方能否同时应对像素、连续控制与稀疏奖励？DreamerV3 用真实经验学习世界模型，在想象轨迹里训练策略，再回到环境行动；Minecraft 是贯穿本讲义的检验案例。",
        grid(*[
            '<div class="card ' + tone + '"><h3 class="card-title"><span class="badge badge-'
            + badge + '">' + label + '</span>' + heading + '</h3><p>' + content + '</p></div>'
            for tone, badge, label, heading, content in [
                ("indigo", "indigo", "问题", "不是每换一个领域就重新调参",
                 "图像或向量、离散或连续动作、稀疏或密集奖励，都可能改变训练信号的尺度。长程任务还要求把眼前动作与很久以后的收益联系起来。"),
                ("emerald", "emerald", "方法", "让世界模型为策略提供练习场",
                 "从回放经验学习潜在状态、奖励与终止预测；Actor 和 Critic 在预测轨迹中更新。归一化、平衡与数值变换让同一配方跨领域稳定学习。"),
                ("amber", "amber", "证据与边界", "找到钻石，不等于每局都能成功",
                 "覆盖 8 个领域、150 多项任务。Minecraft 的 10 个训练种子都曾找到钻石，但最终单局成功率仅 0.4%；固定配方也不等于共享一个模型的权重。"),
            ]
        ]) + '<div class="paper-reference"><a href="https://arxiv.org/abs/2301.04104v2" '
        'target="_blank" rel="noopener">论文原文 ↗</a><span>依据本地 40 页 v2；原图、公式与复现核查见附录。</span></div>',
        "", cls="cover-slide")
    SLIDES[0]["topic"] = "DreamerV3：在想象中练习，再到真实世界行动"
    SLIDES[0]["authors"] = "Danijar Hafner · Jurgis Pasukonis · Jimmy Ba · Timothy Lillicrap"

    add("阅读路线", "先看树前的一次行动，再看跨领域的学习配方",
        "先把真实数据与想象数据分开，再解释价值、策略和稳定性；实验最后回答这些机制是否真的帮助获得钻石。",
        '<div class="route-map">' + "".join(
            f'<a class="route-row" href="#slide-{page}" data-slide-target="{page}">'
            f'<span class="route-number">{i:02}</span><span class="route-content"><strong>{heading}</strong>'
            f'<span class="route-description">{description}</span></span><span class="route-range">{label}</span></a>'
            for i, (page, heading, description, label) in enumerate([
                (3, "任务与闭环", "Minecraft 的起点、奖励与三个网络各自负责什么。", "任务"),
                (7, "世界模型", "从真实观测得到状态，再学会无观测地预测后继。", "表征"),
                (12, "想象中的学习", "奖励、价值、回报和策略更新怎样接起来。", "学习"),
                (18, "跨领域稳定性", "数值变换怎样兼容未知尺度，而非放大稀疏噪声。", "尺度"),
                (24, "证据与边界", "曾发现钻石、单局成功率、跨域比较与消融。", "实验"),
            ], 1)
        ) + "</div>",
        "方向键翻页；↓ / ↑ 走读；M 目录；F 全屏。原图可点击缩放。主案例与数值计算均明确标记教学身份。",
        cls="dreamer-route")

    add("任务起点", "Minecraft Diamond：目标是钻石，眼前却只有一棵树",
        "任务要真正把钻石收进背包。假设我们站在树前，背包还是空的；先从这个尚未采集的起点，找出下一步能做什么。",
        walk(opening_task(), [
            ("先看起点：树在眼前，原木还没到手", "看见资源不等于持有资源。背包里没有原木和工具；要先接近树，才谈得上采集和制作。", "start"),
            ("再看依赖：钻石之前，要做许多准备", "原木用于制作木板、工作台和木镐，再逐步进入石器与铁器阶段。图中压缩了重复采集和中间配方；探索途中还必须维持生存。", "wood"),
            ("现在只推进一步：先朝树移动", "这一步只改变位置，还没有获得原木，更没有完成任务。先盯住这个准备动作：如果环境没给奖励，怎样知道它有没有用？", "approach"),
        ], summary="下一页先看这一步的即时反馈，而不是整段任务的成败。", interval=9000),
        "来源：Introduction / Results，PDF 2、10；Methods—Minecraft，PDF 22。教学假设；死亡或达到 36,000 步结束一局。",
        cls="dreamer-opening opening-paced")

    add("任务困难", "朝树移动，眼前还是零分：有用的准备动作怎样学？",
        "延续刚才的第一步：还没采到原木，只改变了位置。拿“朝树移动”与“离开树”作教学对照，看看即时反馈漏掉了什么。",
        walk(opening_choices(), [
            ("停在本步：两个动作都可能没有奖励", "假设没有获得新物品，也没有生命变化，A/B 的即时奖励都是零。零分只说明“现在没得分”，不能说明这个动作对以后没用。", "same"),
            ("往后看：靠近为采集创造了条件", "沿 A 还要继续采集和拾取，才可能得到原木；位置变化只是准备。B 的后果也取决于后续行动，不能仅凭当前零分就断言整条路线失败。", "later"),
            ("学习要补上：从后来收益看现在的动作", "原木的奖励在真正获得时才出现，准备动作却发生得更早。要学会这种动作，需要把后续收益带回现在，而不只是比较本步的两个零分。", "credit"),
        ], summary="DreamerV3 的切入点：用模型提供后续练习，再把预测回报用于学习动作选择。", interval=9000),
        "来源：Methods—Minecraft，PDF 22。A/B 与零奖励均为教学假设；另有生命变化每颗心 $\\pm0.01$。",
        cls="dreamer-opening opening-paced")

    add("方法总览", "先用真实经验学世界，再在想象中学行动",
        "刚才的问题是：准备动作眼前不得分，怎样学会它有用？DreamerV3 把真实经验变成练习场，让策略在预测的后续里学习，再回到环境行动。",
        walk(opening_loop(), [
            ("先学世界：真实结果是模型的训练依据", "朝树移动后，把新画面、动作和奖励存入 Replay（回放缓冲区）。世界模型据此学习动作后果；只有真实经验能纠正预测。", "real"),
            ("再练行动：从真实起点，预测一段后续", "从 Replay 编码的状态启动，Actor（策略网络）提出动作，世界模型预测后继、奖励和继续概率。不再访问游戏，也不必生成每一步的图片。", "imagine"),
            ("改好策略：让未来收益影响动作选择", "Critic 是估计未来收益的价值网络，帮助 Actor 学习动作选择。用想象回报训练二者后，Actor 回到环境直接抽样行动，不临时搜索。", "learn"),
        ], summary="接着对照论文原图：哪里读真实输入，哪里只用模型预测？", interval=9000),
        "来源：Learning algorithm / Critic learning，PDF 3、5；Figure 3。教学流程图不表示逐步同步的工程调度。",
        cls="dreamer-opening opening-paced")

    add("论文框架原图", "Figure 3：真实输入只在左侧逐步出现",
        "把刚才的闭环映射回论文原图：左边学习“动作之后发生什么”，右边用已学模型练习。先认清数据从哪里来，再解释图中的状态。",
        walk(stack(figure("training", 350, [
            ("observed", 0.5, 47, 49.5, 44),
            ("states", 4, 0, 43, 45),
            ("seed", 58.2, 28, 8.5, 62),
            ("imagined", 74.4, 13, 23.8, 33),
            ("outputs", 72.6, 0, 25.8, 16),
        ]), '<div class="opening-paper-route">'
            '<span data-focus="observed">真实输入与重建</span><i>→</i>'
            '<span data-focus="states">动作与记忆</span><i>→</i>'
            '<span data-focus="seed">真实起点</span><i>→</i>'
            '<span data-focus="imagined">预测续路</span></div>'), [
            ("左下：每一步都有真实输入", "树前移动产生的新画面与向量进入编码器 enc；解码器 dec 尝试重建输入，约束表示保留信息。图中画面并非我们的教学案例。", "observed"),
            ("左上：把动作与历史接起来", "绿色方块是递归记忆，棋盘格是离散表示；上方手柄表示动作。模型学习如何从过去状态和动作预测后继。", "states"),
            ("右下：只用真实输入建立起点", "右图开头仍有 enc 和真实输入：想象不是凭空开始，而是从回放经验得到一个后验状态。", "seed"),
            ("右上：后续不再读取新画面", "后面的状态来自模型预测；Actor 给出动作，奖励头与 Critic 提供学习所需的预测奖励和价值。它们还不是环境确认的事实。", "imagined,outputs"),
        ]),
        "来源：Figure 3，PDF / 论文页 3。图中符号沿用作者；正文下一页区分真实输入、递归记忆与离散表示。",
        cls="dreamer-opening opening-paper")

    add("世界模型 · 状态", "走近树之后：策略读到的，不只是一张新画面",
        "回到同一个案例：朝树移动后，环境返回新输入。RSSM 把当前证据与此前历史合在一起，形成 Actor 和 Critic 真正使用的模型状态。",
        walk(opening_state(), [
            ("当前证据：先把“看见什么”说清楚", "$x_t$ 包含图像，也包含 400 多种物品的背包计数、历史最大计数、装备与生存指标。历史最大计数帮助辨别哪些里程碑已经达到。", "input"),
            ("递归记忆：保留“刚才做过什么”", "$h_t$ 根据上一记忆、上一离散表示和上一动作更新。相似画面不一定意味着相同经历；记忆是网络内部摘要，不是人工写下的日志。", "history"),
            ("当前表示：用新证据补上历史的不足", "编码器结合 $x_t$ 与 $h_t$ 得到离散表示 $z_t$；二者组成 $s_t$，交给 Actor / Critic。它不是人工定义的背包清单，下一页再看更新公式。", "state"),
        ], summary="真实观测建立后验状态；之后才能讨论拿走新观测时，模型如何继续预测。"),
        "来源：Eq. (1)、(4)，PDF 4–5；Methods—Minecraft，PDF 22。RSSM = Recurrent State-Space Model。",
        cls="dreamer-opening")

    add("世界模型 · 真实观测", "先更新记忆，再用新画面校正当前表示",
        "Actor 已选朝树移动的动作。现在环境真的返回新输入；模型把这次真实转移编码成可回放、可预测的状态。",
        walk(stack(case("memory"), equation(r"h_t=f_\phi(h_{t-1},z_{t-1},a_{t-1})", "memory"),
                   equation(r"z_t\sim q_\phi(z_t\mid h_t,x_t)", "posterior")), [
            ("动作进入递归更新", "$a_{t-1}$ 是上一步已执行的动作；$\\phi$ 是世界模型参数。", "memory"),
            ("后验读取真实输入", "$q_\\phi$ 是 Encoder 的分布；本步输入 $x_t$ 能校正记忆里尚不确定的信息。", "posterior"),
            ("把真实表示作为训练目标", "接下来要让只看记忆的 Dynamics Predictor 也能预测这一表示。", "memory,posterior"),
        ]),
        "来源：World model learning，Eq. (1)，PDF 4。树前移动的细节为教学假设。")

    add("世界模型 · 学习目标", "重建、奖励与继续标记，让表示不只是“容易预测”",
        "先检查模型是否保留了输入中的信息，再检查它能否预测任务反馈；否则模型可能学到平凡却无用的潜在状态。",
        walk(stack(case("memory"), grid(
            box("重建输入", "$p_\\phi(x_t\\mid h_t,z_t)$：恢复图像与向量信息", "reconstruct"),
            box("奖励与继续", "$p_\\phi(r_t\\mid h_t,z_t)$、$p_\\phi(c_t\\mid h_t,z_t)$", "heads"),
        ), equation(r"\mathcal L=\mathcal L_{\mathrm{pred}}+\mathcal L_{\mathrm{dyn}}+0.1\mathcal L_{\mathrm{rep}}", "loss")), [
            ("重建是表征的约束", "Decoder 用于训练；想象中的 Actor–Critic 不需要每步生成像素图。", "reconstruct"),
            ("奖励和终止也必须学", "$r_t$ 是本步反馈；$c_t$ 是继续标记，帮助截断终止后的想象收益。", "heads"),
            ("还要把后验与先验接起来", "这条式子省略时间求和与期望，只展示 Eq. (2) 的三项权重。", "loss"),
        ]),
        "来源：Eq. (1)–(3)，PDF 4–5。向量采用 symlog；奖励头采用 symexp twohot；继续头采用 logistic regression。")

    add("世界模型 · KL 平衡", "一边让预测跟上表示，一边让表示更可预测",
        "Encoder 看到了真实输入，Dynamics Predictor 没看到。两项 KL 的方向相同，但停止梯度的位置不同，更新的职责也不同。",
        walk(stack(
            equation(r"\mathcal L_{\mathrm{dyn}}=\max\!\left(1,\mathrm{KL}[\mathrm{sg}(q_\phi)\Vert p_\phi]\right)", "dyn"),
            equation(r"\mathcal L_{\mathrm{rep}}=\max\!\left(1,\mathrm{KL}[q_\phi\Vert\mathrm{sg}(p_\phi)]\right)", "rep"),
            box("同一个比较对象", "$q_\\phi=q_\\phi(z_t\\mid h_t,x_t)$；$p_\\phi=p_\\phi(z_t\\mid h_t)$；sg 表示停止梯度", "meaning"),
        ), [
            ("动态项：固定后验目标", "停止目标后验的梯度，让预测端更接近真实输入产生的表示。", "dyn,meaning"),
            ("表征项：固定预测目标", "让编码端更容易被预测；其权重仅 0.1，避免过度牺牲输入信息。", "rep,meaning"),
            ("Free bits：小到一定程度便不再追", "KL 低于 1 nat 时，截断后的损失是常数，不再产生该项梯度；不是把 KL 强制等于 1。", "dyn,rep"),
        ]),
        "来源：Eq. (2)–(3) 与 free bits 说明，PDF 4–5。完整条件在本页下方给出。")

    add("世界模型 · 分布稳定", "避免概率变成零：1% 均匀混合保护 KL",
        "即使两端已被平衡，极端分类概率仍可能让 KL 尖峰失控。DreamerV3 为分类分布保留少量均匀概率。",
        walk(stack(equation(r"\widetilde p=0.99\,p+0.01\,u", "mix"),
            table(["教学三分类", "网络输出", "均匀混合后"], [
                ("类别 A", "$0.999$", "$0.992343$"),
                ("类别 B", "$0.001$", "$0.004323$"),
                ("类别 C", "$0$", "$0.003333$"),
            ], ["rows", "rows", "rows"]),
            box("适用对象", "编码器和动态预测器的分类分布；Actor 也采用 1% unimix", "scope")), [
                ("先看均匀分布", "$u$ 在此教学例里三类各为 $\\frac{1}{3}$；真实模型的每个 latent 具有自己的分类维度。", "mix"),
                ("不让某一类彻底消失", "概率仍高度偏向 A，但 C 不再为零；这使 KL 更平稳。", "rows"),
                ("不等于随机探索整个环境", "这是概率分布参数化；Actor 的熵正则与探索回报归一化稍后单独讲。", "scope"),
            ]),
        "来源：World model learning，PDF 5；Methods—Previous Dreamer generations、Table 4，PDF 20–21。三类数值为教学计算，四舍五入。")

    add("想象 · 后继状态", "拿走新画面以后：先验替代后验，动作来自 Actor",
        "模型已从真实经验学到动态。现在从树前的 Replay 状态启动想象，预测采集之后可能出现的状态，但不能把预测背包当成真的。",
        walk(stack(case("imagine"), flow(
            box("Actor 抽样", "$a_t\\sim\\pi_\\theta(a_t\\mid s_t)$", "action"),
            box("更新记忆", "$h_{t+1}=f_\\phi(h_t,z_t,a_t)$", "memory"),
            box("预测后继", "$\\hat z_{t+1}\\sim p_\\phi(\\hat z_{t+1}\\mid h_{t+1})$", "prior", "emerald"),
        ), box("注意：没有 $x_{t+1}$", "这里调用 Dynamics Predictor，不调用新观测的 Encoder", "boundary")), [
            ("同一策略也参与生成训练轨迹", "Actor 的参数为 $\\theta$；不是人工列举 A/B 再用树搜索挑选动作。", "action"),
            ("预测端接住动作", "记忆与上一表示共同影响后继；原图的确定性与随机性两部分都保留。", "memory,prior"),
            ("状态、奖励、继续概率都由模型给出", "想象输出可能错误；下页先讲怎样从预测轨迹估计收益。", "boundary,prior"),
        ]),
        "来源：Eq. (1)、(4)，PDF 4–5。带帽表示预测身份；课堂状态不是作者记录的 rollout。")

    add("想象 · 奖励与价值", "得到原木的奖励，只是未来回报中的一项",
        "同一想象轨迹既有本步预测奖励，也有 Critic 对后续收益的估计。二者职责不同，不能都叫“模型打分”。",
        walk(stack(case("predict"), flow(
            box("预测奖励 $r_t$", "奖励头估计本步反馈；真实规则中首次原木里程碑给 $+1$", "reward"),
            box("Critic 价值 $v_t$", "回报分布的期望；估计当前策略在此状态下还能获得多少", "value"),
        ), equation(r"R_t=\sum_{\tau=0}^{\infty}\gamma^\tau r_{t+\tau},\qquad \gamma=0.997", "return")), [
            ("$r_t$：只负责当前反馈", "想象里是预测值；环境里是实际反馈。本页用首次原木解释奖励身份。", "reward"),
            ("$v_t$：跨越有限想象长度", "Critic 学习回报分布，不是输出成功概率，也不是每个动作的搜索访问均值。", "value"),
            ("$R_t$：累计、折扣的未来", "远期奖励通过折扣进入目标；这不意味着模型要一次预测到钻石。", "return"),
        ]),
        "来源：Critic learning，Eq. (4)–(5)，PDF 5；Minecraft 奖励定义，PDF 22。想象奖励沿用原文不加帽记号，但身份已区分。")

    add("想象 · 回报目标", "有限轨迹怎样接上很远的未来？用混合回报回推",
        "回报不是把本步奖励直接交给 Actor。它从末端 Critic 估计开始，沿同一轨迹混合本步奖励与后续回报。",
        walk(stack(
            box("四个量先对齐", "$r_t$：预测奖励；$c_t$：继续概率；$v_t$：Critic 期望；$\\lambda=0.95$：混合权重", "symbols"),
            equation(r"R_t^\lambda=r_t+\gamma c_t\!\left((1-\lambda)v_t+\lambda R_{t+1}^\lambda\right)", "recursive"),
            equation(r"R_T^\lambda=v_T", "tail"),
            note("本页严格沿用 v2 Eq. (5) 的下标约定，不混入其他版本的回报写法。")
        ), [
            ("末端先由 Critic 补足", "正文使用 16 个状态的记法；Table 4 记想象动作 horizon 为 15，不是 15 个完整 episode。", "tail"),
            ("向前一状态回推", "本步奖励加上继续后的折扣收益，混合 Critic 值与已回推的续路回报。", "recursive,symbols"),
            ("终止阻断虚构的未来奖励", "$c_t=0$ 时本步之后的项消失；想象中通常使用模型预测的继续概率。", "recursive"),
        ]),
        "来源：Eq. (5)，PDF 5；Table 4，PDF 21。$\\lambda$-return 是训练目标，不是在线搜索的分支评分。")

    add("想象 · 一次数值回推", "同一条采集轨迹：先算末端，再算眼前动作的收益",
        "用两次预测转移演示回推，末端价值代表尚未显式展开的后续工具收益。所有数字都是教学假设，不是 Minecraft 执行日志。",
        walk(stack(flow(
            box("状态 1 · 树前", "$r_1=0,\\;c_1=1,\\;v_1=2$", "first"),
            box("状态 2 · 预测采集", "$r_2=1,\\;c_2=1,\\;v_2=1$", "second"),
            box("状态 3 · 末端", "$v_3=4$", "tail", "emerald"),
        ), equation(r"R_3^\lambda=4", "tail"),
            equation(r"R_2^\lambda=1+0.997(0.05\cdot1+0.95\cdot4)=4.83845", "second"),
            equation(r"R_1^\lambda=0.997(0.05\cdot2+0.95\cdot4.83845)\approx4.68244", "first")), [
            ("先用末端价值作边界", "沿用上页 $\\gamma=0.997$、$\\lambda=0.95$；这个 4 不是钻石成功概率。", "tail"),
            ("本步原木奖励与未来合并", "奖励 1 进入回报，但后续仍是模型与 Critic 的估计。", "second"),
            ("零即时奖励也能有非零回报", "树前动作可通过后续获得训练信号；终止时必须去掉不再存在的续路收益。", "first"),
        ]),
        "来源：按 v2 Eq. (5) 的教学算例。所有数值、状态语义与短轨迹均为假设；未模拟整条钻石技术链。")

    add("想象 · 策略更新", "回报比基线更好，就提高这次采集动作的概率",
        "Actor 用想象回报减去 Critic 基线构成优势；REINFORCE 更新动作概率，同时用熵鼓励探索，不把模型当成真值评测器。",
        walk(stack(
            equation(r"A_t=R_t^\lambda-v_\psi(s_t)", "adv"),
            equation(r"\mathcal J_{\mathrm{actor}}=\sum_t\mathrm{sg}\!\left(\frac{A_t}{\max(1,S)}\right)\log\pi_\theta(a_t\mid s_t)+\eta\mathcal H[\pi_\theta(\cdot\mid s_t)]", "actor"),
            box("本例树前优势", "$A_1\\approx4.68244-2=2.68244$；$S$ 是批次回报范围，控制更新尺度", "example"),
        ), [
            ("优势把好坏变成相对量", "Critic 基线降低估计噪声；本例正优势倾向提高所抽样动作的概率。", "adv,example"),
            ("只把目标当作停止梯度的权重", "Actor 采用 REINFORCE，离散和连续动作都使用此估计器；不是通过想象动作反传整条动力学链。", "actor"),
            ("熵保留探索", "$\\mathcal H$ 是策略熵，$\\eta=3\\times10^{-4}$ 固定；本页 $\\mathcal J_{\\mathrm{actor}}$ 为按正文语义整理的最大化教学目标。", "actor"),
        ]),
        "来源：Actor learning，PDF 6。PDF Eq. (6) 的熵项正号与最小化约定有歧义；本页按正文“鼓励熵”语义整理，不声称逐字或代数等价。")

    add("想象 · 跨域归一化", "只压低大回报，不把小而稀疏的噪声放大",
        "同一个熵系数要适配不同奖励尺度。DreamerV3 用回报分位距估计范围，且分母至少为 1。",
        walk(stack(
            equation(r"S=\mathrm{EMA}\!\left(\mathrm{Per}(R^\lambda,95)-\mathrm{Per}(R^\lambda,5),\,0.99\right)", "range"),
            table(["教学情形", "优势与范围", "归一化结果"], [
                ("大尺度", "$A=20,\\ S=100$", "$20/100=0.2$"),
                ("稀疏小信号", "$A=0.02,\\ S=0.01$", "$0.02/\\max(1,0.01)=0.02$"),
            ], ["large", "small"]),
            box("不是优势标准化", "范围来自回报批次；不用每批优势标准差强行放大小信号", "contrast"),
        ), [
            ("范围对离群值更稳健", "Per 表示分位数；EMA 平滑批间波动，不用观测到的最大减最小。", "range"),
            ("大值压低，保留探索权衡", "大尺度奖励不会随意吞掉固定熵正则。", "large"),
            ("稀疏噪声不被抬高", "分母下限保留小信号的原尺度；不代表模型已准确预测罕见奖励。", "small,contrast"),
        ]),
        "来源：Eq. (6)–(7)，PDF 6。表中 A、S 与结果为教学数字；非论文消融测量。")

    add("鲁棒预测 · symlog", "大、负、小：用同一个可逆变换兼容未知数值尺度",
        "归一化解决策略的相对权衡；预测头还要学习跨领域的输入与目标。symlog 压缩大幅值，同时保留符号与零附近的细节。",
        walk(stack(
            equation(r"\mathrm{symlog}(x)=\mathrm{sign}(x)\ln(|x|+1)", "log"),
            equation(r"\mathrm{symexp}(x)=\mathrm{sign}(x)(\exp(|x|)-1)", "inverse"),
            table(["教学输入", "变换值", "意义"], [
                ("$-100$", "$-4.61512$", "保留负号，压缩幅值"),
                ("$0.01$", "$0.00995$", "零附近接近恒等"),
                ("$100$", "$4.61512$", "正负对称，不截断目标"),
            ], ["large", "small", "large"]),
        ), [
            ("不是普通对数", "普通 log 无法直接处理负奖励；symlog 正负对称。", "log,large"),
            ("预测后可以还原尺度", "symexp 是逆变换，不是让模型输出永远停留在压缩单位。", "inverse"),
            ("应用于向量输入与重建", "Minecraft 背包等向量进入编码器与重建目标时使用 symlog；不是先对图像统一取对数。", "small,log"),
        ]),
        "来源：Robust predictions，Eq. (8)–(9)，PDF 7；World model learning，PDF 5。数字为函数教学计算。")

    add("鲁棒预测 · twohot", "奖励与价值不直接平方回归：预测分布，再读出均值",
        "稀有奖励与回报可能多峰且尺度很大。v2 用指数间隔的桶与 twohot 软目标，把梯度尺度同目标幅值解耦。",
        walk(stack(
            equation(r"B=\mathrm{symexp}([-20,\ldots,+20]),\qquad\hat y=\mathrm{softmax}(f(x))^\top B", "readout"),
            table(["教学桶位置", "目标 $y=3$ 的 twohot 权重"], [
                ("$b_0=0$", "$0$"), ("$b_1=2$", "$0.5$"), ("$b_2=4$", "$0.5$"),
            ], ["encoding", "encoding", "encoding"]),
            equation(r"\mathcal L=-\mathrm{twohot}(y)^\top\log\mathrm{softmax}(f(x))", "loss"),
        ), [
            ("桶位置在原始数值空间", "先对均匀坐标做 symexp 得到指数间隔位置，读出是这些位置的概率加权平均。", "readout"),
            ("两邻桶能表达连续目标", "教学桶为 0、2、4，并非作者真实桶网格；目标 3 分给两侧各一半，均值仍为 3。", "encoding"),
            ("分类交叉熵控制梯度尺度", "奖励头和 Critic 都使用这项损失；不是将 symlog 的均值再做 symexp 的另一版本写法。", "loss"),
        ]),
        "来源：Eq. (10)–(11)，PDF 7。严格采用 supplied v2 的 symexp twohot，教学三桶仅用于解释编码。")

    add("模型预测证据", "模型能预测 45 帧，但这不等于能可靠预测到钻石",
        "刚讲完潜在状态训练，现在看原始视频证据：给定上下文与已知动作序列，预测未来画面，检验模型捕获了多少环境结构。",
        walk(figure("predictions", 360, [
            ("context", 4, 9, 19, 82), ("future", 23, 9, 76, 82),
        ]), [
            ("输入前五帧", "DMLab 迷宫与四足机器人分别有真实行和预测行；动作序列由外部给定。", "context"),
            ("之后 45 帧开环预测", "不读取中间真实图像；此处是模型能力展示，不是 Actor 持续现场选择 45 次动作的成功日志。", "future"),
            ("视觉一致性只是部分证据", "像素预测看起来合理，不保证稀有奖励、继续概率与潜在回报都准确。", "future"),
        ]),
        "来源：Figure 4，PDF 4；Minecraft 原始视频预测 Figure 7 见附录。该测试不同于训练用的 15 动作想象 horizon。")

    add("真实行动 · 校正", "真正动手以后，新观测可以推翻想象里的原木",
        "Actor 在树前抽样并执行动作；如果环境没有返回原木，不能沿模型的假设继续自我确认。闭环从真实结果重新编码状态。",
        walk(stack(case("correct"), flow(
            box("Actor 直接行动", "用当前后验状态抽样并执行；不先展开树搜索", "act"),
            box("Environment 返回", "真实新输入、奖励与终止信息", "observe", "emerald"),
            box("Replay 与重编码", "保存转移，后验读新输入，继续更新模型和策略", "replay"),
        )), [
            ("预测的原木尚未成为事实", "若采集失败，真实背包和奖励可以不同于想象。该反例是教学假设。", "observe"),
            ("后验重新接回环境", "新输入 $x_{t+1}$ 进入 Encoder；下一次策略输入不是沿用未经校正的幻想。", "replay"),
            ("重复闭环，而非一次规划到底", "从回放真实经验反复学习；训练和交互并行推进。", "act,replay"),
        ]),
        "来源：Learning algorithm / Critic learning，PDF 3、5。失败采集为教学反例，不是论文错误轨迹。")

    add("算法走读 · 外层闭环", "教学伪代码：真实交互与三类学习的顺序",
        "把树前案例压成可追踪的外层控制流。辅助函数明确区分环境调用、模型训练与想象训练；不把完整工程实现伪装成论文逐字算法。",
        algorithm([
            "def learn(env, replay, model, actor, critic, budget):",
            "    obs, state = ResetAndEncode(env, model)",
            "    for step in range(budget):",
            "        action = actor.sample(state)",
            "        next_obs, reward, done = env.step(action)",
            "        replay.add(obs, action, reward, not done)",
            "        batch = replay.sample_sequences()",
            "        model.fit(batch)",
            "        TrainInImagination(batch, model, actor, critic)",
            "        state = Observe(model, state, action, next_obs)",
            "        obs = next_obs",
            "        if done:",
            "            obs, state = ResetAndEncode(env, model)",
            "    return actor, model, critic",
        ], [
            ("1,2,3", "真实起点与预算", "ResetAndEncode 读取环境重置后的真实输入；budget 在此教学代码中计真实交互步数。",
             "空背包与树", "后验模型状态", "省略并行环境、更新频率调度与 Replay 状态缓存；不改变数据身份。"),
            ("4,5,6", "直接抽样与环境执行", "Actor 抽样动作；只有 env.step 产生新真实观测、奖励和终止信息。",
             "当前状态", "真实转移入 Replay", "done 为真实终止；继续标记使用 not done。"),
            ("7,8,9", "回放、模型更新、想象学习", "model.fit 包含预测、动态与表征三项损失；想象训练更新 Actor 和 Critic。",
             "Replay 序列", "模型与策略参数更新", "并非每个 env.step 都必须更新一次；实际更新量由 Replay Ratio 控制。"),
            ("10,11,12,13,14", "后验校正与下一轮", "Observe 结合动作、记忆与新真实输入；终止时重置环境与模型状态。",
             "真实新输入", "下一轮策略输入", "不把想象状态直接当成已执行后的真实状态。"),
        ], "DreamerV3 外层闭环 · 教学抽象"),
        "来源：Learning algorithm，PDF 3–7；Methods—Replay buffer，PDF 18。Python-like 教学伪代码，非作者 Algorithm 原文。")

    add("算法走读 · 想象训练", "教学伪代码：冻结世界模型，用预测轨迹更新 Actor 与 Critic",
        "接住上页 TrainInImagination 的职责：从真实后验状态启动，重复预测，再计算目标；短轨迹的末端交给 Critic。",
        algorithm([
            "def TrainInImagination(batch, model, actor, critic):",
            "    start = EncodeReplay(model, batch)",
            "    traj, state = [], start",
            "    with FrozenParameters(model):",
            "        for t in range(15):",
            "            action = actor.sample(state)",
            "            reward, cont = model.predict_heads(state)",
            "            traj.append((state, action, reward, cont))",
            "            state = model.imagine_next(state, action)",
            "        returns = LambdaReturns(traj, critic, state)",
            "    critic.fit(traj, returns, replay=batch)",
            "    actor.fit_reinforce(traj, returns, critic)",
            "    return actor, critic",
        ], [
            ("1,2,3", "从真实后验表征启动", "EncodeReplay 用真实序列建立后验起点；想象训练起点覆盖回放的输入状态。",
             "真实 Replay", "树前潜在状态", "真实起点不代表其后预测一定真实；这里省略批维度。"),
            ("4,5,6,7,8,9", "15 次动作与后继预测", "Actor 生成动作，模型预测状态、奖励与继续概率；冻结模型参数，避免行为目标改写模型。",
             "状态与抽样动作", "潜在轨迹", "不读取新的环境观测，不执行 env.step，不要求 Decoder 渲染图像。"),
            ("10,11", "回推目标并训练 Critic", "LambdaReturns 包含末端 bootstrap；Critic 用分布目标学习，另含 Replay value loss 与 EMA 正则。",
             "轨迹与末端状态", "$\\lambda$-return 与价值目标", "按 v2 Eq. (5) 的状态 / 奖励下标对齐；Replay value loss 权重 0.3。"),
            ("12,13", "归一化优势更新 Actor", "<code>actor.fit_reinforce</code> 实现停止梯度的优势、回报分位归一化与熵正则。",
             "回报减价值", "动作概率更新", "这是梯度学习策略，不是对多条完整计划排序后输出一条。"),
        ], "DreamerV3 想象训练 · 教学抽象"),
        "来源：Critic / Actor learning，Eq. (4)–(7)，PDF 5–6；Table 4，PDF 21。教学伪代码省略优化器与批处理细节。")

    add("Minecraft · 平均回报", "100M 环境步后，Dreamer 的平均回报为 9.1",
        "闭环与策略更新已经讲通，先看技术链总体推进，再单独看钻石；平均里程碑回报不能直接读作成功率。",
        walk(figure("minecraft-table", 355, [
            ("dreamer", 2, 30, 95, 18), ("baselines", 2, 48, 95, 47),
        ]), [
            ("同一环境步预算", "Minecraft Diamond 上比较 100M 环境步；Dreamer 使用 200M 参数、Replay Ratio 32。", "dreamer"),
            ("平均更深地推进技术链", "回报来自里程碑与微小生命奖惩，不是一个 0–1 钻石成功指标。", "dreamer,baselines"),
            ("增加收益不意味着每局完成", "下页对齐训练种子曾发现钻石与 episode 成功率两个分母。", "dreamer"),
        ]),
        "来源：Table 5，PDF 24；Table 2，PDF 19；奖励协议 PDF 22。Dreamer Minecraft 为 10 个训练种子。")

    add("Minecraft · 成功的分母", "100% 曾找到钻石，和 0.4% 单局成功同时成立",
        "论文最醒目的结果最容易被误读。上图问每个训练种子是否曾发现；下图问训练末期多少 episode 真正拿到钻石。",
        walk(stack(figure("discover", 235, [("agents", 67, 3, 19, 86)]),
            grid(figure("episode-diamond", 185, [("episodes", 20, 14, 73, 60)]),
                 box("两个分母", "10 个训练种子 vs 许多 episode；两者不相互矛盾", "denominator")),
        ), [
            ("Figure 5：训练中曾成功", "100M 环境步内，全部 10 个 Dreamer 种子至少曾获得钻石；对比方法为 0%。", "agents,denominator"),
            ("Figure 9：末期单局成功率", "在预算末端，钻石出现于约 0.4% 的 episode；不是 100% episode 成功。", "episodes,denominator"),
            ("突破与可靠性要分开", "首次从头学到稀有目标是突破；稳定、可重复地每局完成仍是挑战。", "agents"),
        ]),
        "来源：Figure 5，PDF 8；Figure 9 与图注，PDF 24。下图保留 Diamond 原始坐标轴；0.4% 取原文图注明确值。")

    add("任务迁移 · 接口映射", "换成连续控制，迁移的是学习接口，不是 Minecraft 技术链",
        "以 Control Suite 的 Walker Walk 与 Atari 的 Pong 为教学迁移例：前者要保持直立并向前走，后者要移动球拍击球。",
        walk(table(["接口", "Minecraft Diamond", "Walker Walk / Pong"], [
            ("真实输入", "图像 + 背包、装备、生命", "关节与速度向量 / 球与球拍的像素画面"),
            ("动作", "平面分类的移动、采集、抽象制作等", "改变关节控制量 / 向上或向下移动球拍"),
            ("模型后继", "潜在状态、奖励、继续概率", "预测运动后的潜在姿态 / 球与球拍状态"),
            ("奖励与价值", "里程碑与生存；后续技术链回报", "任务运动奖励 / 游戏得分；Critic 估计后续回报"),
            ("输出与评测", "Actor 抽样并真实执行；背包判定", "Actor 抽样并真实执行；真实环境评分"),
        ], ["inputs", "actions", "model", "value", "output"]), [
            ("输入与动作真的改变", "向量输入采用 MLP；图像采用 CNN；连续与离散动作都用 REINFORCE 学习策略。", "inputs,actions"),
            ("想象接口保持一致", "RSSM 都预测潜在后继、奖励与继续概率，Critic 都补足有限轨迹之外的回报。", "model,value"),
            ("评测仍回到各自环境", "没有把 Minecraft 里程碑奖励套到关节控制；没有共享同一训练权重。", "output"),
        ]),
        "来源：World model / Actor learning，PDF 4–6；Benchmarks 与 Figure 10、14。Walker Walk / Pong 为教学接口映射，不是作者运行轨迹。")

    add("跨领域 · 总体结果", "8 个领域的结果支持固定配方，但不支持“所有比较都同预算”",
        "刚把任务接口映射清楚，现在回到论文的汇总图：性能与数据预算必须一起读，不能只看每组最高柱。",
        walk(figure("summary", 380, [
            ("broad", 0, 3, 76, 96), ("minecraft", 76, 7, 24, 85),
        ]), [
            ("广泛优于统一 PPO", "覆盖 8 个领域、150 多项任务；各领域训练独立 Agent，而非一个联合多任务策略。", "broad"),
            ("专门基线并非处处同条件", "ProcGen 与 PPG 相当；DMLab 基线拥有 10 倍数据；Atari100k 的 EfficientZero 设置难直接比较。", "broad"),
            ("Minecraft 是稀有目标验证", "汇总图的回报进展与最大轨迹不应替代前页单局成功率。", "minecraft"),
        ]),
        "来源：Figure 1，PDF 1；Benchmarks / Results，PDF 8–10；协议 PDF 19。")

    add("跨领域 · 计算预算", "固定超参数，不等于环境实例、模型大小与 Replay Ratio 全部相同",
        "同一训练配方仍允许选择计算预算。用 Table 2 的真实配置澄清数据效率与算力之间的权衡。",
        table(["领域 / 任务数", "Env steps", "Action repeat", "Replay Ratio", "模型", "A100 天 / Agent"], [
            ("Minecraft / 1", "100M", "1", "32", "200M", "8.9"),
            ("DMLab / 30", "100M", "4", "32", "200M", "2.9"),
            ("ProcGen / 16", "50M", "1", "64", "200M", "16.1"),
            ("Atari / 57", "200M", "4", "32", "200M", "7.7"),
            ("Atari100k / 26", "400K", "4", "128", "200M", "0.1"),
            ("BSuite / 23", "—", "1", "1024", "200M", "0.5"),
            ("Proprio / 18", "500K", "2", "512", "12M", "0.3"),
            ("Visual / 20", "1M", "2", "512", "12M", "0.1"),
        ]) + note("Minecraft 每个 Agent 用一张 A100 约 8.9 天，还需 64 个环境实例与远程 CPU workers；这不是全研究的总成本。"),
        "来源：Table 2 与 Computational choices，PDF 19。GPU 天为每个 Agent，非整个多种子 / 多任务研究的总量。")

    add("消融 · 稳定性", "这些技巧不是装饰：移除后，14 项任务平均表现下降",
        "KL、回报归一化、twohot 与观察变换已分别讲过。现在用消融检查它们对固定配方到底有何贡献。",
        walk(figure("robust", 380, [
            ("curve", 11, 29, 31, 57), ("legend", 42, 21, 54, 64),
        ]), [
            ("固定 14 项任务集合", "这是多任务曲线的归一化平均；不是 Minecraft 单项的成功率。", "curve"),
            ("每个技巧影响某些任务", "论文指出 KL 目标最重要，其后是 RetNorm 与 symexp twohot；单项影响随任务变化。", "legend"),
            ("平均消融不等于唯一因果故事", "去掉模块的损失证据支持有用性，但不能推出所有领域都依赖同一程度。", "curve,legend"),
        ]),
        "来源：Figure 6a 与 Ablations，PDF 9–10。横轴与纵轴均为该消融的归一化量。")

    add("消融 · 表征信号", "重建梯度很重要，不等于无需奖励也能学到采钻石策略",
        "世界模型的表征主要依赖任务无关的重建信号，但 Actor 与 Critic 仍需任务回报。停止梯度与删除奖励训练不是一回事。",
        walk(figure("signals", 380, [
            ("curve", 11, 24, 31, 62), ("labels", 42, 35, 54, 37),
        ]), [
            ("阻断重建对表征的塑形", "紫线对应 No reconstruction grads；表征学习失去重要信号，性能明显下降。", "labels,curve"),
            ("阻断奖励 / 价值对表征的塑形", "浅蓝线对应 No reward & value grads；不是把奖励头、Critic 或 Actor 全部删掉。", "labels"),
            ("无监督预训练只是未来方向", "论文据此讨论未来预训练机会，但本工作仍从交互与稀疏奖励训练任务策略。", "curve"),
        ]),
        "来源：Figure 6b、Ablations，PDF 9–10；Conclusion，PDF 11。")

    add("扩展性 · 模型与回放", "更多模型与更新，可以换来更少的真实交互",
        "稳定配方让算力有可预测的用途；但“更数据高效”不能直接改写成“更便宜”或“所有任务都验证单调扩展”。",
        walk(figure("scaling", 450, [
            ("size", 1, 1, 98, 48), ("replay", 1, 52, 98, 47),
        ]), [
            ("模型从 12M 到 400M", "在 Crafter 与 DMLab Goals 上，更大模型得到更高表现，并更早获得较高回报。", "size"),
            ("提高 Replay Ratio", "同一批真实经验用于更多梯度更新；增加的是学习计算，不是把想象步算成真实环境步。", "replay"),
            ("范围与成本要明确", "两项扩展实验不能替代所有领域的缩放定律；参数量、GPU 时间与环境数据应分别报告。", "size,replay"),
        ]),
        "来源：Figure 6c–d、Scaling properties，PDF 9–10；Methods—Model sizes、Replay buffer，PDF 18、20。")

    add("定位与边界", "DreamerV3 的“通用”，是可迁移配方，不是一个万能世界模型",
        "实验支持跨任务稳定学习，但本地这版论文没有训练一个跨领域共享世界模型，也没有证明无限长想象准确。",
        grid(
            card("真实交互仍是依据", "不用人类示范或自适应课程，并不意味着没有奖励设计、环境封装或抽象制作动作。Minecraft 还包含跳跃与破坏方块等接口修正。", "indigo"),
            card("每个任务独立训练", "固定损失、优化与稳定性超参数不等于共享权重；模型尺寸与 Replay Ratio 按计算预算选择。", "emerald"),
            card("下一步研究仍然开放", "跨领域共享模型、利用互联网视频预训练与更可靠的稀有任务完成，都在论文的未来方向或结果边界之外。", "amber"),
        ),
        "来源：Methods—Minecraft、Benchmarks，PDF 19、22；Previous work / Conclusion，PDF 11。无需人类数据限定本工作任务训练设置。")

    add("总结", "把一棵树讲到钻石：三件事要分别成立",
        "DreamerV3 的贡献不只是拥有世界模型，而是让表征、想象中的策略学习与数值稳定性接成可跨领域复用的训练闭环。",
        grid(
            card("模型学到了可用的动态", "真实观测训练 RSSM；预测潜在后继、奖励与继续概率。重建与 KL 共同防止平凡表示，原图展示有限长度开环预测。", "indigo"),
            card("策略在想象中获得改进", "$\\lambda$-return 与 Critic 连接短轨迹和远期收益；REINFORCE、熵与回报尺度控制改进策略，行动时直接抽样。", "emerald"),
            card("成功必须由真实环境核查", "Minecraft 平均回报 9.1；10 个种子都曾找到钻石，但单局仅约 0.4%。突破、平均进展与可靠性不是同一个结论。", "amber"),
        ) + note("记住：预测有用 ≠ 在线评分永远可信 ≠ 每次真实执行成功。"),
        "来源：Eq. (1)–(11)、Figure 5–6、Table 5 / Figure 9，PDF 4–10、24。")

    main_count = len(SLIDES)
    appendix_start = main_count + 1
    add("附录导航", "原公式、训练设置与完整证据，按问题回查",
        "正文给出可讲通的推理链；附录保留实现时需要核对的精确信息，不把教学简化冒充逐字算法。",
        '<div class="appendix-grid">' + "".join(
            f'<a class="appendix-entry" href="#slide-{appendix_start+i}" data-slide-target="{appendix_start+i}">'
            f'<span class="badge badge-indigo">A{i:02}</span><strong>{heading}</strong><p>{text}</p></a>'
            for i, (heading, text) in enumerate([
                ("RSSM 与损失", "六类条件预测与三项损失的精确职责。"),
                ("超参数与版本", "v2 的优化、Replay 与 15 动作想象设置。"),
                ("Minecraft 原始预测", "上下文五帧与未来 45 帧的原图。"),
                ("物品成功率与复现边界", "完整 Figure 9、资源与版本核查。"),
            ], 1)
        ) + "</div>",
        '<a href="#slide-2" data-slide-target="2">返回正文路线</a> · 原文：arXiv:2301.04104v2，2024-04-17；PDF 页码与论文页码一致。',
        appendix=True)

    add("附录 A01 · RSSM", "六个输出：后验、先验与任务反馈不能混在一起",
        "补全正文使用的条件分布；参数 $\\phi$ 属于世界模型，随机采样的离散表示通过 straight-through 梯度训练。",
        table(["职责", "v2 Eq. (1)"], [
            ("递归更新", "$h_t=f_\\phi(h_{t-1},z_{t-1},a_{t-1})$"),
            ("观测后验", "$z_t\\sim q_\\phi(z_t\\mid h_t,x_t)$"),
            ("动态先验", "$\\hat z_t\\sim p_\\phi(\\hat z_t\\mid h_t)$"),
            ("奖励预测", "$\\hat r_t\\sim p_\\phi(\\hat r_t\\mid h_t,z_t)$"),
            ("继续预测", "$\\hat c_t\\sim p_\\phi(\\hat c_t\\mid h_t,z_t)$"),
            ("输入重建", "$\\hat x_t\\sim p_\\phi(\\hat x_t\\mid h_t,z_t)$"),
        ]) + note("预测损失权重 1，动态 KL 权重 1，表征 KL 权重 0.1；后两项各有 1 nat 下限。"),
        '来源：Eq. (1)–(3)，PDF 4–5。<a href="#slide-7" data-slide-target="7">返回状态讲解</a>。',
        appendix=True)

    add("附录 A02 · 版本与超参数", "这是 2024 v2 的配方，不混用 2023 v1 或后续版本",
        "论文的图、桶读出、网络与优化器均按本地 PDF 核对。复现时需进一步固定代码提交与环境，而不能只下载任意最新版。",
        table(["类别", "设置"], [
            ("批与 Replay", "容量 $5\\times10^6$；batch 16；序列长度 64"),
            ("优化", "学习率 $4\\times10^{-5}$；LaProp；AGC(0.3)"),
            ("网络", "Block GRU；RMSNorm；SiLU；latent 与 Actor unimix 1%"),
            ("想象与回报", "动作 horizon 15；$\\gamma=0.997$；$\\lambda=0.95$"),
            ("Critic", "想象 loss 1；Replay value loss 0.3；EMA 正则 1，decay 0.98"),
            ("Actor", "loss scale 1；熵 $3\\times10^{-4}$；RetNorm decay 0.99；分母下限 1"),
            ("没有使用", "退火、prioritized replay、weight decay、dropout"),
        ]) + note("Replay 还包含 online queue、潜在状态存储与更新；正文伪代码省略这些工程细节，而非宣称不存在。"),
        '来源：Methods—Replay buffer / Previous Dreamer generations、Table 4，PDF 18、20–21。<a href="#slide-22" data-slide-target="22">返回算法</a>。',
        appendix=True)

    add("附录 A03 · Minecraft 原图", "五帧上下文以后，模型预测未来 45 帧",
        "保留 Minecraft 的原始 True / Model 对照，不把教学树前重绘与作者视频结果混在一起。",
        figure("minecraft-predictions", 490),
        '来源：Figure 7，PDF 23。动作序列已知，不读取中间真实画面。<a href="#slide-20" data-slide-target="20">返回预测证据</a>。',
        appendix=True)

    add("附录 A04 · 完整成功率", "从原木到钻石的完整单局成功率",
        "原图每个面板的纵轴范围不同；Diamond 面板只有 0–1%，不能同其他物品的 0–100% 混读。",
        figure("all-items", 445) + '<p class="dreamer-resource">原文：'
        '<a href="https://arxiv.org/abs/2301.04104v2" target="_blank" rel="noopener">arXiv v2</a> · '
        '<a href="https://danijar.com/project/dreamerv3/" target="_blank" rel="noopener">论文项目页</a> · '
        '离线内嵌原图与 KaTeX；教学重绘、数值与代码均非作者逐字材料。</p>',
        '来源：Figure 9 与图注，PDF 24。<a href="#slide-25" data-slide-target="25">返回成功率辨析</a>。项目后续更新不改变本讲义的 v2 证据边界。',
        appendix=True)
    return main_count


CSS = r"""
.dreamer-slide .dreamer-stack { display:flex;flex-direction:column;gap:16px;min-width:0; }
.dreamer-slide .dreamer-walk { display:grid;grid-template-columns:minmax(0,1.52fr) minmax(0,1fr);gap:24px;align-items:center; }
.dreamer-slide .dreamer-visual { min-width:0; }
.dreamer-slide .dreamer-explanations { display:flex;flex-direction:column;gap:16px;min-width:0; }
.dreamer-slide .dreamer-step { display:grid;grid-template-columns:32px minmax(0,1fr);gap:12px;padding:18px 20px;background:white;border:1.5px solid #e2e8f0;border-radius:16px;cursor:pointer; }
.dreamer-slide .dreamer-step strong { display:block;font-size:20.5px;line-height:1.35;color:#0f172a; }
.dreamer-slide .dreamer-step p { font-size:18px;line-height:1.58;color:#334155;margin:9px 0 0; }
.dreamer-slide .dreamer-step-number { font:700 15px/28px var(--font-mono);color:#4f46e5;background:#eef2ff;border-radius:8px;width:30px;height:28px;text-align:center; }
.dreamer-slide .dreamer-flow { display:flex;align-items:stretch;gap:10px;min-width:0; }
.dreamer-slide .dreamer-node { flex:1;min-width:0;border:1.5px solid #c7d2fe;background:#eef2ff;border-radius:14px;padding:17px 18px;color:#334155; }
.dreamer-slide .dreamer-node.emerald { background:#ecfdf5;border-color:#a7f3d0; }
.dreamer-slide .dreamer-node strong { display:block;font-size:20.5px;line-height:1.35;margin-bottom:8px;color:#0f172a; }
.dreamer-slide .dreamer-node p { font-size:18px;line-height:1.58;margin:0; }
.dreamer-slide .dreamer-arrow { display:flex;align-items:center;color:#4f46e5;font-size:26px;flex:0 0 19px;justify-content:center; }
.dreamer-slide .dreamer-case { min-width:0;border:1.5px solid #e2e8f0;border-radius:14px;padding:10px 12px;background:white; }
.dreamer-slide .dreamer-case svg { display:block;width:100%;height:190px;font-family:var(--font-sans); }
.dreamer-slide .dreamer-case p { font-size:16px;line-height:1.5;color:#64748b;margin:8px 0 0; }
.dreamer-slide .dreamer-figure { position:relative;width:min(100%,calc(var(--figure-height) * var(--figure-ratio)));aspect-ratio:var(--figure-ratio);flex-shrink:0;margin:auto; }
.dreamer-slide .fig-box .dreamer-figure img { width:100%;height:100%;max-width:none;max-height:none;display:block;object-fit:contain; }
.dreamer-slide .fig-box { margin:0;padding:12px; }
.dreamer-slide .image-step-focus { position:absolute;pointer-events:none;opacity:0!important;border-radius:6px; }
.dreamer-slide .image-step-focus.is-current { opacity:1!important;border:2.5px solid #4f46e5!important;background:rgba(79,70,229,.08); }
.dreamer-slide .dreamer-step.is-current { border-color:#4f46e5;background:#eef2ff; }
.dreamer-slide .dreamer-node.is-current,.dreamer-slide .dreamer-case.is-current { border-color:#4f46e5; }
.dreamer-slide .math-block { justify-content:center;margin:0;padding:12px 16px;min-width:0; }
.dreamer-slide .data-table { font-size:18px;line-height:1.5; }
.dreamer-slide .data-table th,.dreamer-slide .data-table td { padding:10px 14px; }
.dreamer-slide .latex-source .katex-display { margin:0; }
.dreamer-slide .dreamer-resource { font-size:16px;line-height:1.5;color:#64748b; }
.dreamer-slide a { color:#4f46e5;text-underline-offset:3px; }
.dreamer-slide .story-source { text-align:left;margin:0; }
.dreamer-route .slide-body { justify-content:flex-start;padding-top:12px; }
.dreamer-route .route-map { height:490px;flex:0 0 490px; }
.dreamer-algorithm .dreamer-node { padding:10px 12px; }
.dreamer-algorithm .dreamer-node strong { font-size:17px; }
.dreamer-algorithm .dreamer-node p { font-size:17px;line-height:1.5; }
.dreamer-algorithm .dreamer-algo-visual { margin:12px 0; }
.dreamer-print-summary { display:none; }
.dreamer-opening .slide-body { gap:24px; }
.dreamer-opening.opening-paced .slide-body { padding-top:16px; }
.dreamer-opening .dreamer-walk { grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);column-gap:40px;row-gap:22px;align-items:center; }
.dreamer-opening .dreamer-explanations { gap:18px; }
.dreamer-opening .dreamer-step { padding:12px 16px;border-color:transparent;background:transparent; }
.dreamer-opening .dreamer-takeaway { grid-column:1/-1;padding:8px 16px;border-left:3px solid #c7d2fe;border-radius:0 10px 10px 0;background:#f1f5f9;font-size:17.2px;line-height:1.5;color:#475569; }
.dreamer-opening .dreamer-diagram { display:flex;flex-direction:column;gap:16px; }
.dreamer-opening .dreamer-diagram-cap { font-size:14px;line-height:1.45;color:#64748b; }
.dreamer-opening .dreamer-step.is-current { border-color:#c7d2fe;background:#eef2ff; }
.dreamer-opening .opening-art { display:block;width:100%;height:auto;overflow:visible;font-family:var(--font-sans); }
.dreamer-opening .opening-label { font:400 18px/1.5 var(--font-sans);color:#334155; }
.dreamer-opening .opening-label.heading { font-size:20.5px;font-weight:700;line-height:1.35;color:#0f172a; }
.dreamer-opening .opening-label.score { text-align:right;color:#4f46e5; }
.dreamer-opening .opening-label .katex { font-size:1.05em; }
.dreamer-opening .visual-sequence svg [data-visual-step] { filter:none!important;box-shadow:none!important; }
.dreamer-opening .opening-node.is-current > rect { stroke:#6366f1;stroke-width:2.5; }
.dreamer-opening .opening-edge.is-current { stroke:#4f46e5;stroke-width:3;stroke-dasharray:1;animation:opening-trace .85s ease-out both; }
.dreamer-opening .opening-edge.opening-uncertain.is-current { stroke-dasharray:.07 .07;animation:none; }
.dreamer-opening .opening-reveal { opacity:1;transition:opacity .35s ease; }
.dreamer-opening [data-current-step="1"] .opening-reveal[data-from="2"],
.dreamer-opening [data-current-step="1"] .opening-reveal[data-from="3"],
.dreamer-opening [data-current-step="2"] .opening-reveal[data-from="3"] { opacity:0;visibility:hidden; }
.dreamer-opening .opening-player { transition:transform .65s ease; }
.dreamer-opening[data-page="3"] [data-current-step="3"] .opening-player { transform:translate(40px,-13px); }
.dreamer-opening[data-page="3"] [data-current-step="3"] .opening-approach { animation:opening-march 1.2s linear 2; }
.dreamer-opening .opening-paper-route { display:flex;align-items:center;gap:10px; }
.dreamer-opening .opening-paper-route > span { flex:1;min-width:0;padding:10px 8px;text-align:center;border:1px solid transparent;border-radius:10px;color:#475569;font-size:17.2px;line-height:1.5; }
.dreamer-opening .opening-paper-route > i { color:#94a3b8;font-style:normal; }
.dreamer-opening .opening-paper-route > .is-current { background:#eef2ff;border-color:#6366f1;color:#4338ca; }
.dreamer-opening.opening-paper .dreamer-walk { grid-template-columns:minmax(0,1.35fr) minmax(0,1fr); }
.dreamer-opening.opening-paper .dreamer-explanations { gap:14px; }
.dreamer-opening.opening-paper .dreamer-step { padding:10px 16px; }
.dreamer-opening.opening-paper .dreamer-step p { margin-top:7px; }
@keyframes opening-trace { from { stroke-dashoffset:1; } to { stroke-dashoffset:0; } }
@keyframes opening-march { to { stroke-dashoffset:-26; } }
@media (prefers-reduced-motion:reduce) {
  .dreamer-opening .opening-edge,.dreamer-opening .opening-approach { animation:none!important; }
  .dreamer-opening .opening-player,.dreamer-opening .opening-reveal { transition:none; }
}
@media print {
  @page { size:1600px 900px;margin:0; }
  .dreamer-slide .image-step-focus { display:none!important; }
  .dreamer-slide [data-visual-step] { box-shadow:none!important; }
  .dreamer-algorithm .algo-step,.dreamer-algorithm .algo-label,.dreamer-algorithm .algo-status { display:none!important; }
  .dreamer-algorithm .dreamer-print-summary { display:block; }
  .dreamer-print-summary h4 { font-size:20.5px;line-height:1.35;margin-bottom:16px; }
  .dreamer-print-summary p { font-size:18px;line-height:1.58;margin:0 0 15px; }
  .dreamer-opening .opening-reveal { opacity:1!important;visibility:visible!important; }
  .dreamer-opening .opening-node > rect { stroke-width:1.5!important; }
  .dreamer-opening .opening-edge { animation:none!important; }
  .dreamer-opening .opening-player { transform:none!important; }
}
"""


def extract_assets(doc):
    assets = {"sources": {}, "views": {}, "images": []}
    pooled_images = {}

    def pool_image(match):
        image = match[0]
        if image not in pooled_images:
            pooled_images[image] = len(assets["images"])
            assets["images"].append(image)
        return f'urn:embedded-figure-image:{pooled_images[image]}'

    for name, (page, coords, _) in CROPS.items():
        source = f"page-{page}"
        if source not in assets["sources"]:
            svg = doc[page - 1].get_svg_image(text_as_path=True)
            page_rect = doc[page - 1].rect
            # PDF paper is white; exported SVG otherwise exposes the dark lightbox through its gaps.
            svg = re.sub(
                r"(<svg\b[^>]*>)",
                lambda m: m[0] + f'<rect width="{page_rect.width}" height="{page_rect.height}" fill="#fff"/>',
                svg, count=1,
            )
            assets["sources"][source] = re.sub(
                r'data:image/[^;"\s]+;base64,[A-Za-z0-9+/=]+', pool_image, svg,
            )
        rect = pymupdf.Rect(coords)
        assert rect in doc[page - 1].rect
        opening = (
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{rect.width}" height="{rect.height}" '
            f'viewBox="{rect.x0} {rect.y0} {rect.width} {rect.height}">'
        )
        assets["views"][name] = {"source": source, "open": opening}
    return assets


def build(paper):
    template = (ROOT / "react.html").read_text()
    assert hashlib.sha256(template.encode()).hexdigest() == BASELINE_SHA256, "Approved ReAct baseline required."
    with pymupdf.open(paper) as doc:
        assert len(doc) == 40 and PAPER_TITLE in doc[0].get_text() and "2301.04104v2" in doc[0].get_text(), \
            "This deck's evidence and crop coordinates require the supplied 40-page arXiv v2."
        assets = extract_assets(doc)
    SLIDES.clear()
    main_count = make_slides()
    styles = "\n".join(re.findall(r"<style(?:\s[^>]*)?>.*?</style>", template, re.S))
    math_scripts = "\n".join(re.findall(r'<script id="latex-[^"]+">.*?</script>', template, re.S))
    runtime = re.search(r"<script>\s*('use strict';.*?)</script>", template, re.S)[1]
    runtime, count = re.subn(r"const imageFocusDefinitions=.*?;\n", "const imageFocusDefinitions={};\n", runtime)
    assert count == 1
    runtime, count = re.subn(
        r"timer=setInterval\(advance,2400\);",
        "timer=setInterval(advance,Number(root.dataset.interval)||(root.closest('.dreamer-opening')?6500:2400));",
        runtime,
    )
    assert count == 1
    runtime += r"""
document.addEventListener('click', e => {
  const step=e.target.closest('.dreamer-step[data-visual-step]');
  if (!step) return;
  const player=activeVisualPlayer();
  if (player) {cancelAutoKick();player.pause();player.show(Number(step.dataset.visualStep));}
});
document.addEventListener('keydown', e => {
  if (['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName) || !viewer.hidden ||
      toc.classList.contains('open')) return;
  const card=e.target.closest('.dreamer-step[data-visual-step]');
  if (card && ['Enter',' '].includes(e.key)) {e.preventDefault();card.click();return;}
  if (!['ArrowDown','ArrowUp'].includes(e.key)) return;
  const player=activeVisualPlayer() || algoPlayers.find(p=>p.root.closest('.slide')===slides[currentIndex]);
  if (player) {
    e.preventDefault();cancelAutoKick();player.pause();
    player.show(player.step+(e.key==='ArrowDown'?1:-1));
  }
});
"""
    nav_start = template.index('<div id="bottom-bar">')
    navigation = template[nav_start:template.index("<section", nav_start)]
    navigation = re.sub(r"R1 · ReAct 目录（共 \d+ 页）", f"DreamerV3 目录（共 {len(SLIDES)} 页）", navigation)
    viewer = re.search(r'<div class="figure-lightbox".*?</div>', template, re.S)[0]
    license_text = re.search(r"<!--\s*KaTeX.*?-->", template, re.S)[0]
    pages = []
    for i, slide in enumerate(SLIDES, 1):
        cover = i == 1
        heading_tag = "h1" if cover else "h2"
        authors = (
            f'<p class="paper-topic">{slide["topic"]}</p><p class="paper-authors">{slide["authors"]}</p>'
        ) if cover else ""
        source = "" if cover else f'<footer class="story-source">{tex(slide["source"])}</footer>'
        title_plain = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"\$([^$]+)\$", r"\1", slide["title"])))
        pages.append(
            f'<section class="slide story-core dreamer-slide {slide["cls"]}" data-page="{i}" '
            f'data-section="{"appendix" if slide["appendix"] else "main"}" '
            f'data-title="{html.escape(title_plain, quote=True)}">'
            f'<div class="slide-top"><span class="chapter-tag">{slide["chapter"]}</span>'
            f'<span class="slide-index">{i:02} / {len(SLIDES)}</span></div>'
            f'<div class="story-heading"><{heading_tag} class="slide-title">{tex(slide["title"])}</{heading_tag}>'
            f'{authors}<p class="slide-lead">{tex(slide["lead"])}</p></div>'
            f'<div class="slide-body">{slide["body"]}{source}</div></section>'
        )
    provenance = {
        "paper": PAPER_TITLE, "arxiv": "2301.04104v2", "date": "2024-04-17",
        "pdf_sha256": hashlib.sha256(paper.read_bytes()).hexdigest(),
        "baseline_sha256": BASELINE_SHA256, "crops": CROPS,
        "physical_pages_equal_printed_pages": True,
        "teaching_material": "Minecraft tree scene, hypothetical transitions, A/B candidates, three-class unimix, lambda-return numbers, return normalization, symlog examples, three-bin twohot, Python-like algorithms, task interface mapping.",
    }
    assets_json = json.dumps(assets, ensure_ascii=False, separators=(",", ":"))
    assets_json = assets_json.replace("&", r"\u0026").replace("<", r"\u003c")
    output = (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>R51 · DreamerV3 · 在想象中练习，再到真实世界行动</title>'
        f'{license_text}{styles}<style id="dreamerv3-style">{CSS}</style></head>'
        f'<body class="narrative-v7" data-main-count="{main_count}" data-appendix-start="{main_count+1}">'
        '<div id="stage-wrapper"><div id="deck-stage" aria-label="DreamerV3 中文论文精读">'
        f'{navigation}{"".join(pages)}</div></div>{viewer}'
        f'<template id="dreamerv3-provenance">{html.escape(json.dumps(provenance, ensure_ascii=False))}</template>'
        f'<template id="embedded-figure-assets">{assets_json}</template>'
        f'<script id="dreamerv3-runtime">{runtime}</script>{math_scripts}</body></html>'
    )
    destination = ROOT / "dreamerv3.html"
    destination.write_text(output)
    print(f"Built {destination.name}: {main_count} main + {len(SLIDES)-main_count} appendix; "
          f"{destination.stat().st_size/1e6:.2f} MB")
    for i, slide in enumerate(SLIDES, 1):
        print(f"{i:02} {slide['title']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper", type=Path, default=ROOT.parent / "R51 - DreamerV3 World Models.pdf")
    build(parser.parse_args().paper.resolve())
