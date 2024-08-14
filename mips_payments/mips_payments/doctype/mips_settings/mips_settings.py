# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt


import json
from enum import Enum
from urllib.parse import urlencode, urlparse

import requests

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import call_hook_method, ceil, get_request_site_address

from payments.payment_gateways.doctype.mpesa_settings.mpesa_settings import (
    create_mode_of_payment,
)
from payments.utils import create_payment_gateway


class MIPSUrls(Enum):
    SANDBOX = "https://stoplight.io/mocks/mips/merchant-api/36020489"
    PRODUCTION = "https://api.mips.mu/api"


class MIPSSettings(Document):
    """MIPS Settings Doctype"""

    supported_currencies = ["MUR"]

    def get_parsed_site_address(self, full_address: bool = True) -> str:
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
        frappe.db.commit()
        create_mode_of_payment(
            "MIPS-" + self.payment_gateway_name, payment_type="Phone"
        )

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

            response = requests.post(url=url, json=payload, headers=header)

            if response and response.status_code == 200:
                self.is_callback_registered = 1

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
                # TODO: This is where I insert the MIPS Integration
                response = frappe._dict(message="Payment Request")

    def split_request_amount_according_to_transaction_limit(
        self, args: Document
    ) -> list:
        request_amount = args.request_amount

        if request_amount > self.transaction_limit:
            # make multiple requests
            request_amounts = []
            requests_to_be_made = ceil(
                request_amount / self.transaction_limit
            )  # 480/150 = ceil(3.2) = 4
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
    data = json.loads(response)
    print(f"Callback response {data}")
