import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

import psycopg2
import psycopg2.errors
import psycopg2.extras
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from prometheus_client import Counter
from prometheus_flask_exporter import PrometheusMetrics
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
# Phía trước app là Nginx (1 lớp proxy): tin X-Forwarded-For / X-Forwarded-Proto
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# ----------  Cấu hình session / cookie ----------
app.config.update(
    SECRET_KEY=os.environ["SECRET_KEY"],
    SESSION_COOKIE_NAME="petshop_session",
    SESSION_COOKIE_HTTPONLY=True,          # JavaScript không đọc được cookie
    SESSION_COOKIE_SAMESITE="Lax",         # giảm nguy cơ CSRF
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
    MAX_CONTENT_LENGTH=1024 * 1024,
    SEND_FILE_MAX_AGE_DEFAULT=timedelta(days=7),   # [V3] cache CSS/JS/ảnh 7 ngày
)

metrics = PrometheusMetrics(app)  # tự động mở /metrics cho Prometheus
metrics.info("petshop_app_info", "Thong tin ung dung PetShop", version="3.0.0")

#  Metric nghiệp vụ để vẽ lên Grafana
LOGIN_ATTEMPTS = Counter("petshop_login_attempts", "So lan dang nhap", ["result"])
BOOKINGS = Counter("petshop_bookings", "So lich hen duoc dat qua website")
LOGIN_ATTEMPTS.labels("success")
LOGIN_ATTEMPTS.labels("failed")

DB_CONFIG = dict(
    host=os.environ.get("DB_HOST", "db"),
    port=int(os.environ.get("DB_PORT", "5432")),
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    connect_timeout=5,
)

# ----------  Hằng số nghiệp vụ ----------
STATUS_PENDING = "Chờ xác nhận"
STATUS_CONFIRMED = "Đã xác nhận"
STATUS_DONE = "Hoàn thành"
STATUS_CANCELLED = "Đã hủy"
STATUSES = [STATUS_PENDING, STATUS_CONFIRMED, STATUS_DONE, STATUS_CANCELLED]
STATUS_CLASS = {STATUS_PENDING: "warn", STATUS_CONFIRMED: "info",
                STATUS_DONE: "ok", STATUS_CANCELLED: "bad"}
SPECIES = ["Chó", "Mèo", "Thỏ", "Khác"]
SPECIES_KEY = {"Chó": "dog", "Mèo": "cat", "Thỏ": "rabbit"}   # [V3] tên avatar SVG
PER_PAGE = 10

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+ ]{8,15}$")
VN_TZ = timezone(timedelta(hours=7))                       # giờ Việt Nam (UTC+7)
DUMMY_HASH = generate_password_hash("khong-phai-mat-khau-that")


def now_vn():
    """Giờ hiện tại theo múi giờ Việt Nam, bỏ tzinfo để so với cột TIMESTAMP."""
    return datetime.now(VN_TZ).replace(tzinfo=None)


def parse_dt(raw):
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def safe(value, limit=100):
    """Làm sạch chuỗi trước khi ghi log (chống giả mạo dòng log)."""
    return re.sub(r"[^\w@.+\-]", "?", str(value))[:limit]


def like(raw):
    """Chuẩn bị chuỗi cho ILIKE: thoát ký tự đặc biệt % _ \\."""
    return "%" + raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def paginate(total):
    """Tính thông tin phân trang từ ?page= và tổng số dòng."""
    pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    page = min(max(request.args.get("page", 1, type=int) or 1, 1), pages)
    offset = (page - 1) * PER_PAGE
    return dict(page=page, pages=pages, total=total, offset=offset,
                first=offset + 1 if total else 0, last=min(offset + PER_PAGE, total))


def safe_next(raw, default):
    """Chỉ cho quay về đường dẫn nội bộ /admin/... (chống open redirect)."""
    if raw and raw.startswith("/admin/") and "//" not in raw and "\\" not in raw:
        return raw
    return default


def service_images(service_ids):
    """Id dịch vụ đã có ảnh local (app/static/service_<id>.jpg|png|webp)."""
    found = set()
    static_dir = os.path.join(app.root_path, "static")
    for sid in service_ids:
        for ext in ("jpg", "png", "webp"):
            if os.path.exists(os.path.join(static_dir, f"service_{sid}.{ext}")):
                found.add(sid)
                break
    return found


