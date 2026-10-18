/* PetShop V3 – JavaScript giao diện (không thư viện, không CDN).
   JavaScript chỉ nâng cấp trải nghiệm: tắt đi thì các chức năng chính vẫn chạy. */
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* 1. Mở / đóng hộp thoại (dialog) ------------------------------------- */
  function openDialog(dlg) {
    if (!dlg) { return; }
    if (typeof dlg.showModal === "function") { dlg.showModal(); } else { dlg.setAttribute("open", ""); }
    var first = $("input:not([type=hidden]), select, textarea", dlg);
    if (first) { first.focus(); }
  }
  function closeDialog(dlg) {
    if (!dlg) { return; }
    if (typeof dlg.close === "function") { dlg.close(); } else { dlg.removeAttribute("open"); }
  }
  document.addEventListener("click", function (e) {
    var opener = e.target.closest("[data-open-dialog]");
    if (opener) { e.preventDefault(); openDialog(document.getElementById(opener.getAttribute("data-open-dialog"))); return; }
    var closer = e.target.closest("[data-close-dialog]");
    if (closer) { e.preventDefault(); closeDialog(closer.closest("dialog")); return; }
    if (e.target.tagName === "DIALOG") { closeDialog(e.target); }   /* bấm vào nền mờ */
  });
  $$("dialog[data-autoopen]").forEach(openDialog);

  /* 2. Hộp thoại xác nhận cho thao tác nguy hiểm ------------------------- */
  var confirmDlg = document.getElementById("confirm-dialog");
  var pendingForm = null;
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-confirm]");
    if (!btn || !confirmDlg || typeof confirmDlg.showModal !== "function") { return; }
    e.preventDefault();
    pendingForm = btn.form || btn.closest("form");
    $("[data-confirm-title]", confirmDlg).textContent = btn.getAttribute("data-confirm-title") || "Bạn chắc chắn chứ?";
    $("[data-confirm-text]", confirmDlg).textContent = btn.getAttribute("data-confirm");
    $("[data-confirm-ok]", confirmDlg).textContent = btn.getAttribute("data-confirm-label") || "Xác nhận";
    openDialog(confirmDlg);
    $("[data-confirm-ok]", confirmDlg).focus();
  });
  if (confirmDlg) {
    $("[data-confirm-ok]", confirmDlg).addEventListener("click", function () {
      var form = pendingForm; pendingForm = null; closeDialog(confirmDlg);
      if (form) { form.submit(); }
    });
    confirmDlg.addEventListener("close", function () { pendingForm = null; });
  }

  /* 3. Nút đang xử lý: tránh bấm hai lần --------------------------------- */
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.hasAttribute("data-no-loading")) { return; }
    var btn = $("button[type=submit]:not([data-no-loading])", form);
    if (btn) { setTimeout(function () { btn.classList.add("is-loading"); btn.setAttribute("aria-busy", "true"); }, 0); }
  });
  window.addEventListener("pageshow", function () {   /* quay lại bằng nút Back */
    $$(".btn.is-loading").forEach(function (b) { b.classList.remove("is-loading"); b.removeAttribute("aria-busy"); });
  });

  /* 4. Thông báo (toast) tự tắt ------------------------------------------ */
  function dismissToast(t) {
    t.classList.add("is-leaving");
    setTimeout(function () { if (t.parentNode) { t.parentNode.removeChild(t); } }, 220);
  }
  $$(".toast").forEach(function (t) {
    var close = $(".toast__close", t);
    if (close) { close.addEventListener("click", function () { dismissToast(t); }); }
    setTimeout(function () { dismissToast(t); }, 5500);
  });

  /* 5. Hiện / ẩn mật khẩu ------------------------------------------------- */
  $$("[data-toggle-password]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = document.getElementById(btn.getAttribute("data-toggle-password"));
      if (!input) { return; }
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      btn.setAttribute("aria-label", show ? "Ẩn mật khẩu" : "Hiện mật khẩu");
      $$("use", btn).forEach(function (u) { u.setAttribute("href", show ? "#i-eye-off" : "#i-eye"); });
    });
  });

  /* 6. Thanh đo độ mạnh mật khẩu ----------------------------------------- */
  $$("[data-meter-for]").forEach(function (meter) {
    var input = document.getElementById(meter.getAttribute("data-meter-for"));
    var label = $("[data-meter-label]", meter.parentNode);
    if (!input) { return; }
    input.addEventListener("input", function () {
      var v = input.value, score = 0;
      if (v.length >= 8) { score++; }
      if (v.length >= 12) { score++; }
      if (/[a-z]/.test(v) && /[A-Z]/.test(v)) { score++; }
      if (/\d/.test(v) && /[^A-Za-z0-9]/.test(v)) { score++; }
      meter.setAttribute("data-level", v ? String(Math.max(score, 1)) : "0");
      if (label) { label.textContent = v ? ["", "Yếu", "Tạm được", "Khá", "Mạnh"][Math.max(score, 1)] : ""; }
    });
  });

  /* 7. Đặt lịch: tóm tắt trực tiếp + chọn nhanh giờ ---------------------- */
  var booking = $("[data-booking]");
  if (booking) {
    var out = function (k) { return $("[data-sum='" + k + "']", booking); };
    var fmtVnd = function (n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ".") + " đ"; };
    var update = function () {
      var pet = $("input[name=pet_id]:checked", booking);
      var svc = $("input[name=service_id]:checked", booking);
      var when = $("input[name=appt_time]", booking);
      out("pet").textContent = pet ? pet.getAttribute("data-name") : "Chưa chọn";
      out("service").textContent = svc ? svc.getAttribute("data-name") : "Chưa chọn";
      out("duration").textContent = svc ? svc.getAttribute("data-duration") + " phút" : "—";
      var tv = when && when.value ? when.value.split("T") : null;
      out("time").textContent = tv && tv[1] ? tv[0].split("-").reverse().join("/") + " · " + tv[1] : "Chưa chọn";
      out("price").textContent = svc ? fmtVnd(svc.getAttribute("data-price")) : "—";
    };
    booking.addEventListener("change", update);
    booking.addEventListener("input", update);
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    $$("[data-quick-time]", booking).forEach(function (chip) {
      chip.addEventListener("click", function () {
        var d = new Date(); d.setDate(d.getDate() + parseInt(chip.getAttribute("data-day-offset"), 10));
        var input = $("input[name=appt_time]", booking);
        input.value = d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + chip.getAttribute("data-quick-time");
        $$("[data-quick-time]", booking).forEach(function (c) { c.classList.toggle("is-active", c === chip); });
        update();
      });
    });
    update();
  }

  /* 8. Menu tài khoản: đóng khi bấm ra ngoài hoặc nhấn Esc ---------------- */
  var menu = $("details.menu");
  if (menu) {
    document.addEventListener("click", function (e) { if (!menu.contains(e.target)) { menu.removeAttribute("open"); } });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { menu.removeAttribute("open"); } });
  }
})();
