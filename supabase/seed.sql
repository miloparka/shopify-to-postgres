-- ============================================================
-- Demo seed data (matches the full schema in
-- 20260908065944_shopify_schema.sql, and the fixtures generated into
-- demo_data/*.json by the same source data).
-- Fictional vendors, products, and customers. Structural patterns
-- (thin vs. rich vendor data, food vs. non-food mix) preserved from v1.
-- ============================================================

-- ---------------------------------------------
-- CUSTOMERS
-- ---------------------------------------------
insert into customers (id, state, verified_email, accepts_marketing, tax_exempt, currency, orders_count, total_spent, tags, customer_locale, country, province, city, created_at, updated_at) values
  (1, 'ENABLED', true,  true,  false, 'EUR', 3, 42.50,  '{newsletter}', 'fi', 'Finland', 'Uusimaa',            'Helsinki', '2025-11-02T10:00:00Z', '2026-08-01T09:00:00Z'),
  (2, 'ENABLED', true,  false, false, 'EUR', 1, 15.00,  '{}',           'fi', 'Finland', 'Uusimaa',            'Espoo',    '2025-12-15T14:30:00Z', '2025-12-15T14:30:00Z'),
  (3, 'ENABLED', true,  true,  false, 'EUR', 5, 88.20,  '{wholesale}',  'fi', 'Finland', 'Pirkanmaa',          'Tampere',  '2025-09-20T08:15:00Z', '2026-09-01T11:20:00Z'),
  (4, 'ENABLED', false, false, false, 'EUR', 0, 0.00,   '{}',           'fi', 'Finland', 'Varsinais-Suomi',    'Turku',    '2026-08-30T16:45:00Z', '2026-08-30T16:45:00Z'),  -- new signup, no orders yet
  (5, 'ENABLED', true,  true,  false, 'EUR', 8, 210.75, '{vip}',        'fi', 'Finland', 'Pohjois-Pohjanmaa',  'Oulu',     '2025-06-11T12:00:00Z', '2026-09-05T10:10:00Z');

-- ---------------------------------------------
-- PRODUCTS
-- ---------------------------------------------
insert into products (id, title, body_html, vendor, product_type, handle, status, tags, package_type, published_at, created_at, updated_at) values
  (101, 'Fruit Chew Candy 14g',        '<p>Fruit Chew Candy 14g</p>',        'Vendor A', 'Candy',      'fruit-chew-candy-14g',        'ACTIVE', '{}', null,            '2025-05-01T00:00:00Z', '2025-05-01T00:00:00Z', '2025-05-01T00:00:00Z'), -- food, thin data
  (102, 'Aged Cheese Wedge 400g',      '<p>Aged Cheese Wedge 400g</p>',      'Vendor B', 'Dairy',      'aged-cheese-wedge-400g',      'ACTIVE', '{}', 'plastic_wrap',  '2025-05-01T00:00:00Z', '2025-05-01T00:00:00Z', '2025-05-01T00:00:00Z'), -- food, rich data
  (103, 'Corn Chips Bag 185g',         '<p>Corn Chips Bag 185g</p>',         'Vendor C', 'Snacks',     'corn-chips-bag-185g',         'ACTIVE', '{}', 'foil_bag',      '2025-05-02T00:00:00Z', '2025-05-02T00:00:00Z', '2025-05-02T00:00:00Z'), -- food, rich data
  (104, 'Family Board Game',           '<p>Family Board Game</p>',           'Vendor D', 'Toys',       'family-board-game',           'ACTIVE', '{}', 'cardboard_box', '2025-05-02T00:00:00Z', '2025-05-02T00:00:00Z', '2025-05-02T00:00:00Z'), -- non-food
  (105, 'Dried Birch Whisk',           '<p>Dried Birch Whisk</p>',           'Vendor E', 'Home',       'dried-birch-whisk',           'ACTIVE', '{}', null,            '2025-05-03T00:00:00Z', '2025-05-03T00:00:00Z', '2025-05-03T00:00:00Z'), -- non-food, thin data
  (106, 'Chocolate Truffle Box 200g',  '<p>Chocolate Truffle Box 200g</p>',  'Vendor F', 'Candy',      'chocolate-truffle-box-200g',  'ACTIVE', '{}', 'gift_box',      '2025-05-03T00:00:00Z', '2025-05-03T00:00:00Z', '2025-05-03T00:00:00Z'), -- food, rich data
  (107, 'Oat Porridge 1kg',            '<p>Oat Porridge 1kg</p>',            'Vendor G', 'Breakfast',  'oat-porridge-1kg',            'ACTIVE', '{}', 'paper_bag',     '2025-05-04T00:00:00Z', '2025-05-04T00:00:00Z', '2025-05-04T00:00:00Z'), -- food, rich data
  (108, 'Smoking Pellets 1L',          '<p>Smoking Pellets 1L</p>',          'Vendor H', 'Outdoor',    'smoking-pellets-1l',          'ACTIVE', '{}', null,            '2025-05-04T00:00:00Z', '2025-05-04T00:00:00Z', '2025-05-04T00:00:00Z'); -- non-food, thin data

-- ---------------------------------------------
-- PRODUCT_VARIANTS (one default variant per product, matching demo_data)
-- ---------------------------------------------
insert into product_variants (id, product_id, title, sku, barcode, price, inventory_quantity, weight, weight_unit, requires_shipping, taxable, position, created_at, updated_at) values
  (1011, 101, 'Default Title', '900001', '1000000000001', 0.89,  100, 0.1, 'KILOGRAMS', true, true, 1, '2025-05-01T00:00:00Z', '2025-05-01T00:00:00Z'),
  (1021, 102, 'Default Title', '900002', '1000000000002', 3.49,  100, 0.1, 'KILOGRAMS', true, true, 1, '2025-05-01T00:00:00Z', '2025-05-01T00:00:00Z'),
  (1031, 103, 'Default Title', '900003', '1000000000003', 2.29,  100, 0.1, 'KILOGRAMS', true, true, 1, '2025-05-02T00:00:00Z', '2025-05-02T00:00:00Z'),
  (1041, 104, 'Default Title', '900004', '1000000000004', 14.90, 100, 0.1, 'KILOGRAMS', true, true, 1, '2025-05-02T00:00:00Z', '2025-05-02T00:00:00Z'),
  (1051, 105, 'Default Title', '900005', '1000000000005', 6.50,  100, 0.1, 'KILOGRAMS', true, true, 1, '2025-05-03T00:00:00Z', '2025-05-03T00:00:00Z'),
  (1061, 106, 'Default Title', '900006', '1000000000006', 5.90,  100, 0.1, 'KILOGRAMS', true, true, 1, '2025-05-03T00:00:00Z', '2025-05-03T00:00:00Z'),
  (1071, 107, 'Default Title', '900007', '1000000000007', 2.99,  100, 0.1, 'KILOGRAMS', true, true, 1, '2025-05-04T00:00:00Z', '2025-05-04T00:00:00Z'),
  (1081, 108, 'Default Title', '900008', '1000000000008', 4.20,  100, 0.1, 'KILOGRAMS', true, true, 1, '2025-05-04T00:00:00Z', '2025-05-04T00:00:00Z');

-- ---------------------------------------------
-- PRODUCT_IMAGES (matching demo_data's has_image products: 101,102,104,106,107)
-- ---------------------------------------------
insert into product_images (id, product_id, src, alt, position) values
  (1010, 101, 'https://cdn.example-shopify.com/products/101.jpg', 'Fruit Chew Candy 14g',       1),
  (1020, 102, 'https://cdn.example-shopify.com/products/102.jpg', 'Aged Cheese Wedge 400g',     1),
  (1040, 104, 'https://cdn.example-shopify.com/products/104.jpg', 'Family Board Game',          1),
  (1060, 106, 'https://cdn.example-shopify.com/products/106.jpg', 'Chocolate Truffle Box 200g', 1),
  (1070, 107, 'https://cdn.example-shopify.com/products/107.jpg', 'Oat Porridge 1kg',           1);

-- ---------------------------------------------
-- ORDERS
-- ---------------------------------------------
insert into orders (id, customer_id, order_number, currency, financial_status, fulfillment_status, total_price, subtotal_price, total_tax, total_discounts, total_shipping, source_name, tags, discount_codes, shipping_country, shipping_province, shipping_city, created_at, updated_at, processed_at, closed_at) values
  (201, 1, '#1001', 'EUR', 'PAID', 'FULFILLED',             15.05, 10.57, 1.48, 0.00, 3.00, 'web', '{}',          '[]',              'Finland', 'Uusimaa',           'City A', '2026-08-01T09:00:00Z', '2026-08-01T09:00:00Z', '2026-08-01T09:00:00Z', '2026-08-01T09:00:00Z'),
  (202, 2, '#1002', 'EUR', 'PAID', 'FULFILLED',             27.76, 18.78, 2.63, 0.00, 6.90, 'web', '{gift}',      '[]',              'Finland', 'Uusimaa',           'City B', '2025-12-15T14:30:00Z', '2025-12-15T14:30:00Z', '2025-12-15T14:30:00Z', '2025-12-15T14:30:00Z'),
  (203, 3, '#1003', 'EUR', 'PAID', 'PARTIAL',   27.34, 21.36, 2.99, 0.00, 3.00, 'web', '{wholesale}', '["WELCOME10"]',  'Finland', 'Pirkanmaa',         'City C', '2026-09-01T11:20:00Z', '2026-09-01T11:20:00Z', '2026-09-01T11:20:00Z', null),
  (204, 5, '#1004', 'EUR', 'PAID', 'FULFILLED',             17.99, 15.78, 2.21, 0.00, 0.00, 'pos', '{}',          '[]',              'Finland', 'Pohjois-Pohjanmaa', 'City D', '2026-09-05T10:10:00Z', '2026-09-05T10:10:00Z', '2026-09-05T10:10:00Z', '2026-09-05T10:10:00Z'),
  (205, 5, '#1005', 'EUR', 'REFUNDED', 'FULFILLED',          8.41, 6.50,  0.91, 0.00, 3.00, 'web', '{}',          '[]',              'Finland', 'Pohjois-Pohjanmaa', 'City D', '2026-06-20T13:00:00Z', '2026-06-20T13:00:00Z', '2026-06-20T13:00:00Z', '2026-06-20T13:00:00Z');

-- ---------------------------------------------
-- ORDER_LINE_ITEMS
-- ---------------------------------------------
insert into order_line_items (id, order_id, product_id, variant_id, title, sku, quantity, price, total_discount) values
  (301, 201, 101, 1011, 'Fruit Chew Candy 14g',       '900001', 2, 0.89,  0.00),
  (302, 201, 103, 1031, 'Corn Chips Bag 185g',        '900003', 1, 2.29,  0.00),
  (303, 201, 105, 1051, 'Dried Birch Whisk',          '900005', 1, 6.50,  0.00),

  (304, 202, 104, 1041, 'Family Board Game',          '900004', 1, 14.90, 0.00),
  (305, 202, 107, 1071, 'Oat Porridge 1kg',           '900007', 1, 2.99,  0.00),
  (306, 202, 101, 1011, 'Fruit Chew Candy 14g',       '900001', 8, 0.89,  0.00),

  (307, 203, 102, 1021, 'Aged Cheese Wedge 400g',     '900002', 3, 3.49,  0.00),
  (308, 203, 106, 1061, 'Chocolate Truffle Box 200g', '900006', 1, 5.90,  0.00),
  (309, 203, 107, 1071, 'Oat Porridge 1kg',           '900007', 2, 2.99,  0.00),

  (310, 204, 104, 1041, 'Family Board Game',          '900004', 1, 14.90, 0.00),
  (311, 204, 101, 1011, 'Fruit Chew Candy 14g',       '900001', 2, 0.89,  0.00),

  (312, 205, 105, 1051, 'Dried Birch Whisk',          '900005', 1, 6.50,  0.00);

-- ---------------------------------------------
-- ORDER_SHIPPING_LINES
-- ---------------------------------------------
insert into order_shipping_lines (order_id, title, price, code) values
  (201, 'Standard Shipping', 3.00, 'STANDARD'),
  (202, 'Express Courier',   6.90, 'EXPRESS'),
  (203, 'Standard Shipping', 3.00, 'STANDARD'),
  (204, 'Store Pickup',      0.00, 'PICKUP'),
  (205, 'Standard Shipping', 3.00, 'STANDARD');
