The Purchase API is used to initiate a payment transaction between a customer and a merchant through PayWay. It allows merchants to request a payment by providing transaction details such as the amount, currency, item list, and other relevant data.
Once the API is called, the customer is redirected to PayWay’s hosted checkout page, bottom sheet, or modal popup—depending on your integration option—where they can complete the payment using the available methods (e.g., card, ABA PAY, KHQR, digital wallets). After the transaction is completed, PayWay will return the transaction result to the merchant via the configured return URL or callback.
Request
Header Params
Content-Type
string 
required
Example:
multipart/form-data
Body Params multipart/form-data
req_time
string 
required
Request date and time in UTC format as YYYYMMDDHHmmss.
merchant_id
string 
required
A unique merchant key which provided by ABA Bank.
<= 30 characters
tran_id
string 
required
A unique transaction identifier for the payment.
<= 20 characters
firstname
string 
optional
Buyer's first name.
<= 100 characters
lastname
string 
optional
Buyer's last name.
<= 100 characters
email
string 
optional
Buyer's email.
<= 50 characters
phone
string 
optional
Buyer's phone.
<= 20 characters
type
string 
optional
Type of the transaction, default value is purchase. Supported value:
pre-auth : for pre purchase
purchase : for full purchase
Note: pre-auth only support ABA PAY, KHQR and Card Payment.
<= 20 characters
payment_option
string 
optional
Payment Methods for Transactions:
cards: For card payments.
abapay_khqr: QR payment that can be scanned and paid using ABA PAY and other KHQR member banks.
abapay_khqr_deeplink: Allows customers to pay using ABA PAY and other KHQR member banks. The payment gateway will respond with a JSON object containing qr_string, abapay_deeplink, and checkout_qr_url. See the sample response in the response section below.
alipay: Allows customers to pay using Alipay Wallet.
wechat: Allows customers to pay using WeChat Wallet.
google_pay: Allows customers to pay using Google Pay Wallet.
If no value is provided, the payment gateway will automatically display the supported payment options based on your profile, allowing the customer to choose a preferred payment method.
<= 20 characters
items
string 
optional
A Base64-encoded JSON array describing the items being purchased. It supports up to 50 line items with no character limit.
Note: This is only description/remark. The price or quantity in this info will not be used for calculation or any validation purposes
PHP Sample Code
$item = base64_encode(json_encode([
    ["name" => "product 1","quantity" => 1,"price" => 1.00], 
    ["name" => "product 2","quantity" => 2, "price" => 4.00]
]));
shipping
number 
optional
Shipping fee.
amount
number 
required
Purchase amount.
currency
string 
optional
Transaction currency of the payment. If you don't pass any value, it will take default value from your merchant profile (the first account's the currency of the first account you registered). Supported values are KHR or USD.
return_url
string 
optional
URL to receive callbacks upon payment completion, encrypted with Base64.
cancel_url
string 
optional
The URL to redirect to after the user closes the payment dialog or when user cancel the payment.
skip_success_page
integer 
optional
Skip success page can be configure on checkout service level. We also provide option via the API for you to override the setting too. If you don't pass this param, it will follow the configuration on the profile level. Supported value:
0 : Don't skip success pages
1: Skip success page.
Once you skipe success page, continue_success_url on profile level will be used to redirect user to the specific location if you don't pass value of continue_success_url in the request.
continue_success_url
string 
optional
The URL to redirect to after a successful payment.
return_deeplink
string 
optional
The deep link for redirecting to the app after a successful payment from ABA Mobile. Must be base64-encoded and include both iOS and Android schemes. This field is mandatory for mobile integration.
PHP Sample Code
$return_deeplink =base64_encode(json_encode([
    "ios_scheme" => "DEEPLINK TO RETURN TO YOUR IOS APP",
    "android_scheme" => "DEEPLINK TO RETURN TO YOUR ANDROID APP"
]));
custom_fields
string 
optional
Additional information that you want to attach to the transaction. This information will appear in the transaction list, transaction details and export report. It's base64-encoded JSON info.
PHP Sample Code
$custom_field = base64_encode(json_encode([
    "field1" => "myvalue1",
    "field2" => "myvalue2"
]));
return_params
string 
optional
Information to include when PayWay calls your return URL after a successful payment.
view_type
string 
optional
Defines the view type for the payment page.
hosted_view : redirect payer to a new tab
popup : Display as a bottom sheet on mobile web browsers and as a modal popup on desktop web browsers.
payment_gate
integer 
optional
If your merchant profile also supports the QR Payment API service, please set this parameter to 0 to use the Checkout service.
payout
string 
optional
Base64-encoded JSON string representing payout details.
PHP Sample Code
$payout = base64_encode(json_encode([
    ["acc" => "000133879","amt"=> 1], 
    ["acc" => "000133880","amt" => 1]
]));
additional_params
string 
optional
Currently, we support WeChat Mini Program. These are the values key wechat sub_appid and wechat_sub_openid.
PHP Sample Code
$additional_params = base64_encode(json_encode([
    'wechat_sub_appid' => 'YOUR WECHAT APP ID',
    'wechat_sub_openid' => 'YOUR WECHAT OPEN ID'
]));
lifetime
integer 
optional
The payment's lifetime in minutes, once it exceeds customer will not allow to make payment. Default value is 30 days.
Min: 3 mins
Max: 30 days
For ABA PAY or Card: Transaction will not go throught.
KHQR: In case payment happen after exceed life time, PayWay will also reject. Fund will be reverse back to payer.
WeChat & Alipay: No reversal.
google_pay_token
string 
optional
This field is required if payment_option is set to google_pay and the payment selection is managed by the merchant. For detailed instructions, please refer to the Google Pay integration guidelines.
hash
string 
required
Base64 encode of hash hmac sha512 encryption of concatenates values below values.
PHP Sample Code
// public key provided by ABA Bank
$api_key = "API KEY PROVIDED BY ABA BANK";

