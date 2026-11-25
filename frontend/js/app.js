/* DOC-SECURE role dashboards and seven-stage request flow. */
(() => {
  const role = document.body.dataset.role || "student";
  const app = document.getElementById("app");
  const localHost = ["localhost", "127.0.0.1"].includes(location.hostname);
  const API = window.PORTAL_API_BASE || (localHost ? "http://localhost:8001" : "");
  const roleName = { student: "Student", cashier: "Cashier", registrar: "Registrar" };
  const stageNames = ["Sign in", "Checklist", "Payment", "Review", "Approval", "QR scan", "Claim"];
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const money = (value) => new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP", maximumFractionDigits: 2 }).format(value || 0);
  const token = () => sessionStorage.getItem("portal_access_token");

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (token()) headers.Authorization = `Bearer ${token()}`;
    if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const response = await fetch(`${API}${path}`, { ...options, credentials: "include", headers });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      const error = new Error(result.detail || `Request failed (${response.status}).`);
      error.status = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  }

  function loginView(error = "") {
    const settings = {
      student: ["Student ID", "e.g. 2024-01842", "Your campus, at your pace.", null],
      cashier: ["Cashier employee ID", "e.g. EMP-00421", "Every detail, in balance.", ["Terminal PIN", "terminalPin"]],
      registrar: ["Registrar staff ID", "e.g. REG-00158", "Good records move us forward.", ["Security token", "securityToken"]]
    }[role];
    document.title = "DOC-SECURE | University of the Assumption";
    app.innerHTML = `<main class="login-screen"><section class="login-aside"><a class="brand" href="index.html"><span class="brand-mark">UA</span><span>DOC-SECURE <small>UNIVERSITY OF THE ASSUMPTION</small></span></a><div class="login-aside-copy"><div class="eyebrow"><span class="eyebrow-line"></span> ${role.toUpperCase()} PORTAL</div><h1>${settings[2]}</h1><p>Request and verify official university documents in one secure workflow.</p></div><div class="login-aside-foot">University of the Assumption · DOC-SECURE</div></section><section class="login-card-wrap"><div class="login-card"><a class="back-link" href="../../index.html">← &nbsp; All portals</a><h2>Welcome back</h2><p class="login-subtitle">Sign in to your ${roleName[role].toLowerCase()} account.</p><form id="login-form"><label class="form-field"><span>${settings[0]}</span><input type="text" name="identifier" required autocomplete="username" placeholder="${settings[1]}"></label>${settings[3] ? `<label class="form-field"><span>${settings[3][0]}</span><input type="text" name="${settings[3][1]}" required autocomplete="one-time-code"></label>` : ""}<label class="form-field"><span>Password</span><div class="password-wrap"><input name="password" required type="password" autocomplete="current-password"><button type="button" class="toggle-password" id="toggle-password">Show</button></div></label><p class="login-error" role="alert">${esc(error)}</p><button class="login-submit">Sign in to ${roleName[role].toLowerCase()} portal &nbsp; →</button></form><p class="login-secure">⌑ &nbsp; Protected role-based access</p></div></section></main>`;
    document.getElementById("toggle-password").addEventListener("click", (event) => {
      const input = document.querySelector(".password-wrap input");
      input.type = input.type === "password" ? "text" : "password";
      event.currentTarget.textContent = input.type === "password" ? "Show" : "Hide";
    });
    document.getElementById("login-form").addEventListener("submit", signIn);
  }

  async function signIn(event) {
    event.preventDefault();
    const button = event.currentTarget.querySelector(".login-submit");
    button.disabled = true;
    button.textContent = "Signing in…";
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const result = await api(`/api/auth/${role}`, { method: "POST", body: JSON.stringify(values) });
      sessionStorage.setItem("portal_access_token", result.access_token);
      location.href = `../../${role}.html`;
    } catch (error) { loginView(error.message); }
  }

  async function imagePayload(file) {
    if (!file) throw new Error("Choose a screenshot of your payment receipt.");
    if (file.size > 2 * 1024 * 1024) throw new Error("The screenshot must be 2 MB or smaller.");
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let start = 0; start < bytes.length; start += 0x8000) binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
    return { proofFilename: file.name, proofMime: file.type, proofBase64: btoa(binary) };
  }

  function statusLabel(status) {
    return ({ PENDING_PAYMENT_REVIEW: "Pending cashier review", PENDING_REGISTRAR_REVIEW: "Pending registrar review", APPROVED: "Approved · ready for QR", REJECTED: "Changes requested", CLAIMED: "Claimed" })[status] || status;
  }

  function workflow() {
    return `<ol class="workflow-ribbon">${stageNames.map((name, i) => `<li><span>${i + 1}</span><small>${name}</small></li>`).join("")}</ol>`;
  }

  function shell(user, content, active) {
    const nav = role === "student" ? [["overview", "Overview"], ["request-form", "Request a document"], ["my-requests", "My requests"]]
      : role === "cashier" ? [["payment-queue", "Payment review"], ["account-lookup", "Student lookup"]]
        : [["registrar-queue", "Request review"], ["counter-scanner", "Counter scanner"], ["audit-trail", "Audit trail"]];
    app.innerHTML = `<div class="workspace"><aside class="sidebar"><a class="brand" href="index.html"><span class="brand-mark">UA</span><span>DOC-SECURE <small>UNIVERSITY OF THE ASSUMPTION</small></span></a><div class="side-label">${roleName[role].toUpperCase()} WORKSPACE</div><nav class="side-nav">${nav.map(([id, label], index) => `<a href="#${id}" class="${active === id ? "active" : ""}"><span>${["⌂", "▤", "◉"][index % 3]}</span>${label}</a>`).join("")}</nav><div class="side-bottom"><div class="help-box"><strong>Seven clear steps</strong><p>From the request checklist to secure document release.</p><a href="#workflow">View request flow ↓</a></div><div class="user-mini"><span class="avatar">${esc(user.name.split(" ").map((part) => part[0]).slice(0, 2).join(""))}</span><span>${esc(user.name)}<small>${roleName[role]} account</small></span></div></div></aside><section class="main-area"><header class="topbar"><div class="breadcrumbs">University of the Assumption &nbsp; / &nbsp; <b>${roleName[role]} workspace</b></div><div class="topbar-right"><span>DOC-SECURE</span><button class="sign-out" id="sign-out" type="button">Sign out</button></div></header><main class="dashboard"><div class="welcome-row"><div><div class="eyebrow"><span class="eyebrow-line"></span> SECURE DOCUMENT SERVICES</div><h1>${esc(user.greeting || `Welcome, ${user.name.split(" ")[0]}.`)}</h1><p>${esc(user.program || "Encrypted QR document requests · UA Registrar's Office")}</p></div><div class="date-chip">${new Intl.DateTimeFormat("en-PH", { dateStyle: "medium" }).format(new Date())}</div></div><section id="workflow" class="workflow-panel"><div class="panel-heading"><h2>Request lifecycle</h2><span class="small-muted">Seven stages · live status</span></div>${workflow()}</section>${content}</main></section></div><div class="toast" role="status" aria-live="polite"></div>`;
    app.querySelectorAll(".side-nav a,.help-box a").forEach((link) => link.addEventListener("click", (event) => {
      const target = document.querySelector(link.getAttribute("href"));
      if (target) { event.preventDefault(); target.scrollIntoView({ behavior: "smooth", block: "start" }); }
    }));
    document.getElementById("sign-out").addEventListener("click", () => {
      sessionStorage.removeItem("portal_access_token");
      location.href = `login/${role}/`;
    });
  }

  function toast(message) {
    const node = document.querySelector(".toast");
    if (!node) return;
    node.textContent = message;
    node.classList.add("visible");
    clearTimeout(window.portalToastTimer);
    window.portalToastTimer = setTimeout(() => node.classList.remove("visible"), 3500);
  }

  async function studentDashboard(user) {
    const [profile, options, requests] = await Promise.all([
      api("/api/students/me"), api("/api/students/me/document-options"), api("/api/students/me/requests")
    ]);
    const requestRows = requests.map(requestCard).join("") || `<div class="empty-state"><span>▤</span><strong>No requests yet</strong><p>Your document requests and their review progress will appear here.</p></div>`;
    shell({ ...user, name: profile.name, program: profile.program, greeting: `Good morning, ${profile.name.split(" ")[0]}.` },
      `<div class="stats-grid">${stat("ENROLLMENT", profile.enrollment_status, profile.program, "✓")}${stat("REQUESTS IN PROGRESS", requests.filter((r) => !["CLAIMED", "REJECTED"].includes(r.status)).length, "Follow review status below", "◷")}${stat("ACTIVE CLEARANCE FLAGS", options.holds.length, options.holds.length ? "Undertaking required for requests" : "No outstanding prerequisites", "!")}</div><div class="content-grid request-content"><div><section class="panel" id="request-form-panel"><div class="panel-heading"><div><h2>Start a document request</h2><p class="panel-subtitle">Choose documents, attach payment proof and submit your OR number.</p></div><span class="badge">STAGE 2–3</span></div>${options.holds.length ? `<div class="notice alert-notice"><strong>Clearance check</strong><span>${options.holds.map(esc).join(" · ")}</span><details><summary>Review digital undertaking</summary><p>${esc(options.undertakingText)}</p></details><label class="undertaking-check"><input id="undertaking-signed" type="checkbox"><span>I have read and agree to the digital undertaking.</span></label></div>` : `<div class="notice">Your prerequisite check is clear. Select the documents you need.</div>`}<form id="request-form"><fieldset class="document-options"><legend>Available documents</legend>${options.documents.map(doc => `<div class="document-option"><input type="checkbox" name="documentIds" value="${esc(doc.id)}" data-fee="${doc.fee}"><span><strong>${esc(doc.name)}</strong><small>${esc(doc.prerequisite)}</small><em>${money(doc.fee)} per paper</em></span><label class="quantity-control"><span>Paper count (max 10)</span><input type="number" name="quantity-${esc(doc.id)}" min="1" max="10" value="1" disabled></label></div>`).join("")}</fieldset><div class="paper-count"><span>Total papers (maximum 10 per request)</span><strong id="selected-paper-count">0 / 10</strong></div><div class="request-total"><span>Request total</span><strong id="request-total">${money(0)}</strong></div><div class="form-grid"><label class="form-field"><span>Official Receipt (OR) number</span><input name="orNumber" required placeholder="Enter the payment receipt reference"></label><label class="form-field"><span>Payment screenshot</span><input name="proof" type="file" accept="image/png,image/jpeg,image/webp" required><small>PNG, JPG, or WebP · up to 2 MB</small></label></div><p class="form-error" id="request-error" role="alert"></p><button class="button-small" type="submit">Submit request for payment review &nbsp; →</button></form></section></div><div><section class="panel profile-panel"><div class="panel-heading"><h2>Student profile</h2><span class="badge">${esc(profile.enrollment_status.toUpperCase())}</span></div><div class="profile-row"><span class="profile-avatar">${esc(profile.name.split(" ").map((part) => part[0]).slice(0, 2).join(""))}</span><div><strong>${esc(profile.name)}</strong><p>${esc(profile.program)}</p></div></div><div class="detail-grid"><div><div class="detail-label">STUDENT ID</div><div class="detail-value">${esc(profile.student_id)}</div></div><div><div class="detail-label">UNITS</div><div class="detail-value">${profile.units}</div></div></div></section><section class="panel"><div class="panel-heading"><h2>Payment &amp; OR review</h2><span class="badge pending">WAIT STATE</span></div><p class="panel-copy">After submission, the cashier reviews your receipt and OR reference. The registrar then checks your request and clearance before approving QR generation.</p><div class="mini-flow"><span>Upload proof</span><b>→</b><span>Cashier review</span><b>→</b><span>Registrar decision</span></div></section></div></div><section id="my-requests" class="panel requests-panel"><div class="panel-heading"><div><h2>My document requests</h2><p class="panel-subtitle">Rejection notices include what to correct. Approved requests unlock one-time QR codes.</p></div><button class="subtle-button" id="refresh-requests">Refresh status</button></div><div id="request-list" class="request-list">${requestRows}</div></section>`, "request-form-panel");
    document.querySelectorAll("input[name=documentIds]").forEach((input) => input.addEventListener("change", () => {
      const quantity = input.closest(".document-option").querySelector('input[type="number"]');
      quantity.disabled = !input.checked;
      updateTotal();
    }));
    document.querySelectorAll(".quantity-control input").forEach((input) => input.addEventListener("input", updateTotal));
    document.getElementById("request-form").addEventListener("submit", (event) => submitRequest(event, options));
    document.getElementById("refresh-requests").addEventListener("click", () => studentDashboard(user).catch(showError));
    requests.forEach(request => attachRequestActions(request, options));
    const undertakingDetails = document.querySelector(".notice details");
    if (undertakingDetails) {
      const agreementText = undertakingDetails.querySelector("p").textContent;
      const reviewButton = document.createElement("button");
      reviewButton.type = "button";
      reviewButton.className = "subtle-button review-undertaking";
      reviewButton.textContent = "Review and sign digital undertaking";
      undertakingDetails.replaceWith(reviewButton);
      const signatureBox = document.getElementById("undertaking-signed");
      signatureBox.disabled = true;
      signatureBox.nextElementSibling.textContent = "Agreement not yet signed";
      const dialog = document.createElement("dialog");
      dialog.className = "undertaking-dialog";
      dialog.innerHTML = `<div class="dialog-kicker">CLEARANCE AGREEMENT</div><h2>Digital undertaking</h2><p class="dialog-copy">${esc(agreementText)}</p><label class="undertaking-check"><input id="agreement-accepted" type="checkbox"><span>I understand and accept these terms.</span></label><div class="dialog-actions"><button type="button" class="subtle-button" id="cancel-agreement">Go back</button><button type="button" class="button-small" id="accept-agreement" disabled>Sign and accept</button></div>`;
      app.append(dialog);
      reviewButton.addEventListener("click", () => dialog.showModal());
      dialog.querySelector("#cancel-agreement").addEventListener("click", () => dialog.close());
      dialog.querySelector("#agreement-accepted").addEventListener("change", (event) => { dialog.querySelector("#accept-agreement").disabled = !event.currentTarget.checked; });
      dialog.querySelector("#accept-agreement").addEventListener("click", () => {
        signatureBox.checked = true;
        signatureBox.nextElementSibling.textContent = "Digital undertaking signed";
        dialog.close();
      });
    }
  }

  function stat(label, value, foot, icon) {
    return `<article class="stat-card"><div class="stat-head"><span>${esc(label)}</span><span class="stat-icon">${esc(icon)}</span></div><div class="stat-value">${esc(value)}</div><div class="stat-foot">${esc(foot)}</div></article>`;
  }

  function updateTotal() {
    const selected = [...document.querySelectorAll("input[name=documentIds]:checked")].reduce((total, input) => {
      const quantity = Number(input.closest(".document-option").querySelector('input[type="number"]').value) || 1;
      total.papers += quantity;
      total.amount += Number(input.dataset.fee) * quantity;
      return total;
    }, { papers: 0, amount: 0 });
    const target = document.getElementById("request-total");
    if (target) target.textContent = money(selected.amount);
    const paperCount = document.getElementById("selected-paper-count");
    if (paperCount) paperCount.textContent = `${selected.papers} / 10`;
  }

  async function submitRequest(event, options, requestId = null) {
    event.preventDefault();
    const form = event.currentTarget;
    const error = form.querySelector(".form-error") || document.getElementById("request-error");
    error.textContent = "";
    const selected = [...form.querySelectorAll("input[name=documentIds]:checked")].map((input) => input.value);
    const quantities = Object.fromEntries(selected.map((documentId) => {
      const input = form.querySelector(`[name="quantity-${CSS.escape(documentId)}"]`);
      return [documentId, Number(input?.value)];
    }));
    const file = form.querySelector('input[name="proof"]')?.files[0];
    if (!requestId && !selected.length) { error.textContent = "Select at least one document."; return; }
    if (!requestId && Object.values(quantities).some((quantity) => !Number.isInteger(quantity) || quantity < 1 || quantity > 10)) {
      error.textContent = "Choose between 1 and 10 papers for each selected document."; return;
    }
    if (!requestId && Object.values(quantities).reduce((sum, quantity) => sum + quantity, 0) > 10) {
      error.textContent = "A request can include at most 10 papers total."; return;
    }
    const undertakingField = form.querySelector('[name="undertakingSigned"]') || document.getElementById("undertaking-signed");
    const undertakingAccepted = undertakingField?.type === "checkbox" ? undertakingField.checked : undertakingField?.value === "true";
    if (options.undertakingRequired && !undertakingAccepted) { error.textContent = "Accept the digital undertaking to continue."; return; }
    try {
      const proof = await imagePayload(file);
      const body = { ...proof, orNumber: new FormData(form).get("orNumber"), undertakingSigned: Boolean(undertakingAccepted), undertakingVersion: options.undertakingVersion };
      if (!requestId) { body.documentIds = selected; body.documentQuantities = quantities; }
      const path = requestId ? `/api/students/requests/${encodeURIComponent(requestId)}/resubmit` : "/api/students/requests";
      await api(path, { method: "POST", body: JSON.stringify(body) });
      toast(requestId ? "Updated receipt proof submitted." : "Request submitted for cashier review.");
      await studentDashboard({ name: "Student" });
    } catch (failure) { error.textContent = failure.message; }
  }

  function requestCard(request) {
    const rejection = request.rejectionReason ? `<div class="notice alert-notice"><strong>Correction needed · ${esc(request.rejectionStage || "review")}</strong><span>${esc(request.rejectionReason)}</span></div>` : "";
    const qr = request.status === "APPROVED" ? `<div class="qr-request" id="qr-${esc(request.id)}"><button class="button-small" data-qr="${esc(request.id)}">Generate one-time encrypted QR</button><p class="small-muted">Expires in 5 minutes and is single-use.</p></div>` : "";
    const resubmit = request.status === "REJECTED" ? `<form class="resubmit-form" data-resubmit="${esc(request.id)}"><h3>Upload corrected payment proof</h3><input name="orNumber" required placeholder="Updated OR number"><input name="proof" type="file" accept="image/png,image/jpeg,image/webp" required><label class="undertaking-check"><input type="checkbox" ${request.undertakingSigned ? "checked" : ""}><span>Confirm the digital undertaking</span></label><p class="form-error" role="alert"></p><button class="button-small outline">Resubmit proof</button></form>` : "";
    return `<article class="request-card"><div class="request-card-head"><div><span class="request-id">REQUEST ${esc(request.id.slice(0, 8).toUpperCase())}</span><h3>${esc(request.documents.join(", "))}</h3></div><span class="status-pill status-${esc(request.status.toLowerCase())}">${esc(statusLabel(request.status))}</span></div><div class="request-facts"><span>Submitted ${esc(new Date(request.createdAt).toLocaleString("en-PH"))}</span><span>OR ${esc(request.orNumber)}</span><span>${money(request.amount)}</span></div>${rejection}${qr}${resubmit}</article>`;
  }

  function attachRequestActions(request, options) {
    document.querySelector(`[data-qr="${CSS.escape(request.id)}"]`)?.addEventListener("click", () => generateRequestQr(request.id));
    const form = document.querySelector(`[data-resubmit="${CSS.escape(request.id)}"]`);
    form?.addEventListener("submit", (event) => {
      const checkbox = form.querySelector('input[type="checkbox"]');
      const hidden = document.createElement("input"); hidden.type = "hidden"; hidden.name = "undertakingSigned"; hidden.value = String(checkbox.checked);
      form.append(hidden);
      submitRequest(event, options, request.id);
    });
  }

  async function generateRequestQr(requestId) {
    const target = document.getElementById(`qr-${requestId}`);
    try {
      const response = await api(`/api/students/requests/${encodeURIComponent(requestId)}/qr`, { method: "POST" });
      target.innerHTML = `<div class="qr-output" id="qr-output-${esc(requestId)}"></div><p class="qr-help">Encrypted request details · single-use · expires in 5 minutes</p><p class="backup-code-display"><strong>Camera backup code</strong><code>${esc(response.backupCode)}</code><small>Give this code to the registrar if the QR cannot be scanned. It expires with the QR and works once.</small></p><button class="button-small outline" data-download="${esc(requestId)}">Download QR and backup code</button>`;
      if (!window.QRCode) throw new Error("QR library unavailable. The backup code is ready to use at the registrar counter.");
      const qrNode = document.getElementById(`qr-output-${requestId}`);
      new QRCode(qrNode, { text: JSON.stringify(response.payload), width: 440, height: 440, correctLevel: QRCode.CorrectLevel.M, colorDark: "#003366", colorLight: "#ffffff" });
      document.querySelector(`[data-download="${CSS.escape(requestId)}"]`).addEventListener("click", () => {
        const qrCanvas = qrNode.querySelector("canvas");
        if (!qrCanvas) return;
        const exportCanvas = document.createElement("canvas");
        exportCanvas.width = 480; exportCanvas.height = 540;
        const context = exportCanvas.getContext("2d");
        context.fillStyle = "#ffffff"; context.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
        context.drawImage(qrCanvas, 20, 20, 440, 440);
        context.fillStyle = "#003366"; context.textAlign = "center";
        context.font = "bold 13px sans-serif"; context.fillText("BACKUP CODE · EXPIRES IN 5 MINUTES", 240, 485);
        context.font = "bold 22px monospace"; context.fillText(response.backupCode, 240, 520);
        const link = document.createElement("a"); link.download = "DOC-SECURE_QR_and_Backup_Code.png"; link.href = exportCanvas.toDataURL("image/png"); link.click();
      });
    } catch (error) { toast(error.message); }
  }

  async function cashierDashboard(user) {
    const queue = await api("/api/cashier/payment-queue");
    const queueHtml = queue.map((request) => `<article class="review-card"><div class="request-card-head"><div><span class="request-id">${esc(request.studentName)} · ${esc(request.studentId)}</span><h3>${esc(request.documents.join(", "))}</h3></div><span class="badge pending">PAYMENT PROOF</span></div><div class="request-facts"><span>Amount ${money(request.amount)}</span><span>OR ${esc(request.orNumber)}</span><span>${request.undertakingSigned ? "Undertaking signed" : "No undertaking"}</span></div><img class="proof-preview" src="${esc(request.proofDataUrl)}" alt="Payment screenshot for OR ${esc(request.orNumber)}"><div class="decision-actions"><button class="button-small" data-payment-valid="${esc(request.id)}">Verify OR &amp; receipt</button><button class="button-small danger-button" data-payment-reject="${esc(request.id)}">Reject proof</button></div></article>`).join("") || `<div class="empty-state"><span>✓</span><strong>All caught up</strong><p>New document request payments will show in this review queue.</p></div>`;
    shell(user, `<div class="stats-grid">${stat("WAITING FOR PAYMENT REVIEW", queue.length, "Receipt and OR verification", "◷")}${stat("PAYMENT STAGE", "03 / 07", "Cashier validates OR evidence", "₱")}${stat("NEXT HANDOFF", "Registrar", "Verified requests move to request review", "→")}</div><div class="content-grid"><section class="panel wide-panel" id="payment-queue"><div class="panel-heading"><div><h2>Payment proof queue</h2><p class="panel-subtitle">Review each receipt screenshot and bind its OR reference to the request.</p></div><button class="subtle-button" id="reload-queue">Refresh queue</button></div><div class="review-list">${queueHtml}</div></section><section class="panel" id="account-lookup"><div class="panel-heading"><h2>Student account lookup</h2></div><form id="account-form" class="search-row"><input class="field-input" name="studentId" required placeholder="Student ID"><button class="button-small">Search</button></form><div id="account-result"></div></section></div>`, "payment-queue");
    document.getElementById("reload-queue").addEventListener("click", () => cashierDashboard(user).catch(showError));
    document.querySelectorAll("[data-payment-valid]").forEach((button) => button.addEventListener("click", () => reviewPayment(button.dataset.paymentValid, true)));
    document.querySelectorAll("[data-payment-reject]").forEach((button) => button.addEventListener("click", () => {
      const reason = window.prompt("Why is this receipt or OR number invalid?");
      if (reason?.trim()) reviewPayment(button.dataset.paymentReject, false, reason.trim());
    }));
    document.getElementById("account-form").addEventListener("submit", async (event) => {
      event.preventDefault(); const id = new FormData(event.currentTarget).get("studentId"); const target = document.getElementById("account-result");
      try { const record = await api(`/api/cashier/students/${encodeURIComponent(id)}`); target.innerHTML = `<div class="notice"><strong>${esc(record.name)}</strong><br>${esc(record.program)} · Balance ${money(record.balance)}<br>Clearance holds: ${record.holds.map(esc).join(", ") || "None"}</div>`; }
      catch (error) { target.innerHTML = `<div class="notice alert-notice">${esc(error.message)}</div>`; }
    });
  }

  async function reviewPayment(requestId, valid, reason = "") {
    try { await api(`/api/cashier/requests/${encodeURIComponent(requestId)}/verify-payment`, { method: "POST", body: JSON.stringify({ valid, reason }) }); toast(valid ? "Payment verified; request sent to the registrar." : "Payment proof rejected with correction instructions."); await cashierDashboard({ name: "Jordan Reyes" }); }
    catch (error) { toast(error.message); }
  }

  let scanner = null;
  async function registrarDashboard(user) {
    const [queue, audits] = await Promise.all([api("/api/registrar/requests"), api("/api/registrar/audit")]);
    const queueHtml = queue.map((request) => `<article class="review-card"><div class="request-card-head"><div><span class="request-id">${esc(request.studentName)} · ${esc(request.studentId)}</span><h3>${esc(request.documents.join(", "))}</h3></div><span class="badge">CASHIER VERIFIED</span></div><div class="request-facts"><span>Fee ${money(request.amount)}</span><span>Verified OR ${esc(request.orNumber)}</span><span>${request.undertakingSigned ? "Undertaking signed" : "No undertaking"}</span></div><img class="proof-preview" src="${esc(request.proofDataUrl)}" alt="Verified payment proof"><div class="decision-actions"><button class="button-small" data-approve="${esc(request.id)}">Approve &amp; enable QR</button><button class="button-small danger-button" data-reject="${esc(request.id)}">Reject with reason</button></div></article>`).join("") || `<div class="empty-state"><span>✓</span><strong>No pending registrar decisions</strong><p>Cashier-verified document requests will appear here.</p></div>`;
    const auditRows = audits.map(entry => `<tr><td>${esc(new Date(entry.createdAt).toLocaleString("en-PH"))}</td><td>${esc(entry.actorRole)} · ${esc(entry.actorId)}</td><td>${esc(entry.action.replaceAll("_", " "))}</td><td>${esc(entry.targetId.slice(0, 8))}</td></tr>`).join("") || `<tr><td colspan="4">No activity has been recorded yet.</td></tr>`;
    shell(user, `<div class="stats-grid">${stat("PENDING REQUEST REVIEWS", queue.length, "Payment verified by cashier", "◷")}${stat("REVIEW QUEUE", "04 / 07", "Audit the request and OR binding", "▤")}${stat("AUDIT EVENTS", audits.length, "Append-only system history", "✓")}</div><div class="content-grid"><section class="panel wide-panel" id="registrar-queue"><div class="panel-heading"><div><h2>Request review &amp; decision</h2><p class="panel-subtitle">Check the selected documents, receipt, OR and undertaking before deciding.</p></div><button class="subtle-button" id="reload-registrar">Refresh queue</button></div><div class="review-list">${queueHtml}</div></section><section class="panel scanner-panel" id="counter-scanner"><div class="panel-heading"><div><h2>Counter QR scanner</h2><p class="panel-subtitle">AES-256-GCM authenticity · expiry · replay defense</p></div></div><div class="camera-frame" id="camera-frame"><div id="qr-reader"></div><div class="camera-placeholder"><span>▦</span><strong>Scan approved request QR</strong>Only current, single-use codes are accepted.</div></div><div class="camera-actions"><button class="button-small" id="start-scan">Start camera</button><button class="button-small outline" id="stop-scan" disabled>Stop</button></div><form id="backup-code-form" class="backup-code-form"><label>Camera backup code<input name="code" required autocomplete="off" maxlength="19" placeholder="ABCD-EF12-3456-7890"></label><button class="button-small outline" type="submit">Verify backup code</button></form><div id="scan-result" class="verification"></div></section></div><section class="panel" id="audit-trail"><div class="panel-heading"><div><h2>Immutable audit trail</h2><p class="panel-subtitle">Submission, review, QR verification and fulfillment actions are appended here.</p></div></div><div class="table-wrap"><table class="table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Request</th></tr></thead><tbody>${auditRows}</tbody></table></div></section>`, "registrar-queue");
    document.getElementById("reload-registrar").addEventListener("click", () => registrarDashboard(user).catch(showError));
    document.querySelectorAll("[data-approve]").forEach((button) => button.addEventListener("click", () => decideRequest(button.dataset.approve, "approve")));
    document.querySelectorAll("[data-reject]").forEach((button) => button.addEventListener("click", () => {
      const reason = window.prompt("Give the student a specific correction or rejection reason:");
      if (reason?.trim()) decideRequest(button.dataset.reject, "reject", reason.trim());
    }));
    document.getElementById("start-scan").addEventListener("click", startScanner);
    document.getElementById("stop-scan").addEventListener("click", stopScanner);
    document.getElementById("backup-code-form").addEventListener("submit", verifyBackupCode);
  }

  async function decideRequest(requestId, decision, reason = "") {
    try { await api(`/api/registrar/requests/${encodeURIComponent(requestId)}/decision`, { method: "POST", body: JSON.stringify({ decision, reason }) }); toast(decision === "approve" ? "Request approved. The student can generate a QR." : "Request rejected with correction instructions."); await registrarDashboard({ name: "Alex Morgan" }); }
    catch (error) { toast(error.message); }
  }

  async function startScanner() {
    if (!window.Html5Qrcode) return toast("The QR scanner library is unavailable. Check your connection and reload.");
    const start = document.getElementById("start-scan"); const stop = document.getElementById("stop-scan");
    try {
      start.disabled = true; stop.disabled = false;
      scanner = new Html5Qrcode("qr-reader");
      document.getElementById("camera-frame").classList.add("scanning");
      await scanner.start({ facingMode: "environment" }, { fps: 8, qrbox: { width: 220, height: 220 } }, handleScan, () => {});
    } catch (error) { start.disabled = false; stop.disabled = true; toast(`Could not start camera: ${error}`); }
  }

  async function stopScanner() {
    if (scanner?.isScanning) await scanner.stop().catch(() => {});
    if (scanner) await scanner.clear().catch(() => {});
    scanner = null;
    const start = document.getElementById("start-scan"); const stop = document.getElementById("stop-scan");
    if (start) start.disabled = false; if (stop) stop.disabled = true;
    document.getElementById("camera-frame")?.classList.remove("scanning");
  }

  async function handleScan(raw) {
    await stopScanner();
    const target = document.getElementById("scan-result");
    target.classList.add("visible"); target.innerHTML = `<div class="notice">Checking GCM authentication, expiry, request binding and single-use nonce…</div>`;
    try {
      const result = await api("/api/registrar/verify-qr", { method: "POST", body: JSON.stringify({ envelope: JSON.parse(raw) }) });
      showVerifiedRequest(result);
    } catch (error) { target.innerHTML = `<div class="notice alert-notice"><strong>Verification failed</strong><span>${esc(error.message)}</span></div>`; }
  }

  async function verifyBackupCode(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const target = document.getElementById("scan-result");
    target.classList.add("visible"); target.innerHTML = `<div class="notice">Checking backup code, expiry and single-use status…</div>`;
    try {
      const result = await api("/api/registrar/verify-backup-code", {
        method: "POST",
        body: JSON.stringify({ code: new FormData(form).get("code") })
      });
      showVerifiedRequest(result);
    } catch (error) {
      target.innerHTML = `<div class="notice alert-notice"><strong>Verification failed</strong><span>${esc(error.message)}</span></div>`;
    }
  }

  function showVerifiedRequest(result) {
    const request = result.request;
    const target = document.getElementById("scan-result");
    target.classList.add("visible");
    target.innerHTML = `<div class="verified-card"><span class="badge">REQUEST VERIFIED · AUTHENTICATED</span><h3>${esc(request.studentName)}</h3><p>${esc(request.studentId)} · ${esc(request.documents.join(", "))}</p><div class="request-facts"><span>Verified OR ${esc(request.orNumber)}</span><span>${request.undertakingSigned ? "Undertaking confirmed" : "No undertaking"}</span></div><p>${esc(result.message)}</p><button class="button-small" id="claim-request">Confirm handover &amp; mark claimed</button></div>`;
    document.getElementById("claim-request").addEventListener("click", () => claimRequest(request.id));
  }

  async function claimRequest(requestId) {
    try { const result = await api(`/api/registrar/requests/${encodeURIComponent(requestId)}/claim`, { method: "POST" }); toast(result.message); document.getElementById("scan-result").innerHTML = `<div class="notice success-notice">Documents marked claimed. The handover was added to the audit trail.</div>`; await registrarDashboard({ name: "Alex Morgan" }); }
    catch (error) { toast(error.message); }
  }

  async function showError(error) {
    app.innerHTML = `<main class="error-screen"><div class="error-card"><span class="brand-mark">UA</span><h1>We couldn't open your workspace.</h1><p>${esc(error.message)}</p><a class="button-small" href="login/${role}/">Return to sign in</a></div></main>`;
  }

  async function openDashboard() {
    if (!token()) return loginView("Sign in to continue to your dashboard.");
    try {
      const user = await api("/api/session/me");
      if (user.role !== role) throw new Error("This session belongs to a different portal role. Please sign in again.");
      if (role === "student") await studentDashboard(user);
      else if (role === "cashier") await cashierDashboard(user);
      else await registrarDashboard(user);
    } catch (error) {
      if ([401, 403].includes(error.status)) sessionStorage.removeItem("portal_access_token");
      await showError(error);
    }
  }

  window.addEventListener("pagehide", stopScanner);
  if (!["student", "cashier", "registrar"].includes(role)) location.replace("index.html");
  else if (location.pathname.toLowerCase().includes("/login/")) loginView();
  else openDashboard();
})();
