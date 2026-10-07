/* STS 战斗调试器前端逻辑（vanilla JS，无构建步骤） */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const META = {};          // /api/meta 结果
const S = {
  battleId: null,
  state: null,
  cfg: null,             // 本场配置（重开用）
  targeting: null,       // {kind: 'card'|'potion', index|slot, choice}
  selectSel: new Set(),  // CARD_SELECT 已选候选下标
  scryKeep: [],          // SCRY 每张 true=保留 / false=弃置（必须是前缀结构）
};

/* ---------------- 通用 ---------------- */

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function statusPills(statuses) {
  const line = el("div", "status-line");
  for (const s of statuses) {
    const pill = el("span", "status-pill" + (s.just_applied ? " fresh" : ""),
      `${s.zh} ${s.n}`);
    pill.title = s.name + (s.just_applied ? "（本回合新施加，回合末不递减）" : "");
    line.appendChild(pill);
  }
  return line;
}

function hpBar(cur, max) {
  const bar = el("div", "bar hp");
  const inner = el("div");
  inner.style.width = `${Math.max(0, cur) / Math.max(1, max) * 100}%`;
  bar.appendChild(inner);
  return bar;
}

function cardEl(c, opts = {}) {
  const d = el("div", `card ${c.ctype.toLowerCase()} ${opts.unplayable ? "unplayable" : "playable"}`);
  const head = el("div", "chead");
  head.appendChild(el("span", "ccost", c.x_cost ? "X" : String(c.cost)));
  head.appendChild(el("span", "ctype", c.ctype));
  d.appendChild(head);
  d.appendChild(el("div", "cname", c.zh + (c.upgraded ? "+" : "")));
  d.appendChild(el("div", "ctext", c.text));
  if (c.upgraded) d.appendChild(el("div", "upg", "已升级"));
  if (opts.reason) d.title = opts.reason;
  return d;
}

function cardName(c) {
  return `${c.zh}${c.upgraded ? "+" : ""}(${c.name})`;
}

/* ---------------- 配置界面 ---------------- */

function setupInit() {
  // 角色
  const charBox = $("#char-choice");
  for (const [key, c] of Object.entries(META.characters)) {
    const label = el("label", null, `${c.zh}（${c.max_hp} HP）`);
    const radio = document.createElement("input");
    radio.type = "radio"; radio.name = "char"; radio.value = key;
    label.prepend(radio);
    radio.addEventListener("change", () => {
      $$("#char-choice label").forEach((l) => l.classList.remove("active"));
      label.classList.add("active");
      S.deck = JSON.parse(JSON.stringify(c.deck));
      renderDeck();
    });
    charBox.appendChild(label);
  }
  charBox.querySelector('input[value="ironclad"]').checked = true;
  S.deck = JSON.parse(JSON.stringify(META.characters.ironclad.deck));

  // 遭遇下拉
  const enc = $("#encounter-select");
  for (const k of META.encounters) {
    const o = document.createElement("option");
    o.value = k; o.textContent = k;
    enc.appendChild(o);
  }

  // 药水 3 格
  const slots = $("#potion-slots");
  S.potions = [null, null, null];
  for (let i = 0; i < 3; i++) {
    const label = el("label", null, `药水槽 ${i + 1}`);
    const sel = document.createElement("select");
    sel.appendChild(new Option("（空）", ""));
    for (const p of META.potions) sel.appendChild(new Option(`${p.zh}（${p.name}）`, p.pid));
    sel.addEventListener("change", () => { S.potions[i] = sel.value || null; });
    label.appendChild(sel);
    slots.appendChild(label);
  }

  // 模式切换
  $$('input[name="monster-mode"]').forEach((r) => r.addEventListener("change", () => {
    $("#encounter-box").classList.toggle("hidden", r.value !== "encounter" || !r.checked);
    $("#custom-monster-box").classList.toggle("hidden", r.value !== "custom" || !r.checked);
  }));

  S.relics = [];
  S.customMonsters = [];

  bindSearch($("#card-search"), $("#card-search-results"), searchCards, renderCardResult);
  bindSearch($("#relic-search"), $("#relic-search-results"), searchRelics, renderRelicResult);
  bindSearch($("#monster-search"), $("#monster-search-results"), searchMonsters, renderMonsterResult);
  renderDeck(); renderRelics(); renderCustomMonsters();

  $("#start-btn").addEventListener("click", startBattle);

  // 恢复上次配置
  const saved = localStorage.getItem("sts-web-cfg");
  if (saved) {
    try { restoreCfg(JSON.parse(saved)); } catch { /* 忽略坏数据 */ }
  }
}

