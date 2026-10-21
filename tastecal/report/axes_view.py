"""A standalone page for the taste calibration (taste/axes.py), in tabs: an overview with the chart the fit aims at, every
paper in one table, the other measures of attention, the clauses with their weights, and how the fit got there.
Click a paper anywhere (a point, a row) to see its levels and why. The page works without its script too: every
tab is then shown one after another."""
from __future__ import annotations

import html
import json
import math
import re
from typing import Dict, List, Optional

from tastecal.taste.axes import FIELD_NEW, views as compute_views

TOP, BOTTOM = 0.6, 0.4     # along y = x: both sides above TOP is "both high", both below BOTTOM "both low"
W, PAD = 640, 56
ZONES = ("gem", "hyped", "good", "junk")
ZONE_COL = {"gem": "var(--focus)", "hyped": "var(--warn)", "good": "var(--ok)", "junk": "var(--muted)", "mid": "var(--hair)",
            "rated": "var(--ink)"}

T = {
    "en": {
        "title": "Taste calibration", "sub": "Your scores are a hard constraint: the clauses must reproduce them. Within "
        "that, the scoring is fitted so that every other paper comes as close to y = x as it can.",
        "tabs": {"overview": "Overview", "papers": "Papers", "views": "Attention measures", "clauses": "Clauses",
                 "process": "How it was fitted"},
        "st_fit": "Your scores reproduced", "st_fit_v": "mean miss {mae:.2f} · worst {mx:.2f}",
        "st_conf": "Trust in the result", "st_conf_v": "the larger, the less to trust",
        "conf_d": "Trust in the result: ±{rms:.2f}, how far the clauses miss your own scores (root mean square over your {n} rated papers; worst {worst:.2f}). The larger it is, the less to trust the result. It is added to every paper's taste-score bar, so the poorer the fit, the further a paper must be from y = x to count as clearly off.",
        "st_n": "Papers compared", "st_n_v": "{n} · last {y} years · {r} at random", "st_n_v0": "{n} · {r} at random",
        "zone": {"gem": "To your taste, little attention", "hyped": "Much attention, not to your taste", "good": "To your taste, much attention", "junk": "Not to your taste, little attention", "mid": "Taste and attention even", "rated": "You rated it"},
        "zone_d": {"gem": "The taste score is clearly above the attention: overlooked good work, or too new to be noticed.", "hyped": "The attention is clearly above the taste score: not to your taste, or carried by fame. Citations include use as a baseline and criticism: worth checking, not a verdict.", "good": "Near y = x, taste score and attention both above {top}.", "junk": "Near y = x, taste score and attention both below {bottom}."},
        "v_title": {"cumulative": "Taste score against the field's attention (all citations)", "recent": "Taste score against recent attention (citations over the last two years)", "influential": "Taste score against influential citations (later work that builds on it)", "stars": "Taste score against code attention (GitHub stars a year)"},
        "m_names": {"cumulative": "All citations", "recent": "Recent", "influential": "Influential", "stars": "Stars"},
        "target": "what the fit aims at",
        "cap_main": "Up: the taste score your clauses give. Across: the field's attention, put on the same 0 to 1 scale (how, under How to read it below). Near y = x the two agree; in the shade a paper is clearly off: top left to your taste but little attended, bottom right much attended but not to your taste. Click a paper for its details.",
        "cap_other": "The same taste scores against another measure of attention. For comparison only: the fit does not aim at it.",
        "how": "How to read it",
        "how_main": ["How attention is put on the same scale: a paper's citation rank among these papers is read as the taste score at the same rank, so y = x means the field ranks a paper where your taste does.", "Up along y = x: to your taste and much attended; down along it: neither. Top left: to your taste, little attention. Bottom right: much attention, not to your taste.", "Diamonds are your rated papers, on y = x at your own score (their attention is not used), with a tick to the taste score the clauses give them.", "Clearly off means further from y = x than max(0.15, twice the noise) plus the paper's two bars; a paper under a year old is never counted (its citations say too little yet) and is drawn dashed. The bars show on hover or with the switch: the vertical one is the taste score's uncertainty, the horizontal one the attention's (wider the newer the paper).", "How every paper is scored: a weighted sum of the clause levels. The weights are fitted so that the papers you have not rated come as close to y = x as possible, while each of your rated papers stays within {tol} of your score (or within step 1's miss, where that was larger) and no pair you scored 0.3 apart changes order (one step 1 already had the wrong way round may not get worse)."],
        "how_log0": "How attention is put on 0 to 1: citations a year, on a log scale, through the normal distribution. The median of these papers ({median} a year) is the middle; below it the spread is these papers' own, so the little-cited new ones are spread out rather than pressed to 0; above it {anchor} is +3 sigma, so nothing of the field reaches the landmark. Papers without a citation count have no attention and are not drawn here.",
        "how_log1": "How attention is put on 0 to 1: citations a year, on a log scale, through the normal distribution, with the median of these papers ({median} a year) in the middle, no citation at -3 sigma and {anchor} at +3 sigma. Papers without a citation count have no attention and are not drawn here.",
        "how_log00": "How attention is put on 0 to 1: citations a year, on a log scale, through the normal distribution, with no citation at -3 sigma and {anchor} at +3 sigma. Papers without a citation count have no attention and are not drawn here.",
        "vx": "field attention (same scale) →", "vy": "taste score (your clauses) →",
        "vx_log": "field attention (citations a year, normal scale) →",
        "labels": "Names", "lab_key": "clearly off and yours", "lab_all": "all", "lab_none": "hide all", "bars": "Error bars",
        "lg_map": "a paper on the map (colour: its thread)", "lg_tp": "turning point", "lg_rand": "drawn at random", "lg_seed": "the seed paper",
        "lg_off": "filled: clearly off", "lg_young": "dashed: under a year old", "lg_rated": "you rated it: on y = x at your own score",
        "none": "None.",
        "f": {"all": "All", "rated": "Rated by you", "off": "Clearly off", "random": "At random"}, "search": "Search titles",
        "c_paper": "Paper", "c_date": "Year", "c_score": "Taste score", "c_att": "Attention", "c_gap": "Gap", "c_zone": "Where", "c_levels": "Levels",
        "gap_d": "taste score minus attention", "shown": "{n} shown",
        "kind": {"rated": "rated by you", "map": "on the map", "random": "drawn at random"},
        "d_yours": "Your score (hard constraint)", "d_fit": "The clauses give", "d_reason": "Your reason",
        "d_score": "Taste score (your clauses)", "d_att": "Attention", "d_levels": "Levels and why",
        "d_not_higher": "Why not higher", "d_drivers": "Most of the score comes from", "d_thread": "Thread",
        "d_recheck": "Re-measured next to {against}; changed: {changed}", "d_recheck0": "Re-measured next to {against}; nothing changed",
        "d_att_none": "Your own score: the field's attention is not used for it.", "close": "Close", "prev": "Previous", "next": "Next",
        "pct_txt": "cited more than {p:.0f}% of works of its field and year", "pct_run": "attention percentile in this run {p:.0f}%",
        "cites": "{n} citations", "months": "{m} months old", "recent_txt": "{r:.1f} citations a month lately",
        "rate_txt": "{r:.1f} citations a year",
        "infl_txt": "{r:.1f} influential citations a year", "stars_txt": "{r:.0f} GitHub stars a year",
        "flag_t": "Under which measures it is clearly off", "flag_d": "Papers clearly off y = x under at least one measure of attention.",
        "cl_d": "Each clause is a step function from 0 to 5, every level a condition that can be checked in the paper. The "
                "share is its weight in the score, fitted so that the papers you have not rated come as close to y = x as "
                "your scores allow (starting from every clause counting the same); the range is what the share becomes "
                "when one of your rated papers is left out.",
        "cl_eq": "Each clause is a step function from 0 to 5, every level a condition that can be checked in the paper. Every "
                 "clause counts the same: the score is the average level, put on your scale by a line (only its slope and "
                 "offset are fitted). All the fitting is in the wording of the clauses.",
        "from": {"default": "general", "reasons": "your reasons", "learned": "learned", "field": "from the field"},
        "share": "share", "range": "range {lo:.0f}–{hi:.0f}%", "how_note": "How to read it", "how_field": " (from the field)",
        "p_fit": "How well your scores are reproduced",
        "p_start": "This fit started from the clauses saved on {d} and went on from there.",
        "p_start0": "This fit started from the general clauses, rewritten from your reasons.",
        "p_refit": "Recomputed with --refit on {d}: the attention scale, the weights, the scores and the charts follow the current settings; the clauses and every paper's levels are those of the original run (no model call).",
        "p_fit_d": "Your scores are a hard constraint; this only checks that the clauses reproduce them. While a paper is "
                   "off by more than {tol:.2f}, the loop keeps changing the clauses. When every paper is then brought "
                   "towards y = x, none of yours may end further than {tol:.2f} from your score (or than step 1's miss, "
                   "where that was larger).",
        "c_yours": "yours", "c_repro": "clauses give", "c_diff": "miss",
        "p_stats": "Pairs 0.3+ apart in the wrong order: {order} · measuring noise ±{noise:.2f} (the same papers measured "
                   "again in another order) · leave-one-out {loo:.2f} (how robust the clauses are: each paper scored by "
                   "clauses fitted without it)",
        "p_field": "Every paper towards y = x",
        "field_q": "{papers} papers with attention took part, each weighted by how reliable its attention is. Objective: "
                   "their distance from y = x, straight up or down. Constraint: each of your rated papers within {tol:.2f} "
                   "of your score (or within step 1's miss, where that was larger), and no pair you scored 0.3 apart out "
                   "of order (one step 1 already had the wrong way round may not get worse). Distance from y = x (root "
                   "mean square): {d0:.2f} with every clause counting the same → {d1:.2f} with the weights fitted. The "
                   "field could also rewrite a clause, add a reading note, or add up to {new} clauses of its own: one half "
                   "of the papers proposes, the other checks, each half scored by weights fitted without it, and a change "
                   "is kept only if the checking half comes closer and the proposing half no further (checking half: "
                   "{b0:.2f} → {b1:.2f}). Your rated "
                   "papers, mean miss: {m0:.2f} → {m1:.2f}. Share of the score from the field's clauses: {share:.0%}.",
        "field_q0": "{papers} papers with attention took part, each weighted by how reliable its attention is. The weights "
                    "of your clauses came from your scores alone; the field could only rewrite a clause, add a reading note, "
                    "or add up to {new} clauses of its own. Checking half, mean rank distance from y = x: {b0:.2f} → {b1:.2f}. "
                    "Your rated papers, mean miss: {m0:.2f} → {m1:.2f}. Share of the score from the field's clauses: {share:.0%}.",
        "field_fb": " After your papers were read a second time, the fitted weights could no longer meet your scores, so every clause counts the same, as in step 1.",
        "field_skip": "Not fitted to the field: {why}.",
        "p_hist": "What the loop changed", "acc": "kept", "rej": "not kept", "ph_field": "field", "ph_yours": "your scores",
        "round": "round {n}", "reason": "reasoning", "h_more": "In full",
        "notes": {"no general change proposed": "no general change proposed", "repeated": "repeated"},
        "how_tol": "{tol:.1f}",
        "p_bias": "The map grows along citations, so it leans to cited work and the little-attended side is thin by "
                  "construction. {n} papers were drawn at random from recent work citing the map's papers and read in "
                  "full to compare against (grey).",
        "p_bias0": "The map grows along citations, so it leans to cited work and the little-attended side is thin by construction.",
        "p_others": "Not scored: tools, datasets, surveys, benchmarks and concept works",
        "types": {"tool": "tool", "dataset": "dataset", "survey": "survey", "benchmark": "benchmark",
                  "concept": "concept work (definitions, taxonomy, terminology)"},
        "p_older": "Not compared: published more than {y} years ago", "p_skipped": "Rated but not used",
        "p_unread": "Not scored: only an abstract or a summary could be read",
        "p_unread_d": "Put each PDF in the papers folder under the name shown, then run gates on this run's graph.json and fit again.",
        "why": {"no full text": "no full text found", "not found": "not found on Semantic Scholar",
                "no full-text reading of it in this run": "no full-text reading", "not a method paper": "not a method paper"},
        "file": "put its PDF in the papers folder as", "p_suggest": "Rate these next",
        "p_suggest_d": "Where your clauses are least sure, and the two ends.", "noview": "Too few papers with attention to draw this chart.",
        "p_dist": "Distance from y = x", "p_eq": "every clause the same", "p_fitw": "weights fitted",
        "p_miss": "Your rated papers, mean miss"
    },
    "zh": {
        "title": "审美校准", "sub": "你给的分是硬约束：条款必须复现它们。在此前提下，打分方式拟合到让其余文章尽量贴近 y = x。",
        "tabs": {"overview": "总览", "papers": "文章", "views": "关注度对比", "clauses": "条款", "process": "过程"},
        "st_fit": "你的打分复现", "st_fit_v": "平均差 {mae:.2f} · 最大 {mx:.2f}",
        "st_conf": "结果可信度", "st_conf_v": "绝对值越大越不准",
        "conf_d": "结果可信度 ±{rms:.2f}：条款给出的分与你的打分之间的均方根偏差（共 {n} 篇，最大 {worst:.2f}），绝对值越大越不准。这个偏差已计入每篇文章审美分的误差条，所以偏差越大，文章要离 y = x 越远才算明显偏离。",
        "st_n": "比较的文章", "st_n_v": "{n} 篇 · 近 {y} 年 · 随机 {r} 篇", "st_n_v0": "{n} 篇 · 随机 {r} 篇",
        "zone": {"gem": "合你审美、关注少", "hyped": "关注多、不合你审美", "good": "合你审美、关注也多", "junk": "不合你审美、关注也少", "mid": "审美和关注相当", "rated": "你打过分的"},
        "zone_d": {"gem": "审美分明显高于关注度：可能是被忽视的好文章，也可能太新，还没被注意。", "hyped": "关注度明显高于审美分：可能不合你的审美，也可能靠名气撑起来。引用也包括被当基线和被批评，所以是值得核对的候选，不是结论。", "good": "落在 y = x 附近，审美分和关注度都在 {top} 以上。", "junk": "落在 y = x 附近，审美分和关注度都在 {bottom} 以下。"},
        "v_title": {"cumulative": "审美分 vs 领域关注度（累计引用）", "recent": "审美分 vs 近期关注（最近两年的引用速度）", "influential": "审美分 vs 有影响的引用（后续工作真在用它）", "stars": "审美分 vs 代码关注（GitHub 每年 star）"},
        "m_names": {"cumulative": "累计引用", "recent": "近期引用", "influential": "有影响的引用", "stars": "代码 star"},
        "target": "优化目标",
        "cap_main": "纵轴是按你的条款给的审美分，横轴是领域关注度，换算到同一把 0–1 的尺上（怎么换算见下方“读法”）。落在 y = x 附近，两者相当；阴影里是明显偏离的：左上合你审美但关注少，右下关注多但不合你审美。点一篇看详情。",
        "cap_other": "同样的审美分，换一种关注度。只作对照，优化不以它为目标。",
        "how": "读法",
        "how_main": ["关注度怎么换算：一篇文章的引用在这些文章里排第几，就取同一名次的审美分。所以 y = x 表示领域给它的名次和你的审美一致。", "沿 y = x 往右上，合你审美、关注也多；往左下，不合你审美、关注也少。左上：合你审美、关注少。右下：关注多、不合你审美。", "菱形是你打过分的文章，放在 y = x 上你给的分处（不看它们的关注度），短竖线指到条款给出的审美分。", "明显偏离的标准：离 y = x 超过 max(0.15, 两倍噪声)，再加上它自己的两条误差线；发表不到一年的文章不算（引用还说明不了什么），画成虚线。误差线悬停或打开开关时显示：竖的是审美分的不确定度，横的是关注度的不确定度（文章越新越宽）。", "每篇文章的审美分是各条款等级的加权和。权重的拟合目标是让你没打分的文章尽量贴近 y = x；约束是你打过分的每篇文章与你的分相差不超过 {tol}（第一步就超过的，不超过第一步的差），分差 0.3 以上的两篇顺序不颠倒（第一步就颠倒的不能更差）。"],
        "how_log0": "关注度怎么换算：每年引用数取对数，按正态分布换算到 0–1。这批文章的中位数（每年 {median} 次）在正中；中位数以下按这批文章自身的离散度换算，引用少的新文章会散开，不会挤在 0 附近；中位数以上 {anchor} 记为 +3σ，领域里的文章都到不了它的位置。没有引用数的文章没有关注度，不画在这张图上。",
        "how_log1": "关注度怎么换算：每年引用数取对数，按正态分布换算到 0–1：这批文章的中位数（每年 {median} 次）在正中，0 次引用记为 −3σ，{anchor} 记为 +3σ。没有引用数的文章没有关注度，不画在这张图上。",
        "how_log00": "关注度怎么换算：每年引用数取对数，0 次引用记为 −3σ，{anchor} 记为 +3σ，按正态分布换算到 0–1。没有引用数的文章没有关注度，不画在这张图上。",
        "vx": "领域关注度（换算到同一把尺）→", "vy": "审美分（按你的条款）→",
        "vx_log": "领域关注度（每年引用数，按正态分布换算）→",
        "labels": "名称", "lab_key": "偏离的和你打过分的", "lab_all": "全部", "lab_none": "隐藏全部", "bars": "误差线",
        "lg_map": "图上的文章（颜色 = 所在的线）", "lg_tp": "转折点", "lg_rand": "随机抽的", "lg_seed": "种子文章", "lg_off": "实心：明显偏离",
        "lg_young": "虚线：不满一年", "lg_rated": "你打过分的：放在 y = x 上你给的分处",
        "none": "无。",
        "f": {"all": "全部", "rated": "你打过分的", "off": "明显偏离", "random": "随机抽的"}, "search": "搜索标题",
        "c_paper": "文章", "c_date": "年份", "c_score": "审美分", "c_att": "关注度", "c_gap": "偏离", "c_zone": "位置", "c_levels": "条款等级",
        "gap_d": "审美分减关注度", "shown": "显示 {n} 篇",
        "kind": {"rated": "你打过分的", "map": "图上的文章", "random": "随机抽的"},
        "d_yours": "你的分（硬约束）", "d_fit": "条款给出", "d_reason": "你的理由", "d_score": "审美分（按你的条款）",
        "d_att": "关注度", "d_levels": "条款等级和依据", "d_not_higher": "为什么不更高", "d_drivers": "分数主要来自",
        "d_thread": "所在的线", "d_recheck": "与 {against} 对照复核，改了：{changed}", "d_recheck0": "与 {against} 对照复核，没有改动",
        "d_att_none": "这是你自己的分，不看领域关注度。", "close": "关闭", "prev": "上一篇", "next": "下一篇",
        "pct_txt": "引用超过同领域同年份 {p:.0f}% 的文章", "pct_run": "本次运行里的关注度分位 {p:.0f}%",
        "cites": "{n} 次引用", "months": "发表 {m} 个月", "recent_txt": "近两年每月 {r:.1f} 次引用",
        "rate_txt": "每年 {r:.1f} 次引用",
        "infl_txt": "每年 {r:.1f} 次有影响的引用", "stars_txt": "每年 {r:.0f} 个 GitHub star",
        "flag_t": "在哪种关注度下明显偏离", "flag_d": "至少在一种关注度下明显偏离 y = x 的文章。",
        "cl_d": "每个条款是 0 到 5 级的台阶，每一级都是能在文章里核对的条件。占比是它在总分里的权重：从所有条款等权出发，在满足你打分的前提下，拟合到让没打分的文章尽量贴近 y = x。范围是每次去掉你打过分的一篇文章、重新拟合后占比的变化范围。",
        "cl_eq": "每个条款是 0 到 5 级的台阶，每一级都是能在文章里核对的条件。所有条款等权：分数是各条款等级的平均，再用一条直线换到你的分数尺上（只拟合斜率和截距）。优化全在条款的写法上。",
        "from": {"default": "通用", "reasons": "来自你的理由", "learned": "循环中学到", "field": "来自领域"},
        "share": "占比", "range": "范围 {lo:.0f}–{hi:.0f}%", "how_note": "读法", "how_field": "（来自领域）",
        "p_fit": "你的打分复现得怎样",
        "p_start": "这次从 {d} 保存的条款开始，在它的基础上继续改。",
        "p_start0": "这次从通用条款开始，按你的理由改写。",
        "p_refit": "这一页由 --refit 于 {d} 重算：横轴刻度、权重、审美分和图按现在的设置重算；条款和每篇文章的等级沿用原来那次运行，没有调用模型。",
        "p_fit_d": "你给的分是硬约束，这里只检查条款有没有复现它们。只要有文章差超过 {tol:.2f}，循环就继续改条款。之后让所有文章靠近 y = x 时，你打过分的每篇与你的分相差也不能超过 {tol:.2f}（第一步就超过的，不能超过第一步的差）。",
        "c_yours": "你的分", "c_repro": "条款给出", "c_diff": "差",
        "p_stats": "分差 0.3 以上却顺序反了的对数：{order} · 测量噪声 ±{noise:.2f}（同样的文章换个顺序再测）· 留一法 {loo:.2f}（每篇用去掉它之后定出的条款来算，只说明条款稳不稳）",
        "p_field": "所有文章向 y = x 靠拢",
        "field_q": "{papers} 篇有关注度的文章参与，按关注度的可靠程度加权。目标：它们离 y = x 的竖直距离。约束：你打过分的每篇文章与你的分相差不超过 {tol:.2f}（第一步就超过的，不超过第一步的差），分差 0.3 以上的两篇顺序不颠倒（第一步就颠倒的不能更差）。离 y = x 的距离（均方根）：所有条款等权时 {d0:.2f} → 拟合权重后 {d1:.2f}。领域还可以改写条款、加读法，或加最多 {new} 个它自己的条款：一半文章提出修改，另一半检验，两半各用不含自己拟合出的权重打分；检验那一半更近、提出那一半不变远，才保留（检验那一半：{b0:.2f} → {b1:.2f}）。你打过分的文章与你的分平均差：{m0:.2f} → {m1:.2f}。总分里来自领域条款的占比：{share:.0%}。",
        "field_q0": "{papers} 篇有关注度的文章参与，按关注度的可靠程度加权。当时你的条款的权重只由你的打分决定；领域只能改写条款、加读法，或加最多 {new} 个它自己的条款。检验那一半离 y = x 的平均名次差：{b0:.2f} → {b1:.2f}。你打过分的文章与你的分平均差：{m0:.2f} → {m1:.2f}。总分里来自领域条款的占比：{share:.0%}。",
        "field_fb": "你的文章第二遍读完后，拟合出的权重已满足不了你的打分，所以改回所有条款等权，和第一步一样。",
        "field_skip": "没有向领域靠拢：{why}。",
        "p_hist": "循环做了哪些修改", "acc": "保留", "rej": "未采纳", "ph_field": "领域", "ph_yours": "你的打分",
        "round": "第 {n} 轮", "reason": "理由", "h_more": "全文",
        "notes": {"no general change proposed": "没有提出一般性的修改", "repeated": "重复的修改",
                  "your scores could no longer be met": "会让你的打分不再满足", "the field may not take out a clause": "领域不能去掉条款",
                  "too many indicators or unusable": "条款太多或无法使用", "the field may add at most 2 indicators": "领域最多只能加 2 个条款",
                  "did not help on the first papers tried": "在先试的几篇上没有帮助"},
        "how_tol": "{tol:.1f}",
        "p_bias": "图上的文章沿引用关系扩展而来，偏向被引用多的工作，“关注少”那一侧天然偏空。为此从引用这些文章的近期工作里随机抽了 {n} 篇，读全文一起比较（灰色）。",
        "p_bias0": "图上的文章沿引用关系扩展而来，偏向被引用多的工作，“关注少”那一侧天然偏空。",
        "p_others": "不打分：工具、数据集、综述、基准、概念类文章",
        "types": {"tool": "工具", "dataset": "数据集", "survey": "综述", "benchmark": "基准", "concept": "概念、术语类"},
        "p_older": "不在比较范围：{y} 年以前发表的", "p_skipped": "打了分但没用上",
        "p_unread": "不打分：只读到了摘要",
        "p_unread_d": "把 PDF 按所示文件名放进 papers 文件夹，再对这个 run 的 graph.json 运行 gates，然后重新 fit。",
        "why": {"no full text": "找不到全文", "not found": "Semantic Scholar 上找不到",
                "no full-text reading of it in this run": "没有全文阅读", "not a method paper": "不是方法论文"},
        "file": "把 PDF 放进 papers 文件夹，命名为", "p_suggest": "建议接下来给这几篇打分",
        "p_suggest_d": "条款最拿不准的几篇，加上两端的。", "noview": "有关注度的文章太少，画不了这张图。",
        "p_dist": "离 y = x 的距离", "p_eq": "条款等权", "p_fitw": "拟合权重后",
        "p_miss": "你打过分的文章平均差"
    },
}


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _short(name: str, n: int = 24) -> str:
    return name if len(name) <= n else name[:n - 1].rstrip() + "…"


