# PetShop – Hệ thống Quản lý Cửa hàng Thú cưng (Đề 28)

Môn: Triển khai và Quản trị Hệ thống Phần mềm
Sinh viên: <Họ tên> – MSSV: <MSSV> – Lớp: <Lớp>

## 1. Giới thiệu
Website quản lý thú cưng, khách hàng, dịch vụ spa và lịch hẹn. Toàn bộ hệ thống chạy bằng Docker Compose, gồm
ứng dụng Flask, PostgreSQL + pgAdmin, Nginx reverse proxy (HTTPS), Prometheus + Grafana (giám sát),
Loki + Promtail (log tập trung) và các biện pháp hardening.

## 2. Kiến trúc
| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| app | Python Flask + Gunicorn | Website quản lý PetShop |
| db | PostgreSQL 16 | Cơ sở dữ liệu |
| pgadmin | pgAdmin 4 | Công cụ quản lý DB |
| nginx | Nginx (unprivileged) | Reverse proxy, HTTPS, security headers |
| prometheus, grafana | Prometheus, Grafana | Giám sát container, web server, DB |
| cadvisor, nginx-exporter, postgres-exporter | Exporters | Thu thập metrics |
| loki, promtail | Grafana Loki | Log tập trung, truy vấn LogQL |

Network: `frontend`, `backend` (internal), `monitoring`.

## 3. Yêu cầu
Ubuntu Server, Docker Engine, Docker Compose v2, RAM >= 4 GB.

## 4. Chạy hệ thống
```bash
git clone git@github.com:<MSSV>/petshop-project.git
cd petshop-project

cp .env.example .env
# Đặt mật khẩu mạnh cho các biến *_PASSWORD (gợi ý: openssl rand -hex 12)
# và sửa VM_IP cho khớp IP máy ảo của bạn
nano .env

./scripts/gen-cert.sh <IP_CUA_VM>

docker compose up -d --build
docker compose ps
```

## 5. Địa chỉ truy cập
| Dịch vụ | URL |
|---|---|
| Website PetShop | https://<IP_VM>/ |
| pgAdmin | https://<IP_VM>/pgadmin/ |
| Grafana | https://<IP_VM>/grafana/ |
| Prometheus | http://127.0.0.1:9090 (qua SSH tunnel: `ssh -L 9090:127.0.0.1:9090 user@<IP_VM>`) |

Chứng chỉ HTTPS tự ký nên trình duyệt sẽ cảnh báo; chọn Advanced → Proceed.

## 6. Demo nhanh
1. Mở website, thêm khách hàng / thú cưng / lịch hẹn.
2. Mở pgAdmin, xem bảng trong database `petshopdb`.
3. Prometheus `/targets`: tất cả target UP.
4. Grafana: dashboard "PetShop - Tổng quan hệ thống" và "PetShop - Log tập trung".
5. Grafana Explore (Loki), ví dụ truy vấn LogQL:
   - `{service="nginx"}`
   - `{service="app"} |= "GET"`
   - `sum by (service) (rate({service=~".+"}[1m]))`
6. Chạy `./scripts/hardening-check.sh` để xem bằng chứng hardening.

## 6.1. Lịch sử commit
- Commit 0: ứng dụng + PostgreSQL + pgAdmin
- Commit 1: Nginx reverse proxy + HTTPS + security headers
- Commit 2: Prometheus + Grafana + exporters
- Commit 3: Loki + Promtail + LogQL
- Commit 4: Hardening

## 7. Hardening
Xem [docs/HARDENING.md](docs/HARDENING.md).

## 8. Dừng / xóa
```bash
docker compose down        # dừng, giữ dữ liệu
docker compose down -v     # dừng và xóa toàn bộ dữ liệu
