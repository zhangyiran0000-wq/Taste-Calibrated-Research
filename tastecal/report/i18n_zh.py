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
CJK_SERIF = '"Songti SC","Noto Serif CJK SC"'

PAIRS: List[Tuple[str, str]] = [
    # ---------- CSS: CJK font fallbacks, upright vertical text ----------
    ('--f-display:"Overpass",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;',
     '--f-display:"Overpass",ui-sans-serif,system-ui,-apple-system,"Segoe UI",' + CJK_SANS + ',sans-serif;'),
    ('--f-body:"Source Serif 4","Iowan Old Style",Georgia,serif;',
     '--f-body:"Source Serif 4","Iowan Old Style",Georgia,' + CJK_SERIF + ',serif;'),
    ('--f-mono:"Overpass Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;',
     '--f-mono:"Overpass Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,' + CJK_SANS + ',monospace;'),
    # The English operator is rotated to read bottom-up; Chinese reads top-down, upright.
    ('letter-spacing:.06em;writing-mode:vertical-rl;transform:rotate(180deg)}',
     'letter-spacing:.06em;writing-mode:vertical-rl}'),

    # ---------- static HTML ----------
    ('<p id="app-error" hidden>This report has no graph data yet. Render it with <code>python -m tastecal render graph.json</code>.</p>',
     '<p id="app-error" hidden>此报告还没有图谱数据。请用 <code>python -m tastecal render graph.json</code> 渲染。</p>'),
    ('<nav class="toc" aria-label="Sections">', '<nav class="toc" aria-label="章节">'),
    ('<a href="#mechanism">Mechanism</a>', '<a href="#mechanism">机制</a>'),
    ('<a href="#map">Map</a>', '<a href="#map">脉络图</a>'),
    ('<a href="#threads">Threads</a>', '<a href="#threads">线索</a>'),
    ('<a href="#story">Story</a>', '<a href="#story">故事</a>'),
    ('<a href="#check">Check</a>', '<a href="#check">检验</a>'),
    ('id="toc-next" hidden>Next</a>', 'id="toc-next" hidden>接下来</a>'),
    ('id="toc-quality" hidden>Holds up?</a>', 'id="toc-quality" hidden>站得住吗</a>'),
    ('<a href="#method">Method</a>', '<a href="#method">方法</a>'),

    # mechanism
    ('<span class="kicker">The mechanism</span>', '<span class="kicker">机制</span>'),
    ('<h2>How the field works</h2>', '<h2>这个领域如何运转</h2>'),
    ('<p>What everyone is trying to do, what makes it hard, and the facts that made progress possible.</p>',
     '<p>大家都想做成什么，难点在哪里，以及哪些事实让进展成为可能。</p>'),
    ('<span class="kicker">Goal</span>', '<span class="kicker">目标</span>'),
    ('<div class="eq-op" aria-hidden="true">but</div>', '<div class="eq-op" aria-hidden="true">然而</div>'),
    ('<span class="kicker">Core tension</span>', '<span class="kicker">核心矛盾</span>'),
    ('<div class="eq-op" aria-hidden="true">unlocked by</div>', '<div class="eq-op" aria-hidden="true">破局靠</div>'),
    ('<span class="kicker">Enabling insight</span>', '<span class="kicker">关键洞见</span>'),
    ('<h3>Driving forces</h3>', '<h3>驱动力</h3>'),
    ('<span class="kicker">Outside pressure</span>', '<span class="kicker">外部压力</span>'),

    # map
    ('<span class="kicker">The lineage map</span>', '<span class="kicker">脉络图</span>'),
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
    ('<span class="kicker">Problem threads</span>', '<span class="kicker">问题线索</span>'),
    ('<h2>Why each thread is hard</h2>', '<h2>每条线索为何难</h2>'),
    ('<p>Each line on the map is one persistent question. Read each ladder left to right: the symptom researchers saw, then "why?" asked until it reaches a root no single paper can change.</p>',
     '<p>图上的每条线都是一个长期存在的问题。每架阶梯从左往右读：先是研究者看到的症状，再不断追问“为什么？”，直到触及任何单篇论文都改变不了的根源。</p>'),

    # story
    ('<span class="kicker">The story</span>', '<span class="kicker">故事</span>'),
    ('<h2>Read it as a story</h2>', '<h2>当作故事来读</h2>'),
    ('<h3>Knock-on effects</h3>', '<h3>连锁效应</h3>'),
    ('>Where solving one problem created the next one.</p>', '>解决一个问题，如何引出了下一个问题。</p>'),
    ('<h3>Still open</h3>', '<h3>仍未解决</h3>'),

    # check
    ('<span class="kicker">Check</span>', '<span class="kicker">检验</span>'),
    ('<h2>Does the explanation hold?</h2>', '<h2>这个解释站得住吗？</h2>'),
    ('<p>A good set of driving forces should explain every work on the map and predict what came next.</p>',
     '<p>一组好的驱动力，应当能解释图上的每项工作，并预测之后出现的工作。</p>'),
    ('<th>Predicted from the forces alone</th><th>Realised by later work</th>',
     '<th>仅凭驱动力做出的预测</th><th>后续工作是否实现</th>'),

    # what's next
    ('<span class="kicker">Outlook</span>', '<span class="kicker">展望</span>'),
    ("<h2>What's next</h2>", '<h2>接下来往哪走</h2>'),
    ('<p>Who is working on what now, the open questions with the experiment that would settle each, and the assumptions everyone shares.</p>',
     '<p>现在谁在做什么；还没解决的问题，以及能给出定论的实验；大家都默认的假设。</p>'),

    # does it hold up: gates, then the audit
    ('<span class="kicker">Reading list</span>', '<span class="kicker">阅读清单</span>'),
    ('<h2>Does it hold up?</h2>', '<h2>哪些站得住</h2>'),
    ('<p>Each paper was read from its own text: does it deliver its claim, does it say why it works, do the gains repeat. Separately, a blind score of its contribution is set against how much notice it got.</p>',
     '<p>每篇论文都按它自己的原文来读：有没有兑现主张，有没有说明为什么有效，收益能不能重复出现。另外，用盲评得出的贡献，对照它得到的关注。</p>'),
    ('<summary id="gt-all-sum">All gated works</summary>', '<summary id="gt-all-sum">全部经过关卡检查的工作</summary>'),
    ('<th>Work</th><th>Verdict</th><th>Claim</th><th>Reason</th><th>Robustness</th><th id="gt-ck-h" hidden>Checks</th><th>Why</th>',
     '<th>工作</th><th>结论</th><th>主张</th><th>理由</th><th>稳健性</th><th id="gt-ck-h" hidden>核查</th><th>原因</th>'),
    ('<h3>How it was judged</h3>', '<h3>评判方式</h3>'),
    ('<h3>Read with care</h3>', '<h3>阅读须知</h3>'),
    ('<h3>Notice versus contribution</h3>', '<h3>关注度与贡献</h3>'),
    ('<p>How much notice each work got, set against how much it contributed. Contribution was scored blind, from evidence with names, venues and counts removed. The corners are where to look twice.</p>',
     '<p>每项工作得到了多少关注，对照它实际贡献了多少。贡献是盲评的：所依据的证据去掉了作者、发表场所和各类计数。四个角落值得多看一眼。</p>'),
    ('aria-label="Scatter plot of attention against contribution"', 'aria-label="关注度与贡献的散点图"'),
    ('<summary id="au-all-sum">All assessed works</summary>', '<summary id="au-all-sum">全部评估过的工作</summary>'),
    ('<th>Work</th><th>Flag</th><th>Contribution</th><th>Attention</th><th>Judge</th><th>Reason</th>',
     '<th>工作</th><th>标记</th><th>贡献</th><th>关注度</th><th>裁判</th><th>理由</th>'),

    # method
    ('<span class="kicker">Method</span>', '<span class="kicker">方法</span>'),
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
    ('const VERDICT_LABEL = Object.assign({ solid: "Solid", treasure: "Treasure candidate", unattributed: "Gain not attributed", incremental: "Incremental", "not-delivered": "Claim not delivered" }, (GT && GT.labels) || {});',
     'const VERDICT_LABEL = Object.assign({}, (GT && GT.labels) || {}, { solid: "扎实", treasure: "宝藏候选", unattributed: "增益来源不明", incremental: "增量改进", "not-delivered": "主张未兑现" });'),
    ('<span class="scores">${un.length} kept on the map</span></h3><p>They deliver, with a reason or repeated gains, but the text shows the gain may come from something other than the idea.</p>',
     '<span class="scores">${un.length} 项，留在图上</span></h3><p>它们兑现了主张，也有理由或可复现的增益，但原文显示增益可能来自想法之外的因素。</p>'),
    ('const NV = { label: "Not verified", abstract: "Only the abstract could be read, so this verdict is not verified and the work is never folded.", card: "Only a short summary could be read, so this verdict is not verified and the work is never folded." };',
     'const NV = { label: "未核实", abstract: "只读到了摘要，所以这个判定未经核实，这项工作也始终不会被折叠。", card: "只读到了一份简短概要，所以这个判定未经核实，这项工作也始终不会被折叠。" };'),
    ('`Taste profile: ${GT.taste_name}`', '`品味档案：${GT.taste_name}`'),
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
     'const GBASIS_ZH = { "full text": "全文", abstract: "摘要", card: "卡片" };\n'
     'const SUP_ZH = { supported: "有支撑", partial: "部分支撑", unsupported: "无支撑", untested: "未检验" };\n'
     'const OVERLAP_ZH = { "same idea": "相同想法", partial: "部分重叠", different: "不同" };\n'
     'const JUDGE_ZH = { substantial: "实质性", modest: "一般", negligible: "可忽略", high: "高", medium: "中等", low: "低" };'),
    ('return p[1] ? `${MONTHS[+p[1] - 1]} ${p[0]}` : p[0]; };',
     'return p[1] ? `${p[0]}年${MONTHS[+p[1] - 1]}` : `${p[0]}年`; };'),

    # ---------- script: header ----------
    ('$("#h-eyebrow").textContent = `Taste-Calibrated Research · lineage of ${seed.short}`;',
     '$("#h-eyebrow").textContent = `Taste-Calibrated Research · ${seed.short} 的脉络`;'),
    ('|| `${seed.short} lineage`;', '|| `${seed.short} 脉络`;'),
    ('$("#h-lede").innerHTML = `<em>${esc(seed.title)}</em> (${esc(seed.authors)}${seed.year ? ", " + esc(seed.year) : ""}) sits at the centre of ${nodes.length} works${field.name ? " in " + esc(field.name.charAt(0).toLowerCase() + field.name.slice(1)) : ""}. The map traces who solved whose problem; the sections around it explain why the field moved the way it did.`;',
     '$("#h-lede").innerHTML = `<em>${esc(seed.title)}</em>（${esc(seed.authors)}${seed.year ? "，" + esc(seed.year) : ""}）位于${field.name ? "“" + esc(field.name) + "”领域" : ""} ${nodes.length} 项工作的中心。脉络图追溯谁解决了谁的问题；其余各节解释这个领域为何这样演进。`;'),
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
    ('? " · not delivered" : " · incremental")', '? " · 主张未兑现" : " · 增量改进")'),
    ('title="${open ? "Fold these side branches back into the badge" : "Show the side branches of this line"}">${open ? `Fold ${nf} back` : `+${nf} side branch${nf > 1 ? "es" : ""}`}</button>',
     'title="${open ? "把这些旁支收回徽标" : "显示这条线的旁支"}">${open ? `收起 ${nf} 项` : `+${nf} 项旁支`}</button>'),
    ('`Showing the links of ${chip(state.selected)} <button type="button" data-clear>Show everything</button>`',
     '`正在显示 ${chip(state.selected)} 的连线 <button type="button" data-clear>显示全部</button>`'),
    ('`Showing the ${esc(tById[state.lane].name)} thread: <span class="serif">${esc(tById[state.lane].question)}</span> <button type="button" data-clear>Show everything</button>`',
     '`正在显示“${esc(tById[state.lane].name)}”线索：<span class="serif">${esc(tById[state.lane].question)}</span> <button type="button" data-clear>显示全部</button>`'),

    # tooltips
    ('· ${esc(n.kind)}${n.role ? " · " + esc(ROLE_LABEL[n.role] || n.role) : ""}',
     '· ${esc(KIND_ZH[n.kind] || n.kind)}${n.role ? " · " + esc(ROLE_LABEL[n.role] || n.role) : ""}'),
    ('${n.gates.fold ? " · folded" : ""}', '${n.gates.fold ? " · 已折叠" : ""}'),
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

    # controls
    ('title="Show or hide “${esc(relOf(t).label.toLowerCase())}” links"', 'title="显示或隐藏“${esc(relOf(t).label)}”连线"'),

    # threads
    ('r.kind === "symptom" ? "Symptom" : r.kind === "root" ? `Root · ', 'r.kind === "symptom" ? "症状" : r.kind === "root" ? `根源 · '),
    ('|| "")}` : "Why?";', '|| "")}` : "为什么？";'),
    ('<span class="status ${statusClass(t.status)}">${esc(t.status)}</span>',
     '<span class="status ${statusClass(t.status)}">${esc(STATUS_ZH[t.status] || t.status)}</span>'),
    ('.replace(esc(t.name), "Show on map")', '.replace(esc(t.name), "在图上显示")'),
    ('<summary>Problem ledger for this thread · ', '<summary>本线索的问题台账 · '),
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
    ('<p>works explained by at least one driving force.</p>', '<p>项工作能被至少一个驱动力解释。</p>'),
    ('<p><b>Misfits:</b></p>', '<p><b>未能解释的工作：</b></p>'),
    ('`<p>No work on the map is left unexplained.</p>`', '`<p>图上没有未被解释的工作。</p>`'),
    ('>Prediction cutoff: ${esc(fmtDate(chk.cutoff))}</p>', '>预测截止：${esc(fmtDate(chk.cutoff))}</p>'),
    ('<span class="hit">Realised</span>', '<span class="hit">已实现</span>'),
    ('<span class="miss">No later match</span>', '<span class="miss">后续无对应工作</span>'),
    ('<span class="miss">Too vague to count</span>', '<span class="miss">太笼统，不计入</span>'),
    ('<div class="small">read from the ${esc(r.basis)}', '<div class="small">读取自：${esc(r.basis)}'),
    ('const TS = { x: "Contribution → (blind score)", y: "Your taste →", liked: "You like it, evidence thin", likedS: "Liked, thin", read: "Read first", strong: "Strong, not your taste", strongS: "Strong, not yours", skip: "Skip", both: "works with both scores", agree: "taste and blind score agree on", pairsOf: "of pairs", rated: "papers you rated", ratedAgree: "ratings vs blind:", of: "/", pairs: "pairs agree", none: "no papers rated yet", lgWork: "A work on the map (colour: its thread)", lgRated: "A paper you rated (your rating, its blind score)", lgFit: "Your ratings fitted to the blind score", lgMed: "Medians of this map", h1: "You like it, the evidence is thin", p1: "Your profile rates these above the middle of the map, the blind score below it. Check whether your taste sees something real here, or is narrowing.", h2: "Strong, but not your taste", p2: "The blind score rates these above the middle of the map, your profile below it. These are the works you would most likely skip and should perhaps not.", noneHere: "None on this map.", taste: "taste", blind: "blind", tipRated: "A paper you rated", yourRating: "your rating" };',
     'const TS = { x: "贡献 →（盲评分数）", y: "你的品味 →", liked: "你喜欢，但证据弱", likedS: "喜欢·证据弱", read: "先读", strong: "扎实，但不合你口味", strongS: "扎实·不合口味", skip: "可跳过", both: "篇同时有两种分数", agree: "品味分与盲评分在", pairsOf: "的文章对上排序一致", rated: "篇你打过分的文章", ratedAgree: "你的打分 vs 盲评：", of: "/", pairs: "对一致", none: "还没有打过分的文章", lgWork: "图上的一篇工作（颜色：所属线索）", lgRated: "你打过分的文章（你的打分，它的盲评分）", lgFit: "你的打分对盲评分的拟合线", lgMed: "本图的中位数", h1: "你喜欢，但证据弱", p1: "你的品味档案把这些排在本图中位数以上，盲评分却在中位数以下。看看是你的品味看到了证据没体现的东西，还是在越收越窄。", h2: "扎实，但不合你口味", p2: "盲评分把这些排在本图中位数以上，你的品味档案却在中位数以下。这些是你最可能跳过、也许不该跳过的工作。", noneHere: "本图没有。", taste: "品味", blind: "盲评", tipRated: "你打过分的文章", yourRating: "你的打分" };'),
    ("<h3>Your taste versus the blind score</h3>\n      <p>Each work's taste score, from your profile, set against its blind contribution score, which never saw your profile. Where the two agree, read with confidence. Where they part, either your taste sees something the evidence does not, or it is narrowing.</p>",
     '<h3>你的品味 vs 盲评分</h3>\n      <p>每篇工作按你的品味档案得到的品味分，对照它的盲评贡献分（盲评看不到你的品味）。两者一致的，可以放心读；两者分歧的，要么你的品味看到了证据没体现的东西，要么它在越收越窄。</p>'),
    ('aria-label="Scatter plot of your taste score against the blind contribution score"', 'aria-label="品味分对盲评贡献分的散点图"'),
    ('<h3>Rate these next</h3><p>Your ratings teach the report your taste. These works are spread from low to high blind score, so a few ratings go a long way. Open one and give it 1–5.</p>',
     '<h3>建议先给这几篇打分</h3><p>你的打分让报告学会你的品味。这几篇的盲评分从低到高分布，打几篇就很有用。点开一篇，给 1–5 分。</p>'),
    ('<div class="wsub">outside the map: ', '<div class="wsub">图外论文：'),
    ('<tr><th colspan="2">Without the forces, from the same early works (baseline)</th></tr>', '<tr><th colspan="2">不用驱动力、只看同一批早期工作的预测（对照组）</th></tr>'),

    # method
    ('<div class="wsub">claimed, not delivered: ${p.claimed_by.map(chip).join(" ")}</div>',
     '<div class="wsub">声称解决但未兑现：${p.claimed_by.map(chip).join(" ")}</div>'),
    ('[["Seed", `${seed.title} (${meta.seed_ref || ""})`], ["Generated", meta.generated_at], ["Generator", meta.generator], ["Model", meta.model], ["Budget", meta.budget ? `${meta.budget} works` : ""], ["Field limit", meta.scope], ["Sources", (meta.sources || []).join(", ")], ["Usage", meta.usage]]',
     '[["种子", `${seed.title}（${meta.seed_ref || ""}）`], ["生成日期", meta.generated_at], ["生成器", meta.generator], ["模型", meta.model], ["预算", meta.budget ? `${meta.budget} 项工作` : ""], ["领域范围", meta.scope], ["来源", (meta.sources || []).join("、")], ["用量", meta.usage]]'),
    ('<h3>Borrowed from other fields</h3>', '<h3>借自其他领域</h3>'),
    ('<p class="bnote">This map is limited to <b id="b-scope"></b>. The works below come from other fields. Works on the map use them, but they are not stations here: they were not expanded, read or audited.</p>',
     '<p class="bnote">这张图限定在<b id="b-scope"></b>。下面这些工作来自其他领域。图上的工作用到了它们，但它们不是图上的站点：没有展开，没有精读，也没有审计。</p>'),
    ('const verb = w.direction === "forward" ? "builds on" : "used by";', 'const verb = w.direction === "forward" ? "借用了" : "被借用于";'),

    # ---------- audit ----------
    ('const FLAG_LABEL = Object.assign({ "hidden-gem": "Possible hidden gem", overhyped: "Possibly overhyped", skip: "Safe to skip", fair: "Fairly valued", "too-early": "Too early to tell" }, (AU && AU.labels) || {});',
     'const FLAG_LABEL = Object.assign({}, (AU && AU.labels) || {}, { "hidden-gem": "可能是遗珠", overhyped: "可能被高估", skip: "可以跳过", fair: "评价恰当", "too-early": "为时尚早" });'),
    ('"Little noticed, yet the blind score and the judge both found a substantial contribution."',
     '"很少有人注意，但盲评分数和裁判都认为它贡献可观。"'),
    ('"Widely noticed, yet the evidence supports only a modest or negligible contribution."',
     '"广受关注，但证据只支持一般或可忽略的贡献。"'),
    ('"Low contribution on the evidence. A newcomer can skip these without losing the thread."',
     '"就证据而言贡献较低。新手跳过它们也不会跟丢主线。"'),
    ('"Too recent for attention or uptake to mean much yet."',
     '"发表太近，关注度和后续采用还说明不了什么。"'),
    ('const ROLE_TXT = { builds_on: "builds on", contrasts: "engages", baseline: "baseline", uses: "uses", mentions: "mentions", not_cited: "not cited" };',
     'const ROLE_TXT = { builds_on: "在其上构建", contrasts: "对照讨论", baseline: "用作基线", uses: "使用", mentions: "提及", not_cited: "未引用" };'),
    ('const BASIS = { "citations+stars": "citations and GitHub stars per year", citations: "citations per year", stars: "GitHub stars per year, because the citation count is undercounted" };',
     'const BASIS = { "citations+stars": "每年引用数与 GitHub 星标数", citations: "每年引用数", stars: "每年 GitHub 星标数（因引用数被低估）" };'),
    ('const raw = [t.citations != null ? `${t.citations_lower_bound ? "at least " : ""}${Number(t.citations).toLocaleString()} citations` : "", t.stars != null ? `${Number(t.stars).toLocaleString()} GitHub stars${t.stars_shared_with ? " (repository shared with another work)" : ""}` : ""].filter(Boolean).join(", ");',
     'const raw = [t.citations != null ? `${t.citations_lower_bound ? "至少 " : ""}${Number(t.citations).toLocaleString()} 次引用` : "", t.stars != null ? `${Number(t.stars).toLocaleString()} 个 GitHub 星标${t.stars_shared_with ? "（仓库与另一项工作共用）" : ""}` : ""].filter(Boolean).join("，");'),
    ('return `<h3>Audit</h3>', 'return `<h3>审计</h3>'),
    ('`<span class="small">flagged as ${esc((FLAG_LABEL[a.candidate] || "").toLowerCase())}, cleared on review</span>`',
     '`<span class="small">曾被标记为“${esc(FLAG_LABEL[a.candidate] || "")}”，复核后撤销</span>`'),
    ('${bar("Contribution", c.score, true)}${bar("novelty", c.novelty)}${bar("significance", c.significance)}${bar("evidence", c.evidence)}${bar("uptake", c.uptake)}',
     '${bar("贡献", c.score, true)}${bar("新颖性", c.novelty)}${bar("重要性", c.significance)}${bar("证据", c.evidence)}${bar("采用度", c.uptake)}'),
    ('${bar("Attention", t.pct, true, pct100(t))}', '${bar("关注度", t.pct, true, pct100(t))}'),
    ('>Attention is a percentile of ${esc(BASIS[t.basis] || t.basis || "")}, among the works assessed${t.lower_bound ? "; this one is a lower bound" : ""}.${raw ? " Counts: " + esc(raw) + "." : ""}</p>',
     '>关注度是${esc(BASIS[t.basis] || t.basis || "")}在所有被评估工作中的百分位${t.lower_bound ? "；此项为下限" : ""}。${raw ? "计数：" + esc(raw) + "。" : ""}</p>'),
    ('<p class="small">Blind scorer: ${esc(c.rationale)}</p>', '<p class="small">盲评者：${esc(c.rationale)}</p>'),
    ('<summary>Adversarial review</summary>', '<summary>对抗式复核</summary>'),
    ('<b>Advocate</b>', '<b>支持方</b>'),
    ('<b>Critic</b>', '<b>批评方</b>'),
    ('<b>Judge · ${esc(j.verdict || "")} · ${esc(j.confidence || "")} confidence</b>',
     '<b>裁判 · ${esc(JUDGE_ZH[j.verdict] || j.verdict || "")} · ${esc(JUDGE_ZH[j.confidence] || j.confidence || "")}置信度</b>'),
    ('>Would change the verdict: ${esc(j.would_change)}</p>', '>可能改变结论的情况：${esc(j.would_change)}</p>'),
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
    ('xl.textContent = "Attention → (percentile within this set)";', 'xl.textContent = "关注度 →（本集合内的百分位）";'),
    ('yl.textContent = "Contribution → (blind score)";', 'yl.textContent = "贡献 →（盲评分数）";'),
    ('ql("Hidden gem?",', 'ql("遗珠？",'),
    ('ql("Classic",', 'ql("经典",'),
    ('ql("Overhyped?",', 'ql("高估？",'),
    ('ql("Noise",', 'ql("噪声",'),
    ('"aria-label": `${w.short}: ${FLAG_LABEL[a.flag]}, contribution ${score2(a.contribution.score)}, attention ${pct100(a.attention)}`',
     '"aria-label": `${w.short}：${FLAG_LABEL[a.flag]}，贡献 ${score2(a.contribution.score)}，关注度 ${pct100(a.attention)}`'),
    ('`${assessed.length} works assessed`', '`已评估 ${assessed.length} 项工作`'),
    ('.length} on the map, ${assessed.filter((w) => !byId[w.id]).length} not`',
     '.length} 项在图上，${assessed.filter((w) => !byId[w.id]).length} 项不在`'),
    ('`${reviewed} argued over by advocate, critic and judge`', '`${reviewed} 项经支持方、批评方与裁判辩论`'),
    ('`as of ${fmtDate(', '`截至 ${fmtDate('),
    ('</svg>Not on the map</span>', '</svg>不在图上</span>'),
    ('</svg>Attention is a lower bound</span>', '</svg>关注度为下限</span>'),
    ('<span class="offmap">not on the map</span>', '<span class="offmap">不在图上</span>'),
    ('<span class="scores">contribution ${score2(a.contribution.score)} · attention ${pct100(a.attention)}/100${j ? ` · judge: ${esc(j.verdict)}` : ""}</span>',
     '<span class="scores">贡献 ${score2(a.contribution.score)} · 关注度 ${pct100(a.attention)}/100${j ? ` · 裁判：${esc(JUDGE_ZH[j.verdict] || j.verdict)}` : ""}</span>'),
    ('`<p class="why">No work was flagged: on this evidence every assessed work is fairly valued.</p>`',
     '`<p class="why">没有工作被标记：就现有证据而言，每项被评估的工作都评价恰当。</p>`'),
    ('`All ${all.length} assessed works`', '`全部 ${all.length} 项评估过的工作`'),
    ('<td>${j ? esc(j.verdict) : "—"}</td>', '<td>${j ? esc(JUDGE_ZH[j.verdict] || j.verdict) : "—"}</td>'),
    ('${byId[w.id] ? "" : " · not on the map"}</span>', '${byId[w.id] ? "" : " · 不在图上"}</span>'),
    ('<br>contribution ${score2(a.contribution.score)} · attention ${pct100(a.attention)}/100',
     '<br>贡献 ${score2(a.contribution.score)} · 关注度 ${pct100(a.attention)}/100'),

    # ---------- gates ----------
    ('const DLV = { delivered: ["supported", "Delivered"], partial: ["partial", "Partly delivered"], not: ["unsupported", "Not delivered"] };',
     'const DLV = { delivered: ["supported", "已兑现"], partial: ["partial", "部分兑现"], not: ["unsupported", "未兑现"] };'),
    ('const RSN = { proof: ["supported", "Proof"], mechanism: ["supported", "Mechanism"], analogy: ["partial", "Analogy only"], none: ["unsupported", "No reason given"] };',
     'const RSN = { proof: ["supported", "证明"], mechanism: ["supported", "机制"], analogy: ["partial", "仅有类比"], none: ["unsupported", "未给出理由"] };'),
    ('const RBS = { repeats: ["supported", "Repeats"], single: ["partial", "One setting"], unclear: ["untested", "Unclear"] };',
     'const RBS = { repeats: ["supported", "可复现"], single: ["partial", "单一设定"], unclear: ["untested", "不明确"] };'),
    ('const LEVER_TXT = { "cost-assumption": "Chosen cost or price ratio", "metric-trained": "Trained on the metric", "unequal-tuning": "Unequal tuning", "mismatched-setup": "Mismatched setup", "small-or-saturated-benchmark": "Small or saturated benchmark", "missing-novelty-ablation": "No ablation of the new idea", other: "Other" };',
     'const LEVER_TXT = { "cost-assumption": "人为选定的成本或价格比", "metric-trained": "针对评测指标训练", "unequal-tuning": "调参力度不对等", "mismatched-setup": "实验设置不一致", "small-or-saturated-benchmark": "基准过小或已饱和", "missing-novelty-ablation": "缺少对新想法的消融", other: "其他" };'),
    ('return "Too recent for later work to have reacted.";', 'return "发表太近，后续工作还来不及反应。";'),
    ('parts.push(`built on by ${r.adopted_by.map(chip).join(" ")}`);', 'parts.push(`${r.adopted_by.map(chip).join(" ")} 在其上继续发展`);'),
    ('parts.push(`challenged by ${r.challenged_by.map(chip).join(" ")}`);', 'parts.push(`${r.challenged_by.map(chip).join(" ")} 对其提出挑战`);'),
    ('parts.push(`${Math.round(r.builds_on_share * 100)}% of sampled citers build on it`);',
     'parts.push(`抽样的施引文献中有 ${Math.round(r.builds_on_share * 100)}% 在其上构建`);'),
    ('return (parts.length ? parts.join("; ") + "." : "No later work on this map builds on it or challenges it.") + (r.robust ? " That counts as robust." : "");',
     'return (parts.length ? parts.join("；") + "。" : "图上没有后续工作在其上构建或对其提出挑战。") + (r.robust ? "这算作稳健。" : "");'),
    ('return `<h3>Gates</h3>', 'return `<h3>关卡</h3>'),
    ('<span class="small">dashed on the map</span>', '<span class="small">图上以虚线标出</span>'),
    ('<span class="small">read from the ${esc(x.basis)} only</span>', '<span class="small">仅依据${esc(GBASIS_ZH[x.basis] || x.basis)}判断</span>'),
    ('${x.fold ? "Why it is folded" : "Why it would be folded"}', '${x.fold ? "为何折叠" : "为何本应折叠"}'),
    ('<dt>0 · Claim vs delivery</dt>', '<dt>0 · 主张与兑现</dt>'),
    ('<b>Claims:</b> ', '<b>主张：</b>'),
    ('<dt>1 · Reason</dt>', '<dt>1 · 理由</dt>'),
    ('>Would not help when: ${esc(x.fails_when)}</span>', '>在这些情况下无效：${esc(x.fails_when)}</span>'),
    ('<dt>2 · Robustness</dt>', '<dt>2 · 稳健性</dt>'),
    ('</b>${l.note ? ": " + esc(l.note) : ""}</li>', '</b>${l.note ? "：" + esc(l.note) : ""}</li>'),
    ('<dt>3 · Field reaction</dt>', '<dt>3 · 领域反应</dt>'),
    ('<div><dt>Taste</dt>', '<div><dt>品味</dt>'),
    ('<div><dt>Check next</dt>', '<div><dt>下一步核查</dt>'),
    # deeper checks: tags, row names, table tags and where the text came from
    ('const CK_TXT = { yes: "Yes", no: "No", unclear: "Unclear", unchecked: "Not checked", released: "Released", promised: "Promised", none: "None", unknown: "Unknown" };',
     'const CK_TXT = { yes: "是", no: "否", unclear: "不明确", unchecked: "未核查", released: "已公开", promised: "承诺公开", none: "没有", unknown: "不详" };'),
    ('const CK_ROW = { numbers: "Numbers match the tables", fair_baselines: "Fair baselines", novelty_ablation: "Ablation that removes the new idea", code: "Code", fails: "Says when it fails" };',
     'const CK_ROW = { numbers: "数字与表格一致", fair_baselines: "基线公平", novelty_ablation: "有去掉新想法的消融", code: "代码", fails: "说明了何时失效" };'),
    ('const CK_BAD = [["novelty_ablation", "no", "no ablation"], ["fair_baselines", "no", "unfair baselines"], ["numbers", "mismatch", "numbers differ"], ["code", "none", "no code"]];',
     'const CK_BAD = [["novelty_ablation", "no", "缺消融"], ["fair_baselines", "no", "基线不公平"], ["numbers", "mismatch", "数字不符"], ["code", "none", "无代码"]];'),
    ('const SOURCE_LABEL = {};',
     'const SOURCE_LABEL = { "arXiv HTML": "arXiv 网页版", "arXiv PDF": "arXiv PDF", "local file": "本地文件", "open-access copy (Unpaywall)": "开放获取副本（Unpaywall）", "abstract only": "仅摘要" };'),
    ('<span class="small">Text read: ${', '<span class="small">所读文本：${'),
    ('<div><dt>Checks</dt>', '<div><dt>核查</dt>'),
    ('${tasteTxt ? " " + esc(tasteTxt) + "." : ""}', '${tasteTxt ? esc(tasteTxt) + "。" : ""}'),
    ('`<span class="tm">Side branches of ${esc(tById[l].name)} · click to ${state.allFolded || state.unfold.has(l) ? "fold them back" : "show them"}</span>`',
     '`<span class="tm">“${esc(tById[l].name)}”线的旁支 · 点击${state.allFolded || state.unfold.has(l) ? "收起" : "显示"}</span>`'),
    ('pl(gated.length, "work gated", "works gated")', 'pl(gated.length, "项工作经过关卡检查", "项工作经过关卡检查")'),
    ('pl(by("treasure").length, "treasure candidate", "treasure candidates")', 'pl(by("treasure").length, "项宝藏候选", "项宝藏候选")'),
    ('`${folded.length} folded`', '`${folded.length} 项被折叠`'),
    ('"A stated reason, not yet verified beyond one setting, and close to what you said you want to read."',
     '"给出了理由，但尚未在单一设定之外得到验证，且贴近你说想读的内容。"'),
    ('"A stated reason, not yet verified beyond one setting. Add a taste profile to keep only the ones close to your interests."',
     '"给出了理由，但尚未在单一设定之外得到验证。添加一份品味档案，就能只保留贴近你兴趣的工作。"'),
    ('`<span class="scores">taste ${score2(n.gates.attractiveness)} · ', '`<span class="scores">品味 ${score2(n.gates.attractiveness)} · '),
    ('>None on this map.</p>', '>此图上没有。</p>'),
    ('<h3>Problems reopened<span class="scores">', '<h3>被重新打开的问题<span class="scores">'),
    ('<p>Their only solutions on this map did not deliver.</p>', '<p>它们在此图上仅有的解决方案都未能兑现。</p>'),
    ('<span class="scores">claimed by ${(p.claimed_by || []).map(chip).join(" ")}</span>',
     '<span class="scores">${(p.claimed_by || []).map(chip).join(" ")} 声称解决</span>'),
    ('<span class="scores">${g.items.length} folded</span>', '<span class="scores">${g.items.length} 项被折叠</span>'),
    ('"The experiments do not show what the title claims. The problems they claimed stay open."',
     '"实验没有证明标题所声称的内容。它们声称解决的问题仍未解决。"'),
    ('"Delivered, but with neither a reason nor evidence that repeats beyond one setting."',
     '"已兑现，但既没有给出理由，也没有在单一设定之外可复现的证据。"'),
    ('`<div class="fl"><h3>Nothing folded</h3><p>Every gated work delivered its claim with a reason or robust evidence, or was read from too little text to fold.</p></div>`',
     '`<div class="fl"><h3>没有被折叠的工作</h3><p>每项经过关卡检查的工作都兑现了主张，并给出了理由或稳健证据；或者可读的文本太少，不足以折叠。</p></div>`'),
    ('`All ${all.length} gated works`', '`全部 ${all.length} 项经过关卡检查的工作`'),
    ('<div class="wsub">dashed on the map</div>', '<div class="wsub">图上以虚线标出</div>'),
    ('+= " Works that did not pass the gates are drawn dashed, in place.";',
     '+= "未通过关卡的工作在原位以虚线显示。";'),
    ('<span>${folded.length} did not pass the gates</span>', '<span>${folded.length} 项未通过关卡</span>'),
    ('+= " A dashed ring marks a treasure candidate.";', '+= "虚线圆环标出宝藏候选。";'),
    ('</svg>Treasure candidate</span>', '</svg>宝藏候选</span>'),

    # ---------- does it hold up ----------
    ('.length} flagged by the audit`', '.length} 项被审计标记`'),
    ('pl(dis.length, "disagreement", "disagreements")', 'pl(dis.length, "处分歧", "处分歧")'),
    ('<h3>Disagreements<span class="scores">', '<h3>分歧<span class="scores">'),
    ('<p>Here the reading of the text and the blind score point different ways.</p>',
     '<p>在这些工作上，原文检查和盲评的结论不一致。</p>'),

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

    ('<p>Each of the ${TC.n} papers you rated was scored by your taste profile with its own rating taken out. The scores put ${TC.agree} of ${TC.pairs} pairs in your order, and are ${score2(TC.gap)} away from your rating on average.</p>',
     '<p>你打过分的 ${TC.n} 篇论文，每篇都在去掉它自己的评分后，由你的口味设置重新打分。结果在 ${TC.pairs} 对里有 ${TC.agree} 对和你的排序一致，平均和你的打分相差 ${score2(TC.gap)}。</p>'),
    ('<p>Rate at least 3 papers that can be found to see how well your taste profile predicts you. So far: ${TC.papers.length}.</p>',
     '<p>至少给 3 篇能找到的论文打分，才能看口味设置猜得准不准。目前：${TC.papers.length} 篇。</p>'),
    ('`<div class="calib"><h3>How well your taste profile predicts you</h3>${tcHead}<table><thead><tr><th>Paper you rated</th><th class="num">Yours</th><th class="num">Predicted</th></tr></thead>',
     '`<div class="calib"><h3>口味设置猜得准不准</h3>${tcHead}<table><thead><tr><th>你打过分的论文</th><th class="num">你的分</th><th class="num">预测</th></tr></thead>'),
    # ---------- your scale ----------
    ('${a.your_scale != null ? bar("On your scale", a.your_scale, true) : ""}', '${a.your_scale != null ? bar("按你的尺度", a.your_scale, true) : ""}'),
    ('<div class="small"> · yours ${score2(a.your_scale)}</div>', '<div class="small"> · 你的尺度 ${score2(a.your_scale)}</div>'),
    ('<p>Calibrated on ${used.length} papers you rated. Their blind scores and your ratings put ${CAL.agree} of ${CAL.pairs} pairs in the same order. Each work also shows its blind score on your scale. The blind score itself is unchanged.</p>',
     '<p>按你打过分的 ${used.length} 篇论文校准。它们的盲评分和你的打分，在 ${CAL.pairs} 对里有 ${CAL.agree} 对排序一致。每篇工作另外显示换算到你的尺度上的分数，盲评分本身不变。</p>'),
    ('<p>You rated ${used.length} papers that could be scored. That is too few, or their blind scores do not rise with your ratings (${CAL.agree} of ${CAL.pairs} pairs in the same order). So no work is put on your scale.</p>',
     '<p>你打过分、能参与评分的论文有 ${used.length} 篇。数量太少，或者盲评分没有随你的打分升高（${CAL.pairs} 对里 ${CAL.agree} 对排序一致），所以不换算到你的尺度。</p>'),
    ('` <span class="small">not found</span>`', '` <span class="small">没找到</span>`'),
    ('`<h3>On your scale</h3>${head}<table><thead><tr><th>Paper you rated</th><th class="num">Yours</th><th class="num">Blind</th></tr></thead>',
     '`<h3>按你的尺度</h3>${head}<table><thead><tr><th>你打过分的论文</th><th class="num">你的分</th><th class="num">盲评</th></tr></thead>'),

    # ---------- what's next ----------
    ('<h3>Active now${', '<h3>正在进行${'),
    ('<span class="scores">Last ${esc(o.window_months)} months</span>', '<span class="scores">近 ${esc(o.window_months)} 个月</span>'),
    ('<h3>Open questions<span class="scores">', '<h3>未解的问题<span class="scores">'),
    ('<b>Closest attempts:</b> ', '<b>最接近的尝试：</b>'),
    ('<b>Would settle it:</b> ', '<b>能定论的实验：</b>'),
    ('<h3>Shared assumptions<span class="scores">', '<h3>共同的假设<span class="scores">'),
    ('<b>If it is wrong:</b> ', '<b>如果它不成立：</b>'),
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
