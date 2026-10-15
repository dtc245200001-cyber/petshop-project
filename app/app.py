import os

import psycopg2
import psycopg2.extras
from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for
from prometheus_flask_exporter import PrometheusMetrics

app = Flask(__name__)
metrics = PrometheusMetrics(app)  # tự động mở /metrics cho Prometheus
metrics.info("petshop_app_info", "Thong tin ung dung PetShop", version="1.0.0")

DB_CONFIG = dict(
    host=os.environ.get("DB_HOST", "db"),
    port=int(os.environ.get("DB_PORT", "5432")),
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    connect_timeout=5,
)

# ---------- Cấu hình các trang CRUD ----------
ENTITIES = {
    "customers": {
        "title": "Khách hàng",
        "columns": [("id", "ID"), ("name", "Họ tên"), ("phone", "Điện thoại"), ("email", "Email")],
        "list_sql": "SELECT id, name, phone, email FROM customers ORDER BY id DESC",
        "insert_sql": "INSERT INTO customers (name, phone, email) VALUES (%s, %s, %s)",
        "delete_sql": "DELETE FROM customers WHERE id = %s",
        "fields": [
            {"name": "name", "label": "Họ tên", "type": "text", "required": True},
            {"name": "phone", "label": "Điện thoại", "type": "text"},
            {"name": "email", "label": "Email", "type": "email"},
        ],
    },
    "pets": {
        "title": "Thú cưng",
        "columns": [("id", "ID"), ("name", "Tên"), ("species", "Loài"), ("breed", "Giống"),
                    ("age", "Tuổi"), ("owner", "Chủ nuôi")],
        "list_sql": """SELECT p.id, p.name, p.species, p.breed, p.age, c.name AS owner
                       FROM pets p JOIN customers c ON c.id = p.customer_id
                       ORDER BY p.id DESC""",
        "insert_sql": "INSERT INTO pets (name, species, breed, age, customer_id) VALUES (%s, %s, %s, %s, %s)",
        "delete_sql": "DELETE FROM pets WHERE id = %s",
        "fields": [
            {"name": "name", "label": "Tên", "type": "text", "required": True},
            {"name": "species", "label": "Loài", "type": "select", "required": True,
             "static_options": ["Chó", "Mèo", "Thỏ", "Khác"]},
            {"name": "breed", "label": "Giống", "type": "text"},
            {"name": "age", "label": "Tuổi", "type": "number"},
            {"name": "customer_id", "label": "Chủ nuôi", "type": "select", "required": True,
             "options_sql": "SELECT id, name AS label FROM customers ORDER BY name"},
        ],
    },
    "services": {
        "title": "Dịch vụ spa",
        "columns": [("id", "ID"), ("name", "Dịch vụ"), ("price", "Giá (VNĐ)"), ("duration_min", "Thời lượng (phút)")],
        "list_sql": "SELECT id, name, price, duration_min FROM services ORDER BY id",
        "insert_sql": "INSERT INTO services (name, price, duration_min) VALUES (%s, %s, %s)",
        "delete_sql": "DELETE FROM services WHERE id = %s",
        "fields": [
            {"name": "name", "label": "Tên dịch vụ", "type": "text", "required": True},
            {"name": "price", "label": "Giá (VNĐ)", "type": "number", "required": True},
            {"name": "duration_min", "label": "Thời lượng (phút)", "type": "number", "required": True},
        ],
    },
    "appointments": {
        "title": "Lịch hẹn",
        "columns": [("id", "ID"), ("appt_time", "Thời gian"), ("pet", "Thú cưng"),
                    ("service", "Dịch vụ"), ("status", "Trạng thái")],
        "list_sql": """SELECT a.id, to_char(a.appt_time, 'DD/MM/YYYY HH24:MI') AS appt_time,
                              p.name AS pet, s.name AS service, a.status
                       FROM appointments a
                       JOIN pets p ON p.id = a.pet_id
                       JOIN services s ON s.id = a.service_id
                       ORDER BY a.appt_time DESC""",
        "insert_sql": "INSERT INTO appointments (pet_id, service_id, appt_time, status) VALUES (%s, %s, %s, %s)",
        "delete_sql": "DELETE FROM appointments WHERE id = %s",
        "fields": [
            {"name": "pet_id", "label": "Thú cưng", "type": "select", "required": True,
             "options_sql": "SELECT id, name AS label FROM pets ORDER BY name"},
            {"name": "service_id", "label": "Dịch vụ", "type": "select", "required": True,
             "options_sql": "SELECT id, name AS label FROM services ORDER BY name"},
            {"name": "appt_time", "label": "Thời gian", "type": "datetime-local", "required": True},
            {"name": "status", "label": "Trạng thái", "type": "select", "required": True,
             "static_options": ["Chờ xác nhận", "Đã xác nhận", "Hoàn thành", "Đã hủy"]},
        ],
    },
}


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


def execute(sql, params=None):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


# ---------- Bảo mật & lỗi ----------
@app.after_request
def add_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    return resp


@app.errorhandler(psycopg2.Error)
def db_error(err):
    app.logger.error("Loi database: %s", err)
    return "Lỗi cơ sở dữ liệu, vui lòng thử lại.", 500


# ---------- Routes ----------
@app.route("/health")
def health():
    try:
        query("SELECT 1")
        return jsonify(status="ok"), 200
    except Exception as exc:  # noqa: BLE001
        app.logger.error("Health check failed: %s", exc)
        return jsonify(status="error"), 503


@app.route("/")
def index():
    stats = query(
        """SELECT (SELECT count(*) FROM customers)    AS customers,
                  (SELECT count(*) FROM pets)         AS pets,
                  (SELECT count(*) FROM services)     AS services,
                  (SELECT count(*) FROM appointments) AS appointments"""
    )[0]
    upcoming = query(
        """SELECT to_char(a.appt_time, 'DD/MM/YYYY HH24:MI') AS appt_time,
                  p.name AS pet, s.name AS service, a.status
           FROM appointments a
           JOIN pets p ON p.id = a.pet_id
           JOIN services s ON s.id = a.service_id
           WHERE a.appt_time >= now() - interval '1 day'
           ORDER BY a.appt_time LIMIT 10"""
    )
    return render_template("index.html", stats=stats, upcoming=upcoming)


@app.route("/<entity>", methods=["GET", "POST"])
def entity_page(entity):
    cfg = ENTITIES.get(entity)
    if cfg is None:
        abort(404)

    if request.method == "POST":
        values = [(request.form.get(f["name"]) or None) for f in cfg["fields"]]
        execute(cfg["insert_sql"], values)
        return redirect(url_for("entity_page", entity=entity))

    fields = []
    for f in cfg["fields"]:
        f = dict(f)
        if f.get("options_sql"):
            f["options"] = query(f["options_sql"])
        elif f.get("static_options"):
            f["options"] = [{"id": o, "label": o} for o in f["static_options"]]
        fields.append(f)

    rows = query(cfg["list_sql"])
    return render_template("page.html", entity=entity, cfg=cfg, fields=fields, rows=rows)


@app.route("/<entity>/<int:item_id>/delete", methods=["POST"])
def delete_item(entity, item_id):
    cfg = ENTITIES.get(entity)
    if cfg is None:
        abort(404)
    execute(cfg["delete_sql"], (item_id,))
    return redirect(url_for("entity_page", entity=entity))