def overlaps(existing_start, existing_end, new_start, new_end):
    return existing_start < new_end and new_start < existing_end


try:  # phiên bản tài nguyên tĩnh: đổi file CSS/JS thì trình duyệt tải lại bản mới
    ASSET_V = int(os.path.getmtime(os.path.join(app.root_path, "static", "css", "app.css")))
except OSError:
    ASSET_V = 0


@app.template_filter("species_key")
def species_key(value):
    return SPECIES_KEY.get(value, "other")


@app.template_filter("initials")
def initials(value):
    parts = [p for p in str(value or "?").split() if p]
    if not parts:
        return "?"
    letters = parts[0][0] if len(parts) == 1 else parts[0][0] + parts[-1][0]
    return letters.upper()


@app.template_filter("vnd")
def vnd(value):
    try:
        return f"{int(value):,}".replace(",", ".") + " đ"
    except (TypeError, ValueError):
        return value


@app.template_filter("status_class")
def status_class(value):
    return STATUS_CLASS.get(value, "info")


# ---------- Hàm truy cập DB ----------
def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(**DB_CONFIG)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, params=None):
    conn = get_db()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    conn.commit()
    return rows


def query_one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    """Thực thi INSERT/UPDATE/DELETE, trả về số dòng bị ảnh hưởng."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        count = cur.rowcount
    conn.commit()
    return count


# ----------  Tự tạo tài khoản admin khi khởi động ----------
def bootstrap_admin():
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not email or not password:
        app.logger.warning("Thieu ADMIN_EMAIL/ADMIN_PASSWORD: khong tao admin")
        return
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn, conn.cursor() as cur:
            cur.execute("SELECT role FROM customers WHERE email = %s", (email,))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO customers (name, phone, email, password_hash, role) "
                    "VALUES (%s, NULL, %s, %s, 'admin')",
                    ("Quản trị viên", email, generate_password_hash(password)),
                )
                app.logger.info("Da tao tai khoan admin: %s", safe(email))
            elif row[0] != "admin":
                app.logger.warning("Email %s da ton tai nhung khong phai admin", safe(email))
    except psycopg2.Error as exc:
        app.logger.error("Khong tao duoc admin: %s", exc)
    finally:
        if conn is not None:
            conn.close()


bootstrap_admin()


# ----------  Xác thực, CSRF, phân quyền ----------
@app.before_request
def load_user_and_check_csrf():
    g.user = None
    if request.path in ("/health", "/metrics") or request.endpoint == "static":
        return None   # [V3] file tĩnh (CSS/JS/SVG) không cần truy vấn DB
    uid = session.get("uid")
    if uid:
        # Đọc lại từ DB mỗi request: bị xóa/đổi quyền là có hiệu lực ngay
        g.user = query_one("SELECT id, name, email, role FROM customers WHERE id = %s", (uid,))
        if g.user is None:
            session.clear()
    if request.method == "POST" and request.endpoint is not None:
        sent = (request.form.get("csrf_token") or "").encode()
        expected = (session.get("csrf_token") or "").encode()
        if not expected or not secrets.compare_digest(sent, expected):
            app.logger.warning("CSRF_FAIL path=%s ip=%s", safe(request.path), request.remote_addr)
            abort(400)
    return None


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.context_processor
def inject_user():
    return {"user": getattr(g, "user", None), "asset_v": ASSET_V}


def role_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login"))
            if role == "admin" and g.user["role"] != "admin":
                abort(403)
            if role == "user" and g.user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


login_required = role_required(None)   # đã đăng nhập (user hoặc admin)
user_required = role_required("user")  # khách hàng
admin_required = role_required("admin")  # quản trị viên


# ---------- Bảo mật & lỗi ----------
@app.after_request
def add_headers(resp):
    # [V3] Siết CSP: không còn inline style/script. CSS + JS nằm trong /static/.
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
    )
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store"   # không cache trang đã đăng nhập
    return resp


def render_error(code, message):
    return render_template("error.html", code=code, message=message), code


@app.errorhandler(400)
def bad_request(_err):
    return render_error(400, "Yêu cầu không hợp lệ hoặc phiên làm việc đã hết hạn. Hãy tải lại trang và thử lại.")


@app.errorhandler(403)
def forbidden(_err):
    return render_error(403, "Bạn không có quyền truy cập trang này.")


@app.errorhandler(404)
def not_found(_err):
    return render_error(404, "Không tìm thấy trang bạn yêu cầu.")


@app.errorhandler(405)
def not_allowed(_err):
    return render_error(405, "Phương thức không được hỗ trợ (hãy dùng nút Đăng xuất trên thanh menu).")


@app.errorhandler(psycopg2.Error)
def db_error(err):
    app.logger.error("Loi database: %s", err)
    return "Lỗi cơ sở dữ liệu, vui lòng thử lại.", 500


# =====================================================================
# ROUTES CÔNG KHAI
# =====================================================================
@app.route("/health")
def health():
    try:
        query("SELECT 1")
        return jsonify(status="ok"), 200
    except Exception as exc:  # noqa: BLE001
        app.logger.error("Health check failed: %s", exc)
        return jsonify(status="error"), 503


@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="img/favicon.svg"), code=301)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("admin_dashboard" if g.user["role"] == "admin" else "home"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        row = query_one(
            "SELECT id, role, password_hash FROM customers WHERE email = %s", (email,)
        )
        if row and row["password_hash"]:
            ok = check_password_hash(row["password_hash"], password)
        else:
            check_password_hash(DUMMY_HASH, password)   # thời gian xử lý tương đương
            ok = False
        if ok:
            session.clear()                 # chống session fixation
            session["uid"] = row["id"]
            session.permanent = True
            LOGIN_ATTEMPTS.labels("success").inc()
            app.logger.info("LOGIN_OK email=%s role=%s", safe(email), row["role"])
            return redirect(url_for("admin_dashboard" if row["role"] == "admin" else "home"))
        LOGIN_ATTEMPTS.labels("failed").inc()
        app.logger.warning("LOGIN_FAIL email=%s ip=%s", safe(email), request.remote_addr)
        flash("Email hoặc mật khẩu không đúng.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("home"))
    form = {}
    if request.method == "POST":
        form = request.form
        name = (form.get("name") or "").strip()
        phone = (form.get("phone") or "").strip()
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""
        confirm = form.get("confirm") or ""
        errors = []
        if not 2 <= len(name) <= 100:
            errors.append("Họ tên phải từ 2 đến 100 ký tự.")
        if not EMAIL_RE.match(email) or len(email) > 100:
            errors.append("Email không hợp lệ.")
        if phone and not PHONE_RE.match(phone):
            errors.append("Số điện thoại không hợp lệ (8-15 chữ số).")
        if not 8 <= len(password) <= 128:
            errors.append("Mật khẩu phải từ 8 đến 128 ký tự.")
        if password != confirm:
            errors.append("Mật khẩu nhập lại không khớp.")
        if not errors and query_one("SELECT 1 AS x FROM customers WHERE email = %s", (email,)):
            errors.append("Email này đã được đăng ký.")
        if not errors:
            try:
                # role luôn là 'user' (mặc định của DB); KHÔNG nhận role từ form
                execute(
                    "INSERT INTO customers (name, phone, email, password_hash) VALUES (%s, %s, %s, %s)",
                    (name, phone or None, email, generate_password_hash(password)),
                )
                flash("Đăng ký thành công! Hãy đăng nhập.", "success")
                return redirect(url_for("login"))
            except psycopg2.errors.UniqueViolation:
                get_db().rollback()
                errors.append("Email này đã được đăng ký.")
        for e in errors:
            flash(e, "error")
    return render_template("register.html", form=form)


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("Bạn đã đăng xuất.", "info")
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Đổi mật khẩu cho cả User và Admin (phải biết mật khẩu hiện tại)."""
    if request.method == "POST":
        current = request.form.get("current") or ""
        new = request.form.get("new") or ""
        confirm = request.form.get("confirm") or ""
        row = query_one("SELECT password_hash FROM customers WHERE id = %s", (g.user["id"],))
        errors = []
        if not row or not row["password_hash"] or not check_password_hash(row["password_hash"], current):
            errors.append("Mật khẩu hiện tại không đúng.")
        if not 8 <= len(new) <= 128:
            errors.append("Mật khẩu mới phải từ 8 đến 128 ký tự.")
        if new != confirm:
            errors.append("Mật khẩu nhập lại không khớp.")
        if new == current:
            errors.append("Mật khẩu mới phải khác mật khẩu hiện tại.")
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            execute("UPDATE customers SET password_hash = %s WHERE id = %s",
                    (generate_password_hash(new), g.user["id"]))
            session.clear()   # đổi mật khẩu thì đăng xuất hết các phiên
            flash("Đổi mật khẩu thành công! Hãy đăng nhập lại.", "success")
            return redirect(url_for("login"))
    home_url = "admin_dashboard" if g.user["role"] == "admin" else "home"
    return render_template("change_password.html", home_url=home_url)