/* 搜索框通用：输入过滤 + 失焦隐藏 */
function bindSearch(input, dropdown, searcher, renderer) {
  input.addEventListener("input", () => {
    dropdown.innerHTML = "";
    const rows = searcher(input.value.trim());
    for (const item of rows.slice(0, 14)) dropdown.appendChild(renderer(item));
    dropdown.classList.toggle("hidden", rows.length === 0 || !input.value.trim());
  });
  input.addEventListener("blur", () => setTimeout(() => dropdown.classList.add("hidden"), 180));
}

const zhMatch = (s, q) => (s || "").toLowerCase().includes(q.toLowerCase());

function searchCards(q) {
  if (!q) return [];
  return META.cards.filter((c) =>
    zhMatch(c.zh, q) || zhMatch(c.name, q) ||
    zhMatch(c.ctype, q) || zhMatch(c.module_zh, q));
}

function renderCardResult(c) {
  const row = el("div", "row");
  row.appendChild(el("span", "cost", c.x_cost ? "X" : String(c.cost)));
  row.appendChild(el("span", "cname", `${c.zh}（${c.name}）`));
  row.appendChild(el("span", "ctype", `${c.module_zh}·${c.ctype}`));
  const bAdd = el("button", null, "+1");
  const bUpg = el("button", null, "+1 升级");
  bAdd.addEventListener("mousedown", (e) => { e.preventDefault(); deckAdd(c.id, 1, 0); });
  bUpg.addEventListener("mousedown", (e) => { e.preventDefault(); deckAdd(c.id, 1, 1); });
  row.appendChild(bAdd); row.appendChild(bUpg);
  row.title = c.text;
  return row;
}

function deckAdd(id, count, upgraded) {
  let e = S.deck.find((d) => d.id === id);
  if (!e) { e = { id, count: 0, upgraded: 0 }; S.deck.push(e); }
  e.count += count;
  e.upgraded += upgraded;
  renderDeck();
}

function renderDeck() {
  const tbody = $("#deck-tbody");
  tbody.innerHTML = "";
  for (const e of S.deck) {
    const c = META.cards.find((x) => x.id === e.id);
    const tr = document.createElement("tr");
    const tdName = el("td", null, `${c.zh}（${c.name}）`);
    tdName.title = c.text;
    tr.appendChild(tdName);
    tr.appendChild(el("td", null, c.x_cost ? "X" : String(c.cost)));
    tr.appendChild(el("td", null, c.ctype));
    const tdCount = el("td");
    const step = (delta, field, min) => {
      const btn = el("button", null, delta > 0 ? "+" : "−");
      btn.addEventListener("click", () => {
        e[field] = Math.max(min, e[field] + delta);
        if (field === "count" && e.upgraded > e.count) e.upgraded = e.count;
        renderDeck();
      });
      return btn;
    };
    const sc = el("span", "stepper");
    sc.append(step(-1, "count", 0), el("span", null, String(e.count)), step(1, "count", 0));
    tdCount.appendChild(sc); tr.appendChild(tdCount);
    const tdUpg = el("td");
    const su = el("span", "stepper");
    su.append(step(-1, "upgraded", 0), el("span", null, String(e.upgraded)),
               step(1, "upgraded", 0));
    tdUpg.appendChild(su); tr.appendChild(tdUpg);
    const tdDel = el("td");
    const del = el("button", null, "删");
    del.addEventListener("click", () => { S.deck = S.deck.filter((x) => x !== e); renderDeck(); });
    tdDel.appendChild(del); tr.appendChild(tdDel);
    tbody.appendChild(tr);
  }
  $("#deck-count").textContent = `${S.deck.reduce((a, e) => a + e.count, 0)} 张`;
}

