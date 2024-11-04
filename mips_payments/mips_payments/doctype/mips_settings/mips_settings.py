# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

from enum import Enum
from urllib.parse import urlencode, urlparse

import requests
from requests.auth import HTTPBasicAuth

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import call_hook_method, ceil, get_request_site_address
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

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
            payment_channel="Email",
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
def imn_callback(**kwargs) -> None:
    """Decrypt IMN Callback Data"""
    data = frappe._dict(kwargs)

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
        "received_crypted_data": data.get("crypted_callback"),
    }
    headers = {
        "Content-Type": "application/json",
        "user-agent": "ERPNext",
    }

    imn_callback_response = requests.post(
        url="https://api.mips.mu/api/decrypt_imn_data",
        json=payload,
        auth=HTTPBasicAuth(settings.username, settings.password),
        headers=headers,
        timeout=300,
    )
    if imn_callback_response and imn_callback_response.status_code == 200:
        response_detail = frappe._dict(imn_callback_response.json())

        if response_detail.status == "success":
            process_payment(response_detail.data)

        else:
            # TODO: Handle failure response
            # TODO: Notify user?
            pass

    else:
        # TODO: Handle failure response
        pass


def process_payment(response_detail):
    """Process and create payment entries with system permissions."""
    sales_order = fetch_sales_order(response_detail.get("id_order"))
    if sales_order:
        print(sales_order)
        create_payment_entry(sales_order, response_detail)


def fetch_sales_order(order_id: str) -> Document:
    """Fetch Sales Order based on Payment Request's reference_name field."""
    payment_request = frappe.get_doc("Payment Request", {"name": order_id})
    sales_order = frappe.get_doc("Sales Order", payment_request.reference_name)
    return sales_order


def create_payment_entry(sales_order: Document, response_detail: frappe._dict) -> None:
    """Create a Payment Entry for the given Sales Order and response details using Administrator user."""
    original_user = frappe.session.user
    frappe.set_user("Administrator")

    try:
        payment_entry = get_payment_entry(dt="Sales Order", dn=sales_order.name)
        payment_entry.reference_date = frappe.utils.nowdate()
        payment_entry.payment_type = "Receive"
        payment_entry.party_type = "Customer"
        payment_entry.party = sales_order.customer
        payment_entry.currency = response_detail.get("currency")
        payment_entry.reference_no = response_detail.get("id_transaction")
        payment_entry.insert()
        payment_entry.submit()

        frappe.db.commit()

    finally:
        frappe.set_user(original_user)