# =====================================================================
# ROUTES KHÁCH HÀNG (role = user)
# =====================================================================
@app.route("/")
@user_required
def home():
    q = (request.args.get("q") or "").strip()[:60]
    if q:
        services = query(
            "SELECT id, name, price, duration_min, description, icon FROM services "
            "WHERE name ILIKE %s ORDER BY id", (like(q),))
    else:
        services = query(
            "SELECT id, name, price, duration_min, description, icon FROM services ORDER BY id")
    summary = query_one(
        """SELECT (SELECT count(*) FROM pets WHERE customer_id = %(uid)s) AS pets,
                  (SELECT count(*) FROM appointments a JOIN pets p ON p.id = a.pet_id
                    WHERE p.customer_id = %(uid)s AND a.status IN (%(s1)s, %(s2)s)
                      AND a.appt_time >= %(now)s) AS upcoming""",
        dict(uid=g.user["id"], s1=STATUS_PENDING, s2=STATUS_CONFIRMED, now=now_vn()),
    )
    next_appt = query_one(
        """SELECT to_char(a.appt_time, 'DD/MM/YYYY HH24:MI') AS appt_time, p.name AS pet, s.name AS service
           FROM appointments a JOIN pets p ON p.id = a.pet_id JOIN services s ON s.id = a.service_id
           WHERE p.customer_id = %s AND a.status IN (%s, %s) AND a.appt_time >= %s
           ORDER BY a.appt_time LIMIT 1""",
        (g.user["id"], STATUS_PENDING, STATUS_CONFIRMED, now_vn()),
    )
    images = service_images([s["id"] for s in services])
    return render_template("home.html", services=services, q=q, images=images,
                           summary=summary, next_appt=next_appt)