function searchRelics(q) {
  if (!q) return [];
  return META.relics.filter((r) => zhMatch(r.zh, q) || zhMatch(r.name, q) || zhMatch(r.id, q));
}

function renderRelicResult(r) {
  const row = el("div", "row");
  row.appendChild(el("span", "cname", `${r.zh}（${r.name}）`));
  row.appendChild(el("span", "ctype", r.id));
  const b = el("button", null, "+ 添加");
  b.addEventListener("mousedown", (e) => {
    e.preventDefault();
    if (!S.relics.includes(r.id)) { S.relics.push(r.id); renderRelics(); }
  });
  row.appendChild(b);
  row.title = r.text;
  return row;
}

function renderRelics() {
  const box = $("#relic-chips");
  box.innerHTML = "";
  for (const id of S.relics) {
    const r = META.relics.find((x) => x.id === id);
    const chip = el("span", "chip", `${r.zh}（${r.name}）`);
    const x = el("span", "x", "×");
    x.addEventListener("click", () => { S.relics = S.relics.filter((i) => i !== id); renderRelics(); });
    chip.appendChild(x);
    chip.title = r.text;
    box.appendChild(chip);
  }
  $("#relic-count").textContent = `${S.relics.length} 个`;
}

function searchMonsters(q) {
  if (!q) return [];
  return META.monsters.filter((m) => zhMatch(m.zh, q) || zhMatch(m.name, q) || zhMatch(m.key, q));
}

function renderMonsterResult(m) {
  const row = el("div", "row");
  const hp = m.hp_range.length === 2 ? `HP ${m.hp_range[0]}-${m.hp_range[1]}` : "";
  row.appendChild(el("span", "cname", `${m.zh}（${m.name}）`));
  row.appendChild(el("span", "ctype", hp));
  const b = el("button", null, "+ 添加");
  b.addEventListener("mousedown", (e) => {
    e.preventDefault();
    if (S.customMonsters.length >= 5) { showError("最多 5 只怪"); return; }
    S.customMonsters.push(m.key);
    renderCustomMonsters();
  });
  row.appendChild(b);
  return row;
}

function renderCustomMonsters() {
  const box = $("#custom-monster-list");
  box.innerHTML = "";
  S.customMonsters.forEach((key, i) => {
    const m = META.monsters.find((x) => x.key === key);
    const chip = el("span", "chip", `${i + 1}. ${m.zh}（${m.name}）`);
    const x = el("span", "x", "×");
    x.addEventListener("click", () => {
      S.customMonsters = S.customMonsters.filter((_, j) => j !== i);
      renderCustomMonsters();
    });
    chip.appendChild(x);
    box.appendChild(chip);
  });
}

function currentCfg() {
  const customMode = $('input[name="monster-mode"]:checked').value === "custom";
  return {
    character: $('input[name="char"]:checked').value,
    deck: S.deck,
    relics: S.relics,
    potions: S.potions.filter(Boolean),
    monsters: customMode ? S.customMonsters : [],
    encounter: $("#encounter-select").value,
    seed: $("#seed-input").value === "" ? null : Number($("#seed-input").value),
    ascension: Number($("#ascension-input").value || 0),
  };
}

function restoreCfg(cfg) {
  if (!cfg || !META.characters[cfg.character]) return;
  // 先选角色（change 事件会载入默认牌组），再覆盖为保存的配置
  const radio = $(`input[name="char"][value="${cfg.character}"]`);
  if (radio) {
    radio.checked = true;
    radio.dispatchEvent(new Event("change"));
  }
  S.deck = cfg.deck || META.characters[cfg.character].deck;
  S.relics = cfg.relics || [];
  S.potions = [...(cfg.potions || []), null, null, null].slice(0, 3);
  S.customMonsters = cfg.monsters || [];
  if (cfg.encounter) $("#encounter-select").value = cfg.encounter;
  if (cfg.seed !== null && cfg.seed !== undefined) $("#seed-input").value = cfg.seed;
  if (cfg.ascension !== undefined) $("#ascension-input").value = cfg.ascension;
  if (S.customMonsters.length) {
    const r = $('input[name="monster-mode"][value="custom"]');
    r.checked = true;
    r.dispatchEvent(new Event("change"));
  }
  $$("#potion-slots select").forEach((sel, i) => { sel.value = S.potions[i] || ""; });
  renderDeck(); renderRelics(); renderCustomMonsters();
}

