This API allow you to get the transaction status of a transaction, you can only check the transaction that created within 7 days only. To get a details of a transaction which is older than 7 days please use Get a transaction details API.
💡
Request limit 600 requests/second
Request
Header Params
Content-Type
string 
required
Example:
application/json
Body Params
application/json
req_time
string 
required
Request date and time in UTC format as YYYYMMDDHHmmss.
merchant_id
string 
required
A unique merchant key which provided by ABA Bank.
tran_id
string 
required
Your purchase transaction id.
hash
string 
required
Base64 encode of hash hmac sha512 encryption of concatenates values merchant_id, and tran_id with public_key.
PHP Sample Code
// public key provided by ABA Bank
$api_key = "API KEY PROVIDED BY ABA BANK";
// Prepare the data to be hashed
$b4hash = $req_time . $merchant_id . $tran_id;
// Generate the HMAC hash using SHA-512 and encode it in Base64 
$hash = base64_encode(hash_hmac('sha512', $b4hash, $api_key, true));
Example
{
    "req_time": "20250213065545",
    "merchant_id": "ec000002",
    "tran_id": "17394277693",
    "hash": "4slqXzgVig09Hf...2vgALgdENA=="
}
Request Code Samples
http.client
Requests
import http.client
import json

conn = http.client.HTTPSConnection("checkout-sandbox.payway.com.kh")
payload = json.dumps({
   "req_time": "20250213065545",
   "merchant_id": "ec000002",
   "tran_id": "17394277693",
   "hash": "4slqXzgVig09Hf...2vgALgdENA=="
})
headers = {
   'Content-Type': 'application/json'
}
conn.request("POST", "/api/payment-gateway/v1/payments/check-transaction-2", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))
Responses
🟢200
OK
application/json
data
object 
optional
payment_status_code
integer 
optional
Transaction status code:
0 : APPROVED, PRE-AUTH
2 : PENDING
3 : DECLINED
4 : REFUNDED
7 : CANCELLED
total_amount
number 
optional
Amount that customer suppose to pay after discount.
original_amount
number 
optional
Original purchase amount
refund_amount
number 
optional
Total of all refunded amount.
discount_amount
number 
optional
Discounted amount and its currency follow the original transaction currency.
payment_amount
number 
optional
The amount that customer has paid.
payment_currency
string 
optional
The payment currency that the customer has paid.
apv
string 
optional
Transaction approval code
payment_status
string 
optional
Possible values:
APPROVED : Transaction successfully completed with the full purchase amount.
PRE-AUTH : Transaction successfully processed with a pre-authorization hold on funds pending final capture.
REFUNDED : Transaction has been fully or partially refunded.
PENDING : Transaction is awaiting payment completion by the payer.
DECLINED : Transaction has been declined.
CANCELLED : Merchant canceled the pre-authorization or closed the transaction.
transaction_date
string 
optional
Date and time of the transaction created in payment gateway.
status
object 
optional
Examples
Success
Exception
{
    "data": {
        "payment_status_code": 0,
        "total_amount": 0.1,
        "original_amount": 0.1,
        "refund_amount": 0,
        "discount_amount": 0,
        "payment_amount": 0.1,
        "payment_currency": "USD",
        "apv": "753786",
        "payment_status": "APPROVED",
        "transaction_date": "2025-02-13 13:55:25"
    },
    "status": {
        "code": "00",
        "message": "Success!",
        "tran_id": "17394277693"
    }
}