def parse_age(raw):
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return False
    return round(value, 1) if 0 <= value <= 50 else False


@app.route("/my-pets", methods=["GET", "POST"])
@user_required
def my_pets():
    form, errors = {}, []
    if request.method == "POST":
        form = request.form
        name = (form.get("name") or "").strip()
        species = form.get("species") or ""
        breed = (form.get("breed") or "").strip()
        age = parse_age((form.get("age") or "").strip())
        if not 1 <= len(name) <= 100:
            errors.append("Tên thú cưng bắt buộc (tối đa 100 ký tự).")
        if species not in SPECIES:
            errors.append("Vui lòng chọn loài.")
        if len(breed) > 80:
            errors.append("Giống tối đa 80 ký tự.")
        if age is False:
            errors.append("Tuổi phải là số từ 0 đến 50.")
        if not errors:
            execute(
                "INSERT INTO pets (name, species, breed, age, customer_id) VALUES (%s, %s, %s, %s, %s)",
                (name, species, breed or None, age, g.user["id"]),
            )
            flash(f"Đã thêm thú cưng «{name}».", "success")
            return redirect(url_for("my_pets"))
    pets = query(
        "SELECT id, name, species, breed, age FROM pets WHERE customer_id = %s ORDER BY id DESC",
        (g.user["id"],),
    )
    return render_template("my_pets.html", pets=pets, species_list=SPECIES, form=form, errors=errors)