/* ---------------- 战斗流程 ---------------- */

async function startBattle() {
  const cfg = currentCfg();
  const res = await post("/api/battle/new", cfg);
  if (!res.ok) { showError(res.error, true); return; }
  S.cfg = cfg;
  localStorage.setItem("sts-web-cfg", JSON.stringify(cfg));
  $("#setup-view").classList.add("hidden");
  $("#battle-view").classList.remove("hidden");
  $("#log").innerHTML = "";
  S.battleId = res.id;
  absorb(res);
}

async function restart(sameSeed) {
  const cfg = JSON.parse(JSON.stringify(S.cfg));
  if (!sameSeed) cfg.seed = null;
  const res = await post("/api/battle/new", cfg);
  if (!res.ok) { showError(res.error, true); return; }
  S.cfg = cfg;
  S.battleId = res.id;
  $("#log").innerHTML = "";
  hideOverlays();
  absorb(res);
}

async function act(body) {
  if (!S.battleId) return;
  const res = await post("/api/battle/action", { id: S.battleId, ...body });
  if (res.error && res.state === undefined) { showError(res.error, true); return; }
  absorb(res);
  if (!res.ok && res.error) showError(res.error, res.error.includes("引擎异常"));
}

/* 服务端响应 → 界面 */
function absorb(res) {
  if (res.log && res.log.length) {
    const log = $("#log");
    for (const line of res.log) {
      log.appendChild(el("div", "line", line));
    }
    log.scrollTop = log.scrollHeight;
  }
  if (res.state) renderBattle(res.state);
}

/* ---------------- 战斗渲染 ---------------- */

function renderBattle(state) {
  S.state = state;
  S.targeting = null;
  $("#targeting-banner").classList.toggle("hidden", true);

  const meta = [];
  meta.push(`回合 ${state.turn}`);
  meta.push(`种子 ${state.seed ?? "随机"}`);
  if (S.cfg?.monsters?.length) meta.push(`自定义组怪 × ${S.cfg.monsters.length}`);
  else if (S.cfg?.encounter) meta.push(S.cfg.encounter);
  $("#battle-meta").textContent = meta.join(" · ");

  renderEnemies(state);
  renderPlayer(state);
  renderHand(state);
  renderPiles(state);

  const canAct = state.input_state === "PLAYER_NORMAL" && !state.over;
  $("#end-turn-btn").disabled = !canAct;

  if (state.card_select) openCardSelectModal(state.card_select);
  else if (state.scry) openScryModal(state.scry);
  else hideModal();

  if (state.over) showResult(state);
}

function renderEnemies(state) {
  const box = $("#enemy-area");
  box.innerHTML = "";
  for (const m of state.monsters) {
    const d = el("div", "monster-card" + (m.alive && !m.escaping ? "" : " dead"));
    d.appendChild(el("div", "mname", m.zh));
    const stat = el("div", "mstat");
    stat.appendChild(el("span", null, `HP ${m.hp}/${m.max_hp}`));
    if (m.block > 0) stat.appendChild(el("span", "block", `格挡 ${m.block}`));
    d.appendChild(stat);
    d.appendChild(hpBar(m.hp, m.max_hp));
    d.appendChild(statusPills(m.statuses));
    if (m.intent && m.alive && !m.escaping) {
      const txt = m.intent.kind === "attack"
        ? `${m.intent.kind_zh}：${m.intent.zh}${m.intent.damage !== null ? ` ${m.intent.damage}` : ""}`
        : `${m.intent.kind_zh}：${m.intent.zh}${m.intent.text ? `（${m.intent.text}）` : ""}`;
      d.appendChild(el("div", `intent ${m.intent.kind}`, txt));
    }
    if (m.half_dead) d.appendChild(el("div", "hint", "（假死二阶段）"));
    if (m.escaping) d.appendChild(el("div", "hint", "（逃跑中）"));
    if (m.alive && !m.escaping && S.targeting) {
      d.classList.add("targetable");
      d.addEventListener("click", () => onTargetPick(m.pos));
    }
    box.appendChild(d);
  }
}

