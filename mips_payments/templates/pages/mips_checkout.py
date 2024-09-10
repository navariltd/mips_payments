from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date


def get_context(context: frappe._dict) -> None:
    form_dict = frappe._dict(frappe.form_dict)
    context.no_cache = 1

    payment_gateway_acct: Document = frappe.db.get_singles_value(
        "WebShop Settings", "payment_gateway_account"
    )
    gateway = frappe.db.get_value(
        "Payment Gateway Account",
        {"name": payment_gateway_acct},
        ["payment_gateway"],
    )
    controller = frappe.db.get_value("Payment Gateway", gateway, ["gateway_controller"])
    settings = frappe.get_doc("MIPS Settings", {"name": controller})

    if settings:
        user = frappe.session.user
        user_details = frappe.get_doc("User", {"name": user})

        # TODO: Handle fetching of MIPS url properly
        mips_url = "https://api.mips.mu/api/create_payment_request"
        expiry_date = add_to_date(datetime.now(), days=1)
        max_date = expiry_date
        start_time = datetime.now().strftime("%Y-%m-%d")

        payload = {
            "authentify": {
                "id_merchant": settings.merchant_id,
                "id_entity": settings.entity_id,
                "id_operator": settings.operator_id,
                "operator_password": settings.operator_password,
            },
            "request": {
                "request_mode": "simple",
                "options": "warranty",
                "sending_mode": "mail",
                "request_title": "Your GT Away Purchase",
                "exp_date": expiry_date.strftime("%Y-%m-%d"),
                "client_details": {
                    "first_name": user_details.first_name,
                    "last_name": user_details.last_name or "",
                    "client_email": user_details.email,
                    "phone_number": user_details.mobile_no or "",
                },
                "max_amount_total": float(form_dict.amount),
                "max_amount_per_claim": 0,
                "max_frequency": 0,
                "max_date": max_date.strftime("%Y-%m-%d"),
                "deposit_amount": form_dict.amount,
                "balance_pattern": [
                    {
                        "balance_number": 1,
                        "balance_mode": "auto",
                        "condition": f'"Upon request" or {max_date.strftime("%Y-%m-%d")}',
                    }
                ],
                "client_account_number": "string",
            },
            "initial_payment": {
                "id_order": form_dict.order_id,
                "currency": "MUR",
                "amount": float(form_dict.amount),
            },
            # "iframe_behavior": {"custom_redirection_url": "string"},
        }

        credentials = HTTPBasicAuth(
            settings.username, settings.get_password("password")
        )
        mips_payment_request = requests.post(
            mips_url,
            json=payload,
            auth=credentials,
            headers={
                "Content-Type": "application/json",
                "user-agent": "ERPNext",
            },
        )
        context.fetch_code = mips_payment_request.status_code

        if mips_payment_request.status_code == 200:
            result_body = mips_payment_request.json()
            context.status = result_body["operation_status"]

            if result_body["operation_status"] == "success":
                context.request = payload
                context.data = result_body
                context.redirect_to = str(result_body["payment_link"]["url"])
                context.qr_code = result_body["payment_link"]["qr_code"]

            elif result_body["operation_status"] == "error":
                # TODO: Handle error cases
                context.text = mips_payment_request.text
                context.error = result_body["operation_status_details"]

        else:
            frappe.msgprint("Fatal Error encountered")