@app.route("/booking", methods=["GET", "POST"])
@user_required
def booking():
    pets = query("SELECT id, name, species FROM pets WHERE customer_id = %s ORDER BY name", (g.user["id"],))
    services = query("SELECT id, name, price, duration_min, icon FROM services ORDER BY id")
    form = request.form if request.method == "POST" else {}
    selected_service = (request.form if request.method == "POST" else request.args).get("service_id", type=int)
    selected_pet = form.get("pet_id", type=int) if form else None
    if selected_pet is None and len(pets) == 1:
        selected_pet = pets[0]["id"]
    errors = []

    if request.method == "POST":
        svc = next((s for s in services if s["id"] == selected_service), None)
        if not any(p["id"] == selected_pet for p in pets):          # thú cưng phải của chính mình
            errors.append("Vui lòng chọn thú cưng của bạn.")
        if svc is None:
            errors.append("Vui lòng chọn dịch vụ.")
        appt_time = parse_dt(form.get("appt_time", ""))
        if appt_time is None:
            errors.append("Thời gian không hợp lệ.")
        elif appt_time < now_vn():
            errors.append("Không thể đặt lịch trong quá khứ.")
        elif appt_time > now_vn() + timedelta(days=365):
            errors.append("Chỉ nhận đặt lịch trong vòng 1 năm.")
        if not errors:
            new_end = appt_time + timedelta(minutes=int(svc["duration_min"]))
            busy = query(
                """SELECT a.appt_time, s.duration_min, s.name
                   FROM appointments a JOIN services s ON s.id = a.service_id
                   WHERE a.pet_id = %s AND a.status <> %s""",
                (selected_pet, STATUS_CANCELLED),
            )
            for b in busy:
                old_end = b["appt_time"] + timedelta(minutes=int(b["duration_min"]))
                if overlaps(b["appt_time"], old_end, appt_time, new_end):
                    errors.append(f"Thú cưng này đã có lịch «{b['name']}» giao với khung giờ bạn chọn.")
                    break
        if not errors:
            execute(
                "INSERT INTO appointments (pet_id, service_id, appt_time, status) VALUES (%s, %s, %s, %s)",
                (selected_pet, selected_service, appt_time, STATUS_PENDING),
            )
            BOOKINGS.inc()
            flash("Đặt lịch thành công! Lịch hẹn đang chờ cửa hàng xác nhận.", "success")
            return redirect(url_for("my_appointments"))

    return render_template(
        "booking.html", pets=pets, services=services, form=form, errors=errors,
        selected_service=selected_service, selected_pet=selected_pet,
        min_time=now_vn().strftime("%Y-%m-%dT%H:%M"),
    )


APPT_SELECT = """SELECT a.id, to_char(a.appt_time, 'DD/MM/YYYY HH24:MI') AS appt_time,
                  to_char(a.appt_time, 'DD') AS day, to_char(a.appt_time, 'MM') AS mon,
                  to_char(a.appt_time, 'HH24:MI') AS hm,
                  p.name AS pet, p.species AS species, s.name AS service, s.price, s.duration_min, a.status
           FROM appointments a
           JOIN pets p ON p.id = a.pet_id
           JOIN services s ON s.id = a.service_id"""


@app.route("/my-appointments")
@user_required
def my_appointments():
    tab = "history" if request.args.get("tab") == "history" else "upcoming"
    active = "(a.status IN (%s, %s) AND a.appt_time >= %s)"
    base_params = (STATUS_PENDING, STATUS_CONFIRMED, now_vn())
    counts = query_one(
        f"""SELECT count(*) FILTER (WHERE {active}) AS upcoming,
                   count(*) FILTER (WHERE NOT {active}) AS history
            FROM appointments a JOIN pets p ON p.id = a.pet_id WHERE p.customer_id = %s""",
        base_params + base_params + (g.user["id"],),
    )
    cond = active if tab == "upcoming" else f"NOT {active}"
    order = "ASC" if tab == "upcoming" else "DESC"
    pg = paginate(counts[tab])
    rows = query(
        f"{APPT_SELECT} WHERE p.customer_id = %s AND {cond} ORDER BY a.appt_time {order} LIMIT %s OFFSET %s",
        (g.user["id"],) + base_params + (PER_PAGE, pg["offset"]),
    )
    return render_template("my_appointments.html", rows=rows, pending=STATUS_PENDING,
                           tab=tab, counts=counts, pg=pg)


