# Các biện pháp hardening

1. Container chạy non-root (app UID 10001, nginx UID 101, pgadmin/grafana/prometheus/loki dùng user riêng của image).
2. Network isolation: 3 network `frontend`, `backend` (internal), `monitoring`. Mỗi dịch vụ nặng có giới hạn RAM (`mem_limit`) để VM 4 GB không bị OOM. Database không publish port.
3. Mật khẩu mạnh sinh bằng `openssl rand -hex 12`, lưu trong `.env` (không commit).
4. PostgreSQL least privilege: `petshop_app` chỉ CRUD; `exporter` chỉ `pg_monitor`; thu hồi quyền PUBLIC.
5. Nginx: security headers, TLS 1.2/1.3, `server_tokens off`, rate limiting, chặn `/metrics`.
6. `cap_drop: ALL`, `no-new-privileges`, filesystem `read_only` cho app và nginx.
7. UFW chỉ mở 22/80/443; các cổng nội bộ bind 127.0.0.1.
8. Mật khẩu người dùng băm scrypt (có salt), không lưu bản rõ.
9. CSRF token cho mọi form POST; cookie phiên HttpOnly, Secure, SameSite=Lax, hết hạn sau 2 giờ; `Cache-Control: no-store`.
10. Phân quyền User/Admin kiểm tra ở server (decorator), vai trò đọc lại từ DB mỗi request; User chỉ truy cập dữ liệu của chính mình.
11. Nginx giới hạn tốc độ riêng cho `/login`, `/register`; app ghi log `LOGIN_OK`/`LOGIN_FAIL`/`CSRF_FAIL` để truy vết bằng Loki.

## Hạn chế đã biết
- Chứng chỉ HTTPS tự ký, trình duyệt sẽ cảnh báo (môi trường lab).
- Promtail và cAdvisor cần quyền đọc Docker socket / hệ thống; đây là đánh đổi chấp nhận được trong lab.
- Chưa có WAF; chưa có 2FA, khóa tài khoản sau nhiều lần sai, hay chức năng quên mật khẩu (chỉ có giới hạn tốc độ ở Nginx).
- Mật khẩu admin ban đầu truyền qua biến môi trường (`docker inspect` thấy được); chỉ dùng để khởi tạo, nên đổi trong môi trường thật.
