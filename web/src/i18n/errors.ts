// Friendly messages per API error code, English + Khmer. The 13 designed ones come from the design handoff
// (docs/design/error-messages.json) and win; the rest cover every other ErrorCode of the backend
// (shared/pharmacy_shared/errors.py). An unknown code falls back to the API's own message.
import designed from '@design/error-messages.json';

export type Severity = 'hard_stop' | 'warning' | 'info' | 'error';
export interface ErrorText {
  en: string;
  km: string;
  severity: Severity;
}

const E = (severity: Severity, en: string, km: string): ErrorText => ({ severity, en, km });

const OTHER: Record<string, ErrorText> = {
  BATCH_EXPIRED: E('hard_stop', 'This batch has expired and cannot be used.', 'ឡូត៍នេះផុតកំណត់ហើយ មិនអាចប្រើបានទេ។'),
  BATCH_BLOCKED: E('hard_stop', 'This batch is blocked (quarantine or recall).', 'ឡូត៍នេះត្រូវបានរារាំង (ដាក់ដាច់ដោយឡែក ឬរំលឹកមកវិញ)។'),
  TRANSFER_STATE: E('error', 'This transfer cannot do that in its current status.', 'ការផ្ទេរនេះមិនអាចធ្វើសកម្មភាពនេះក្នុងស្ថានភាពបច្ចុប្បន្នទេ។'),
  RX_EXPIRED: E('hard_stop', 'This prescription has expired.', 'វេជ្ជបញ្ជានេះផុតសុពលភាពហើយ។'),
  PRESCRIPTION_STATE: E('error', 'This prescription cannot be used in its current status.', 'វេជ្ជបញ្ជានេះមិនអាចប្រើក្នុងស្ថានភាពបច្ចុប្បន្នទេ។'),
  DUPLICATE_THERAPY_WARNING: E('warning', 'The patient already has a medicine of the same kind. Check before you continue.', 'អ្នកជំងឺមានឱសថប្រភេទដូចគ្នារួចហើយ។ សូមពិនិត្យមុនបន្ត។'),
  ALLERGY_WARNING: E('warning', 'The patient is allergic to an ingredient of this medicine.', 'អ្នកជំងឺមានប្រតិកម្មអាឡែស៊ីនឹងសារធាតុក្នុងឱសថនេះ។'),
  MFA_REQUIRED_FOR_ROLE: E('error', 'Your role must use two-factor login. You can only reset it.', 'តួនាទីរបស់អ្នកត្រូវប្រើការផ្ទៀងផ្ទាត់ពីរជំហាន។ អ្នកអាចកំណត់ឡើងវិញបានតែប៉ុណ្ណោះ។'),
  PIN_REQUIRED: E('warning', 'Enter your PIN to continue.', 'សូមបញ្ចូល PIN របស់អ្នកដើម្បីបន្ត។'),
  PIN_INVALID: E('error', 'The PIN is wrong or the approval has expired. Try again.', 'PIN មិនត្រឹមត្រូវ ឬការអនុម័តផុតកំណត់។ សូមព្យាយាមម្តងទៀត។'),
  WITNESS_REQUIRED: E('warning', 'A witness must confirm with their PIN.', 'សាក្សីត្រូវបញ្ជាក់ដោយ PIN របស់គេ។'),
  WITNESS_INVALID: E('error', 'This person cannot be the witness (different user, same branch, witness permission).', 'អ្នកនេះមិនអាចធ្វើជាសាក្សីបានទេ (ត្រូវជាអ្នកផ្សេង សាខាដូចគ្នា និងមានសិទ្ធិធ្វើសាក្សី)។'),
  REGISTER_STATE: E('error', 'The register cannot do that now.', 'បញ្ជីមិនអាចធ្វើសកម្មភាពនេះឥឡូវបានទេ។'),
  BRANCH_FORBIDDEN: E('error', 'You do not have access to this branch.', 'អ្នកមិនមានសិទ្ធិចូលសាខានេះទេ។'),
  RATE_LIMITED: E('error', 'Too many tries. Wait a minute and try again.', 'ព្យាយាមច្រើនដងពេក។ សូមរង់ចាំមួយនាទី ហើយព្យាយាមម្តងទៀត។'),
  ACCOUNT_LOCKED: E('hard_stop', 'Account locked after too many failed logins.', 'គណនីត្រូវបានចាក់សោក្រោយចូលខុសច្រើនដង។'),
  SESSION_REVOKED: E('error', 'Your session was ended. Please sign in again.', 'វគ្គរបស់អ្នកត្រូវបានបញ្ចប់។ សូមចូលម្តងទៀត។'),
  FILE_REJECTED: E('error', 'This file cannot be used. Use a JPEG, PNG or PDF up to 10 MB.', 'មិនអាចប្រើឯកសារនេះបានទេ។ សូមប្រើ JPEG, PNG ឬ PDF មិនលើស 10 MB។'),
  AI_DISABLED: E('info', 'AI features are turned off.', 'មុខងារ AI ត្រូវបានបិទ។'),
  AI_UNAVAILABLE: E('error', 'The AI service is not available right now.', 'សេវា AI មិនអាចប្រើបានឥឡូវនេះទេ។'),
  AI_LIMIT_REACHED: E('error', 'The AI limit for today is reached.', 'បានដល់ដែនកំណត់ AI សម្រាប់ថ្ងៃនេះ។'),
  AI_UNREADABLE: E('error', 'The AI could not read this.', 'AI មិនអាចអានឯកសារនេះបានទេ។'),
  INVALID_CREDENTIALS: E('error', 'Wrong phone number or password.', 'លេខទូរស័ព្ទ ឬពាក្យសម្ងាត់មិនត្រឹមត្រូវ។'),
  NOT_AUTHENTICATED: E('error', 'Please sign in.', 'សូមចូលប្រើប្រព័ន្ធ។'),
  IDEMPOTENCY_KEY_REQUIRED: E('error', 'Something went wrong sending this. Try again.', 'មានបញ្ហាក្នុងការផ្ញើ។ សូមព្យាយាមម្តងទៀត។'),
  IDEMPOTENCY_KEY_INVALID: E('error', 'Something went wrong sending this. Try again.', 'មានបញ្ហាក្នុងការផ្ញើ។ សូមព្យាយាមម្តងទៀត។'),
  IDEMPOTENCY_KEY_REUSED: E('error', 'This was already sent with different data. Start again.', 'ទិន្នន័យនេះបានផ្ញើរួចជាមួយព័ត៌មានផ្សេង។ សូមចាប់ផ្តើមម្តងទៀត។'),
  IDEMPOTENCY_IN_PROGRESS: E('info', 'Still working on the previous try. Wait a moment.', 'កំពុងដំណើរការការព្យាយាមមុន។ សូមរង់ចាំបន្តិច។'),
  MFA_REQUIRED: E('info', 'Enter the code from your authenticator app.', 'សូមបញ្ចូលលេខកូដពីកម្មវិធីផ្ទៀងផ្ទាត់។'),
  MFA_SETUP_REQUIRED: E('warning', 'Set up two-factor sign-in before you continue.', 'សូមរៀបចំការផ្ទៀងផ្ទាត់ពីរជំហានមុនបន្ត។'),
  FORBIDDEN: E('error', 'You do not have permission to do this.', 'អ្នកមិនមានសិទ្ធិធ្វើសកម្មភាពនេះទេ។'),
  LAST_OWNER: E('error', 'The last active owner cannot be changed or deactivated.', 'មិនអាចកែប្រែ ឬបិទម្ចាស់សកម្មចុងក្រោយបានទេ។'),
  ROLE_IN_USE: E('error', 'This role is still given to staff.', 'តួនាទីនេះនៅតែមានបុគ្គលិកប្រើ។'),
  ROLE_NOT_EDITABLE: E('error', 'This role cannot be edited.', 'មិនអាចកែតួនាទីនេះបានទេ។'),
  UNKNOWN_ROLE: E('error', 'Unknown role.', 'តួនាទីមិនស្គាល់។'),
  UNKNOWN_PERMISSION: E('error', 'Unknown permission.', 'សិទ្ធិមិនស្គាល់។'),
  UNKNOWN_BRANCH: E('error', 'Unknown branch.', 'សាខាមិនស្គាល់។'),
  DUPLICATE_CODE: E('info', 'This code is already used.', 'លេខកូដនេះត្រូវបានប្រើរួចហើយ។'),
  WEAK_PASSWORD: E('error', 'The password is too weak. Use at least 8 characters.', 'ពាក្យសម្ងាត់ខ្សោយពេក។ សូមប្រើយ៉ាងតិច ៨ តួ។'),
  INVALID_PIN: E('error', 'The PIN must be 4 to 6 digits and not too simple.', 'PIN ត្រូវមាន ៤ ដល់ ៦ ខ្ទង់ ហើយមិនសាមញ្ញពេក។'),
  CANNOT_CHANGE_SELF: E('error', 'You cannot do this to your own account.', 'អ្នកមិនអាចធ្វើសកម្មភាពនេះលើគណនីខ្លួនឯងបានទេ។'),
  UNKNOWN_FEATURE: E('error', 'Unknown feature.', 'មុខងារមិនស្គាល់។'),
  DUPLICATE_SKU: E('info', 'This SKU is already used.', 'SKU នេះត្រូវបានប្រើរួចហើយ។'),
  DUPLICATE_BARCODE: E('info', 'This barcode is already used.', 'បាកូដនេះត្រូវបានប្រើរួចហើយ។'),
  DUPLICATE_NAME: E('info', 'This name is already used.', 'ឈ្មោះនេះត្រូវបានប្រើរួចហើយ។'),
  UNKNOWN_CATEGORY: E('error', 'Unknown category.', 'ប្រភេទមិនស្គាល់។'),
  UNKNOWN_BRAND: E('error', 'Unknown brand.', 'ម៉ាកមិនស្គាល់។'),
  IMPORT_HAS_ERRORS: E('error', 'The file has errors. Fix them or skip the invalid rows.', 'ឯកសារមានកំហុស។ សូមកែ ឬរំលងជួរដែលមិនត្រឹមត្រូវ។'),
  IMPORT_STATE: E('error', 'This import was already committed or is not ready.', 'ការនាំចូលនេះបានបញ្ចប់រួច ឬមិនទាន់រួចរាល់។'),
  UNKNOWN_MEDICINE: E('error', 'Unknown or inactive medicine.', 'ឱសថមិនស្គាល់ ឬមិនសកម្ម។'),
  UNKNOWN_SUPPLIER: E('error', 'Unknown or inactive supplier.', 'អ្នកផ្គត់ផ្គង់មិនស្គាល់ ឬមិនសកម្ម។'),
  PO_STATE: E('error', 'This purchase order cannot do that in its current status.', 'បញ្ជាទិញនេះមិនអាចធ្វើសកម្មភាពនេះក្នុងស្ថានភាពបច្ចុប្បន្នទេ។'),
  REQUEST_STATE: E('error', 'This request cannot do that in its current status.', 'សំណើនេះមិនអាចធ្វើសកម្មភាពនេះក្នុងស្ថានភាពបច្ចុប្បន្នទេ។'),
  RECEIVE_EXCEEDS_ORDER: E('warning', 'More than ordered. Receiving extra needs permission.', 'លើសចំនួនបានបញ្ជា។ ការទទួលលើសត្រូវការសិទ្ធិ។'),
  PAYMENT_STATE: E('error', 'This payment cannot do that in its current status.', 'ការទូទាត់នេះមិនអាចធ្វើសកម្មភាពនេះក្នុងស្ថានភាពបច្ចុប្បន្នទេ។'),
  INITIALIZE_LOCKED: E('hard_stop', 'Opening stock is locked for this branch. Only the owner can unlock it.', 'ស្តុកដើមគ្រាត្រូវបានចាក់សោសម្រាប់សាខានេះ។ មានតែម្ចាស់ទេដែលអាចដោះសោ។'),
  OPENING_HAS_ERRORS: E('error', 'The opening stock file has errors.', 'ឯកសារស្តុកដើមគ្រាមានកំហុស។'),
  DOCUMENT_NOT_READY: E('info', 'The document is not ready yet. Try again in a few seconds.', 'ឯកសារមិនទាន់រួចរាល់។ សូមព្យាយាមម្តងទៀតក្នុងប៉ុន្មានវិនាទី។'),
  SHRINKAGE_STATE: E('error', 'This shrinkage record cannot do that in its current status.', 'កំណត់ត្រាខូចខាតនេះមិនអាចធ្វើសកម្មភាពនេះទេ។'),
  COUNT_STATE: E('error', 'This stock take cannot do that in its current status.', 'ការរាប់ស្តុកនេះមិនអាចធ្វើសកម្មភាពនេះក្នុងស្ថានភាពបច្ចុប្បន្នទេ។'),
  OWNER_APPROVAL_REQUIRED: E('warning', 'The variance is above the limit. The owner must approve.', 'ភាពខុសគ្នាលើសដែនកំណត់។ ម្ចាស់ត្រូវអនុម័ត។'),
  CONTROLLED_NOT_AVAILABLE: E('hard_stop', 'Controlled medicines cannot be sold this way.', 'ឱសថគ្រប់គ្រងមិនអាចលក់តាមវិធីនេះបានទេ។'),
  PAYMENT_SHORT: E('warning', 'The payment is less than the total.', 'ការទូទាត់តិចជាងសរុប។'),
  PROMOTION_LIMIT: E('info', 'This promotion has reached its limit.', 'ប្រូម៉ូសិននេះបានដល់ដែនកំណត់ហើយ។'),
  ORDER_STATE: E('error', 'This sale order cannot do that in its current status.', 'បញ្ជាលក់នេះមិនអាចធ្វើសកម្មភាពនេះក្នុងស្ថានភាពបច្ចុប្បន្នទេ។'),
  CART_STATE: E('error', 'This cart was already resumed or has expired.', 'រទេះនេះត្រូវបានបន្តរួច ឬផុតកំណត់ហើយ។'),
  DEPOSIT_EXCEEDED: E('error', 'More than the deposit left.', 'លើសប្រាក់កក់ដែលនៅសល់។'),
  EXPORT_TOO_LARGE: E('error', 'Too many rows to export. Narrow the filters.', 'ជួរច្រើនពេកសម្រាប់នាំចេញ។ សូមបង្រួមតម្រង។'),
  TELEGRAM_NOT_CONFIGURED: E('info', 'Telegram is not set up on the server.', 'Telegram មិនទាន់បានរៀបចំនៅលើម៉ាស៊ីនមេ។'),
  KHQR_NOT_PAID: E('warning', 'The KHQR payment is not received yet.', 'មិនទាន់ទទួលបានការទូទាត់ KHQR ទេ។'),
  KHQR_MISMATCH: E('hard_stop', 'The KHQR payment does not match this sale.', 'ការទូទាត់ KHQR មិនត្រូវនឹងការលក់នេះទេ។'),
  KHQR_USED: E('hard_stop', 'This KHQR payment was already used.', 'ការទូទាត់ KHQR នេះត្រូវបានប្រើរួចហើយ។'),
  KHQR_STATE: E('error', 'This KHQR payment cannot do that in its current status.', 'ការទូទាត់ KHQR នេះមិនអាចធ្វើសកម្មភាពនេះក្នុងស្ថានភាពបច្ចុប្បន្នទេ។'),
  KHQR_REFUND_TOO_MUCH: E('hard_stop', 'More than is left to refund on this KHQR payment.', 'លើសចំនួនដែលនៅសល់ត្រូវសងលើការទូទាត់ KHQR នេះ។'),
  KHQR_REFUND_BUSY: E('warning', 'ABA PayWay is still working on another refund of this payment. Try again in a few seconds.', 'ABA PayWay កំពុងដំណើរការការសងមួយទៀតនៃការទូទាត់នេះ។ សូមព្យាយាមម្តងទៀតក្នុងពេលបន្តិចទៀត។'),
  KHQR_REFUND_NO_BALANCE: E('error', 'The merchant account has not enough balance for this refund.', 'គណនីអាជីវករមិនមានសមតុល្យគ្រប់គ្រាន់សម្រាប់ការសងនេះទេ។'),
  PAYWAY_AUTH_FAILED: E('error', 'ABA PayWay refused the request signature. Ask the administrator to check the PayWay settings.', 'ABA PayWay បដិសេធហត្ថលេខាសំណើ។ សូមឲ្យអ្នកគ្រប់គ្រងពិនិត្យការកំណត់ PayWay។'),
  PAYWAY_REJECTED: E('error', 'ABA PayWay refused the request.', 'ABA PayWay បានបដិសេធសំណើ។'),
  RECALL_STATE: E('error', 'This recall cannot do that in its current status.', 'ការរំលឹកនេះមិនអាចធ្វើសកម្មភាពនេះក្នុងស្ថានភាពបច្ចុប្បន្នទេ។'),
  SUPPLIER_RETURN_STATE: E('error', 'This supplier return cannot do that in its current status.', 'ការប្រគល់ទៅអ្នកផ្គត់ផ្គង់នេះមិនអាចធ្វើសកម្មភាពនេះទេ។'),
  EXCHANGE_RATE_MISSING: E('hard_stop', 'No exchange rate is set for this branch.', 'មិនទាន់កំណត់អត្រាប្តូរប្រាក់សម្រាប់សាខានេះទេ។'),
  INVOICE_STATE: E('error', 'This invoice cannot do that in its current status.', 'វិក្កយបត្រនេះមិនអាចធ្វើសកម្មភាពនេះក្នុងស្ថានភាពបច្ចុប្បន្នទេ។'),
  RETURN_EXCEEDS_SOLD: E('hard_stop', 'More than was sold and not yet returned.', 'លើសចំនួនដែលបានលក់ និងមិនទាន់ប្រគល់វិញ។'),
  OPENED_PACK_RETURN: E('hard_stop', 'This branch does not take back opened packs.', 'សាខានេះមិនទទួលកញ្ចប់ដែលបានបើករួចវិញទេ។'),
  CUSTOMER_REQUIRED: E('warning', 'Choose a customer first.', 'សូមជ្រើសរើសអតិថិជនជាមុនសិន។'),
  CUSTOMER_OVERPAYMENT: E('info', 'The payment is more than the customer owes.', 'ការទូទាត់លើសចំនួនដែលអតិថិជនជំពាក់។'),
  TEMPORARILY_UNAVAILABLE: E('error', 'A service is not answering. Try again in a moment.', 'សេវាមួយមិនឆ្លើយតប។ សូមព្យាយាមម្តងទៀតបន្តិចទៀត។'),
  NOT_FOUND: E('error', 'Not found.', 'រកមិនឃើញ។'),
  VALIDATION_ERROR: E('error', 'Some fields need attention.', 'វាលខ្លះត្រូវការកែតម្រូវ។'),
  NETWORK_ERROR: E('error', 'No connection to the server.', 'មិនអាចភ្ជាប់ទៅម៉ាស៊ីនមេបានទេ។'),
  INTERNAL_ERROR: E('error', 'Something went wrong on the server.', 'មានបញ្ហានៅលើម៉ាស៊ីនមេ។'),
};

export const ERROR_TEXTS: Record<string, ErrorText> = {
  ...OTHER,
  ...(designed.messages as Record<string, ErrorText>),
};

export function errorText(code: string, lang: 'km' | 'en', fallback?: string): string {
  return ERROR_TEXTS[code]?.[lang] ?? fallback ?? ERROR_TEXTS.INTERNAL_ERROR[lang];
}

export function errorSeverity(code: string): Severity {
  return ERROR_TEXTS[code]?.severity ?? 'error';
}