@app.route("/my-appointments/<int:appt_id>/cancel", methods=["POST"])
@user_required
def cancel_appointment(appt_id):
    # Chỉ hủy được lịch CỦA MÌNH và đang ở trạng thái "Chờ xác nhận"
    changed = execute(
        """UPDATE appointments a SET status = %s
           FROM pets p
           WHERE a.id = %s AND a.pet_id = p.id AND p.customer_id = %s AND a.status = %s""",
        (STATUS_CANCELLED, appt_id, g.user["id"], STATUS_PENDING),
    )
    if changed:
        flash("Đã hủy lịch hẹn.", "success")
    else:
        flash("Không thể hủy lịch này (đã được xử lý hoặc không phải lịch của bạn).", "error")
    return redirect(url_for("my_appointments"))


# =====================================================================
# ROUTES QUẢN TRỊ (role = admin)
# =====================================================================
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    stats = query_one(
        """SELECT (SELECT count(*) FROM customers WHERE role = 'user') AS customers,
                  (SELECT count(*) FROM pets)                          AS pets,
                  (SELECT count(*) FROM services)                      AS services,
                  (SELECT count(*) FROM appointments)                  AS appointments,
                  (SELECT count(*) FROM appointments WHERE status = %s) AS pending,
                  (SELECT COALESCE(sum(s.price), 0) FROM appointments a
                     JOIN services s ON s.id = a.service_id WHERE a.status = %s) AS revenue_done,
                  (SELECT COALESCE(sum(s.price), 0) FROM appointments a
                     JOIN services s ON s.id = a.service_id
                     WHERE a.status IN (%s, %s)) AS revenue_expected""",
        (STATUS_PENDING, STATUS_DONE, STATUS_PENDING, STATUS_CONFIRMED),
    )
    pending = query(
        """SELECT a.id, to_char(a.appt_time, 'DD/MM/YYYY HH24:MI') AS appt_time,
                  p.name AS pet, p.species AS species, c.name AS owner, s.name AS service
           FROM appointments a
           JOIN pets p ON p.id = a.pet_id
           JOIN customers c ON c.id = p.customer_id
           JOIN services s ON s.id = a.service_id
           WHERE a.status = %s
           ORDER BY a.appt_time LIMIT 20""",
        (STATUS_PENDING,),
    )
    # [V3] Phân bố trạng thái + số lịch 7 ngày tới (dữ liệu thật, vẽ bằng SVG)
    by_status = {r["status"]: r["n"] for r in query(
        "SELECT status, count(*) AS n FROM appointments GROUP BY status")}
    status_rows = [dict(name=st, n=by_status.get(st, 0), cls=STATUS_CLASS[st]) for st in STATUSES]
    total_status = sum(r["n"] for r in status_rows)
    offset = 0.0
    for r in status_rows:
        r["pct"] = round(100.0 * r["n"] / total_status, 2) if total_status else 0
        r["x"] = round(offset, 2)
        offset += r["pct"]
    today = now_vn().date()
    per_day = {r["d"]: r["n"] for r in query(
        """SELECT a.appt_time::date AS d, count(*) AS n FROM appointments a
           WHERE a.appt_time::date BETWEEN %s AND %s AND a.status <> %s GROUP BY 1""",
        (today, today + timedelta(days=6), STATUS_CANCELLED))}
    peak = max(per_day.values(), default=0)
    week = []
    for i in range(7):
        d = today + timedelta(days=i)
        n = per_day.get(d, 0)
        h = round(64 * n / peak) if peak else 0
        week.append(dict(label=d.strftime("%d/%m"), dow=("CN" if d.weekday() == 6 else f"T{d.weekday() + 2}"),
                         n=n, h=h, y=76 - h, x=8 + i * 44))
    return render_template("admin_dashboard.html", stats=stats, pending=pending,
                           status_rows=status_rows, total_status=total_status, week=week)


