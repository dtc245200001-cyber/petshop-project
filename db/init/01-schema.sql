CREATE TABLE customers (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    phone      VARCHAR(20),
    email      VARCHAR(100),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE pets (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    species     VARCHAR(50)  NOT NULL,
    breed       VARCHAR(80),
    age         NUMERIC(4,1),
    customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE
);

CREATE TABLE services (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    price        NUMERIC(10,0) NOT NULL,
    duration_min INT NOT NULL DEFAULT 30
);

CREATE TABLE appointments (
    id         SERIAL PRIMARY KEY,
    pet_id     INT NOT NULL REFERENCES pets(id)     ON DELETE CASCADE,
    service_id INT NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    appt_time  TIMESTAMP NOT NULL,
    status     VARCHAR(30) NOT NULL DEFAULT 'Chờ xác nhận'
);

INSERT INTO customers (name, phone, email) VALUES
 ('Nguyễn Văn An',  '0901234567', 'an@example.com'),
 ('Trần Thị Bình',  '0912345678', 'binh@example.com'),
 ('Lê Hoàng Cường', '0923456789', 'cuong@example.com');

INSERT INTO pets (name, species, breed, age, customer_id) VALUES
 ('Mực',   'Chó', 'Poodle',   3.0, 1),
 ('Mimi',  'Mèo', 'Anh lông ngắn', 2.0, 2),
 ('Bông',  'Chó', 'Corgi',    1.5, 2),
 ('Lu',    'Mèo', 'Ba Tư',    4.0, 3);

INSERT INTO services (name, price, duration_min) VALUES
 ('Tắm spa cơ bản',      150000, 45),
 ('Cắt tỉa lông',        200000, 60),
 ('Spa cao cấp',         350000, 90),
 ('Khám sức khỏe tổng quát', 250000, 30);

INSERT INTO appointments (pet_id, service_id, appt_time, status) VALUES
 (1, 1, now() + interval '1 day',  'Đã xác nhận'),
 (2, 3, now() + interval '2 days', 'Chờ xác nhận'),
 (3, 2, now() + interval '3 days', 'Chờ xác nhận');
