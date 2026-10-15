#!/usr/bin/env bash
# Tạo chứng chỉ TLS tự ký cho Nginx. Cách dùng: ./scripts/gen-cert.sh 192.168.211.129
set -e
IP="${1:-192.168.211.129}"
mkdir -p nginx/certs
sudo rm -f nginx/certs/selfsigned.key nginx/certs/selfsigned.crt

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/selfsigned.key \
  -out nginx/certs/selfsigned.crt \
  -subj "/C=VN/O=PetShop/CN=${IP}" \
  -addext "subjectAltName=IP:${IP},DNS:localhost"

# Nginx (unprivileged) chạy với UID 101 -> chỉ user này đọc được khóa riêng
sudo chown 101:101 nginx/certs/selfsigned.key
sudo chmod 600 nginx/certs/selfsigned.key
chmod 644 nginx/certs/selfsigned.crt
echo "Da tao chung chi cho ${IP}"
