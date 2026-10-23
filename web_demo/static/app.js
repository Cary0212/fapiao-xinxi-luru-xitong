const state = { jobId: null, job: null, selectedId: null, polling: null };
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[char]));
const money = (value) => {
  const number = Number(value);
  return Number.isFinite(number) ? `¥${number.toFixed(2)}` : "待核对";
};
const selectedReceipt = () => state.job?.receipts.find((receipt) => receipt.id === state.selectedId);

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast${isError ? " error" : ""}`;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 4800);
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const body = await response.json();
      message = Array.isArray(body.detail) ? body.detail.join("；") : (body.detail || message);
    } catch { /* retain the status message */ }
    throw new Error(message);
  }
  return response;
}

function setWorkflow(stage) {
  document.querySelectorAll(".workflow .step").forEach((step, index) => {
    step.classList.toggle("active", index <= stage);
  });
}

function renderSummary() {
  const receipts = state.job?.receipts || [];
  const shopping = receipts.filter((receipt) => receipt.kind === "shopping");
  const taxi = receipts.filter((receipt) => receipt.kind === "taxi");
  const sum = (items) => items.reduce((total, receipt) => total + (Number(receipt.final_amount) || 0), 0);
  $("countValue").innerHTML = `${receipts.length} <small>张</small>`;
  $("shoppingValue").textContent = money(sum(shopping));
  $("taxiValue").textContent = money(sum(taxi));
  $("totalValue").textContent = money(sum(receipts));
}

function renderList() {
  const job = state.job;
  const receipts = job?.receipts || [];
  $("listSubtitle").textContent = job ? `本批次 ${receipts.length} 张票据` : "上传后在这里查看识别结果";
  const badge = $("progressBadge");
  if (!job) { badge.textContent = "待上传"; badge.className = "badge"; }
  else if (job.status === "processing") { badge.textContent = `识别中 ${job.processed}/${job.total}`; badge.className = "badge warn"; }
  else if (job.status === "failed") { badge.textContent = "识别失败"; badge.className = "badge warn"; }
  else { badge.textContent = "可核对"; badge.className = "badge good"; }
  if (!receipts.length) {
    $("receiptList").innerHTML = job?.status === "processing"
      ? '<div class="empty-state"><span class="empty-glyph">◌</span><strong>正在识别 PDF</strong><p>扫描件需要一些时间，请稍候。</p></div>'
      : '<div class="empty-state"><span class="empty-glyph">▤</span><strong>尚无票据</strong><p>上传 PDF 后，识别结果会显示在这里。</p></div>';
  } else {
    $("receiptList").innerHTML = receipts.map((receipt, index) => `
      <button class="receipt-card ${receipt.id === state.selectedId ? "selected" : ""}" data-receipt-id="${escapeHtml(receipt.id)}" type="button">
        <div class="receipt-card-top"><span class="receipt-card-title">${escapeHtml(receipt.merchant || receipt.source_name || `票据 ${index + 1}`)}</span><span class="receipt-card-type">${receipt.kind === "taxi" ? "出租车" : "购物小票"}</span></div>
        <div class="receipt-card-bottom"><span>${escapeHtml(receipt.date || "日期待核对")} · ${escapeHtml(receipt.source_name)}</span><strong>${receipt.final_amount ? money(receipt.final_amount) : '<span class="warning-dot">金额待核对</span>'}</strong></div>
      </button>`).join("");
  }
  const errors = job?.errors || [];
  $("errorList").hidden = errors.length === 0;
  $("errorList").innerHTML = errors.map((error) => `<p>${escapeHtml(error)}</p>`).join("");
  $("exportButton").disabled = !job || job.status !== "ready" || receipts.length === 0;
}

function renderPreview() {
  const receipt = selectedReceipt();
  $("sourceLabel").textContent = receipt ? `${receipt.source_name} · 第${receipt.page_number}页` : "—";
  $("previewBody").innerHTML = receipt
    ? `<img src="${escapeHtml(receipt.preview_url)}" alt="${escapeHtml(receipt.source_name)} 第 ${receipt.page_number} 页票据预览">`
    : '<div class="empty-preview"><span>PDF</span><p>选择左侧票据后显示原件</p></div>';
}

function field(label, name, value, options = {}) {
  const type = options.type || "text";
  const hint = options.hint ? `<span class="field-hint">${escapeHtml(options.hint)}</span>` : "";
  return `<div class="field"><label for="field-${name}">${escapeHtml(label)}</label><input id="field-${name}" name="${name}" type="${type}" value="${escapeHtml(value)}" ${options.step ? `step="${options.step}"` : ""}>${hint}</div>`;
}

function renderEditor() {
  const receipt = selectedReceipt();
  if (!receipt) {
    $("reviewBadge").textContent = "未选择";
    $("reviewBadge").className = "badge muted";
    $("editorBody").innerHTML = '<div class="empty-state"><span class="empty-glyph">✎</span><strong>等待选择票据</strong><p>选择左侧一张票据开始核对。</p></div>';
    return;
  }
  $("reviewBadge").textContent = receipt.reviewed ? "已核对" : "待核对";
  $("reviewBadge").className = receipt.reviewed ? "badge good" : "badge warn";
  const warnings = receipt.warnings?.length
    ? `<div class="warning-box"><strong>原始识别提示</strong><ul>${receipt.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul></div>` : "";
  const shopping = receipt.kind === "shopping";
  const items = receipt.items || [];
  const itemRows = items.map((item, index) => `
    <div class="item-row" data-item-index="${index}">
      <div class="item-row-head"><span>商品 ${index + 1}</span><button class="button button-danger remove-item" type="button" data-index="${index}">删除</button></div>
      ${field("商品名称", `item-name-${index}`, item.name)}
      <div class="field-grid">
        ${field("单价 (¥)", `item-price-${index}`, item.unit_price, {type:"number",step:"0.01"})}
        ${field("数量", `item-quantity-${index}`, item.quantity, {type:"number",step:"any"})}
        ${field("单位", `item-unit-${index}`, item.unit)}
      </div>
    </div>`).join("");
  $("editorBody").innerHTML = `
    <form class="editor-form" id="receiptForm">
      ${warnings}
      <section class="form-section"><h3 class="form-section-title">票据类别与来源</h3>
        <div class="field"><label for="field-kind">票据类型</label><select id="field-kind" name="kind"><option value="shopping" ${shopping ? "selected" : ""}>购物小票</option><option value="taxi" ${!shopping ? "selected" : ""}>出租车发票</option></select></div>
        ${field("商户 / 开具方", "merchant", receipt.merchant)}
        ${shopping ? field("地址（Word 模板字段）", "address", receipt.address, {hint:"原票没有详细地址时，可填写“原票未载明”。"}) : ""}
        <div class="field-grid">${field("日期", "date", receipt.date, {type:"date"})}${field("时间", "time", receipt.time)}</div>
        <div class="field-grid">${field(shopping ? "票号 / 流水号" : "发票号码", "number", receipt.number)}${shopping ? "" : field("发票代码", "invoice_code", receipt.invoice_code)}</div>
      </section>
      <section class="form-section"><h3 class="form-section-title">金额与支付</h3>
        ${shopping ? `<div class="field-grid">${field("商品原价合计 (¥)", "gross_amount", receipt.gross_amount, {type:"number",step:"0.01"})}${field("商家优惠 (¥)", "merchant_discount", receipt.merchant_discount, {type:"number",step:"0.01"})}</div>
        <div class="field-grid">${field("支付渠道优惠 (¥)", "payment_discount", receipt.payment_discount, {type:"number",step:"0.01"})}${field("支付方式", "payment_method", receipt.payment_method)}</div>` : ""}
        ${field(shopping ? "最终应收 / 实付金额 (¥)" : "金额 (¥)", "final_amount", receipt.final_amount, {type:"number",step:"0.01",hint:"Word 中填入此金额。"})}
      </section>
      ${shopping ? `<section class="form-section"><h3 class="form-section-title">商品明细</h3>${itemRows}<div class="item-actions"><button class="button button-quiet" id="addItemButton" type="button">＋ 添加商品</button></div></section>` : ""}
      <details class="raw-details"><summary>查看 OCR 原文</summary><pre>${escapeHtml(receipt.raw_text || "")}</pre></details>
    </form>
    <div class="editor-footer"><label class="review-check"><input id="reviewedCheck" type="checkbox" ${receipt.reviewed ? "checked" : ""}>已对照原票核对</label><button class="button button-primary" id="saveButton" type="button">保存修改</button></div>`;
}

function collectEditor() {
  const receipt = selectedReceipt();
  const form = $("receiptForm");
  if (!receipt || !form) return null;
  const value = (name) => form.elements.namedItem(name)?.value ?? "";
  const payload = {
    kind: value("kind"), merchant: value("merchant"), date: value("date"), time: value("time"),
    number: value("number"), final_amount: value("final_amount"), reviewed: $("reviewedCheck").checked,
  };
  if (payload.kind === "shopping") {
    Object.assign(payload, {
      address: value("address"), gross_amount: value("gross_amount"), merchant_discount: value("merchant_discount"),
      payment_discount: value("payment_discount"), payment_method: value("payment_method"),
      items: (receipt.items || []).map((_, index) => ({
        name: value(`item-name-${index}`), unit_price: value(`item-price-${index}`),
        quantity: value(`item-quantity-${index}`), unit: value(`item-unit-${index}`),
      })),
    });
  } else {
    payload.invoice_code = value("invoice_code");
  }
  return payload;
}

async function saveCurrent(silent = false) {
  const receipt = selectedReceipt();
  if (!receipt) return;
  const payload = collectEditor();
  if (!payload) return;
  const response = await request(`/api/jobs/${state.jobId}/receipts/${receipt.id}`, {
    method: "PUT", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload),
  });
  const saved = await response.json();
  Object.assign(receipt, saved);
  renderSummary(); renderList();
  if (!silent) { renderEditor(); toast("修改已保存"); }
}

async function selectReceipt(id) {
  if (state.selectedId === id) return;
  try { await saveCurrent(true); } catch (error) { toast(error.message, true); return; }
  state.selectedId = id;
  renderList(); renderPreview(); renderEditor();
}

async function refreshJob() {
  if (!state.jobId) return;
  try {
    const response = await request(`/api/jobs/${state.jobId}`);
    state.job = await response.json();
    if (!state.selectedId || !state.job.receipts.some((receipt) => receipt.id === state.selectedId)) {
      state.selectedId = state.job.receipts[0]?.id || null;
    }
    renderSummary(); renderList(); renderPreview(); renderEditor();
    if (state.job.status !== "processing") {
      clearInterval(state.polling); state.polling = null;
      setWorkflow(state.job.receipts.length ? 1 : 0);
      if (state.job.status === "ready") toast(`已识别 ${state.job.receipts.length} 张票据，请核对后导出`);
      else toast("没有识别出可用票据，请检查上传文件", true);
    }
  } catch (error) {
    clearInterval(state.polling); state.polling = null;
    toast(error.message, true);
  }
}

async function uploadFiles(files) {
  const selected = [...files].filter((file) => file.name.toLowerCase().endsWith(".pdf"));
  if (!selected.length) { toast("请选择 PDF 文件", true); return; }
  if (selected.length !== files.length) { toast("已忽略非 PDF 文件"); }
  const data = new FormData();
  selected.forEach((file) => data.append("files", file));
  $("selectButton").disabled = true;
  $("selectButton").textContent = "上传中…";
  try {
    const response = await request("/api/upload", {method:"POST", body:data});
    const result = await response.json();
    state.jobId = result.job_id; state.selectedId = null; state.job = null;
    location.hash = result.job_id;
    clearInterval(state.polling);
    await refreshJob();
    if (state.job?.status === "processing") state.polling = setInterval(refreshJob, 1400);
    if (state.job?.status === "processing") setWorkflow(0);
  } catch (error) { toast(error.message, true); }
  finally { $("selectButton").disabled = false; $("selectButton").textContent = "选择 PDF"; $("fileInput").value = ""; }
}

async function exportWord() {
  try {
    await saveCurrent(true);
    $("exportButton").disabled = true;
    const response = await request(`/api/jobs/${state.jobId}/export`, {method:"POST"});
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `发票信息汇总_${new Date().toISOString().slice(0,10)}.docx`;
    document.body.appendChild(link);
    link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    setWorkflow(2);
    toast("Word 文档已开始下载");
  } catch (error) { toast(error.message, true); }
  finally { $("exportButton").disabled = !state.job || state.job.status !== "ready"; }
}

$("selectButton").addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", (event) => uploadFiles(event.target.files));
$("exportButton").addEventListener("click", exportWord);
$("receiptList").addEventListener("click", (event) => {
  const card = event.target.closest("[data-receipt-id]");
  if (card) selectReceipt(card.dataset.receiptId);
});
$("editorBody").addEventListener("click", (event) => {
  if (event.target.id === "saveButton") saveCurrent().catch((error) => toast(error.message, true));
  if (event.target.id === "addItemButton") {
    const receipt = selectedReceipt();
    Object.assign(receipt, collectEditor());
    receipt.items.push({name:"",unit_price:"",quantity:"1",unit:"件"});
    renderEditor();
  }
  if (event.target.classList.contains("remove-item")) {
    const receipt = selectedReceipt();
    Object.assign(receipt, collectEditor());
    receipt.items.splice(Number(event.target.dataset.index), 1);
    renderEditor();
  }
});
$("editorBody").addEventListener("change", (event) => {
  if (event.target.id === "field-kind") {
    const receipt = selectedReceipt();
    Object.assign(receipt, collectEditor());
    renderEditor();
  }
});
const uploadArea = $("uploadArea");
for (const eventName of ["dragenter", "dragover"]) uploadArea.addEventListener(eventName, (event) => { event.preventDefault(); uploadArea.classList.add("drag-over"); });
for (const eventName of ["dragleave", "drop"]) uploadArea.addEventListener(eventName, (event) => { event.preventDefault(); uploadArea.classList.remove("drag-over"); });
uploadArea.addEventListener("drop", (event) => uploadFiles(event.dataTransfer.files));
if (/^[0-9a-f]{32}$/.test(location.hash.slice(1))) {
  state.jobId = location.hash.slice(1);
  refreshJob().then(() => { if (state.job?.status === "processing") state.polling = setInterval(refreshJob, 1400); });
}
