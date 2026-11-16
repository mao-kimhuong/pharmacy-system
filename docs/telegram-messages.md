# Telegram messages (T2)

Generated from the templates (`notification_service/services/customer_texts.py`, `texts.py`, `staff_bot.py`). Customer messages go in the customer's language; staff, supplier and bot messages are Khmer then English.

### Receipt (km) + A4 PDF
```
🧾 សាខាទួលគោក
បង្កាន់ដៃ PP1-INV-2026-000123: 12.50 USD (51,300 ៛)
សូមអរគុណ!
```

### Refill reminder (km)
```
💊 ថ្នាំតាមវេជ្ជបញ្ជា PP1-RX-2026-000009 នឹងអស់ប្រហែលថ្ងៃទី 03/11/2026។
អ្នកអាចមកយកថ្នាំបន្តនៅ សាខាទួលគោក។
```

### Refill reminder, medicine names on, no refills left (km)
```
💊 ថ្នាំ Amlodipine 5 mg តាមវេជ្ជបញ្ជា PP1-RX-2026-000009 នឹងអស់ប្រហែលថ្ងៃទី 03/11/2026។
សូមយកវេជ្ជបញ្ជាថ្មីមក សាខាទួលគោក។
```

### Order ready (km)
```
📦 ការកម្ម៉ង់ PP1-SO-2026-000004 រួចរាល់ហើយ សូមមកយកនៅ សាខាទួលគោក។
ប្រាក់ត្រូវបង់ពេលមកយក: 4.50 USD។
```

### Clinic order status (km)
```
📋 សាខាទួលគោក: ការកម្ម៉ង់ PP1-SO-2026-000004 – បានប្រគល់មួយផ្នែក។
```

### Monthly balance (km) + statement PDF
```
📄 សមតុល្យគណនីប្រចាំខែ
សមតុល្យជំពាក់: 30.00 USD
របាយការណ៍គណនីភ្ជាប់មកជាមួយ។ អាចបង់ប្រាក់នៅសាខាណាមួយរបស់យើង។
```

### Overdue (km) + statement PDF
```
⏰ ប្រាក់ជំពាក់ហួសកាលកំណត់
សមតុល្យជំពាក់: 30.00 USD
ហួសកាលកំណត់: 12.00 USD (តាំងពី 01/10/2026)
របាយការណ៍គណនីភ្ជាប់មកជាមួយ។ អាចបង់ប្រាក់នៅសាខាណាមួយរបស់យើង។
```

### Deposit received (km)
```
💵 សាខាទួលគោក: បានទទួលប្រាក់កក់ 5.00 USD សម្រាប់ការកម្ម៉ង់ PP1-SO-2026-000004។ សូមអរគុណ!
```

### Deposit refunded (km)
```
↩️ សាខាទួលគោក: បានសងប្រាក់កក់ 5.00 USD វិញ សម្រាប់ការកម្ម៉ង់ PP1-SO-2026-000004។
```

### Deposit kept as credit (km)
```
💳 សាខាទួលគោក: ប្រាក់កក់ 5.00 USD នៃការកម្ម៉ង់ PP1-SO-2026-000004 ត្រូវបានរក្សាទុកជាឥណទានសម្រាប់ការទិញលើកក្រោយ។
```

### Return refund (km)
```
↩️ សាខាទួលគោក: បានសងប្រាក់ 2.00 USD ជាសាច់ប្រាក់ សម្រាប់ការប្តូរយកវិញ PP1-RT-2026-000001។
```

### Promotion (km)
```
🎁 បញ្ចុះតម្លៃ ១០% លើវីតាមីន

មិនចង់ទទួលប្រូម៉ូសិន? ផ្ញើ /settings
```

### Linked (km)
```
✅ បានភ្ជាប់រួចរាល់! អ្នកនឹងទទួលបង្កាន់ដៃ ការរំលឹក និងព័ត៌មានគណនីនៅទីនេះ។
ផ្ញើ /settings ដើម្បីជ្រើសរើស ឬ /stop ដើម្បីបញ្ឈប់។
```

### /settings (km)
```
ជ្រើសរើសសារដែលអ្នកចង់ទទួល (ចុចដើម្បីបើក/បិទ):
✅ បង្កាន់ដៃ
✅ ការរំលឹកយកថ្នាំ
⬜ សមតុល្យជំពាក់
⬜ ការកម្ម៉ង់
⬜ បង្ហាញឈ្មោះថ្នាំ
⬜ ប្រូម៉ូសិន
🛑 /stop
```

### Receipt (en) + A4 PDF
```
🧾 PP1 Toul Kork
Receipt PP1-INV-2026-000123: 12.50 USD (51,300 KHR)
Thank you!
```

### Refill reminder (en)
```
💊 Your medicine from prescription PP1-RX-2026-000009 runs out around 03/11/2026.
You can collect a refill at PP1 Toul Kork.
```

