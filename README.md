# PetShop – Hệ thống Quản lý Cửa hàng Thú cưng (Đề 28)

Môn: Triển khai và Quản trị Hệ thống Phần mềm
Sinh viên: <Họ tên> – MSSV: <MSSV> – Lớp: <Lớp>

## 1. Giới thiệu
Website quản lý thú cưng, khách hàng, dịch vụ spa và lịch hẹn, có **đăng nhập/đăng ký** và **phân quyền
User / Admin**. Toàn bộ hệ thống chạy bằng Docker Compose, gồm ứng dụng Flask, PostgreSQL + pgAdmin,
Nginx reverse proxy (HTTPS), Prometheus + Grafana (giám sát), Loki + Promtail (log tập trung) và các
biện pháp hardening.

## 2. Kiến trúc
| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| app | Python Flask + Gunicorn | Website (đăng nhập, luồng User, luồng Admin) |
| db | PostgreSQL 16 | Cơ sở dữ liệu |
| pgadmin | pgAdmin 4 | Công cụ quản lý DB |
| nginx | Nginx (unprivileged) | Reverse proxy, HTTPS, security headers, rate limit |
| prometheus, grafana | Prometheus, Grafana | Giám sát container, web server, DB, ứng dụng |
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
# Đặt mật khẩu mạnh cho các biến *_PASSWORD (gợi ý: openssl rand -hex 12),
# SECRET_KEY (openssl rand -hex 32), ADMIN_EMAIL, và sửa VM_IP cho khớp IP máy ảo
nano .env

./scripts/gen-cert.sh <IP_CUA_VM>

docker compose up -d --build
docker compose ps