@app.route("/admin/appointments")
@admin_required
def admin_appointments():
    flt = request.args.get("status")
    flt = flt if flt in STATUSES else None
    counts = {r["status"]: r["n"] for r in query(
        "SELECT status, count(*) AS n FROM appointments GROUP BY status")}
    total_all = sum(counts.values())
    pg = paginate(counts.get(flt, 0) if flt else total_all)
    where = "WHERE a.status = %s" if flt else ""
    params = ((flt,) if flt else ()) + (PER_PAGE, pg["offset"])
    rows = query(
        f"""SELECT a.id, to_char(a.appt_time, 'DD/MM/YYYY HH24:MI') AS appt_time,
                   p.name AS pet, p.species AS species, c.name AS owner, c.phone AS phone,
                   s.name AS service, s.price, a.status
            FROM appointments a
            JOIN pets p ON p.id = a.pet_id
            JOIN customers c ON c.id = p.customer_id
            JOIN services s ON s.id = a.service_id
            {where}
            ORDER BY a.appt_time DESC LIMIT %s OFFSET %s""",
        params,
    )
    return render_template("admin_appointments.html", rows=rows, statuses=STATUSES, current=flt,
                           counts=counts, total_all=total_all, pg=pg,
                           s_pending=STATUS_PENDING, s_confirmed=STATUS_CONFIRMED,
                           s_done=STATUS_DONE, s_cancelled=STATUS_CANCELLED)


@app.route("/admin/appointments/<int:appt_id>/status", methods=["POST"])
@admin_required
def admin_update_status(appt_id):
    status = request.form.get("status")
    if status not in STATUSES:
        abort(400)
    execute("UPDATE appointments SET status = %s WHERE id = %s", (status, appt_id))
    flash(f"Đã cập nhật lịch hẹn #{appt_id}: {status}.", "success")
    if request.form.get("next") == "dashboard":
        return redirect(url_for("admin_dashboard"))
    return redirect(safe_next(request.form.get("back"), url_for("admin_appointments")))


@app.route("/admin/appointments/<int:appt_id>/delete", methods=["POST"])
@admin_required
def admin_delete_appointment(appt_id):
    execute("DELETE FROM appointments WHERE id = %s", (appt_id,))
    flash(f"Đã xóa lịch hẹn #{appt_id}.", "success")
    return redirect(safe_next(request.form.get("back"), url_for("admin_appointments")))


def parse_service_form(form):
    name = (form.get("name") or "").strip()
    description = (form.get("description") or "").strip()
    icon = (form.get("icon") or "").strip() or "🐾"
    try:
        price = int(form.get("price", ""))
    except ValueError:
        price = None
    try:
        duration = int(form.get("duration_min", ""))
    except ValueError:
        duration = None
    errors = []
    if not 1 <= len(name) <= 100:
        errors.append("Tên dịch vụ bắt buộc (tối đa 100 ký tự).")
    if price is None or not 0 <= price <= 100_000_000:
        errors.append("Giá không hợp lệ.")
    if duration is None or not 5 <= duration <= 600:
        errors.append("Thời lượng phải từ 5 đến 600 phút.")
    if len(description) > 300:
        errors.append("Mô tả tối đa 300 ký tự.")
    if len(icon) > 8:
        errors.append("Biểu tượng (emoji) tối đa 8 ký tự.")
    data = dict(name=name, price=price, duration_min=duration,
                description=description or None, icon=icon)
    return data, errors


@app.route("/admin/services", methods=["GET", "POST"])
@admin_required
def admin_services():
    form, errors = {}, []
    if request.method == "POST":
        form = request.form
        data, errors = parse_service_form(form)
        if not errors:
            execute(
                "INSERT INTO services (name, price, duration_min, description, icon) "
                "VALUES (%(name)s, %(price)s, %(duration_min)s, %(description)s, %(icon)s)",
                data,
            )
            flash(f"Đã thêm dịch vụ «{data['name']}».", "success")
            return redirect(url_for("admin_services"))
    rows = query("SELECT id, name, price, duration_min, description, icon FROM services ORDER BY id")
    return render_template("admin_services.html", rows=rows, form=form, errors=errors)