### Refill reminder, medicine names on, no refills left (en)
```
💊 Your Amlodipine 5 mg from prescription PP1-RX-2026-000009 runs out around 03/11/2026.
Please bring a new prescription to PP1 Toul Kork.
```

### Order ready (en)
```
📦 Order PP1-SO-2026-000004 is ready for pickup at PP1 Toul Kork.
To pay at pickup: 4.50 USD.
```

### Clinic order status (en)
```
📋 PP1 Toul Kork: order PP1-SO-2026-000004 – partly delivered.
```

### Monthly balance (en) + statement PDF
```
📄 Monthly account balance
Balance: 30.00 USD
Your statement is attached. You can pay at any of our branches.
```

### Overdue (en) + statement PDF
```
⏰ Payment overdue
Balance: 30.00 USD
Overdue: 12.00 USD (since 01/10/2026)
Your statement is attached. You can pay at any of our branches.
```

### Deposit received (en)
```
💵 PP1 Toul Kork: deposit of 5.00 USD received for order PP1-SO-2026-000004. Thank you!
```

### Deposit refunded (en)
```
↩️ PP1 Toul Kork: deposit of 5.00 USD refunded for order PP1-SO-2026-000004.
```

### Deposit kept as credit (en)
```
💳 PP1 Toul Kork: the deposit of 5.00 USD from order PP1-SO-2026-000004 is kept as credit for your next purchase.
```

### Return refund (en)
```
↩️ PP1 Toul Kork: 2.00 USD refunded in cash for return PP1-RT-2026-000001.
```

### Promotion (en)
```
🎁 10% off vitamins this week

No more promotions? Send /settings
```

### Linked (en)
```
✅ Linked! You will get receipts, reminders and account news here.
Send /settings to choose, or /stop to stop.
```

### /settings (en)
```
Choose what you get (tap to turn on/off):
✅ Receipts
✅ Refill reminders
⬜ Account balance
⬜ Orders
⬜ Show medicine names
⬜ Promotions
🛑 /stop
```

### Bot: greeting (unknown chat)
```
សួស្តី! នេះជាបូតរបស់ឱសថស្ថាន។ ដើម្បីភ្ជាប់ សូមស្កេន QR នៅលើបង្កាន់ដៃ ឬសួរបុគ្គលិក។

Hello! This is the pharmacy's bot. To link your account, scan the QR code on your receipt or ask our staff.
```

### Bot: share your phone
```
ដើម្បីការពារគណនីរបស់អ្នក សូមចុចប៊ូតុងខាងក្រោម ដើម្បីចែករំលែកលេខទូរស័ព្ទរបស់អ្នក។

To protect your account, tap the button below to share your phone number.
[📱 ចែករំលែកលេខទូរស័ព្ទ / Share phone number]
```

### Bot: phone does not match
```
លេខទូរស័ព្ទនេះមិនត្រូវនឹងគណនីរបស់យើងទេ។ សូមសួរបុគ្គលិកដើម្បីភ្ជាប់នៅតុបញ្ជរ។

This phone number does not match our records. Ask our staff to link you at the counter.
```

### Bot: link used / expired
```
តំណនេះមិនអាចប្រើបានទៀតទេ (បានប្រើរួច ឬផុតកំណត់)។ សូមសួរបុគ្គលិកដើម្បីទទួលតំណថ្មី។

This link can no longer be used (already used or expired). Ask our staff for a new one.
```

### Bot: /stop
```
អ្នកនឹងមិនទទួលសារពីយើងទៀតទេ។ ដើម្បីភ្ជាប់ម្តងទៀត សូមស្កេន QR ថ្មី។

You will get no more messages from us. To link again, scan a new QR code.
```

### Staff linked
```
✅ បានភ្ជាប់គណនីបុគ្គលិក Dara។ ផ្ញើ /help ដើម្បីមើលពាក្យបញ្ជា។

✅ Staff account linked (Dara). Send /help for the commands.
```

### Supplier linked
```
✅ បានភ្ជាប់ Sales – Vuthy។ អ្នកនឹងទទួលការបញ្ជាទិញនៅទីនេះ។

✅ Linked (Sales – Vuthy). You will get our purchase orders here.
```

### Supplier: PO sent (+ PDF, button)
```
🛒 ការបញ្ជាទិញ PP1-PO-2026-000007 ពី សាខាទួលគោក · 02/11/2026។ សូមចុច "បានទទួល / បញ្ជាក់" នៅពេលអ្នកបានឃើញ។

🛒 Purchase order PP1-PO-2026-000007 from PP1 Toul Kork · 02/11/2026. Please tap "Received / Confirmed" once you have seen it.
[✅ បានទទួល / បញ្ជាក់ · Received / Confirmed]
```