def _name(r: dict, n: int = 200) -> str:
    """A paper's display name: its short name on the map, else its title up to the colon."""
    return _short(r.get("short") or re.split(r"[:：]", r.get("title") or "")[0].strip() or r.get("title") or "", n)


def _txt(s) -> str:
    """Model-written text, with the reader's taste called 审美 in Chinese."""
    return str(s or "").replace("品味", "审美")


def place_labels(labels: List[tuple], avoid: List[tuple] = (), width_px: float = W) -> List[str]:
    """Right of the mark, else left of it, else a line lower (up to six), never over a placed label or a box in
    `avoid` (other marks). labels: (cx, cy, r, text, cls); a label whose cls has "more" is shown only on request."""
    placed, out = list(avoid), []
    hit = lambda b: any(b[0] < q[2] and q[0] < b[2] and b[1] < q[3] and q[1] < b[3] for q in placed)  # noqa: E731
    for cx, cy, r, text, cls in labels:
        width = sum(12 if ord(ch) > 0x2e80 else 6.6 for ch in text) + 4
        sides = [s_ for s_ in (True, False) if (cx + r + 4 + width <= width_px - 6 if s_ else cx - r - 4 - width >= 6)] or [False]
        right, y, found = sides[0], cy + 4, False
        for step in range(6):
            for s_ in sides:
                x0, yy = (cx + r + 4 if s_ else cx - r - 4 - width), cy + 4 + 13 * step
                if not hit((x0, yy - 10, x0 + width, yy + 3)):
                    right, y, found = s_, yy, True
                    break
            if found:
                break
        x0 = cx + r + 4 if right else cx - r - 4 - width
        placed.append((x0, y - 10, x0 + width, y + 3))
        lead = "lead more" if "more" in cls.split() else "lead key"
        if y != cy + 4:
            out.append(f'<line class="{lead}" x1="{cx:.1f}" y1="{cy:.1f}" x2="{(x0 if right else x0 + width):.1f}" y2="{y - 4:.1f}"/>')
        out.append(f'<text class="{cls}" x="{(x0 if right else x0 + width):.1f}" y="{y:.1f}" '
                   f'text-anchor="{"start" if right else "end"}">{esc(text)}</text>')
    return out