function renderPlayer(state) {
  const p = state.player;
  const box = $("#player-area");
  box.innerHTML = "";
  const top = el("div", "player-top");
  const hpWrap = el("div", "hp-wrap");
  hpWrap.appendChild(el("div", null, `HP ${p.hp}/${p.max_hp}`));
  hpWrap.appendChild(hpBar(p.hp, p.max_hp));
  top.appendChild(hpWrap);
  if (p.block > 0) top.appendChild(el("div", "big-stat block", `格挡 ${p.block}`));
  top.appendChild(el("div", "big-stat energy", `能量 ${p.energy}`));
  top.appendChild(el("div", null, `金币 ${p.gold}`));
  if (p.raw_stance !== "NEUTRAL") top.appendChild(el("div", null, `姿态：${p.stance}`));
  if (p.orbs.length || p.orb_slots) {
    const orbs = el("div", "orbs");
    for (const o of p.orbs) orbs.appendChild(el("div", "orb", o.slice(0, 1)));
    orbs.title = p.orbs.join("、") + `（槽位 ${p.orbs.length}/${p.orb_slots}${p.dark_stacks ? `，暗球存层 ${p.dark_stacks}` : ""}）`;
    top.appendChild(orbs);
  }
  box.appendChild(top);
  box.appendChild(statusPills(p.statuses));

  // 药水
  const belt = el("div", "potion-belt");
  belt.appendChild(el("span", null, "药水："));
  p.potions.forEach((pd, slot) => {
    if (!pd) {
      belt.appendChild(el("button", "potion-btn empty", `空槽 ${slot + 1}`));
      return;
    }
    const b = el("button", "potion-btn", pd.zh);
    b.title = pd.description;
    b.disabled = state.input_state !== "PLAYER_NORMAL" || state.over || pd.auto_only;
    b.addEventListener("click", () => onPotionClick(slot, pd));
    belt.appendChild(b);
    if (pd.choices && pd.choices.length) {
      const sel = document.createElement("select");
      sel.appendChild(new Option("wrath", "wrath"));
      sel.appendChild(new Option("calm", "calm"));
      sel.dataset.potionChoice = String(slot);
      belt.appendChild(sel);
    }
  });
  box.appendChild(belt);

  // 遗物
  if (state.relics.length) {
    const line = el("div", "relic-line");
    for (const r of state.relics) {
      const chip = el("span", "relic-chip", r.zh + (r.counter ? ` ${r.counter}` : ""));
      const tip = el("div", "tip", `${r.name}\n${r.text}`);
      chip.appendChild(tip);
      line.appendChild(chip);
    }
    box.appendChild(line);
  }
}

function renderHand(state) {
  const box = $("#hand");
  box.innerHTML = "";
  for (const c of state.hand) {
    const d = cardEl(c, { unplayable: !c.playable, reason: c.reason });
    d.addEventListener("click", () => onHandClick(c));
    box.appendChild(d);
  }
  if (!state.hand.length) box.appendChild(el("div", "hint", "（无手牌）"));
}

function renderPiles(state) {
  // 抽牌堆仅构成可见（信息边界）：按名称聚合 + 计数，不展示顺序；
  // 弃牌/消耗/保留区玩家可见，按实际顺序
  const fill = (detailsId, list, aggregated) => {
    const det = $(detailsId);
    const total = list.reduce((a, c) => a + (c.count || 1), 0);
    det.querySelector("[data-count]").textContent = String(total);
    const box = det.querySelector(".pile-list");
    box.innerHTML = "";
    if (aggregated) {
      box.appendChild(el("div", "pc hint2", "实际抽牌顺序不可见（按名称排序）"));
    }
    list.forEach((c) => {
      const pc = el("div", "pc");
      pc.appendChild(el("span", null, cardName(c) + (c.count > 1 ? ` ×${c.count}` : "")));
      pc.title = c.text;
      box.appendChild(pc);
    });
    if (!list.length) box.appendChild(el("div", "pc", "（空）"));
  };
  fill("#pile-draw", state.draw_pile, true);
  fill("#pile-discard", state.discard_pile, false);
  fill("#pile-exhaust", state.exhaust_pile, false);
  fill("#pile-limbo", state.limbo, false);
}

