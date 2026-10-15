1. Container chạy non-root (app UID 10001, nginx UID 101, pgadmin/grafana/prometheus/loki dùng user riêng của image).
2. Network isolation: 3 network `frontend`, `backend` (internal), `monitoring`. Mỗi dịch vụ nặng có giới hạn RAM (`mem_limit`) để VM 4 GB không bị OOM. Database không publish port.
3. Mật khẩu mạnh sinh bằng `openssl rand -hex 12`, lưu trong `.env` (không commit).
4. PostgreSQL least privilege: `petshop_app` chỉ CRUD; `exporter` chỉ `pg_monitor`; thu hồi quyền PUBLIC.
5. Nginx: security headers, TLS 1.2/1.3, `server_tokens off`, rate limiting, chặn `/metrics`.
6. `cap_drop: ALL`, `no-new-privileges`, filesystem `read_only` cho app và nginx.
7. UFW chỉ mở 22/80/443; các cổng nội bộ bind 127.0.0.1.

## Hạn chế đã biết
- Chứng chỉ HTTPS tự ký, trình duyệt sẽ cảnh báo (môi trường lab).
- Promtail và cAdvisor cần quyền đọc Docker socket / hệ thống; đây là đánh đổi chấp nhận được trong lab.
- Chưa có WAF, chưa bật xác thực cho ứng dụng PetShop.
