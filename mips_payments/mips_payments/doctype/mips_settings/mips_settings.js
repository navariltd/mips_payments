// Copyright (c) 2024, Frappe Technologies and contributors
// For license information, please see license.txt

const url = {
  SANDBOX: 'https://stoplight.io/mocks/mips/merchant-api/36020489',
  PRODUCTION: 'https://api.mips.mu/api',
};

frappe.ui.form.on('MIPS Settings', {
  refresh: async function (frm) {
    frm.add_custom_button(
      __('Register IMN Callback'),
      async function () {
        const siteAddress = `${window.location.protocol}//${window.location.hostname}`;
        const remote = frm.doc.sandbox === 1 ? url.SANDBOX : url.PRODUCTION;

        const response = await fetch(`${remote}/IMN_CALLBACK_ARCH`, {
          method: 'POST',
          body: JSON.stringify({
            crypted_callback: `${siteAddress}/api/method/mips_payments.mips_payments.mips_payments.doctype.mips_settings.imn_callback`,
          }),
          headers: {
            'Content-Type': 'application/json',
            accept: 'application/json',
          },
        });

        const info = await response.text();
        if (response.ok && info === 'success') {
          frm.set_value('is_callback_registered', 1);
          frm.save();
        }
      },
      __('MIPS Actions'),
    );
  },
});