/* ---------------- 交互：出牌 / 药水 / 目标 ---------------- */

function targetableMonsters() {
  return (S.state?.monsters || []).filter((m) => m.alive && !m.escaping);
}

function onHandClick(c) {
  if (!c.playable) return;
  if (c.needs_target && targetableMonsters().length > 1) {
    S.targeting = { kind: "card", index: c.index };
    $("#targeting-banner").classList.remove("hidden");
    renderEnemies(S.state);
    return;
  }
  act({ type: "play", index: c.index });
}

function onPotionClick(slot, pd) {
  const choice = $(`select[data-potion-choice="${slot}"]`)?.value || null;
  if (pd.targeting && targetableMonsters().length > 1) {
    S.targeting = { kind: "potion", slot, choice };
    $("#targeting-banner").classList.remove("hidden");
    renderEnemies(S.state);
    return;
  }
  act({ type: "use_potion", slot, choice });
}

function onTargetPick(pos) {
  if (!S.targeting) return;
  if (S.targeting.kind === "card") {
    act({ type: "play", index: S.targeting.index, target: pos });
  } else {
    act({ type: "use_potion", slot: S.targeting.slot, target: pos, choice: S.targeting.choice });
  }
}

/* ---------------- 弹层：CARD_SELECT / SCRY ---------------- */

function hideModal() {
  $("#modal-overlay").classList.add("hidden");
}

function hideOverlays() {
  $("#modal-overlay").classList.add("hidden");
  $("#result-overlay").classList.add("hidden");
}

function openCardSelectModal(info) {
  S.selectSel = new Set();
  const overlay = $("#modal-overlay");
  $("#modal-title").textContent = "选卡";
  $("#modal-hint").textContent =
    `${info.prompt}（选 ${info.pick_count} 张${info.can_pick_any_number ? "，可选任意张" : ""}${info.can_pick_zero ? "，可空选" : ""}）`;
  const box = $("#modal-cards");
  box.innerHTML = "";
  const confirm = $("#modal-confirm");
  const refresh = () => {
    confirm.disabled = S.selectSel.size === 0 && !info.can_pick_zero;
    confirm.textContent = `确认（已选 ${S.selectSel.size}）`;
  };
  info.candidates.forEach((c, i) => {
    const d = cardEl(c);
    d.addEventListener("click", () => {
      if (S.selectSel.has(i)) S.selectSel.delete(i);
      else if (S.selectSel.size < info.pick_count || info.can_pick_any_number) S.selectSel.add(i);
      $$("#modal-cards .card").forEach((n, j) => n.classList.toggle("selected", S.selectSel.has(j)));
      refresh();
    });
    box.appendChild(d);
  });
  confirm.onclick = () => {
    if (S.selectSel.size === 0 && !info.can_pick_zero) return;
    // 展示序 → 引擎候选下标（展示按名称排序，不泄露抽牌堆内部顺序）
    const indices = [...S.selectSel].map((i) => info.candidates[i].engine_idx);
    act({ type: "choose_cards", indices });
    hideModal();
  };
  refresh();
  const skip = $("#modal-cancel");
  skip.classList.toggle("hidden", !info.can_pick_zero);
  skip.onclick = () => { act({ type: "choose_cards", indices: [] }); hideModal(); };
  overlay.classList.remove("hidden");
}