def _diamond(x: float, y: float, r: float = 5.0) -> str:
    return (f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r:.0f}" height="{2 * r:.0f}" '
            f'transform="rotate(45 {x:.1f} {y:.1f})"/>')


def thread_color(res: dict, r: dict) -> str:
    """A paper's colour on the map: its first thread's place in the map's order of threads."""
    ids = [t["id"] for t in res.get("threads") or []]
    tid = next((t for t in r.get("threads") or [] if t in ids), None)
    return f"var(--l{(ids.index(tid) % 6) + 1})" if tid in ids else "var(--ink-2)"


def thread_name(res: dict, r: dict) -> str:
    names = {t["id"]: t.get("name") or t["id"] for t in res.get("threads") or []}
    return "、".join(names[t] for t in r.get("threads") or [] if t in names)


def zone_of(pid: str, pred: float, x: float, vw: dict) -> str:
    if pid in set(vw.get("gem") or []):
        return "gem"
    if pid in set(vw.get("hyped") or []):
        return "hyped"
    if pred >= TOP and x >= TOP:
        return "good"
    if pred <= BOTTOM and x <= BOTTOM:
        return "junk"
    return "mid"


def view_chart(res: dict, L: dict, metric: str, vw: dict) -> str:
    """One measure of attention against your score, drawn as on the map: across, the attention on your scale; up,
    the score your clauses give; y = x where the two agree, shaded beyond the allowed distance; your rated papers on
    y = x at your score, with a tick to what your clauses give them. Every mark carries its paper's id (data-id), so
    the page's script can show it on hover and open it on a click."""
    pos = vw.get("pos") or {}
    est = [r for r in res.get("map") or [] if r["id"] in pos]
    if not est:
        return ""
    far, noise = vw.get("far", res.get("far", 0.15)), res.get("noise", 0.0)
    rated = res.get("rated") or []
    vals = ([r["pred"] for r in est] + [pos[r["id"]]["x"] for r in est] +
            [r["yours"] for r in rated] + [r["pred"] for r in rated])
    lo_v = max(0.0, math.floor((min(vals) - 0.04) * 10) / 10)
    hi_v = min(1.0, math.ceil((max(vals) + 0.04) * 10) / 10)
    span = (hi_v - lo_v) or 1.0
    side = W - 2 * PAD
    x0, x1, y1 = 46.0, 46.0 + side, 30.0
    y0 = y1 + side
    px = lambda v: x0 + (max(lo_v, min(hi_v, v)) - lo_v) / span * side  # noqa: E731
    py = lambda v: y0 - (max(lo_v, min(hi_v, v)) - lo_v) / span * side  # noqa: E731
    width, height = x1 + 14, y0 + 46
    out = [f'<svg class="att" viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{esc(L["v_title"].get(metric, metric))}">']
    if lo_v + far < hi_v:      # the zones beyond the allowed distance: above y = x + far, below y = x - far
        out.append(f'<polygon class="q-zone gem" points="{px(lo_v)},{py(lo_v + far)} {px(hi_v - far)},{py(hi_v)} {px(lo_v)},{py(hi_v)}"/>'
                   f'<polygon class="q-zone hyped" points="{px(lo_v + far)},{py(lo_v)} {px(hi_v)},{py(hi_v - far)} {px(hi_v)},{py(lo_v)}"/>'
                   f'<line class="q-line" x1="{px(lo_v)}" y1="{py(lo_v + far)}" x2="{px(hi_v - far)}" y2="{py(hi_v)}"/>'
                   f'<line class="q-line" x1="{px(lo_v + far)}" y1="{py(lo_v)}" x2="{px(hi_v)}" y2="{py(hi_v - far)}"/>')
    out.append(f'<line class="ax" x1="{x0}" x2="{x1}" y1="{y0}" y2="{y0}"/><line class="ax" x1="{x0}" x2="{x0}" y1="{y0}" y2="{y1}"/>')
    for i in range(5):
        v = round(lo_v + i * span / 4, 3)
        out.append(f'<text class="ax-t" x="{px(v):.1f}" y="{y0 + 16:.1f}" text-anchor="middle">{v:g}</text>'
                   f'<text class="ax-t" x="{x0 - 6:.1f}" y="{py(v) + 4:.1f}" text-anchor="end">{v:g}</text>')
    mid = (y0 + y1) / 2
    vx = L["vx_log"] if (metric != "cumulative" or res.get("attention_source") == "citations a year") and res.get("attention_source") else L["vx"]
    out.append(f'<text class="ax-l" x="{x1:.1f}" y="{height - 6:.1f}" text-anchor="end">{esc(vx)}</text>'
               f'<text class="ax-l" x="14" y="{mid:.1f}" text-anchor="middle" transform="rotate(-90 14 {mid:.1f})">{esc(L["vy"])}</text>'
               f'<line class="fit" x1="{px(lo_v)}" y1="{py(lo_v)}" x2="{px(hi_v)}" y2="{py(hi_v)}"/>')
    qboxes = []
    # the shaded corners are named inside; the two ends of y = x just outside the plot, with an arrow along the line
    for key, x, y, anchor in (("gem", x0 + 8, y1 + 14, "start"), ("hyped", x1 - 8, y0 - 8, "end"),
                              ("good", x1, y1 - 10, "end"), ("junk", x0, y0 + 34, "start")):
        text = {"good": L["zone"]["good"] + " ↗", "junk": "↙ " + L["zone"]["junk"]}.get(key, L["zone"][key])
        w_ = sum(11 if ord(ch) > 0x2e80 else 7 for ch in text)
        qboxes.append((x if anchor == "start" else x - w_, y - 11, x + w_ if anchor == "start" else x, y + 3))
        out.append(f'<text class="q-label {key}" x="{x}" y="{y:.1f}" text-anchor="{anchor}">{esc(text)}</text>')
    key_labels, more_labels, marks = [], [], []
    for r in rated:            # your rated papers: on y = x at your score, a tick to what your clauses give
        x, yv, yp = px(r["yours"]), py(r["yours"]), py(r["pred"])
        rid = "rated:" + str(r.get("key") or r["title"])
        out.append(f'<g class="anc" data-id="{esc(rid)}" data-z="rated" tabindex="0" role="button" aria-label="{esc(r["title"])}">'
                   f'<title>{esc(r["title"])} · {r["yours"]:.2f}</title>'
                   f'<line class="tick" x1="{x:.1f}" x2="{x:.1f}" y1="{yv:.1f}" y2="{yp:.1f}"/>'
                   f'<circle class="halo" cx="{x:.1f}" cy="{yv:.1f}" r="10"/>{_diamond(x, yv, 5)}</g>')
        marks.append((x - 7, yv - 7, x + 7, yv + 7))
        key_labels.append((x, yv, 7, _name(r, 16), "lbl anc-l key"))
    for r in sorted(est, key=lambda r: zone_of(r["id"], r["pred"], pos[r["id"]]["x"], vw) in ("gem", "hyped")):
        q = pos[r["id"]]
        z = zone_of(r["id"], r["pred"], q["x"], vw)
        off = z in ("gem", "hyped")
        x, y = px(q["x"]), py(r["pred"])
        rand = r.get("sample") == "random"
        col = "var(--muted)" if rand else thread_color(res, r)
        tp = r.get("role") == "turning-point"
        seed = r.get("role") == "seed"
        rad = 7.5 if tp else 5.5
        half = max((r.get("unsure") or 0) / 2, noise)
        months = (r.get("m") or {}).get("months")
        cls = ("pt" + (" flagged" if off else "") + (" young" if months is not None and months < 12 else "") + (" rand" if rand else "")
               + (" seed" if seed else ""))
        out.append(f'<g class="{cls}" style="--fc:{col}" data-id="{esc(r["id"])}" data-z="{z}" tabindex="0" role="button" '
                   f'aria-label="{esc(r.get("title") or r["id"])}"><title>{esc(r.get("title") or r["id"])}</title>'
                   f'<line class="bar" x1="{px(q["lo"]):.1f}" x2="{px(q["hi"]):.1f}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<line class="bar" x1="{x:.1f}" x2="{x:.1f}" y1="{py(r["pred"] - half):.1f}" y2="{py(r["pred"] + half):.1f}"/>'
                   f'<circle class="halo" cx="{x:.1f}" cy="{y:.1f}" r="{rad + 5}"/>'
                   f'<circle class="dot-o" cx="{x:.1f}" cy="{y:.1f}" r="{rad}"/>'
                   + (f'<circle class="core" cx="{x:.1f}" cy="{y:.1f}" r="3"/>' if tp else "")
                   + (f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="1.8"/>' if rand and not off else "")
                   + (f'<rect class="seed-ring" x="{x - rad - 4:.1f}" y="{y - rad - 4:.1f}" width="{2 * rad + 8:.1f}" height="{2 * rad + 8:.1f}" rx="2"/>' if seed else "")
                   + '</g>')
        marks.append((x - rad - 4, y - rad - 4, x + rad + 4, y + rad + 4) if seed else (x - rad - 1, y - rad - 1, x + rad + 1, y + rad + 1))
        if seed:
            key_labels.insert(0, (x, y, rad + 4, f'{L["lg_seed"]}：{_name(r, 18)}' if L is T["zh"] else f'{L["lg_seed"]}: {_name(r, 18)}', "lbl strong key"))
        else:
            (key_labels if off else more_labels).append((x, y, rad, _name(r, 18), "lbl strong key" if off else "lbl more"))
    out.extend(place_labels(key_labels + more_labels, marks + qboxes + [(0, y1 - 4, x0 - 2, y0 + 4)], width))
    out.append("</svg>")
    return "".join(out)


def _legend(res: dict, L: dict) -> str:
    rand = '<circle cx="8" cy="8" r="5" fill="var(--surface)" stroke="var(--muted)" stroke-width="2"/><circle cx="8" cy="8" r="1.8" fill="var(--muted)"/>'
    items = [('<circle cx="8" cy="8" r="5" fill="var(--surface)" stroke="var(--ink-2)" stroke-width="2"/>', L["lg_map"]),
             ('<circle cx="8" cy="8" r="6.5" fill="var(--surface)" stroke="var(--ink-2)" stroke-width="2"/><circle cx="8" cy="8" r="2.8" fill="var(--ink-2)"/>', L["lg_tp"])]
    if any(r.get("role") == "seed" for r in res.get("map") or []):
        items.append(('<circle cx="8" cy="8" r="3.5" fill="var(--surface)" stroke="var(--ink-2)" stroke-width="1.6"/><rect x="2" y="2" width="12" height="12" rx="1.5" fill="none" stroke="var(--ink)" stroke-width="1.6"/>', L["lg_seed"]))
    if any(r.get("sample") == "random" for r in res.get("map") or []):
        items.append((rand, L["lg_rand"]))
    items += [('<circle cx="8" cy="8" r="5" fill="var(--ink-2)" stroke="var(--ink-2)" stroke-width="2"/>', L["lg_off"]),
              ('<circle cx="8" cy="8" r="5" fill="var(--surface)" stroke="var(--ink-2)" stroke-width="2" stroke-dasharray="2.4 1.8"/>', L["lg_young"]),
              ('<rect x="4" y="4" width="8" height="8" transform="rotate(45 8 8)" fill="var(--ink)"/>', L["lg_rated"])]
    shapes = "".join(f'<span><svg width="16" height="16" aria-hidden="true">{b}</svg>{esc(t)}</span>' for b, t in items)
    threads = "".join(f'<span><i class="ln" style="background:var(--l{(i % 6) + 1})"></i>{esc(t["name"])}</span>'
                      for i, t in enumerate(res.get("threads") or []))
    return f'<div class="legend">{shapes}</div>' + (f'<div class="legend">{threads}</div>' if threads else "")


LABELS_HIDDEN_ABOVE = 20   # a chart with more papers than this starts with every name hidden (hover or click to see one)


def _figure(res: dict, L: dict, metric: str, vw: dict, uid: str) -> str:
    """The chart with its switches: which names to show (radio buttons, so they work without the page's script) and
    the error bars. `uid` keeps each chart's buttons apart."""
    svg = view_chart(res, L, metric, vw)
    if not svg:
        return f'<p class="m">{esc(L["noview"])}</p>'
    n = sum(1 for r in res.get("map") or [] if r["id"] in (vw.get("pos") or {}))
    start = "none" if n > LABELS_HIDDEN_ABOVE else "key"
    seg = "".join(f'<label><input type="radio" name="lab-{uid}" value="{k}" data-lab{" checked" if k == start else ""}>'
                  f'<span>{esc(L["lab_" + k])}</span></label>' for k in ("key", "all", "none"))
    return (f'<figure class="chart" data-metric="{metric}"><div class="tools"><span class="t-l">{esc(L["labels"])}</span>'
            f'<span class="seg rad" role="radiogroup" aria-label="{esc(L["labels"])}">{seg}</span>'
            f'<label class="sw"><input type="checkbox" data-bars> {esc(L["bars"])}</label></div>'
            f'{svg}</figure>')


def _levels_svg(x: dict, names: List[str]) -> str:
    """The levels as a row of small bars, one per clause (0 to 5)."""
    bars, tip = [], []
    for i, n in enumerate(names):
        v = (x or {}).get(n)
        lv = None if v is None else round(v * 5, 1)
        h = 2 if not lv else 2 + lv * 2.4
        bars.append(f'<rect x="{i * 6}" y="{16 - h:.1f}" width="4" height="{h:.1f}"{" class=na" if lv is None else ""}/>')
        tip.append(f"{n} {'–' if lv is None else format(lv, 'g')}/5")
    return (f'<svg class="lv" width="{len(names) * 6}" height="16" viewBox="0 0 {len(names) * 6} 16" role="img" '
            f'aria-label="{esc(" · ".join(tip))}"><title>{esc(" · ".join(tip))}</title>{"".join(bars)}</svg>')


def _basis(text: str) -> List[str]:
    """[why, why not higher]"""
    parts = re.split(r"\s+[—–-]{1,2}\s+", _txt(text), maxsplit=1)
    return [parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""]


def _rubric_levels(rubric: str) -> List[tuple]:
    """'0 = ...; 1 = ...' as [(level, text)], or [] when it does not read that way."""
    bits = re.split(r"[;；]\s*(?=\d\s*[=＝])", rubric or "")
    out = []
    for b in bits:
        m = re.match(r"\s*(\d)\s*[=＝]\s*(.*)", b, re.S)
        if not m:
            return []
        out.append((int(m.group(1)), m.group(2).strip().rstrip("。.;；")))
    return out


def _views_of(res: dict) -> dict:
    """The attention views of a result; a result from before they existed gets them from its stored percentiles."""
    if res.get("views") is not None:
        return res["views"]
    rows = [{"id": r["id"], "m": {"cumulative": r.get("attention"), "rel": 1.0}} for r in res.get("map") or []]
    return compute_views(rows, {r["id"]: r["pred"] for r in res.get("map") or []},
                         {r["id"]: r.get("unsure", 0) for r in res.get("map") or []}, res.get("far", 0.15))


def _normalise(res: dict) -> dict:
    """A result from before your scores were a hard constraint kept the leave-one-out prediction as "pred" and the
    in-sample one as "fit": read it the new way."""
    res = dict(res)
    rated = []
    for r in res.get("rated") or []:
        r = dict(r)
        if "loo" not in r:
            r["loo"], r["pred"] = r["pred"], r.get("fit", r["pred"])
        rated.append(r)
    res["rated"] = rated
    if rated and "loo_mae" not in res:
        errs = [abs(r["pred"] - r["yours"]) for r in rated]
        res["loo_mae"] = res.get("mae", 0.0)
        res["mae"], res["max_err"] = sum(errs) / len(errs), max(errs)
    res.setdefault("max_err", max([abs(r["pred"] - r["yours"]) for r in rated] or [0.0]))
    if "confidence" not in res and rated:
        # a result from before the label: the label from its rated rows, and every score bar widened by the mean miss
        # (as a new run does), with the papers off the line found again on the wider bars
        from tastecal.taste.axes import confidence
        errs = [abs(r["pred"] - r["yours"]) for r in rated]
        res["confidence"] = confidence(errs, res.get("order_errors", 0), res.get("fit_tol", 0.1))
        rms = res["confidence"]["rms"]
        res["map"] = [dict(r, unsure=round(2 * math.sqrt((r.get("unsure") or 0) ** 2 / 4 + rms ** 2), 3)) for r in res.get("map") or []]
        if res.get("views") is not None and all(r.get("m") for r in res["map"]):
            res["views"] = compute_views([{"id": r["id"], "m": r["m"]} for r in res["map"]], {r["id"]: r["pred"] for r in res["map"]},
                                         {r["id"]: r["unsure"] for r in res["map"]}, res.get("far", 0.15))
    return res


def _att_lines(r: dict, L: dict) -> List[str]:
    m, bits = r.get("m") or {}, []
    if m.get("scale") == "log":                  # citations a year: the count itself, and OpenAlex's field percentile
        if m.get("cumulative") is not None:
            bits.append(L["rate_txt"].format(r=m["cumulative"]))
        if m.get("pct_field") is not None:
            bits.append(L["pct_txt"].format(p=100 * m["pct_field"]))
    elif m.get("cumulative") is not None:
        bits.append((L["pct_txt"] if "OpenAlex" in (m.get("source") or "") else L["pct_run"]).format(p=100 * m["cumulative"]))
    elif r.get("attention") is not None:
        bits.append(L["pct_run"].format(p=100 * r["attention"]))
    if m.get("citations") is not None:
        bits.append(L["cites"].format(n=m["citations"]))
    if m.get("recent") is not None:
        bits.append(L["recent_txt"].format(r=m["recent"]))
    if m.get("influential") is not None:
        bits.append(L["infl_txt"].format(r=m["influential"]))
    if m.get("stars") is not None:
        bits.append(L["stars_txt"].format(r=m["stars"]))
    if m.get("months") is not None:
        bits.append(L["months"].format(m=m["months"]))
    return bits


def _data(res: dict, L: dict, names: List[str], vws: dict, fit_metric: str) -> dict:
    """Everything the page's script shows for a paper, by id."""
    papers, order = {}, []

    def pub(r: dict) -> str:
        """Where it appeared and who wrote it, as the map recorded them."""
        au = r.get("authors")
        if isinstance(au, list):
            au = ", ".join(a for a in au[:3] if a) + (" et al." if len(au) > 3 else "")
        return " · ".join(t for t in (str(r.get("venue") or "").strip(), str(au or "").strip()) if t)
    for r in sorted(res.get("rated") or [], key=lambda r: -r["yours"]):
        pid = "rated:" + str(r.get("key") or r["title"])
        papers[pid] = {"kind": "rated", "title": r["title"], "name": _name(r), "date": r.get("date", ""), "pub": pub(r),
                       "yours": r["yours"], "fit": r["pred"], "comment": r.get("comment", ""),
                       # the average of two reads: may fall between two levels (3.5)
                       "levels": {n: (None if (r.get("x") or {}).get(n) is None else round(r["x"][n] * 5, 1)) for n in names},
                       "basis": {n: _basis((r.get("basis") or {}).get(n, "")) for n in names},
                       "drivers": [[n, c] for n, c in (r.get("contrib") or [])[:3] if c > 0]}
        order.append(pid)
    for r in sorted(res.get("map") or [], key=lambda r: -r["pred"]):
        att = {}
        for metric, vw in vws.items():
            q = (vw.get("pos") or {}).get(r["id"])
            if q:
                att[metric] = {"x": q["x"], "lo": q["lo"], "hi": q["hi"], "z": zone_of(r["id"], r["pred"], q["x"], vw)}
        rc = r.get("recheck") or {}
        recheck = ""
        if rc.get("against"):
            recheck = (L["d_recheck"].format(against=rc["against"], changed="、".join(rc["changed"]))
                       if rc.get("changed") else L["d_recheck0"].format(against=rc["against"]))
        basis = r.get("basis") or {}
        papers[r["id"]] = {"kind": "random" if r.get("sample") == "random" else "map", "title": r.get("title", ""), "pub": pub(r),
                           "name": _name(r), "date": r.get("date", ""), "score": r["pred"],
                           "unsure": max((r.get("unsure") or 0) / 2, res.get("noise", 0.0)),
                           "levels": {n: (None if (r.get("x") or {}).get(n) is None else round(r["x"][n] * 5)) for n in names},
                           "basis": {n: _basis(basis.get(n, "") if isinstance(basis, dict) else "") for n in names},
                           "att": att, "raw": _att_lines(r, L), "thread": thread_name(res, r),
                           "tp": r.get("role") == "turning-point", "seed": r.get("role") == "seed", "recheck": recheck}
        order.append(r["id"])
    i18n = {k: L[k] for k in ("d_yours", "d_fit", "d_reason", "d_score", "d_att", "d_levels", "d_not_higher",
                              "d_drivers", "d_thread", "d_att_none", "close", "prev", "next", "c_gap", "lg_tp", "lg_seed", "shown")}
    i18n.update({"zone": L["zone"], "kind": L["kind"], "m_names": L["m_names"]})
    return {"names": names, "papers": papers, "order": order, "fit_metric": fit_metric, "i18n": i18n}


def _row_list(ids: List[str], data: dict, metric: str, L: dict) -> str:
    """One line per paper: name, score, attention, gap. A click opens it."""
    items = []
    for i in ids:
        p = data["papers"].get(i)
        if not p:
            continue
        a = (p.get("att") or {}).get(metric)
        gap = "" if not a else f' · {esc(L["c_gap"])} {p["score"] - a["x"]:+.2f}'
        att = "" if not a else f' · {esc(L["c_att"])} {a["x"]:.2f}'
        items.append(f'<li><button type="button" class="rowbtn" data-id="{esc(i)}"><b>{esc(p["name"])}</b>'
                     f'<span class="m">{esc(p["date"][:4])} · {esc(L["c_score"])} {p["score"]:.2f}{att}{gap}</span></button></li>')
    return f'<ul class="rows">{"".join(items)}</ul>' if items else f'<p class="m">{esc(L["none"])}</p>'


def _zone_ids(data: dict, metric: str, zone: str) -> List[str]:
    ids = [i for i, p in data["papers"].items() if ((p.get("att") or {}).get(metric) or {}).get("z") == zone]
    gap = lambda i: data["papers"][i]["score"] - data["papers"][i]["att"][metric]["x"]  # noqa: E731
    if zone == "gem":
        return sorted(ids, key=lambda i: -gap(i))
    if zone == "hyped":
        return sorted(ids, key=gap)
    return sorted(ids, key=lambda i: -data["papers"][i]["score"] if zone == "good" else data["papers"][i]["score"])


def _zones(data: dict, metric: str, L: dict, fmt: dict) -> str:
    """The four regions as chips (a click picks out its papers on the chart) and their one-line lists."""
    chips, lists = [], []
    for z in ZONES:
        ids = _zone_ids(data, metric, z)
        chips.append(f'<button type="button" class="zchip" data-zone="{z}" aria-pressed="false" style="--c:{ZONE_COL[z]}">'
                     f'<i></i>{esc(L["zone"][z])} <b>{len(ids)}</b></button>')
        lists.append(f'<section class="zl" data-zone="{z}"{"" if z in ("gem", "hyped") else " hidden"} style="--c:{ZONE_COL[z]}">'
                     f'<h3>{esc(L["zone"][z])} <span class="m">{len(ids)}</span></h3>'
                     f'<p class="d">{esc(L["zone_d"][z].format(**fmt))}</p>{_row_list(ids, data, metric, L)}</section>')
    return f'<div class="zones" data-metric="{metric}">{"".join(chips)}</div><div class="zlists" data-metric="{metric}">{"".join(lists)}</div>'


def _table(data: dict, L: dict, fit_metric: str) -> str:
    names = data["names"]
    seed_tag = f' <span class="pill">{esc(L["lg_seed"])}</span>'
    rows = []
    for pid in data["order"]:
        p = data["papers"][pid]
        if p["kind"] == "rated":
            score, att, gap, z = p["yours"], None, None, "rated"
        else:
            a = (p.get("att") or {}).get(fit_metric)
            score, att = p["score"], (a or {}).get("x")
            gap, z = (None if att is None else score - att), (a or {}).get("z", "mid")
        title = p["title"] if p["title"] != p["name"] else ""
        rows.append(f'<tr data-id="{esc(pid)}" data-kind="{p["kind"]}" data-z="{z}" data-t="{esc((p["title"] + " " + p["name"]).lower())}" '
                    f'data-score="{score:.3f}" data-att="{"" if att is None else f"{att:.3f}"}" data-gap="{"" if gap is None else f"{gap:.3f}"}" '
                    f'data-date="{esc(p["date"])}" tabindex="0">'
                    f'<td class="tt"><b>{esc(p["name"])}</b>{seed_tag if p.get("seed") else ""}'
                    f'{f"<span class=sub>{esc(title)}</span>" if title else ""}</td>'
                    f'<td class="n m">{esc(p["date"][:4])}</td>'
                    f'<td class="n">{score:.2f}</td><td class="n">{"—" if att is None else f"{att:.2f}"}</td>'
                    f'<td class="n gap">{"—" if gap is None else f"{gap:+.2f}"}</td>'
                    f'<td><span class="zt" style="--c:{ZONE_COL.get(z, "var(--hair)")}">{esc(L["zone"].get(z, z))}</span></td>'
                    f'<td class="lvc">{_levels_svg({n: (None if v is None else v / 5) for n, v in p["levels"].items()}, names)}</td></tr>')
    filters = "".join(f'<button type="button" data-filter="{k}" aria-pressed="{"true" if k == "all" else "false"}">{esc(v)}</button>'
                      for k, v in L["f"].items())
    head = "".join(f'<th{f" class=n" if k not in ("paper", "zone", "levels") else ""}{f" data-sort={k}" if k in ("score", "att", "gap", "date") else ""}>'
                   f'{esc(L["c_" + k])}</th>' for k in ("paper", "date", "score", "att", "gap", "zone", "levels"))
    return (f'<div class="ptools"><span class="seg" id="pfilter">{filters}</span>'
            f'<input type="search" id="psearch" placeholder="{esc(L["search"])}" aria-label="{esc(L["search"])}">'
            f'<span class="m" id="pcount">{esc(L["shown"].format(n=len(rows)))}</span></div>'
            f'<p class="m">{esc(L["c_gap"])}: {esc(L["gap_d"])} · {esc(L["c_levels"])}: {esc(" · ".join(names))}</p>'
            f'<div class="tw"><table id="ptable"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _flags(data: dict, vws: dict, L: dict) -> str:
    """Papers off the line under any measure, and which."""
    metrics = list(vws)
    ids = [i for i in data["order"] if any(((data["papers"][i].get("att") or {}).get(m) or {}).get("z") in ("gem", "hyped") for m in metrics)]
    if not ids:
        return ""
    head = "".join(f'<th>{esc(L["m_names"].get(m, m))}</th>' for m in metrics)
    body = []
    for i in ids:
        p = data["papers"][i]
        cells = []
        for m in metrics:
            z = ((p.get("att") or {}).get(m) or {}).get("z")
            chip = f'<span class="zt" style="--c:{ZONE_COL[z]}">{esc(L["zone"][z])}</span>' if z in ("gem", "hyped") else ""
            cells.append(f"<td>{chip}</td>")
        body.append(f'<tr data-id="{esc(i)}" tabindex="0"><td class="tt"><b>{esc(p["name"])}</b></td><td class="n">{p["score"]:.2f}</td>{"".join(cells)}</tr>')
    return (f'<h2>{esc(L["flag_t"])}</h2><p class="m">{esc(L["flag_d"])}</p><div class="tw"><table class="flags"><thead><tr><th></th>'
            f'<th class="n">{esc(L["c_score"])}</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def _equal(res: dict) -> bool:
    """Every clause counts the same (the fit since 2026-10-20); older results had fitted weights."""
    shares = [round(d.get("share", 0), 3) for d in res.get("weights") or []]
    return len(set(shares)) <= 1


def _clauses(res: dict, L: dict) -> str:
    ind_by = {d["name"]: d for d in res.get("indicators") or []}
    equal = _equal(res)
    cards = []
    for d in sorted(res.get("weights") or [], key=lambda d: -d.get("share", 0)):
        src = ind_by.get(d["name"]) or {}
        lv = _rubric_levels(_txt(d.get("rubric")))
        body = ("<ol class=steps>" + "".join(f'<li><b>{n}</b><span>{esc(t)}</span></li>' for n, t in lv) + "</ol>"
                if lv else f'<p>{esc(_txt(d.get("rubric")))}</p>')
        hs, hf = src.get("how") or [], src.get("how_from") or []
        how = "".join(f'<div class="cnote"><b>{esc(L["how_note"])}{esc(L["how_field"]) if (hf[i] if i < len(hf) else "") == "field" else ""}</b>'
                      f'<span>{esc(_txt(h))}</span></div>' for i, h in enumerate(hs))
        sh, lo, hi = 100 * d.get("share", 0), 100 * d.get("low", 0), 100 * d.get("high", 0)
        weight = "" if equal else (
            f'<div class="sbar" title="{esc(L["range"].format(lo=lo, hi=hi))}"><span class="rng" style="left:{lo:.1f}%;width:{max(0.6, hi - lo):.1f}%"></span>'
            f'<span class="val" style="width:{sh:.1f}%"></span></div><p class="m">{esc(L["share"])} {sh:.0f}% · {esc(L["range"].format(lo=lo, hi=hi))}</p>')
        cards.append(f'<article class="clause"><header><h3>{esc(d["name"])}</h3>'
                     f'<span class="pill">{esc(L["from"].get(d.get("from"), d.get("from") or ""))}</span>'
                     + ("" if equal else f'<span class="shv">{sh:.0f}%</span>') + f'</header>{weight}{body}{how}</article>')
    return "".join(cards)


def _history(res: dict, L: dict) -> str:
    items = []
    for h in res.get("history") or []:
        field = h.get("phase") == "field"
        if field:
            moved = "" if h.get("err_after") is None else f'{h["err_before"]:.3f} → {h["err_after"]:.3f}'
        else:
            moved = "" if h.get("mae_after") is None else f'{h["mae_before"]:.3f} → {h["mae_after"]:.3f}'
        what = _txt(h.get("change") or L["notes"].get(h.get("note") or "", h.get("note")) or h.get("type") or "")
        why = _txt(h.get("why") or "")
        # "rewrite Clause: 0 = ...; 1 = ...": the line names the change, the clause in full is folded under it
        m = re.match(r"(.+?\S)[:：]\s*(.*)", what, re.S)
        head, rest = (m.group(1), m.group(2)) if m else (what, "")
        fold = (f'<p>{esc(rest)}</p>' if rest else "") + (f'<p class="why"><b>{esc(L["reason"])}</b>{esc(why)}</p>' if why else "")
        items.append(f'<li><div class="hl"><span class="pill {"ok" if h.get("accepted") else "no"}">{esc(L["acc"] if h.get("accepted") else L["rej"])}</span>'
                     f'<span class="m">{esc(L["ph_field"] if field else L["ph_yours"])} · {esc(L["round"].format(n=h.get("round", "")))}'
                     f'{" · " + esc(moved) if moved else ""}</span></div><div class="hw">{esc(head)}</div>'
                     + (f'<details><summary>{esc(L["h_more"])}</summary>{fold}</details>' if fold else "") + '</li>')
    return f'<ul class="hist">{"".join(items)}</ul>' if items else f'<p class="m">{esc(L["none"])}</p>'


def _lang(language: str) -> dict:
    return T["zh"] if str(language).lower().startswith("zh") else T["en"]


TAB_KEYS = ("overview", "papers", "views", "clauses", "process")


def _build(res: dict, L: dict) -> dict:
    """What the standalone page and the combined report share: the five panels, the drawer and the data the script
    shows for each paper."""
    res = _normalise(res)
    names = [d["name"] for d in res.get("indicators") or []]
    vws = _views_of(res)
    fit_metric = res.get("fit_metric") or "cumulative"
    if fit_metric not in vws and vws:
        fit_metric = next(iter(vws))
    order_m = [m for m in ("cumulative", "recent", "influential", "stars") if m in vws] + [m for m in vws if m not in
                                                                                          ("cumulative", "recent", "influential", "stars")]
    data = _data(res, L, names, vws, fit_metric)
    fmt = {"top": TOP, "bottom": BOTTOM}
    rated, maps = res.get("rated") or [], res.get("map") or []
    n_rand = sum(1 for r in maps if r.get("sample") == "random")
    main = vws.get(fit_metric) or {}

    # the numbers that say how far to trust the page and where to look first
    years = res.get("years")
    n_txt = (L["st_n_v"].format(n=len(maps), y=years, r=n_rand) if years else L["st_n_v0"].format(n=len(maps), r=n_rand))
    cf = res.get("confidence") or {}
    stats = (f'<button type="button" class="stat cstat" data-goto="process"><span class="k">{esc(L["st_conf"])}</span>'
             f'<span class="v">±{cf.get("rms", 0):.2f}</span>'
             f'<span class="m">{esc(L["st_conf_v"].format(worst=cf.get("worst", 0)))}</span></button>'
             f'<div class="stat"><span class="k">{esc(L["st_n"])}</span><span class="v">{len(maps)}</span><span class="m">{esc(n_txt)}</span></div>'
             + "".join(f'<button type="button" class="stat zstat" data-zone="{z}" style="--c:{ZONE_COL[z]}"><span class="k">{esc(L["zone"][z])}</span>'
                       f'<span class="v">{len(main.get(z) or [])}</span><span class="m">{esc(L["m_names"].get(fit_metric, fit_metric))}</span></button>'
                       for z in ("gem", "hyped")))

    # overview: the chart the fit aims at, with the papers off the line beside it
    log_scale = res.get("attention_source") == "citations a year"
    anchor = (res.get("attention_anchor") or {}).get(fit_metric, "")
    how_items = list(L["how_main"])
    med = ((res.get("attention_scale") or {}).get(fit_metric) or {}).get("median")
    med_txt = "" if med is None else (f"{med:.1f}" if med < 10 else f"{med:.0f}")
    if log_scale and anchor:
        newer = "lo" in ((res.get("attention_scale") or {}).get(fit_metric) or {})   # lower half by the papers' spread
        how_items[0] = (L["how_log0" if newer else "how_log1"].format(anchor=anchor, median=med_txt) if med_txt else
                        L["how_log00"].format(anchor=anchor))         # results from before the scale was centred
    tol_txt = L["how_tol"].format(tol=res.get("fit_tol", 0.1))
    how_items = [t.replace("{tol}", tol_txt) for t in how_items]
    how = "".join(f"<li>{esc(t)}</li>" for t in how_items)
    overview = (f'<div class="intro"><p class="lede">{esc(L["sub"])}</p><div class="stats">{stats}</div></div>'
                f'<h2>{esc(L["v_title"].get(fit_metric, fit_metric))}</h2><p class="cap">{esc(L["cap_main"])}</p>'
                + (f'<div class="duo"><div class="duo-main">{_figure(res, L, fit_metric, main, "ov")}{_legend(res, L)}</div>'
                   f'<div class="duo-side">{_zones(data, fit_metric, L, fmt)}</div></div>' if main else
                   f'<p class="m">{esc(L["noview"])}</p>')
                + f'<details class="how"><summary>{esc(L["how"])}</summary><ul>{how}</ul></details>')

    # the other measures, one at a time
    seg = "".join(f'<label><input type="radio" name="vm" id="vm-{m}" value="{m}"{" checked" if m == fit_metric else ""}>'
                  f'<span>{esc(L["m_names"].get(m, m))}{" · " + esc(L["target"]) if m == fit_metric else ""}</span></label>' for m in order_m)
    vpanels = "".join(f'<section class="vpanel" data-metric="{m}"><h2>{esc(L["v_title"].get(m, m))}</h2>'
                      f'<p class="cap">{esc(L["cap_main"] if m == fit_metric else L["cap_other"])}</p>'
                      f'<div class="duo"><div class="duo-main">{_figure(res, L, m, vws[m], "vw-" + m)}</div><div class="duo-side">' + "".join(
                          f'<section class="zl" style="--c:{ZONE_COL[z]}"><h3>{esc(L["zone"][z])} <span class="m">{len(vws[m].get(z) or [])}</span></h3>'
                          f'{_row_list(_zone_ids(data, m, z), data, m, L)}</section>' for z in ("gem", "hyped")) + '</div></div></section>'
                      for m in order_m)
    views_html = ((f'<div class="vtools"><span class="seg rad" id="vseg" role="radiogroup">{seg}</span></div>' if len(order_m) > 1 else "")
                  + vpanels + _flags(data, vws, L)) if vws else f'<p class="m">{esc(L["noview"])}</p>'

    # how it was fitted: the numbers and the loop on the left, the lists to act on beside them
    tol = res.get("fit_tol", 0.1)
    fit_rows = "".join(f'<tr data-id="{esc("rated:" + str(r.get("key") or r["title"]))}" tabindex="0"><td class="tt"><b>{esc(_name(r))}</b>'
                       f'<span class="sub">{esc(r["title"]) if _name(r) != r["title"] else ""}</span></td><td class="n">{r["yours"]:.2f}</td>'
                       f'<td class="n">{r["pred"]:.2f}</td><td class="n{" bad" if abs(r["pred"] - r["yours"]) > tol + 1e-3 else ""}">{r["pred"] - r["yours"]:+.2f}</td></tr>'
                       for r in sorted(rated, key=lambda r: -r["yours"]))
    fld = res.get("field") or {}
    delta = ""
    if fld.get("skipped"):
        field_txt = L["field_skip"].format(why=fld["skipped"])
    elif fld.get("start") and fld.get("equal"):
        fin = fld.get("final") or fld["end"]
        field_txt = L["field_q"].format(papers=fld.get("papers", 0), new=FIELD_NEW, tol=tol, d0=fld["equal"]["dist"],
                                        d1=fin["dist"], b0=fld["start"]["err_B"], b1=fld["end"]["err_B"],
                                        m0=fld["equal"]["mae"], m1=fin["mae"], share=fld.get("share", 0))
        if fld.get("fallback"):
            field_txt += L["field_fb"]
        delta = (f'<div class="stats delta"><div class="stat"><span class="k">{esc(L["p_dist"])}</span>'
                 f'<span class="v">{fld["equal"]["dist"]:.2f} → {fin["dist"]:.2f}</span>'
                 f'<span class="m">{esc(L["p_eq"])} → {esc(L["p_fitw"])}</span></div>'
                 f'<div class="stat"><span class="k">{esc(L["p_miss"])}</span>'
                 f'<span class="v">{fld["equal"]["mae"]:.2f} → {fin["mae"]:.2f}</span>'
                 f'<span class="m">{esc(L["p_eq"])} → {esc(L["p_fitw"])}</span></div></div>')
    elif fld.get("start"):                       # results from before 2026-10-20: rank distance, weights from your scores
        field_txt = L["field_q0"].format(papers=fld.get("papers", 0), new=FIELD_NEW, b0=fld["start"]["err_B"], b1=fld["end"]["err_B"],
                                         m0=fld["start"]["mae"], m1=fld["end"]["mae"], share=fld.get("share", 0))
    else:
        field_txt = ""
    unread = {u["ref"]: u for u in res.get("unread") or []}

    def why(s_: dict) -> str:
        u = unread.get(s_["ref"]) or s_
        w = (u.get("why") or "").split(" (")[0]
        txt = esc(L["why"].get(w, w))
        if u.get("file"):
            txt += f" · {esc(L['file'])} <code>{esc(u['file'])}</code>"
        return txt
    by_id = {r["id"]: r for r in maps}
    others = "".join(f'<li>{esc(o.get("short") or o["title"])} <span class="m">{esc(L["types"].get(o.get("type"), o.get("type") or ""))}</span></li>'
                     for o in res.get("others") or [])
    older = "".join(f'<li>{esc(o["title"])} <span class="m">{esc(o.get("date", ""))}</span></li>' for o in res.get("older") or [])
    skipped = "".join(f'<li>{esc(s["ref"])} <span class="m">{esc(L["c_yours"])} {s["yours"]:.2f} · {why(s)}</span></li>'
                      for s in res.get("skipped") or [])
    unread_map = "".join(f'<li>{esc(u.get("short") or u["title"])} <span class="m">{esc(L["file"])} <code>{esc(u["file"])}</code></span></li>'
                         for u in res.get("unread_map") or [] if u.get("file"))
    sug = _row_list([i for i in res.get("suggest") or [] if i in by_id], data, fit_metric, L)
    bias = L["p_bias"].format(n=n_rand) if n_rand else L["p_bias0"]
    conf_txt = f'<p class="cap">{esc(L["conf_d"].format(rms=cf.get("rms", 0), n=cf.get("n", 0), worst=cf.get("worst", 0)))}</p>'
    start_txt = f'<p class="m">{esc(L["p_start"].format(d=res["started_from"]) if res.get("started_from") else L["p_start0"])}</p>'
    if res.get("refit"):
        start_txt += f'<p class="m">{esc(L["p_refit"].format(d=(res["refit"] or {}).get("on", "")))}</p>'
    proc_main = (f'<h2>{esc(L["p_fit"])}</h2>{conf_txt}<p class="cap">{esc(L["p_fit_d"].format(tol=tol))}</p>'
                 f'<div class="tw"><table class="fit"><thead><tr><th></th><th class="n">{esc(L["c_yours"])}</th><th class="n">{esc(L["c_repro"])}</th>'
                 f'<th class="n">{esc(L["c_diff"])}</th></tr></thead><tbody>{fit_rows}</tbody></table></div>'
                 f'<p class="m">{esc(L["p_stats"].format(order=res.get("order_errors", 0), noise=res.get("noise", 0), loo=res.get("loo_mae", 0)))}</p>'
                 f'{start_txt}'
                 + (f'<h2>{esc(L["p_field"])}</h2>{delta}<p class="cap">{esc(field_txt)}</p>' if field_txt else "")
                 + f'<p class="m">{esc(bias)}</p>'
                 f'<h2>{esc(L["p_hist"])}</h2>{_history(res, L)}')
    proc_side = (f'<section class="side"><h3>{esc(L["p_suggest"])}</h3><p class="m">{esc(L["p_suggest_d"])}</p>{sug}</section>'
                 + (f'<section class="side"><h3>{esc(L["p_skipped"])}</h3><ul class="plain">{skipped}</ul></section>' if skipped else "")
                 + (f'<section class="side"><h3>{esc(L["p_unread"])}</h3><p class="m">{esc(L["p_unread_d"])}</p>'
                    f'<ul class="plain">{unread_map}</ul></section>' if unread_map else "")
                 + (f'<section class="side"><h3>{esc(L["p_older"].format(y=years))}</h3><ul class="plain">{older}</ul></section>' if older and years else "")
                 + (f'<section class="side"><h3>{esc(L["p_others"])}</h3><ul class="plain">{others}</ul></section>' if others else ""))
    process = f'<div class="duo proc"><div class="duo-main">{proc_main}</div><aside class="duo-side">{proc_side}</aside></div>'

    bodies = {"overview": overview, "papers": _table(data, L, fit_metric), "views": views_html,
              "clauses": f'<p class="cap">{esc(L["cl_eq"] if _equal(res) else L["cl_d"])}</p><div class="clauses">{_clauses(res, L)}</div>',
              "process": process}
    panels = "".join(f'<section class="panel" role="tabpanel" id="panel-{k}" aria-label="{esc(L["tabs"][k])}">{bodies[k]}</section>'
                     for k in TAB_KEYS)
    drawer = (f'<aside id="drawer" class="drawer" hidden aria-label=""><div class="dhead"><button type="button" class="dnav" data-step="-1" aria-label="{esc(L["prev"])}">‹</button>'
              f'<button type="button" class="dnav" data-step="1" aria-label="{esc(L["next"])}">›</button>'
              f'<button type="button" class="dclose" aria-label="{esc(L["close"])}">×</button></div><div class="dbody"></div></aside>')
    meta = " · ".join(x for x in (res.get("topic") or "", res.get("as_of") or "") if x)
    return {"tabs": [(k, L["tabs"][k]) for k in TAB_KEYS], "panels": panels, "drawer": drawer, "meta": meta,
            "blob": json.dumps(data, ensure_ascii=False).replace("</", "<\\/")}


def _body(b: dict, L: dict, embedded: bool) -> str:
    """The tabs are radio buttons the stylesheet reads, so the page shows the right panel even before its script runs.
    In the combined report the report's own bar picks the tab, so there are no labels here and the buttons stay out
    of the keyboard order."""
    radios = "".join(f'<input type="radio" name="tab" class="tabr" id="t-{k}" value="{k}" aria-label="{esc(lab)}"'
                     f'{" tabindex=-1" if embedded else ""}{" checked" if i == 0 else ""}>' for i, (k, lab) in enumerate(b["tabs"]))
    nav = "" if embedded else (
        f'<nav class="tabs" role="tablist" aria-label="{esc(L["title"])}"><div class="wrap">'
        + "".join(f'<label for="t-{k}" role="tab" id="tab-{k}" data-tab="{k}" aria-controls="panel-{k}">{esc(lab)}</label>' for k, lab in b["tabs"])
        + '</div></nav>')
    return (f'<div class="tf">{radios}{nav}<main class="wrap">{b["panels"]}</main>'
            f'<div id="tip" class="tip" hidden></div>{b["drawer"]}'
            f'<script type="application/json" id="fit-data">{b["blob"]}</script></div>')


FONTS = ("https://fonts.googleapis.com/css2?family=Overpass:wght@400;600;700;800"
         "&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400")


def page(res: dict, language: str = "en") -> str:
    """The taste calibration as a page of its own (taste_fit.html)."""
    L = _lang(language)
    b = _build(res, L)
    zh = L is T["zh"]
    fonts = FONTS + ("&family=Noto+Serif+SC:wght@400;600" if zh else "") + "&display=swap"
    return (f'<!doctype html><html lang="{"zh-CN" if zh else "en"}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(L["title"])}</title>'
            '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link rel="stylesheet" href="{fonts}">'
            f'<style>{TOKENS}{CSS}</style></head><body>'
            f'<header class="top"><div class="wrap"><p class="eyebrow">{esc(b["meta"])}</p><h1>{esc(L["title"])}</h1></div></header>'
            f'{_body(b, L, False)}<script>{JS}tasteFit(document);</script></body></html>')


def embed(res: dict, language: str = "en") -> str:
    """The taste calibration as the second part of the combined report: the same panels in a shadow root, so their
    styles and ids stay their own, with the colours and type taken from the report. The report's script starts it
    with tasteFit(root, {embedded: true, onTab}) and puts its tabs in the report's bar."""
    L = _lang(language)
    b = _build(res, L)
    return (f'<div id="taste-host"><template shadowrootmode="open"><style>{CSS}</style>{_body(b, L, True)}</template></div>'
            f'<script>{JS}</script>')


# The colours and type of the report (report/report.html), for the page on its own; the combined report passes its
# own to the shadow root, so the two parts always match.
TOKENS = """
:root{--bg:#f1f3f5;--surface:#ffffff;--surface-2:#e8ecf0;--ink:#121a23;--ink-2:#3a4450;--muted:#626d7a;--hair:#d5dbe2;--challenge:#c4373b;--focus:#2a78d6;--ok:#0f7a2e;--warn:#a15c00;
--l1:#2a78d6;--l2:#eb6834;--l3:#1baf7a;--l4:#eda100;--l5:#e87ba4;--l6:#6250d6;--shadow:0 18px 50px rgba(18,26,35,.16);
--f-display:"Overpass",ui-sans-serif,system-ui,-apple-system,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif;
--f-body:"Source Serif 4","Iowan Old Style",Georgia,"Noto Serif SC","Songti SC","Noto Serif CJK SC",serif;--f-mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0e1217;--surface:#161b22;--surface-2:#1e242d;--ink:#e8ecf1;--ink-2:#bcc4cf;--muted:#8e98a5;--hair:#2b333e;--challenge:#ee6d6d;--focus:#6da7ec;--ok:#3fc463;--warn:#e3a43a;
--l1:#3987e5;--l2:#d95926;--l3:#199e70;--l4:#c98500;--l5:#d55181;--l6:#9085e9;--shadow:0 18px 50px rgba(0,0,0,.55);color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0e1217;--surface:#161b22;--surface-2:#1e242d;--ink:#e8ecf1;--ink-2:#bcc4cf;--muted:#8e98a5;--hair:#2b333e;--challenge:#ee6d6d;--focus:#6da7ec;--ok:#3fc463;--warn:#e3a43a;
--l1:#3987e5;--l2:#d95926;--l3:#199e70;--l4:#c98500;--l5:#d55181;--l6:#9085e9;--shadow:0 18px 50px rgba(0,0,0,.55);color-scheme:dark}
body{margin:0;background:var(--bg)}
"""

CSS = """
:host{display:block}
*{box-sizing:border-box}
[hidden]{display:none!important}
.tf{color:var(--ink);font:15px/1.55 var(--f-display);-webkit-font-smoothing:antialiased}
.wrap{max-width:1200px;margin:0 auto;padding-inline:clamp(16px,4vw,40px)}
button{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
h1,h2,h3{font-family:var(--f-display);margin:0;text-wrap:balance}
h2{font-size:clamp(20px,2.2vw,24px);line-height:1.25;font-weight:800;letter-spacing:-.01em;margin:30px 0 8px}
h3{font-size:16px;line-height:1.3;font-weight:700}
.cap{font:16px/1.65 var(--f-body);color:var(--ink-2);max-width:72ch;margin:0 0 14px}
.m{color:var(--muted);font-size:13px} code{font:12.5px var(--f-mono)}
p.m{margin:8px 0;max-width:90ch}

/* the page on its own: a header and the tabs as stations on a line, as in the report */
header.top{padding:40px 0 20px}
.eyebrow{font:600 14px/1.4 var(--f-display);color:var(--muted);margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
h1{font-size:clamp(30px,4.2vw,46px);line-height:1.08;font-weight:800;letter-spacing:-.02em;margin:6px 0 0}
nav.tabs{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--hair)}
nav.tabs .wrap{display:flex;overflow-x:auto;scrollbar-width:none;min-height:58px;align-items:flex-end}
nav.tabs label{position:relative;flex:none;padding:10px 15px 21px;font:600 14.5px var(--f-display);color:var(--muted);cursor:pointer;white-space:nowrap;user-select:none}
nav.tabs label:hover{color:var(--ink)}
nav.tabs label::before{content:"";position:absolute;left:0;right:0;bottom:10px;height:2px;background:var(--hair)}
nav.tabs label:first-child::before{left:50%} nav.tabs label:last-child::before{right:50%}
nav.tabs label::after{content:"";position:absolute;left:50%;bottom:5px;width:12px;height:12px;margin-left:-6px;border-radius:50%;background:var(--bg);border:2px solid var(--hair);box-sizing:border-box}
nav.tabs label.past::before{background:var(--ink-2)} nav.tabs label.past::after{border-color:var(--ink-2)}
nav.tabs label[aria-selected="true"]{color:var(--ink)}
nav.tabs label[aria-selected="true"]::before{background:linear-gradient(90deg,var(--ink-2) 50%,var(--hair) 50%)}
nav.tabs label:first-child[aria-selected="true"]::before{background:var(--hair)}
nav.tabs label[aria-selected="true"]::after{width:14px;height:14px;margin-left:-7px;bottom:4px;background:var(--ink);border-color:var(--ink)}
.tabr{position:fixed;top:0;left:0;opacity:0;pointer-events:none;width:1px;height:1px}
.tf:has(#t-overview:focus-visible) label[for="t-overview"],.tf:has(#t-papers:focus-visible) label[for="t-papers"],.tf:has(#t-views:focus-visible) label[for="t-views"],
.tf:has(#t-clauses:focus-visible) label[for="t-clauses"],.tf:has(#t-process:focus-visible) label[for="t-process"]{outline:2px solid var(--focus);outline-offset:-4px;border-radius:8px}
.panel{display:none;padding-top:30px}
.tf:has(#t-overview:checked) #panel-overview,.tf:has(#t-papers:checked) #panel-papers,.tf:has(#t-views:checked) #panel-views,
.tf:has(#t-clauses:checked) #panel-clauses,.tf:has(#t-process:checked) #panel-process{display:block}
main{padding-bottom:64px}
.panel > h2:first-child,.panel > .cap:first-child,.duo-main > h2:first-child{margin-top:0}

/* the key numbers: one strip, the cells apart by hairlines */
.intro{display:grid;gap:16px;margin-bottom:8px}
.lede{font:17px/1.6 var(--f-body);color:var(--ink-2);max-width:64ch;margin:0}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));background:var(--surface);border:1px solid var(--hair);border-radius:16px;overflow:hidden}
.stat{display:flex;flex-direction:column;gap:3px;text-align:left;padding:14px 18px 15px;border:0;border-left:1px solid var(--hair);background:none;font:inherit;color:inherit;min-width:0}
.stat:first-child{border-left:0}
.stat .k{display:flex;align-items:center;gap:7px;font:600 13px/1.35 var(--f-display);color:var(--muted)}
.zstat .k::before{content:"";flex:none;width:9px;height:9px;border-radius:50%;background:var(--c)}
.stat .v{font-size:28px;font-weight:800;line-height:1.1;font-variant-numeric:tabular-nums}
.stat .m{font-size:12.5px}
button.stat{cursor:pointer} button.stat:hover{background:var(--surface-2)}
.delta{grid-template-columns:repeat(2,minmax(0,1fr));margin:4px 0 14px}
.delta .v{font-size:24px}
@media (max-width:720px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.stat:nth-child(3){border-left:0}.stat:nth-child(n+3){border-top:1px solid var(--hair)}}

/* a chart with what to read beside it */
.duo{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);gap:24px 32px;align-items:start}
.duo-side{display:grid;gap:14px;min-width:0;align-content:start}
@media (max-width:960px){.duo{grid-template-columns:minmax(0,1fr)}}
.seg{display:inline-flex;flex-wrap:wrap;border:1px solid var(--hair);border-radius:999px;overflow:hidden;background:var(--surface)}
.seg button{border:0;background:transparent;color:var(--ink-2);padding:5px 13px;font:600 13px var(--f-display);cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
.seg.rad label{display:block;cursor:pointer;position:relative}
.seg.rad input{position:absolute;opacity:0;pointer-events:none;width:1px;height:1px}
.seg.rad span{display:block;padding:5px 13px;font:600 13px var(--f-display);color:var(--ink-2);white-space:nowrap}
.seg.rad input:checked+span{background:var(--ink);color:var(--bg)}
.seg.rad input:focus-visible+span{outline:2px solid var(--focus);outline-offset:-2px}
.pill{font:600 12.5px var(--f-display);border-radius:6px;padding:2px 8px;color:var(--ink-2);background:var(--surface-2);white-space:nowrap}
.pill.ok{color:var(--ok);background:color-mix(in srgb,var(--ok) 12%,var(--surface))} .pill.no{color:var(--muted)}
figure.chart{margin:0}
.tools{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:0 0 8px}
.t-l{font:600 13px var(--f-display);color:var(--muted)}
.sw{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--ink-2);cursor:pointer}
svg.att{width:100%;height:auto;background:var(--surface);border:1px solid var(--hair);border-radius:16px;display:block;touch-action:manipulation}
.ax{stroke:var(--ink-2);stroke-width:1} .ax-t{font:400 11.5px var(--f-display);fill:var(--muted)} .ax-l{font:600 12.5px var(--f-display);fill:var(--ink-2)}
.q-zone.hyped{fill:var(--warn);opacity:.07} .q-zone.gem{fill:var(--focus);opacity:.07}
.q-line{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 4;opacity:.6}
.q-label{font:600 11.5px var(--f-display);fill:var(--muted);opacity:.9}
line.fit{stroke:var(--ink);stroke-width:1.4;stroke-dasharray:7 5;opacity:.6;fill:none}
[data-id]{cursor:pointer;outline:none}
.pt .dot-o{fill:var(--surface);stroke:var(--fc);stroke-width:2} .pt.flagged .dot-o{fill:var(--fc)}
.pt.young .dot-o{stroke-dasharray:2.4 1.8} .pt .core{fill:var(--fc)} .pt.flagged .core{fill:var(--surface)}
.pt .dot{fill:var(--fc)} .pt .seed-ring{fill:none;stroke:var(--ink);stroke-width:1.6} .pt .bar{stroke:var(--fc);stroke-width:1.4;opacity:.5;display:none}
.chart:has(input[data-bars]:checked) .pt .bar,.pt:hover .bar,.pt:focus .bar,.pt.sel .bar{display:inline}
.halo{fill:none;stroke:var(--ink);stroke-width:1.5;opacity:0} .pt:hover .halo,.anc:hover .halo,[data-id]:focus .halo{opacity:.35} .sel .halo{opacity:.9}
.anc rect{fill:var(--ink);stroke:var(--surface);stroke-width:1.5} .anc .tick{stroke:var(--ink);stroke-width:1.6;opacity:.45}
.lbl{font:600 10.5px var(--f-display);fill:var(--ink-2);paint-order:stroke;stroke:var(--surface);stroke-width:3.5px;stroke-linejoin:round;pointer-events:none}
.lbl.strong{fill:var(--ink)} .lbl.anc-l{fill:var(--muted);font-weight:600} .lead{stroke:var(--hair);stroke-width:1}
.chart:has(input[data-lab][value="key"]:checked) .more,.chart:has(input[data-lab][value="none"]:checked) .lbl,.chart:has(input[data-lab][value="none"]:checked) .lead{display:none}
.chart.dim .pt,.chart.dim .anc{opacity:.14} .chart.dim .pt.hi,.chart.dim .anc.hi{opacity:1}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--ink-2);align-items:center;margin-top:10px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend svg{width:16px;height:16px;flex:none} .legend i.ln{width:16px;height:4px;border-radius:2px;display:inline-block}
.zones{display:flex;flex-wrap:wrap;gap:8px}
.zchip{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--hair);background:var(--surface);border-radius:999px;padding:5px 12px;font:600 13px var(--f-display);color:var(--ink-2);cursor:pointer}
.zchip i{width:9px;height:9px;border-radius:50%;background:var(--c)} .zchip b{font-variant-numeric:tabular-nums;color:var(--ink)}
.zchip[aria-pressed="true"]{border-color:var(--c);box-shadow:inset 0 0 0 1px var(--c);color:var(--ink)}
.zlists{display:grid;grid-template-columns:minmax(0,1fr);gap:12px}
.zl{background:var(--surface);border:1px solid var(--hair);border-radius:14px;padding:14px 16px;box-shadow:inset 3px 0 0 var(--c)}
.zl h3{display:flex;align-items:baseline;gap:8px}
.zl .d{margin:4px 0 8px;color:var(--muted);font-size:13.5px;line-height:1.5}
ul.rows{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:minmax(0,1fr);gap:2px}
.rowbtn{display:flex;flex-wrap:wrap;gap:2px 10px;align-items:baseline;width:100%;text-align:left;border:0;background:none;padding:7px 8px;margin:0 -8px;border-radius:8px;font:inherit;color:inherit;cursor:pointer}
.rowbtn:hover,.rowbtn:focus-visible,.rowbtn.sel{background:var(--surface-2)}
.rowbtn b{max-width:min(60ch,100%);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
details.how{margin-top:20px;max-width:900px;border-top:1px solid var(--hair);padding-top:12px}
details.how ul{font:15px/1.65 var(--f-body);color:var(--ink-2);padding-left:20px;display:grid;gap:6px}
summary{cursor:pointer;font-weight:700}
.ptools,.vtools{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:0 0 10px}
#psearch{flex:1 1 200px;max-width:320px;border:1px solid var(--hair);background:var(--surface);color:var(--ink);border-radius:999px;padding:6px 14px;font:14px var(--f-display)}
.tw{overflow-x:auto;border:1px solid var(--hair);border-radius:14px;background:var(--surface)}
table{border-collapse:collapse;width:100%}
td,th{padding:9px 12px;border-bottom:1px solid var(--hair);text-align:left;vertical-align:middle}
tbody tr:last-child td{border-bottom:0}
th{font:600 12.5px var(--f-display);color:var(--muted);white-space:nowrap}
th[data-sort]{cursor:pointer} th[data-sort]::after{content:" ↕";opacity:.35} th[aria-sort="ascending"]::after{content:" ↑";opacity:1} th[aria-sort="descending"]::after{content:" ↓";opacity:1}
.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tbody tr[data-id]{cursor:pointer} tbody tr[data-id]:hover,tbody tr.sel{background:var(--surface-2)}
td.tt b{display:block;font-weight:700;max-width:60ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap} td.tt .sub{display:block;color:var(--muted);font-size:12.5px;max-width:52ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
td.gap{color:var(--ink-2)} td.bad{color:var(--challenge);font-weight:700}
table.fit td.tt b,table.fit td.tt .sub{white-space:normal;max-width:none}
.zt{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--ink-2);white-space:nowrap}
.zt::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--c)}
svg.lv rect{fill:var(--ink-2);opacity:.8} svg.lv rect.na{fill:var(--hair)}
@media (max-width:720px){#ptable th:nth-child(5),#ptable td:nth-child(5),#ptable th:nth-child(7),#ptable td:nth-child(7),#ptable th:nth-child(2),#ptable td:nth-child(2){display:none}}
.vpanel{display:none}
#panel-views:has(#vm-cumulative:checked) .vpanel[data-metric="cumulative"],#panel-views:has(#vm-recent:checked) .vpanel[data-metric="recent"],
#panel-views:has(#vm-influential:checked) .vpanel[data-metric="influential"],#panel-views:has(#vm-stars:checked) .vpanel[data-metric="stars"]{display:block}
table.flags td{font-size:13.5px}
.clauses{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,470px),1fr));gap:16px;align-items:start}
.clause{background:var(--surface);border:1px solid var(--hair);border-radius:16px;padding:16px 18px 18px}
.clause header{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.clause .shv{margin-left:auto;font-size:22px;font-weight:800;font-variant-numeric:tabular-nums}
.sbar{position:relative;height:8px;border-radius:4px;background:var(--surface-2);margin:10px 0 4px;overflow:hidden}
.sbar .val{position:absolute;left:0;top:0;bottom:0;background:var(--ink);border-radius:4px}
.sbar .rng{position:absolute;top:0;bottom:0;background:var(--focus);opacity:.35}
ol.steps{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:6px}
ol.steps li{display:grid;grid-template-columns:24px minmax(0,1fr);gap:10px;font:14.5px/1.55 var(--f-body);color:var(--ink-2)}
ol.steps b{font:800 12.5px/24px var(--f-display);color:var(--ink);text-align:center;background:var(--surface-2);border-radius:6px;height:24px}
.cnote{display:grid;grid-template-columns:auto minmax(0,1fr);gap:8px;margin-top:12px;padding-top:12px;border-top:1px dashed var(--hair);font-size:13.5px;line-height:1.55;color:var(--ink-2)}
.cnote b{font:600 12.5px/1.6 var(--f-display);color:var(--muted);white-space:nowrap}
ul.hist{list-style:none;margin:0;padding:0;display:grid;gap:0}
ul.hist li{padding:12px 0;border-bottom:1px solid var(--hair)}
.hl{display:flex;flex-wrap:wrap;gap:8px;align-items:center} .hw{margin-top:5px;font:700 15px/1.45 var(--f-display);color:var(--ink)}
ul.hist details{margin-top:4px} ul.hist summary{font-size:13px;color:var(--muted);font-weight:600}
ul.hist details p{margin:6px 0 0;font:14.5px/1.65 var(--f-body);color:var(--ink-2);max-width:80ch} ul.hist .why b{font:700 12.5px var(--f-display);color:var(--muted);margin-right:8px}
ul.plain{margin:6px 0 0;padding-left:18px;display:grid;gap:5px;font-size:14px}
.side{background:var(--surface);border:1px solid var(--hair);border-radius:14px;padding:14px 16px}
.side h3{margin-bottom:2px}
.proc .duo-side{position:sticky;top:76px}
@media (max-width:960px){.proc .duo-side{position:static}}
.tip{position:fixed;z-index:40;pointer-events:none;max-width:300px;background:var(--ink);color:var(--bg);border-radius:10px;padding:8px 11px;font-size:13px;line-height:1.4;box-shadow:var(--shadow)}
.tip b{display:block;font-size:13.5px}
.drawer{position:fixed;z-index:50;top:0;right:0;bottom:0;width:min(470px,100vw);background:var(--surface);border-left:1px solid var(--hair);box-shadow:var(--shadow);display:flex;flex-direction:column}
.dhead{display:flex;gap:6px;justify-content:flex-end;padding:12px 14px;border-bottom:1px solid var(--hair)}
.dhead button{border:1px solid var(--hair);background:var(--surface);color:var(--ink);width:34px;height:34px;border-radius:999px;font:700 18px/1 var(--f-display);cursor:pointer}
.dhead .dclose{margin-left:8px}
.dbody{overflow-y:auto;padding:18px 24px 40px}
.dbody h2{margin:6px 0 4px;font-size:22px;line-height:1.25}
.dk{font:600 13px/1.4 var(--f-display);color:var(--muted)}
.dpub{margin:4px 0 14px;color:var(--muted);font-size:13.5px}
.dstats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:0 0 14px}
.dstats > div{background:var(--surface-2);border-radius:12px;padding:10px 14px} .dstats .v{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums}
.dstats .k{font:600 12.5px var(--f-display);color:var(--muted)}
.dsec{margin:18px 0 0;padding-top:14px;border-top:1px solid var(--hair)} .dsec h3{font:700 14px var(--f-display);color:var(--ink);margin:0 0 8px}
.dsec p{margin:0 0 6px;font:15px/1.6 var(--f-body);color:var(--ink-2)}
.atts{display:grid;gap:4px;margin:0;padding:0;list-style:none;font-size:13.5px}
.atts li{display:flex;justify-content:space-between;gap:10px;border-bottom:1px dashed var(--hair);padding:4px 0}
.lvl{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.lvl .h{display:flex;align-items:center;gap:8px;font-weight:700;font-size:14px}
.pips{display:inline-flex;gap:2px} .pips i{width:10px;height:6px;border-radius:2px;background:var(--hair)} .pips i.on{background:var(--ink)}
.lvl .h .n{margin-left:auto;font:600 12.5px var(--f-display);color:var(--muted)}
.lvl p{margin:3px 0 0;font:14.5px/1.6 var(--f-body);color:var(--ink-2)} .lvl p.nh{color:var(--muted);font-size:14px}
.lvl p.nh b{font:700 12.5px var(--f-display);margin-right:6px}
@media (max-width:720px){.drawer{top:auto;left:0;width:100vw;max-height:84vh;border-left:0;border-top:1px solid var(--hair);border-radius:18px 18px 0 0}}
"""

# tasteFit(root, opts): root is the document (the page on its own) or the shadow root it sits in (the combined
# report). Events are heard on the document and acted on only when they happened inside root, at their real target.
JS = r"""
window.tasteFit=function(R,opts){
opts=opts||{};
var doc=R.ownerDocument||R,own=R===doc;
function $(s,el){return (el||R).querySelector(s)}
function $$(s,el){return Array.prototype.slice.call((el||R).querySelectorAll(s))}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function f2(v){return (Math.round(v*100)/100).toFixed(2)}
function sg(v){return (v>=0?'+':'')+f2(v)}
function inner(e){var p=e.composedPath?e.composedPath():[e.target];if(!own&&p.indexOf(R)<0)return null;var t=p[0];while(t&&!t.closest)t=t.parentNode;return t||null}
var D=JSON.parse($('#fit-data').textContent),I=D.i18n;
/* tabs: radio buttons shown by the stylesheet */
var radios=$$('input.tabr'),tabs=radios.map(function(r){return {key:r.value,label:r.getAttribute('aria-label')}});
function sync(){var i=-1;radios.forEach(function(r,k){if(r.checked)i=k});
  radios.forEach(function(r,k){var t=$('#tab-'+r.value);if(!t)return;t.setAttribute('aria-selected',k===i?'true':'false');t.classList.toggle('past',k<i)})}
function show(name){var r=$('#t-'+name)||radios[0];if(!r)return '';r.checked=true;sync();return r.value}
function go(name){                       /* a tab chosen from inside the page */
  name=show(name);
  if(opts.onTab){opts.onTab(name);return}
  try{history.replaceState(null,'','#'+name)}catch(e){}
  var hd=$('header.top'),y=hd?hd.offsetTop+hd.offsetHeight:0;if(window.scrollY>y)window.scrollTo(0,y);
}
radios.forEach(function(r){r.addEventListener('change',function(){if(r.checked)go(r.value)})});
if(!opts.embedded){show((location.hash||'').slice(1));window.addEventListener('hashchange',function(){show(location.hash.slice(1))})}
else sync();
/* names on the charts: one choice for every chart, remembered in this browser */
$$('svg [data-id] > title').forEach(function(t){t.parentNode.removeChild(t)});
function labels(v){$$('input[data-lab]').forEach(function(i){if(i.value===v)i.checked=true})}
var saved=null;try{saved=localStorage.getItem('fit-labels')}catch(e){}
if(saved)labels(saved);
$$('input[data-lab]').forEach(function(i){i.addEventListener('change',function(){if(!i.checked)return;labels(i.value);try{localStorage.setItem('fit-labels',i.value)}catch(e){}})});
/* tooltip */
var tip=$('#tip');
function tipFor(id,metric){
  var p=D.papers[id];if(!p)return '';
  if(p.kind==='rated')return '<b>'+esc(p.name)+'</b>'+esc(I.d_yours)+' '+f2(p.yours)+' · '+esc(I.d_fit)+' '+f2(p.fit);
  var a=(p.att||{})[metric];
  return '<b>'+esc(p.name)+'</b>'+esc(I.d_score)+' '+f2(p.score)+' ±'+f2(p.unsure)+(a?' · '+esc(I.d_att)+' '+f2(a.x):'')+(p.date?' · '+esc(p.date.slice(0,4)):'');
}
doc.addEventListener('pointermove',function(e){
  var t=inner(e),g=t&&t.closest('svg.att [data-id]');
  if(!g||e.pointerType==='touch'){tip.hidden=true;return}
  var fig=g.closest('figure');tip.innerHTML=tipFor(g.dataset.id,fig?fig.dataset.metric:D.fit_metric);tip.hidden=false;
  var x=e.clientX+14,y=e.clientY+14,w=tip.offsetWidth,h=tip.offsetHeight;
  if(x+w>window.innerWidth-8)x=e.clientX-w-14;if(y+h>window.innerHeight-8)y=e.clientY-h-14;
  tip.style.left=x+'px';tip.style.top=y+'px';
});
/* the drawer */
var dr=$('#drawer'),body=$('.dbody',dr),cur=null,list=D.order;
function pips(v){var s='';for(var i=1;i<=5;i++)s+='<i class="'+(v!=null&&i<=v?'on':'')+'"></i>';return '<span class="pips">'+s+'</span>'}
function render(id){
  var p=D.papers[id];if(!p)return;var h='';
  h+='<div class="dk">'+esc(I.kind[p.kind]||'')+(p.date?' · '+esc(p.date):'')+(p.tp?' · '+esc(I.lg_tp):'')+(p.seed?' · '+esc(I.lg_seed):'')+'</div><h2>'+esc(p.title)+'</h2>'+(p.pub?'<p class="dpub">'+esc(p.pub)+'</p>':'');
  if(p.kind==='rated'){
    h+='<div class="dstats"><div><div class="k">'+esc(I.d_yours)+'</div><div class="v">'+f2(p.yours)+'</div></div><div><div class="k">'+esc(I.d_fit)+'</div><div class="v">'+f2(p.fit)+'</div></div></div>';
    if(p.comment)h+='<div class="dsec"><h3>'+esc(I.d_reason)+'</h3><p>'+esc(p.comment)+'</p></div>';
    if(p.drivers&&p.drivers.length)h+='<div class="dsec"><h3>'+esc(I.d_drivers)+'</h3><p>'+p.drivers.map(function(d){return esc(d[0])+' '+f2(d[1])}).join(' · ')+'</p></div>';
    h+='<div class="dsec"><p class="m">'+esc(I.d_att_none)+'</p></div>';
  }else{
    var a=(p.att||{})[D.fit_metric];
    h+='<div class="dstats"><div><div class="k">'+esc(I.d_score)+'</div><div class="v">'+f2(p.score)+'</div><div class="m">±'+f2(p.unsure)+'</div></div>';
    h+='<div><div class="k">'+esc(I.d_att)+' · '+esc(I.m_names[D.fit_metric]||'')+'</div><div class="v">'+(a?f2(a.x):'—')+'</div><div class="m">'+(a?esc(I.zone[a.z]||'')+' · '+esc(I.c_gap)+' '+sg(p.score-a.x):'')+'</div></div></div>';
    if(p.thread)h+='<div class="dsec"><h3>'+esc(I.d_thread)+'</h3><p>'+esc(p.thread)+'</p></div>';
    var ms=Object.keys(p.att||{});
    if(ms.length||(p.raw||[]).length){
      h+='<div class="dsec"><h3>'+esc(I.d_att)+'</h3><ul class="atts">'+ms.map(function(m){var q=p.att[m];return '<li><span>'+esc(I.m_names[m]||m)+'</span><span>'+f2(q.x)+' · '+esc(I.zone[q.z]||'')+'</span></li>'}).join('')+'</ul>';
      if((p.raw||[]).length)h+='<p class="m">'+p.raw.map(esc).join(' · ')+'</p>';
      h+='</div>';
    }
    if(p.recheck)h+='<div class="dsec"><p class="m">'+esc(p.recheck)+'</p></div>';
  }
  h+='<div class="dsec"><h3>'+esc(I.d_levels)+'</h3><ul class="lvl">'+D.names.map(function(n){
    var v=p.levels[n],b=(p.basis||{})[n]||['',''];
    return '<li><div class="h">'+esc(n)+pips(v)+'<span class="n">'+(v==null?'–':v)+'/5</span></div>'+(b[0]?'<p>'+esc(b[0])+'</p>':'')+(b[1]?'<p class="nh"><b>'+esc(I.d_not_higher)+'</b>'+esc(b[1])+'</p>':'')+'</li>'}).join('')+'</ul></div>';
  body.innerHTML=h;body.scrollTop=0;
}
function mark(id){$$('.sel').forEach(function(el){el.classList.remove('sel')});if(id)$$('[data-id]').forEach(function(el){if(el.dataset.id===id)el.classList.add('sel')})}
function open(id,from){
  if(!D.papers[id])return;cur=id;
  var vis=from&&from.closest('#ptable')?$$('#ptable tbody tr').filter(function(r){return !r.hidden}).map(function(r){return r.dataset.id}):D.order;
  list=vis.indexOf(id)>=0?vis:D.order;
  render(id);mark(id);dr.hidden=false;tip.hidden=true;
}
function close(){dr.hidden=true;mark(null);cur=null}
doc.addEventListener('click',function(e){
  var t=inner(e);if(!t||t.closest('#drawer'))return;
  var el=t.closest('[data-id]');
  if(el){open(el.dataset.id,el);return}
  if(!dr.hidden&&!t.closest('button,input,a,summary,label'))close();
});
doc.addEventListener('keydown',function(e){
  if(e.key==='Escape'&&!dr.hidden){close();return}
  var t=inner(e);if(!t)return;
  var el=t.closest('[data-id][tabindex]');
  if(el&&(e.key==='Enter'||e.key===' ')){e.preventDefault();open(el.dataset.id,el)}
  if(!dr.hidden&&(e.key==='ArrowDown'||e.key==='ArrowUp')&&!t.closest('input')){e.preventDefault();step(e.key==='ArrowDown'?1:-1)}
});
function step(k){if(!cur)return;var i=list.indexOf(cur),keep=list;open(list[(i+k+list.length)%list.length]);list=keep}
$('.dclose',dr).addEventListener('click',close);
$$('.dnav',dr).forEach(function(b){b.addEventListener('click',function(){step(+b.dataset.step)})});
/* regions: a chip picks out its papers on the chart, and shows their list */
function pick(metric,zone){
  $$('.zones[data-metric="'+metric+'"] .zchip').forEach(function(c){c.setAttribute('aria-pressed',c.dataset.zone===zone?'true':'false')});
  $$('.zlists[data-metric="'+metric+'"] .zl').forEach(function(s){s.hidden=zone?s.dataset.zone!==zone:!(s.dataset.zone==='gem'||s.dataset.zone==='hyped')});
  $$('#panel-overview figure.chart[data-metric="'+metric+'"]').forEach(function(fig){
    fig.classList.toggle('dim',!!zone);
    $$('[data-z]',fig).forEach(function(g){g.classList.toggle('hi',g.dataset.z===zone)})});
}
$$('.zchip').forEach(function(c){c.addEventListener('click',function(){var m=c.closest('.zones').dataset.metric;pick(m,c.getAttribute('aria-pressed')==='true'?null:c.dataset.zone)})});
$$('[data-goto]').forEach(function(c){c.addEventListener('click',function(){go(c.dataset.goto)})});
$$('.zstat').forEach(function(c){c.addEventListener('click',function(){go('overview');pick(D.fit_metric,c.dataset.zone);var z=$('.zones');if(z)z.scrollIntoView({behavior:'smooth',block:'center'})})});
/* the table: filter, search, sort */
var tb=$('#ptable tbody');
if(tb){
  var rows=$$('tr',tb),flt='all',q='',cnt=$('#pcount');
  var apply=function(){var n=0;rows.forEach(function(r){var k=r.dataset.kind,z=r.dataset.z;
    var ok=(flt==='all'||(flt==='rated'&&k==='rated')||(flt==='random'&&k==='random')||(flt==='off'&&(z==='gem'||z==='hyped')))&&(!q||r.dataset.t.indexOf(q)>=0);
    r.hidden=!ok;if(ok)n++});if(cnt)cnt.textContent=I.shown.replace('{n}',n)};
  $$('#pfilter button').forEach(function(b){b.addEventListener('click',function(){flt=b.dataset.filter;$$('#pfilter button').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false')});apply()})});
  var s=$('#psearch');if(s)s.addEventListener('input',function(){q=s.value.trim().toLowerCase();apply()});
  $$('#ptable th[data-sort]').forEach(function(th){th.addEventListener('click',function(){
    var key=th.dataset.sort,dir=th.getAttribute('aria-sort')==='descending'?1:-1;
    $$('#ptable th[data-sort]').forEach(function(x){x.removeAttribute('aria-sort')});th.setAttribute('aria-sort',dir<0?'descending':'ascending');
    rows.sort(function(a,b){var x=a.dataset[key],y=b.dataset[key];
      if(x===''&&y==='')return 0;if(x==='')return 1;if(y==='')return -1;
      var u=key==='date'?x:parseFloat(x),v=key==='date'?y:parseFloat(y);return u<v?-dir:u>v?dir:0});
    rows.forEach(function(r){tb.appendChild(r)})})});
}
return {tabs:tabs,show:function(k){return show(k)},close:close};
};
"""
