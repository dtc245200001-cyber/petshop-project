#!/usr/bin/env bash
# In ra bằng chứng các biện pháp hardening. Chạy tại thư mục gốc dự án.
cd "$(dirname "$0")/.." || exit 1
set -a; . ./.env; set +a

CONTAINERS="petshop-nginx petshop-app petshop-pgadmin petshop-db petshop-grafana petshop-prometheus petshop-loki"

echo "=== 1. USER CHAY TIEN TRINH CHINH (khong phai root) ==="
for c in $CONTAINERS; do
  printf "%-22s " "$c"
  docker top "$c" -eo user 2>/dev/null | sed -n '2p'
done

echo
echo "=== 2. CAP_DROP / NO-NEW-PRIVILEGES / READ-ONLY ==="
docker inspect -f '{{.Name}}  cap_drop={{.HostConfig.CapDrop}}  security={{.HostConfig.SecurityOpt}}  read_only={{.HostConfig.ReadonlyRootfs}}' \
  $(docker ps -q) | sort

echo
echo "=== 3. CONG DUOC PUBLISH RA NGOAI ==="
docker ps --format 'table {{.Names}}\t{{.Ports}}'

echo
echo "=== 4. NETWORK ISOLATION ==="
for n in frontend backend monitoring; do
  printf "petshop_%-11s internal=%s\n" "$n" "$(docker network inspect petshop_$n --format '{{.Internal}}')"
done
echo "Database co the truy cap tu host khong? (mong doi: KHONG)"
nc -zv -w2 127.0.0.1 5432 2>&1 | tail -1 || true

echo
echo "=== 5. SECURITY HEADERS CUA NGINX ==="
curl -skI https://localhost | grep -iE "HTTP/|strict-transport|x-frame|x-content-type|referrer-policy|permissions-policy|content-security|server:"

echo
echo "=== 6. HTTP -> HTTPS REDIRECT ==="
curl -sI http://localhost | head -3

echo
echo "=== 7. ROLE DATABASE (least privilege) ==="
docker exec petshop-db psql -U "$DB_ADMIN_USER" -d "$DB_NAME" -c "\du"
echo "Thu DROP TABLE bang user cua app (mong doi: permission denied / must be owner):"
docker exec petshop-db psql -U petshop_app -d "$DB_NAME" -c "DROP TABLE pets;" 2>&1 | head -2

echo
echo "=== 8. /metrics KHONG LO RA NGOAI ==="
curl -sk -o /dev/null -w "HTTP %{http_code}\n" https://localhost/metrics

echo
echo "=== 9. TUONG LUA UFW ==="
sudo ufw status | head -12

# ===== [MỚI] Các kiểm tra tầng ứng dụng (đăng nhập / phân quyền) =====
echo
echo "=== 10. XAC THUC VA PHAN QUYEN (tang ung dung) ==="
echo "Chua dang nhap vao /admin/dashboard (mong doi 302 -> /login):"
curl -sk -o /dev/null -w "  HTTP %{http_code} -> %{redirect_url}\n" https://localhost/admin/dashboard
echo "Chua dang nhap vao /my-pets (mong doi 302 -> /login):"
curl -sk -o /dev/null -w "  HTTP %{http_code} -> %{redirect_url}\n" https://localhost/my-pets
echo "POST /login khong co CSRF token (mong doi 400):"
curl -sk -o /dev/null -w "  HTTP %{http_code}\n" -X POST -d "email=a@b.c&password=x" https://localhost/login
echo "Cookie phien (mong doi co HttpOnly, Secure, SameSite=Lax):"
curl -skI https://localhost/login | grep -i '^set-cookie' | sed 's/=[^;]*;/=<an>;/'
echo "Mat khau trong DB la hash scrypt, khong phai ban ro:"
docker exec petshop-db psql -U "$DB_ADMIN_USER" -d "$DB_NAME" -c "SELECT email, role, left(password_hash, 22) || '...' AS hash FROM customers WHERE password_hash IS NOT NULL;"
echo "Admin dang nhap va vao /admin/dashboard (mong doi 200):"
CJ=$(mktemp)
TOKEN=$(curl -sk -c "$CJ" https://localhost/login | grep -o 'name="csrf_token" value="[^"]*"' | cut -d'"' -f4)
curl -sk -b "$CJ" -c "$CJ" -o /dev/null -d "csrf_token=$TOKEN&email=$ADMIN_EMAIL&password=$ADMIN_PASSWORD" https://localhost/login
curl -sk -b "$CJ" -o /dev/null -w "  HTTP %{http_code}\n" https://localhost/admin/dashboard
rm -f "$CJ"
