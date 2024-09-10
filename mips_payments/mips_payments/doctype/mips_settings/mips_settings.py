# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt


import json
from enum import Enum
from urllib.parse import urlencode, urlparse

import requests
from requests.auth import HTTPBasicAuth

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import call_hook_method, ceil, get_request_site_address

from payments.payment_gateways.doctype.mpesa_settings.mpesa_settings import (
    create_mode_of_payment,
)
from payments.utils import create_payment_gateway


class MIPSUrls(Enum):
    SANDBOX = "https://api.mips.mu/api"
    PRODUCTION = "https://api.mips.mu/api"


class MIPSSettings(Document):
    """MIPS Settings Doctype"""

    supported_currencies = ["MUR"]

    def get_parsed_site_address(self, full_address: bool = True) -> str:
        # TODO: For development use. Not intended for production
        site_address = get_request_site_address(full_address=full_address)
        parsed = urlparse(site_address)
        address = f"{parsed.scheme}://{parsed.hostname}"  # Discard port portion
        return address

    def get_payment_url(self, **kwargs) -> str:
        return f"{self.get_parsed_site_address()}/mips_checkout?{urlencode(kwargs)}"

    def on_update(self) -> None:
        """On Update Hook"""
        create_payment_gateway(
            "MIPS-" + self.payment_gateway_name,
            settings="MIPS Settings",
            controller=self.payment_gateway_name,
        )
        call_hook_method(
            "payment_gateway_enabled",
            gateway="MIPS-" + self.payment_gateway_name,
            payment_channel="Phone",
        )

        # required to fetch the bank account details from the payment gateway account
        create_mode_of_payment(
            "MIPS-" + self.payment_gateway_name, payment_type="Phone"
        )
        frappe.db.commit()

        if self.is_callback_registered == 0:
            # Register IMN Callback URL
            if self.sandbox == 1:
                url = MIPSUrls.SANDBOX.value
            else:
                url = MIPSUrls.PRODUCTION.value

            payload = {
                "crypted_callback": f"{self.get_parsed_site_address()}/api/method/mips_payments.mips_payments.mips_payments.doctype.mips_settings.imn_callback"
            }
            header = {"Content-Type": "application/json", "Accept": "application/json"}

            response = requests.post(
                url=url,
                json=payload,
                auth=HTTPBasicAuth(self.username, self.password),
                headers=header,
            )

            if response and response.status_code == 200:
                if response.text == "success":
                    self.is_callback_registered = 1

                else:
                    frappe.throw(
                        "IMN Callback was not registered", title="Setup Failure"
                    )

            else:
                frappe.throw(response.text, title=f"Error: {response.status_code}")

    def validate_transaction_currency(self, currency: str) -> None:
        if currency not in self.supported_currencies:
            frappe.throw(
                _(
                    "Please select another payment method. MIPS does not support transactions in currency '{0}'"
                ).format(currency)
            )

    def request_for_payment(self, **kwargs) -> None:
        args = frappe._dict(kwargs)
        request_amounts = self.split_request_amount_according_to_transaction_limit(args)

        for i, amount in enumerate(request_amounts):
            args.request_amount = amount

            if frappe.flags.in_test:
                from payments.payment_gateways.doctype.mpesa_settings.test_mpesa_settings import (
                    get_payment_request_response_payload,
                )

                response = frappe._dict(get_payment_request_response_payload(amount))
            else:
                response = frappe._dict(message="Payment Request")

    def split_request_amount_according_to_transaction_limit(
        self, args: Document
    ) -> list:
        request_amount = args.request_amount

        if request_amount > self.transaction_limit:
            # make multiple requests
            request_amounts = []
            requests_to_be_made = ceil(request_amount / self.transaction_limit)
            for i in range(requests_to_be_made):
                amount = self.transaction_limit
                if i == requests_to_be_made - 1:
                    amount = request_amount - (
                        self.transaction_limit * i
                    )  # for 4th request, 480 - (150 * 3) = 30
                request_amounts.append(amount)

        else:
            request_amounts = [request_amount]

        return request_amounts


@frappe.whitelist(allow_guest=True)
def imn_callback(response: str) -> None:
    """Decrypt IMN Callback Data"""
    data = json.loads(response)

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

    payload = {
        "authentify": {
            "id_merchant": settings.merchant_id,
            "id_entity": settings.entity_id,
            "id_operator": settings.operator_id,
            "operator_password": settings.operator_password,
        },
        "salt": settings.hash_salt,
        "cipher_key": settings.cipher_key,
        "received_crypted_data": response,
    }
    headers = {
        "Content-Type": "application/json",
        "user-agent": "ERPNext",
    }

    imn_callback_response = requests.post(
        url="",
        json=payload,
        auth=HTTPBasicAuth(settings.username, settings.password),
        headers=headers,
    )

    if imn_callback_response and imn_callback_response.status_code == 200:
        # TODO: Handle success response
        pass

    else:
        # TODO: Handle failure response
        pass