### Approval: shrinkage (owner chat, buttons)
```
🟡 ត្រូវការការអនុម័ត · PP1 Toul Kork
ការកាត់ចេញពីស្តុក PP1-SH-2026-000012 · Sreyneang
20 · lot L1 · damaged

🟡 Approval needed · PP1 Toul Kork
Shrinkage PP1-SH-2026-000012 by Sreyneang
20 · lot L1 · damaged
Value: 30.00 USD
[✅ អនុម័ត / Approve] [❌ បដិសេធ / Reject]
```

### Approval: discount (branch chat)
```
🟡 ត្រូវការការអនុម័ត · PP1 Toul Kork
ការបញ្ចុះតម្លៃលើសកំណត់  · Sreyneang
15.00% (កំណត់ 5.00%) · 1.20 USD លើការលក់ 6.80 USD

🟡 Approval needed · PP1 Toul Kork
Discount above the cap  by Sreyneang
15.00% (cap 5.00%) · 1.20 USD on a 6.80 USD sale
Discount: 1.20 USD
```

### Approval: controlled (no buttons)
```
🟡 ត្រូវការការអនុម័ត · PP1 Toul Kork
ការកាត់ចេញពីស្តុក PP1-SH-2026-000013 · Sreyneang
5 · lot D2 · damaged

🟡 Approval needed · PP1 Toul Kork
Shrinkage PP1-SH-2026-000013 by Sreyneang
5 · lot D2 · damaged
📱 ថ្នាំគ្រប់គ្រង – បើកក្នុងកម្មវិធី / controlled medicine – open in the app: https://pharmacy.example.com/approvals
```

### Approval decided (edit)
```
✅ អនុម័តដោយ Dara · 27/10 14:32 (Telegram) / Approved by Dara · 27/10 14:32 (Telegram)
```

### /today
```
📊 PP1 Toul Kork – 27/10/2026 (ថ្ងៃនេះ / today)
លក់ / Sales: 120.50 USD · 494,000 ៛
វិក្កយបត្រ / Invoices: 15 · មធ្យម / avg 8.03 USD
ប្រគល់វិញ / Returns: 0.00 USD
ចំណេញដុល / Gross profit: 40.10 USD (33.3%)
លក់ដំបូង–ចុងក្រោយ / First–last sale: 07:12–19:40
កំពូល / Top: PARA500 30.00
```

### /help (cashier)
```
/stock – ស្តុក៖ /stock ឈ្មោះ ឬបាកូដ / stock: /stock name or barcode
/expiring – ជិតផុតកំណត់ / expiring soon
/help – ជំនួយ / this help
```

### Command limit
```
⏳ ពាក្យបញ្ជាច្រើនពេក សូមរង់ចាំមួយនាទី។ / Too many commands: wait a minute.
```

### Till offline
```
📴 PP1 Toul Kork: គ្មានបញ្ជរណាមួយតភ្ជាប់អស់ ១០ នាទី (ចុងក្រោយ 08:00)។ ពិនិត្យអ៊ីនធឺណិត ឬកុំព្យូទ័រ POS។
📴 PP1 Toul Kork: no till has been online for 10 minutes (last seen 08:00). Check the internet or the POS computer.
```

### Till back
```
✅ PP1 Toul Kork: បញ្ជរតភ្ជាប់វិញហើយ (បាត់ពី 08:00 ដល់ 08:40)។
✅ PP1 Toul Kork: the till is back online (offline 08:00–08:40).
```

### Late opening
```
⏰ PP1 Toul Kork: មិនទាន់មានការលក់ទេ 30 នាទីក្រោយម៉ោងបើក (07:00)។
⏰ PP1 Toul Kork: no sale yet, 30 minutes after opening (07:00).
```

### Fridge out of range
```
🌡️ PP1 Toul Kork Fridge A: 9.8 °C អស់ 11 នាទី (អនុញ្ញាត 2–8 °C)។ ពិនិត្យទូទឹកកក!
🌡️ PP1 Toul Kork Fridge A: 9.8 °C for 11 minutes (allowed 2–8 °C). Check the fridge!
```

### Fridge back in range
```
✅ PP1 Toul Kork Fridge A: ត្រឡប់មកក្នុងកម្រិតវិញ 6.1 °C (ក្រៅកម្រិតពី 09:01 ដល់ 09:20)។
✅ PP1 Toul Kork Fridge A: back in range, 6.1 °C (out 09:01–09:20).
```

### Fridge silent
```
📡 PP1 Toul Kork Fridge A: គ្មានការអានសីតុណ្ហភាព ៣០ នាទី (ចុងក្រោយ 09:20)។ ពិនិត្យឧបករណ៍ចាប់សញ្ញា។
📡 PP1 Toul Kork Fridge A: no reading for 30 minutes (last 09:20). Check the sensor.
```

### 07:30 digest fridge lines
```
🌡️ ទូទឹកកកម្សិលមិញ / Fridges yesterday:
• Fridge A: 2.4–8.6 °C (3) · 1 ក្រៅកម្រិត / out of range
```
