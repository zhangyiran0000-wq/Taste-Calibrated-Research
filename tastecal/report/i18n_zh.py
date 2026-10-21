"""Simplified-Chinese UI chrome for the report template.

`localize(tpl)` rewrites the English UI text of report.html with exact, ordered string
replacements. Only reader-visible text is translated: text nodes, button labels, title/aria-label
attributes, label maps and sentences built in the script. Object keys, CSS classes, ids, data-*
values and values the script compares against stay as they are. Graph content comes from the data
and is never touched.

Every pair must match the template. When the template changes and a pair no longer matches,
`localize` raises instead of silently leaving English behind.
"""
from __future__ import annotations

from typing import List, Tuple

CJK_SANS = '"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC"'
CJK_SERIF = '"Noto Serif SC","Songti SC","Noto Serif CJK SC"'

PAIRS: List[Tuple[str, str]] = [
    # ---------- CSS: CJK font fallbacks, upright vertical text ----------
    ('--f-display:"Overpass",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;',
     '--f-display:"Overpass",ui-sans-serif,system-ui,-apple-system,"Segoe UI",' + CJK_SANS + ',sans-serif;'),
    ('--f-body:"Source Serif 4","Iowan Old Style",Georgia,serif;',
     '--f-body:"Source Serif 4","Iowan Old Style",Georgia,' + CJK_SERIF + ',serif;'),
    # the Chinese serif for reading, served the same way on every system (Windows has no good one of its own)
    ('family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap">',
     'family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&family=Noto+Serif+SC:wght@400;600&display=swap">'),

    # ---------- static HTML ----------
    ('<p id="app-error" hidden>This report has no graph data yet. Render it with <code>python -m tastecal render graph.json</code>.</p>',
     '<p id="app-error" hidden>此报告还没有图谱数据。请用 <code>python -m tastecal render graph.json</code> 渲染。</p>'),
    # the bar: the two parts, and the sections of the first
    ('<nav class="navbar" aria-label="Report">', '<nav class="navbar" aria-label="报告">'),
    ('aria-label="Parts" id="parts"', 'aria-label="两部分" id="parts"'),
    ('aria-selected="true">Lineage and logic</button>', 'aria-selected="true">脉络与逻辑</button>'),
    ('aria-selected="false">Taste calibration</button>', 'aria-selected="false">审美校准</button>'),
    ('aria-label="Taste calibration" data-part="taste"', 'aria-label="审美校准" data-part="taste"'),
    ('aria-label="Sections" data-part="logic">', 'aria-label="章节" data-part="logic">'),
    ('data-tab="mechanism">Mechanism</button>', 'data-tab="mechanism">机制</button>'),
    ('data-tab="map">Map</button>', 'data-tab="map">脉络图</button>'),
    ('data-tab="threads">Threads</button>', 'data-tab="threads">各条线</button>'),
    ('data-tab="story">Story</button>', 'data-tab="story">故事</button>'),
    ('id="toc-next" hidden>Next</button>', 'id="toc-next" hidden>接下来</button>'),
    ('data-tab="method">Method</button>', 'data-tab="method">方法</button>'),

    # mechanism
    ('<h2>How the field works</h2>', '<h2>这个领域如何运转</h2>'),
    ('<p>What everyone is trying to do, what makes it hard, and the facts that made progress possible.</p>',
     '<p>大家都想做成什么，难点在哪里，以及哪些事实让进展成为可能。</p>'),
    ('<h3 class="lab">Goal</h3>', '<h3 class="lab">目标</h3>'),
    ('<div class="th-op" aria-hidden="true">but</div>', '<div class="th-op" aria-hidden="true">然而</div>'),
    ('<h3 class="lab">Core tension</h3>', '<h3 class="lab">核心矛盾</h3>'),
    ('<h3>Unlocked by these insights</h3>', '<h3>破局靠这些洞见</h3>'),
    ('<h3>Driving forces</h3>', '<h3>驱动力</h3>'),
    ('<h3>Outside pressure</h3>', '<h3>外部压力</h3>'),

    # map
    ('<h2>Who solved whose problem</h2>', '<h2>谁解决了谁的问题</h2>'),
    ('<div class="seg" role="group" aria-label="View">', '<div class="seg" role="group" aria-label="视图">'),
    ('id="v-map" aria-pressed="true">Map</button>', 'id="v-map" aria-pressed="true">脉络图</button>'),
    ('id="v-list" aria-pressed="false">List</button>', 'id="v-list" aria-pressed="false">列表</button>'),
    ('aria-label="Relation types"><span class="ctl-label">Links</span>',
     'aria-label="关系类型"><span class="ctl-label">连线</span>'),
    ('<span class="ctl-label">Side branches</span><div class="seg" role="group" aria-label="Side branches">',
     '<span class="ctl-label">旁支</span><div class="seg" role="group" aria-label="旁支">'),
    ('title="Keep the side branches folded into the badge on each line">Hide</button>',
     'title="把旁支收进各线的徽标">隐藏</button>'),
    ('title="Show every side branch on the map">Show</button>',
     'title="在图上显示所有旁支">显示</button>'),
    ('id="t-blogs" aria-pressed="true">Blogs &amp; reports</button>',
     'id="t-blogs" aria-pressed="true">博客与报告</button>'),
    ('title="Shrink the map to the window width">Fit width</button>',
     'title="把脉络图缩放到窗口宽度">适应宽度</button>'),
    ('</svg>Paper</span>', '</svg>论文</span>'),
    ('</svg>Blog or report</span>', '</svg>博客或报告</span>'),
    ('</svg>Turning point</span>', '</svg>转折点</span>'),
    ('</svg>Outside driver</span>', '</svg>外部驱动</span>'),
    ('</svg>Seed (on every line it touches)</span>', '</svg>种子（出现在它经过的每条线上）</span>'),
    ('role="img" aria-label="Lineage map"', 'role="img" aria-label="脉络图"'),
    ('<th>Date</th><th>Work</th><th>Thread</th><th>Role</th><th>Links</th>',
     '<th>日期</th><th>工作</th><th>线索</th><th>角色</th><th>连线</th>'),

    # threads
    ('<h2>Why each thread is hard</h2>', '<h2>每条线索为何难</h2>'),
    ('<p>Each line on the map is one persistent question. Read its ladder from the top: the symptom researchers saw, then "why?" asked until it reaches a root no single paper can change.</p>',
     '<p>图上的每条线都是一个长期存在的问题。它的阶梯从上往下读：先是研究者看到的症状，再不断追问“为什么？”，直到触及任何单篇论文都改变不了的根源。</p>'),
    ('role="tablist" aria-label="Threads"', 'role="tablist" aria-label="线索"'),
    ('const statusTxt = (s) => s;', 'const statusTxt = (s) => STATUS_ZH[s] || s;'),

    # story
    ('<h2>Read it as a story</h2>', '<h2>当作故事来读</h2>'),
    ('<h3>Knock-on effects</h3>', '<h3>连锁效应</h3>'),
    ('>Where solving one problem created the next one.</p>', '>解决一个问题，如何引出了下一个问题。</p>'),
    ('<h3>Still open</h3>', '<h3>仍未解决</h3>'),

    # check

    # what's next
    ("<h2>What's next</h2>", '<h2>接下来往哪走</h2>'),
    ('<p>Who is working on what now, the open questions with the experiment that would settle each, and the assumptions everyone shares.</p>',
     '<p>现在谁在做什么；还没解决的问题，以及能给出定论的实验；大家都默认的假设。</p>'),

    # method
    ('<h2>How this map was grown</h2>', '<h2>这张图是怎样长出来的</h2>'),
    ('<p>Expansion follows problems, not raw citation counts, so the map stays small enough to read.</p>',
     '<p>扩展沿着问题走，而不是看原始引用数，所以图能保持在读得过来的规模。</p>'),
    ('<li><b>Read the seed</b><span>Reduce it to what it inherits, the move it makes, its key insight, and the limitations it leaves. The limitations open the problem ledger.</span></li>',
     '<li><b>读种子论文</b><span>把它归结为：继承了什么、做了什么、关键洞见是什么、留下了哪些局限。这些局限构成问题台账的起点。</span></li>'),
    ('<li><b>Open citations by how they are cited</b><span>Backward: keep references the seed cites when framing its problem. Forward: keep citers whose citing sentence fixes, extends or challenges it. Drop mere users.</span></li>',
     '<li><b>按引用方式展开引文</b><span>回溯：保留种子论文在界定问题时引用的参考文献。追踪：保留那些在引用句中修正、扩展或挑战它的施引文献。只是使用它的不保留。</span></li>'),
    ('<li><b>Search by problem</b><span>Each open problem becomes a query over papers and the web, which finds work that tackles it without citing the seed, and blogs.</span></li>',
     '<li><b>按问题搜索</b><span>每个未解决的问题都变成一条面向论文和网络的查询，借此找到不引用种子论文却在解决这个问题的工作，以及博客。</span></li>'),
    ('<li><b>Update the ledger, repeat</b><span>New works close problems and open new ones. Stop when the budget is full or rounds stop producing new problems.</span></li>',
     '<li><b>更新台账，重复</b><span>新工作解决旧问题，也带来新问题。预算用完，或新一轮不再产生新问题时停止。</span></li>'),
    ('<li><b>Synthesize</b><span>Group problems into threads, ask "why?" down to a root, merge shared roots into driving forces, then test them against later work.</span></li>',
     '<li><b>综合</b><span>把问题归入线索，一路追问“为什么？”直到根源，把共同的根源合并为驱动力，再用后续工作检验它们。</span></li>'),
    ('<th>Round</th><th>Opened from</th><th>Kept</th><th>New problems</th><th>Problems addressed</th><th>What happened</th>',
     '<th>轮次</th><th>展开自</th><th>保留</th><th>新问题</th><th>已解决问题</th><th>经过</th>'),
    ('<summary>Full problem ledger</summary>', '<summary>完整问题台账</summary>'),
    ('<th>Id</th><th>Problem</th><th>Thread</th><th>Raised by</th><th>Addressed by</th>',
     '<th>编号</th><th>问题</th><th>线索</th><th>提出者</th><th>解决者</th>'),
    ('aria-label="Work details"', 'aria-label="工作详情"'),

    # ---------- script: label maps ----------
    # The pipeline writes its English labels into the data; Chinese labels win for known keys.
    # Relation verbs are sentence templates: {A} is the later work (edge target), {B} the earlier (source).
    ('{ label: "Resolves",   verb: "resolves a limitation of",', '{ label: "解决",   verb: "{A} 解决了 {B} 的局限",'),
    ('{ label: "Extends",    verb: "extends",                 ', '{ label: "扩展",    verb: "{A} 扩展了 {B}",          '),
    ('{ label: "Inspired",   verb: "was inspired by",         ', '{ label: "启发",   verb: "{A} 受到 {B} 的启发",     '),
    ('{ label: "Challenges", verb: "challenges",              ', '{ label: "挑战", verb: "{A} 挑战了 {B}",          '),
    ('{ label: "Competes",   verb: "competes with",           ', '{ label: "竞争",   verb: "{A} 与 {B} 相互竞争",     '),
    ('{ label: "Applies",    verb: "applies",                 ', '{ label: "应用",    verb: "{A} 应用了 {B}",          '),
    ('{ label: "Explains",   verb: "explains",                ', '{ label: "解释",   verb: "{A} 解释了 {B}",          '),
    ('const ROOT_LABEL = { hardware: "Hardware limit", math: "Mathematical fact", data: "Property of data", goal: "The field\'s goal", economics: "Economics", other: "Root cause" };',
     'const ROOT_LABEL = { hardware: "硬件限制", math: "数学事实", data: "数据特性", goal: "领域目标", economics: "经济因素", other: "根本原因" };'),
    ('const ROLE_LABEL = { seed: "Seed", foundation: "Foundation", driver: "Outside driver", "turning-point": "Turning point", improvement: "Improvement", branch: "Branch", frontier: "Frontier", explainer: "Explainer" };',
     'const ROLE_LABEL = { seed: "种子", foundation: "奠基", driver: "外部驱动", "turning-point": "转折点", improvement: "改进", branch: "分支", frontier: "前沿", explainer: "解读" };'),
    # Months, plus display names for enum values the script prints as they are in the data.
    ('const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];',
     'const MONTHS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];\n'
     'const KIND_ZH = { paper: "论文", blog: "博客", report: "报告", news: "新闻" };\n'
     'const STATUS_ZH = { open: "未解决", active: "进行中", "largely solved": "基本解决", solved: "已解决", addressed: "已解决", claimed: "声称解决" };\n'
     'const SUP_ZH = { supported: "有支撑", partial: "部分支撑", unsupported: "无支撑", untested: "未检验" };\n'
     'const OVERLAP_ZH = { "same idea": "相同想法", partial: "部分重叠", different: "不同" };\n'
     'const JUDGE_ZH = { substantial: "实质性", modest: "一般", negligible: "可忽略", high: "高", medium: "中等", low: "低" };'),
    ('return p[1] ? `${MONTHS[+p[1] - 1]} ${p[0]}` : p[0]; };',
     'return p[1] ? `${p[0]}年${MONTHS[+p[1] - 1]}` : `${p[0]}年`; };'),

    # ---------- script: header ----------
    ('$("#h-eyebrow").textContent = `The lineage of ${seed.short}${asOf ? `, as of ${asOf}` : ""}`;',
     '$("#h-eyebrow").textContent = `${seed.short} 的脉络${asOf ? `，截至 ${asOf}` : ""}`;'),
    ('|| `${seed.short} lineage`;', '|| `${seed.short} 脉络`;'),
    ('`<span class="kw-l">Keywords</span>', '`<span class="kw-l">关键词</span>'),
    ('const KW_SEP = ", ";', 'const KW_SEP = "、";'),
    ('<title>${y} · ${n} ${n === 1 ? "work" : "works"}${y === sy ? " · seed" : ""}</title>', '<title>${y} 年 · ${n} 项工作${y === sy ? " · 种子" : ""}</title>'),
    ('aria-label="Works per year, ${y0} to ${y1}"', 'aria-label="每年的工作数，${y0}–${y1}"'),
    ('<span>Works per year · most ${max}</span>', '<span>每年工作数 · 最多 ${max}</span>'),
    ('<summary>Still open in this thread · ', '<summary>本线索仍未解决 · '),
    ('<p class="pmore">${po.length - ps.length} more in the full ledger under Method.</p>', '<p class="pmore">还有 ${po.length - ps.length} 个，完整台账见“方法”一节。</p>'),
    ('[`${nodes.length} works`, `${edges.length} links`, `${threads.length} problem threads`, `${forces.length} driving forces`, `${y0}–${y1}`]',
     '[`${nodes.length} 项工作`, `${edges.length} 条连线`, `${threads.length} 条问题线索`, `${forces.length} 个驱动力`, `${y0}–${y1}`]'),

    # mechanism
    ('`${forces.length} root causes behind ${threads.length} threads`',
     '`${threads.length} 条线索背后的 ${forces.length} 个根本原因`'),

    # map
    ('`Each coloured line is a problem thread and each station a work, placed by date. ${seed.short}, the seed, is the interchange every line passes through. Links run from earlier to later work. Hover a station for a summary, click it for the full card.`',
     '`每条彩色线是一条问题线索，每个站点是一项工作，按日期排列。种子论文 ${seed.short} 是每条线都经过的换乘站。连线从较早的工作指向较晚的工作。悬停站点可看摘要，点击可看完整卡片。`'),
    ('"aria-label": `${seed.short}, the seed, ${fmtDate(seed.date)}`',
     '"aria-label": `${seed.short}，种子论文，${fmtDate(seed.date)}`'),
    ('const pillTxt = `SEED · ${String(seed.short).toUpperCase()}',
     'const pillTxt = `种子 · ${String(seed.short).toUpperCase()}'),
    # Chinese glyphs are about 1.6 times wider than the mono Latin estimate.
    ('const pw = pillTxt.length * 7.3 + 18;',
     'const pw = pillTxt.length * 7.3 + (pillTxt.match(/[\\u2e80-\\u9fff\\uff00-\\uffef]/g) || []).length * 4.8 + 18;'),
    ('"aria-label": `${n.short}, ${fmtDate(n.date)}`', '"aria-label": `${n.short}，${fmtDate(n.date)}`'),
    ('dt.textContent = (n.kind !== "paper" ? n.kind + " · " : "")',
     'dt.textContent = (n.kind !== "paper" ? (KIND_ZH[n.kind] || n.kind) + " · " : "")'),
    ('title="${open ? "Fold these side branches back into the badge" : "Show the side branches of this line"}">${open ? `Fold ${nf} back` : `+${nf} side branch${nf > 1 ? "es" : ""}`}</button>',
     'title="${open ? "把这些旁支收回徽标" : "显示这条线的旁支"}">${open ? `收起 ${nf} 项` : `+${nf} 项旁支`}</button>'),
    ('`Showing the links of ${chip(state.selected)} <button type="button" data-clear>Show everything</button>`',
     '`正在显示 ${chip(state.selected)} 的连线 <button type="button" data-clear>显示全部</button>`'),
    ('`Showing the ${esc(tById[state.lane].name)} thread: <span class="serif">${esc(tById[state.lane].question)}</span> <button type="button" data-clear>Show everything</button>`',
     '`正在显示“${esc(tById[state.lane].name)}”线索：<span class="serif">${esc(tById[state.lane].question)}</span> <button type="button" data-clear>显示全部</button>`'),

    # tooltips
    ('· ${esc(n.kind)}${n.role ? " · " + esc(ROLE_LABEL[n.role] || n.role) : ""}',
     '· ${esc(KIND_ZH[n.kind] || n.kind)}${n.role ? " · " + esc(ROLE_LABEL[n.role] || n.role) : ""}'),
    ('const edgeSentence = (e) => `${esc((byId[e.target] || {}).short)} ${esc(relOf(e.type).verb)} ${esc((byId[e.source] || {}).short)}`;',
     'const edgeSentence = (e) => esc(relOf(e.type).verb).replace(/\\{([AB])\\}/g, (m, k) => esc((byId[k === "A" ? e.target : e.source] || {}).short));'),
    ('e.confidence === "stated" ? "stated" : "inferred"}</span>', 'e.confidence === "stated" ? "原文明述" : "推断"}</span>'),

    # drawer
    ('e.confidence === "stated" ? "Stated in the source" : "Inferred"', 'e.confidence === "stated" ? "原文明确陈述" : "推断得出"'),
    ('<span class="pill">${esc(n.kind || "paper")}</span>', '<span class="pill">${esc(KIND_ZH[n.kind || "paper"] || n.kind)}</span>'),
    (': "Not on the map"}</span>', ': "不在图上"}</span>'),
    ('<span class="pill">Did not pass the gates</span>', '<span class="pill">未通过关卡</span>'),
    ('aria-label="Close details"', 'aria-label="关闭详情"'),
    ('Number(n.citations).toLocaleString() + " citations"', 'Number(n.citations).toLocaleString() + " 次引用"'),
    ('<div><dt>Inherits</dt>', '<div><dt>继承</dt>'),
    ('<div><dt>Move</dt>', '<div><dt>做法</dt>'),
    ('<div><dt>Key insight</dt>', '<div><dt>关键洞见</dt>'),
    ('<div><dt>Leaves open</dt>', '<div><dt>遗留问题</dt>'),
    ('`<p class="dr-auth">Considered next to ${chip(n.near)}${n.reason ? ": " + esc(n.reason) : ""}. It was audited but did not fit the map\'s budget.</p>`',
     '`<p class="dr-auth">曾与 ${chip(n.near)} 一同考虑${n.reason ? "：" + esc(n.reason) : ""}。它经过了审计，但超出了这张图的预算。</p>`'),
    ('<h3>Builds on</h3>', '<h3>基于</h3>'),
    ('<h3>Led to</h3>', '<h3>引出</h3>'),
    ('<h3>Problems it addresses</h3>', '<h3>它解决的问题</h3>'),
    ('<h3>Problems it claims but does not solve</h3>', '<h3>它声称解决但未解决的问题</h3>'),
    ('<h3>Problems it leaves</h3>', '<h3>它留下的问题</h3>'),
    ('rel="noopener">Open the source ↗</a>', 'rel="noopener">打开原文 ↗</a>'),
    ('data-show-map="${esc(id)}">Show on the map</button>', 'data-show-map="${esc(id)}">在脉络图上看</button>'),

    # controls
    ('title="Show or hide “${esc(relOf(t).label.toLowerCase())}” links"', 'title="显示或隐藏“${esc(relOf(t).label)}”连线"'),

    # threads
    ('r.kind === "symptom" ? "Symptom" : r.kind === "root" ? `Root · ', 'r.kind === "symptom" ? "症状" : r.kind === "root" ? `根源 · '),
    ('|| "")}` : "Why?";', '|| "")}` : "为什么？";'),
    ('<span class="status ${statusClass(t.status)}">${esc(t.status)}</span>',
     '<span class="status ${statusClass(t.status)}">${esc(STATUS_ZH[t.status] || t.status)}</span>'),
    ('.replace(esc(t.name), "Show on map")', '.replace(esc(t.name), "在图上显示")'),
    ('<span class="ps ${esc(p.status)}">${esc(p.status)}</span>',
     '<span class="ps ${esc(p.status)}">${esc(STATUS_ZH[p.status] || p.status)}</span>'),
    ('"Raised by " + p.raised_by.map(chip).join(" ") : "Identified by the work that solved it"',
     '"由 " + p.raised_by.map(chip).join(" ") + " 提出" : "由解决它的工作发现"'),
    (r'" <span aria-hidden=\"true\">→</span> addressed by " + p.addressed_by.map(chip).join(" ") : ""',
     r'" <span aria-hidden=\"true\">→</span> 由 " + p.addressed_by.map(chip).join(" ") + " 解决" : ""'),
    ('" · claimed, not delivered, by " + p.claimed_by.map(chip).join(" ") : ""',
     '" · " + p.claimed_by.map(chip).join(" ") + " 声称解决但未兑现" : ""'),

    # story
    ('<span class="via">via ${chip(k.via)}</span>', '<span class="via">经由 ${chip(k.via)}</span>'),
    ('"<li>None recorded.</li>"', '"<li>暂无记录。</li>"'),

    # check

    # method
    ('<div class="wsub">claimed, not delivered: ${p.claimed_by.map(chip).join(" ")}</div>',
     '<div class="wsub">声称解决但未兑现：${p.claimed_by.map(chip).join(" ")}</div>'),
    ('[["Seed", `${seed.title} (${meta.seed_ref || ""})`], ["Generated", meta.generated_at], ["Generator", meta.generator], ["Model", meta.model], ["Budget", meta.budget ? `${meta.budget} works` : ""], ["Field limit", meta.scope ? meta.scope + (meta.scope_source === "inferred" ? " (inferred)" : "") : ""], ["Sources", (meta.sources || []).join(", ")], ["Usage", meta.usage]]',
     '[["种子", `${seed.title}（${meta.seed_ref || ""}）`], ["生成日期", meta.generated_at], ["生成器", meta.generator], ["模型", meta.model], ["预算", meta.budget ? `${meta.budget} 项工作` : ""], ["领域范围", meta.scope ? meta.scope + (meta.scope_source === "inferred" ? " (inferred)" : "") : ""], ["来源", (meta.sources || []).join("、")], ["用量", meta.usage]]'),

    # ---------- audit ----------
    ('const ROLE_TXT = { builds_on: "builds on", contrasts: "engages", baseline: "baseline", uses: "uses", mentions: "mentions", not_cited: "not cited" };',
     'const ROLE_TXT = { builds_on: "在其上构建", contrasts: "对照讨论", baseline: "用作基线", uses: "使用", mentions: "提及", not_cited: "未引用" };'),
    ('const raw = [t.citations != null ? `${t.citations_lower_bound ? "at least " : ""}${Number(t.citations).toLocaleString()} citations` : "", t.stars != null ? `${Number(t.stars).toLocaleString()} GitHub stars${t.stars_shared_with ? " (repository shared with another work)" : ""}` : ""].filter(Boolean).join(", ");',
     'const raw = [t.citations != null ? `${t.citations_lower_bound ? "至少 " : ""}${Number(t.citations).toLocaleString()} 次引用` : "", t.stars != null ? `${Number(t.stars).toLocaleString()} 个 GitHub 星标${t.stars_shared_with ? "（仓库与另一项工作共用）" : ""}` : ""].filter(Boolean).join("，");'),
    ('<summary>Claims and how well they hold · ', '<summary>主张及其成立程度 · '),
    ('<span class="sup ${esc(x.support)}">${esc(x.support)}</span>', '<span class="sup ${esc(x.support)}">${esc(SUP_ZH[x.support] || x.support)}</span>'),
    ('font-weight:700">Fairness notes</p>', 'font-weight:700">公平性说明</p>'),
    ('<summary>Earlier work with a similar idea · ', '<summary>思路相近的更早工作 · '),
    ('"partial"}">${esc(p.overlap)}</span>', '"partial"}">${esc(OVERLAP_ZH[p.overlap] || p.overlap)}</span>'),
    ('<span class="small">· not cited by this work</span>', '<span class="small">· 未被本工作引用</span>'),
    ('<summary>What later papers do with it</summary>', '<summary>后续论文如何使用它</summary>'),
    ('${ev.uptake_basis ? ". " + esc(ev.uptake_basis) : ""}', '${ev.uptake_basis ? "。" + esc(ev.uptake_basis) : ""}'),
    ('<summary>Later evidence against it · ', '<summary>后续的反面证据 · '),
    ('<summary>Notes</summary>', '<summary>备注</summary>'),

    # ---------- side branches ----------
    ('`<span class="tm">Side branches of ${esc(tById[l].name)} · click to ${state.allFolded || state.unfold.has(l) ? "fold them back" : "show them"}</span>`',
     '`<span class="tm">“${esc(tById[l].name)}”线的旁支 · 点击${state.allFolded || state.unfold.has(l) ? "收起" : "显示"}</span>`'),

    # ---------- map hint ----------
    ('+= " Side branches (applications, parallel routes and explanations off the main chain) are folded into the “+N side branches” badge on their line.";',
     '+= "旁支（主链之外的应用、并行路线和解读）收在所在线上的“+N 项旁支”徽标里。";'),
    # ---------- your ratings ----------
    ('<h3>Your rating</h3>', '<h3>你的评分</h3>'),
    ('<p class="small">How much does this paper really contribute, in your view? 1 means nothing real, 5 means a major step. It is saved to your taste profile${RATE.title ? ` “${esc(RATE.title)}”` : ""}, and later runs calibrate on it.</p>',
     '<p class="small">你认为这篇论文真正的贡献有多大？1 表示没有实质贡献，5 表示重大进展。评分会存进你的口味设置${RATE.title ? `“${esc(RATE.title)}”` : ""}，之后的运行会用它来校准。</p>'),
    ('aria-label="Your rating">', 'aria-label="你的评分">'),
    ('placeholder="Why, in a line (optional)"', 'placeholder="一句话说明理由（可选）"'),
    ('<button type="button" class="rate-save">Save</button>${mine ? `<button type="button" class="rate-clear">Remove</button>` : ""}',
     '<button type="button" class="rate-save">保存</button>${mine ? `<button type="button" class="rate-clear">删除</button>` : ""}'),
    ('msg.textContent = "Pick a number from 1 to 5 first.";', 'msg.textContent = "请先选 1 到 5 的分数。";'),
    ('clear ? "Removed." : `Saved. “${d.title}” now has ${d.rated} rated papers.`', 'clear ? "已删除。" : `已保存。“${d.title}”现在有 ${d.rated} 篇打过分的论文。`'),
    ('`Not saved (${e.message}). Is the tastecal page still running?`', '`没有保存（${e.message}）。tastecal 页面还开着吗？`'),

    # ---------- what's next ----------
    ('<h3>Active now${', '<h3>正在进行${'),
    ('<span class="scores">Last ${esc(o.window_months)} months</span>', '<span class="scores">近 ${esc(o.window_months)} 个月</span>'),
    ('<h3>Open questions<span class="scores">', '<h3>未解的问题<span class="scores">'),
    ('<b>Closest attempts:</b> ', '<b>最接近的尝试：</b>'),
    ('<b>Would settle it:</b> ', '<b>能定论的实验：</b>'),
    ('<h3>Shared assumptions<span class="scores">', '<h3>共同的假设<span class="scores">'),
    ('<b>If it is wrong:</b> ', '<b>如果它不成立：</b>'),

    # Evidence status and reading recommendations are independent.
    ('<span class="pill">Borrowed tool</span>', '<span class="pill">借用工具</span>'),
    ('const MUST_TXT = "Must-read, named by you";', 'const MUST_TXT = "你指定的必读";'),
    ('[["Must-read", nodes.filter(', '[["你指定的必读", nodes.filter('),
    ('["Must-read not found", (meta.must_missing', '["没找到的必读", (meta.must_missing'),
    ('" (inferred)"', '"（自动推断）"'),
    # the work's context (audit) and the not-read-in-full mark
    ('return `<h3>Context</h3>', 'return `<h3>背景</h3>'),
    ('<p class="small">Counts: ${esc(raw)}.</p>', '<p class="small">计数：${esc(raw)}。</p>'),
    ('const NV = { label: "Not read in full", abstract: "Only the abstract could be read, so these notes are not checked against the paper.", card: "Only a short summary could be read, so these notes are not checked against the paper." };',
     'const NV = { label: "未读全文", abstract: "只读到了摘要，所以这些笔记没有对照论文原文核对。", card: "只读到了一份简短概要，所以这些笔记没有对照论文原文核对。" };'),
]


def localize(tpl: str) -> str:
    """Apply every (english, chinese) pair in order; raise if one no longer matches the template."""
    missing = []
    for en, zh in PAIRS:
        if en not in tpl:
            missing.append(en)
            continue
        tpl = tpl.replace(en, zh)
    if missing:
        raise ValueError("i18n_zh: %d pair(s) not found in the template, first: %r" % (len(missing), missing[0][:120]))
    return tpl


def is_zh(graph: dict) -> bool:
    lang = (graph.get("meta") or {}).get("language")
    return isinstance(lang, str) and lang.strip().lower().startswith("zh")