@app.route("/admin/services/<int:service_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_service_edit(service_id):
    svc = query_one(
        "SELECT id, name, price, duration_min, description, icon FROM services WHERE id = %s",
        (service_id,),
    )
    if svc is None:
        abort(404)
    errors = []
    if request.method == "POST":
        data, errors = parse_service_form(request.form)
        if not errors:
            data["id"] = service_id
            execute(
                "UPDATE services SET name = %(name)s, price = %(price)s, duration_min = %(duration_min)s, "
                "description = %(description)s, icon = %(icon)s WHERE id = %(id)s",
                data,
            )
            flash("Đã cập nhật dịch vụ.", "success")
            return redirect(url_for("admin_services"))
        svc = dict(svc, **{k: request.form.get(k, "") for k in ("name", "price", "duration_min", "description", "icon")})
    return render_template("admin_service_edit.html", svc=svc, errors=errors)


@app.route("/admin/services/<int:service_id>/delete", methods=["POST"])
@admin_required
def admin_delete_service(service_id):
    execute("DELETE FROM services WHERE id = %s", (service_id,))   # CASCADE xóa lịch hẹn liên quan
    flash(f"Đã xóa dịch vụ #{service_id}.", "success")
    return redirect(url_for("admin_services"))


@app.route("/admin/customers")
@admin_required
def admin_customers():
    q = (request.args.get("q") or "").strip()[:60]
    where, params = "", ()
    if q:
        where = "WHERE c.name ILIKE %s OR c.email ILIKE %s OR c.phone ILIKE %s"
        params = (like(q),) * 3
    total = query_one(f"SELECT count(*) AS n FROM customers c {where}", params or None)["n"]
    pg = paginate(total)
    rows = query(
        f"""SELECT c.id, c.name, c.phone, c.email, c.role,
                   to_char(c.created_at, 'DD/MM/YYYY') AS created,
                   (SELECT count(*) FROM pets p WHERE p.customer_id = c.id) AS pet_count,
                   (c.password_hash IS NOT NULL) AS has_account
            FROM customers c {where}
            ORDER BY c.role, c.id DESC LIMIT %s OFFSET %s""",
        params + (PER_PAGE, pg["offset"]),
    )
    return render_template("admin_customers.html", rows=rows, q=q, pg=pg)


@app.route("/admin/customers/<int:customer_id>/delete", methods=["POST"])
@admin_required
def admin_delete_customer(customer_id):
    # Không cho xóa tài khoản admin; CASCADE tự xóa thú cưng + lịch hẹn của khách
    deleted = execute("DELETE FROM customers WHERE id = %s AND role = 'user'", (customer_id,))
    flash("Đã xóa khách hàng (kèm thú cưng và lịch hẹn liên quan)." if deleted
          else "Không thể xóa tài khoản này.", "success" if deleted else "error")
    return redirect(safe_next(request.form.get("back"), url_for("admin_customers")))


@app.route("/admin/pets")
@admin_required
def admin_pets():
    q = (request.args.get("q") or "").strip()[:60]
    where, params = "", ()
    if q:
        where = "WHERE p.name ILIKE %s OR p.breed ILIKE %s OR c.name ILIKE %s"
        params = (like(q),) * 3
    total = query_one(
        f"SELECT count(*) AS n FROM pets p JOIN customers c ON c.id = p.customer_id {where}",
        params or None)["n"]
    pg = paginate(total)
    rows = query(
        f"""SELECT p.id, p.name, p.species, p.breed, p.age, c.name AS owner
            FROM pets p JOIN customers c ON c.id = p.customer_id {where}
            ORDER BY p.id DESC LIMIT %s OFFSET %s""",
        params + (PER_PAGE, pg["offset"]),
    )
    return render_template("admin_pets.html", rows=rows, q=q, pg=pg)


@app.route("/admin/pets/<int:pet_id>/delete", methods=["POST"])
@admin_required
def admin_delete_pet(pet_id):
    execute("DELETE FROM pets WHERE id = %s", (pet_id,))
    flash(f"Đã xóa thú cưng #{pet_id}.", "success")
    return redirect(safe_next(request.form.get("back"), url_for("admin_pets")))