function openScryModal(cards) {
  // cards[0] = 堆顶；保留必须是前缀：keep_top_n
  S.scryKeep = cards.map(() => true);
  const overlay = $("#modal-overlay");
  $("#modal-title").textContent = "检视（Scry）";
  $("#modal-hint").textContent = "从堆顶往下逐张决定保留 / 弃置；保留的必须是顶部连续若干张。";
  const box = $("#modal-cards");
  box.innerHTML = "";
  const renders = cards.map((c, i) => {
    const d = cardEl(c);
    d.appendChild(el("div", "upg", i === 0 ? "堆顶" : `第 ${i + 1}`));
    const btns = el("div", "modal-controls");
    const bKeep = el("button", null, "保留");
    const bDisc = el("button", null, "弃置");
    const refresh = () => {
      d.classList.toggle("kept", S.scryKeep[i]);
      d.classList.toggle("discarded", !S.scryKeep[i]);
      bKeep.disabled = S.scryKeep[i];
      bDisc.disabled = !S.scryKeep[i];
    };
    bKeep.addEventListener("click", () => {
      // 保留第 i 张：上方全部强制保留
      for (let j = 0; j <= i; j++) S.scryKeep[j] = true;
      renders.forEach((r, j) => r.refresh(j));
    });
    bDisc.addEventListener("click", () => {
      // 弃置第 i 张：下方全部强制弃置
      for (let j = i; j < cards.length; j++) S.scryKeep[j] = false;
      renders.forEach((r, j) => r.refresh(j));
    });
    btns.append(bKeep, bDisc);
    d.appendChild(btns);
    box.appendChild(d);
    return { refresh };
  });
  renders.forEach((r, j) => r.refresh(j));
  const confirm = $("#modal-confirm");
  confirm.disabled = false;
  confirm.onclick = () => {
    const keep = S.scryKeep.filter(Boolean).length;
    act({ type: "scry", keep_top_n: keep });
    hideModal();
  };
  $("#modal-cancel").classList.add("hidden");
  overlay.classList.remove("hidden");
}

/* ---------------- 终局 / 错误 ---------------- */

function showResult(state) {
  const isWin = state.outcome === "PLAYER_VICTORY";
  const isEsc = state.outcome === "ESCAPED";
  $("#result-title").textContent = isWin ? "胜利！" : isEsc ? "已逃离" : "战败……";
  $("#result-title").style.color = isWin ? "#6fd08a" : isEsc ? "#e8c87a" : "#c94f4f";
  const p = state.player;
  $("#result-detail").textContent =
    `${state.turn} 回合 · 剩余 HP ${p.hp}/${p.max_hp}` + (isWin ? " · 铁甲开局遗物（若有）的回复已结算" : "");
  $("#result-overlay").classList.remove("hidden");
}

function showError(msg, sticky) {
  const banner = $("#error-banner");
  banner.textContent = msg;
  banner.classList.remove("hidden");
  if (!sticky) setTimeout(() => banner.classList.add("hidden"), 3500);
  else banner.addEventListener("click", () => banner.classList.add("hidden"), { once: true });
}

/* ---------------- 绑定 & 启动 ---------------- */

function bindBattleControls() {
  $("#end-turn-btn").addEventListener("click", () => act({ type: "end" }));
  $("#cancel-targeting").addEventListener("click", () => {
    S.targeting = null;
    $("#targeting-banner").classList.add("hidden");
    renderEnemies(S.state);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && S.targeting) {
      S.targeting = null;
      $("#targeting-banner").classList.add("hidden");
      renderEnemies(S.state);
    }
  });
  $("#restart-same").addEventListener("click", () => restart(true));
  $("#restart-new").addEventListener("click", () => restart(false));
  $("#back-to-setup").addEventListener("click", () => {
    hideOverlays();
    $("#battle-view").classList.add("hidden");
    $("#setup-view").classList.remove("hidden");
    S.battleId = null; S.state = null;
  });
  $("#result-close").addEventListener("click", () => $("#result-overlay").classList.add("hidden"));
  $("#result-restart").addEventListener("click", () => restart(true));
}

async function boot() {
  const res = await fetch("/api/meta").then((r) => r.json());
  Object.assign(META, res);
  setupInit();
  bindBattleControls();
}

boot();