// Prepare the data to be hashed
$b4hash = $req_time . $merchant_id . $tran_id . $amount . $items . $shipping . $firstname . $lastname . $email . $phone . $type . $payment_option . $return_url . $cancel_url . $continue_success_url . $return_deeplink . $currency . $custom_fields . $return_params . $payout . $lifetime . $additional_params . $google_pay_token .$skip_success_page;


// Generate the HMAC hash using SHA-512 and encode it in Base64 
$hash = base64_encode(hash_hmac('sha512', $b4hash, $api_key, true));
Request Code Samples
http.client
Requests
import http.client
import mimetypes
from codecs import encode

conn = http.client.HTTPSConnection("checkout-sandbox.payway.com.kh")
dataList = []
boundary = 'wL36Yn8afVp8Ag7AmP8qZ0SA4n1v9T'
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=req_time;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=merchant_id;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=tran_id;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=firstname;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=lastname;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=email;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=phone;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=type;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=payment_option;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=items;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=shipping;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=amount;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=currency;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=return_url;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=cancel_url;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=skip_success_page;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=continue_success_url;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=return_deeplink;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=custom_fields;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=return_params;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=view_type;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=payment_gate;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=payout;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=additional_params;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=lifetime;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=google_pay_token;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=hash;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode(""))
dataList.append(encode('--'+boundary+'--'))
dataList.append(encode(''))
body = b'\r\n'.join(dataList)
payload = body
headers = {
    'Content-type': 'multipart/form-data; boundary={}'.format(boundary) 
}
conn.request("POST", "/api/payment-gateway/v1/payments/purchase", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))
Responses
🟢200
Success
text/html
Examples
Success
Success
<!DOCTYPE html>
<html data-capo="">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalab
<title>PayWay - Checkout</title>
...
</head>
<body>
...
</body>
</html>
🟢200
OK
🟢200
Exception