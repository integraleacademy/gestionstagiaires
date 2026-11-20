/* Shared by the trainee sheet and the session billing screen. */
const SepaMandateAmount = (() => {
  const field = () => document.getElementById('mandateDebitAmount');
  const currency = new Intl.NumberFormat('fr-FR', {style: 'currency', currency: 'EUR'});

  function mount(line, rebalance) {
    const terms = document.getElementById('installments')?.closest('.billing-modal-grid');
    const preview = document.getElementById('installmentPreview');
    if (!terms || !preview || field()) return;
    const invoiceTerms = terms.id === 'sepaPaymentFields';
    if (invoiceTerms && line.qonto_direct_debit_mandate_id && line.paymentPlan?.debitAmount != null
        && line.directDebitInstallments?.length) {
      const summary = document.createElement('p');
      summary.textContent = `Échéancier SEPA déjà enregistré · ${currency.format(line.paymentPlan.debitAmount)} en ${line.paymentPlan.installments} échéance(s).`;
      terms.closest('.qonto-invoice-card').replaceChildren(summary);
      return;
    }
    const available = line.mandateAvailableCents == null
      ? Number(line.amountTTC || line.amount || 0) : line.mandateAvailableCents / 100;
    const label = document.createElement('label');
    label.innerHTML = '<span class="label">Montant total à prélever (€)</span><input type="number" id="mandateDebitAmount" min="0.01" step="0.01" required><small></small>';
    const input = label.querySelector('input');
    input.max = available.toFixed(2);
    input.value = available.toFixed(2);
    label.querySelector('small').textContent = 'Solde de la ligne de financement · ' + currency.format(available);
    terms.prepend(label);
    input.addEventListener('input', rebalance);
    preview.addEventListener('input', event => {
      if (!event.target.matches('[data-installment-amount]')) return;
      const amounts = [...preview.querySelectorAll('[data-installment-amount]')];
      if (amounts.every(item => item.value && item.checkValidity())) {
        const cents = amounts.reduce((sum, item) => sum + Math.round(item.valueAsNumber * 100), 0);
        input.value = (cents / 100).toFixed(2);
      }
    });
  }

  function total() {
    return field()?.valueAsNumber || 0;
  }

  function plan(showError) {
    const mode = document.querySelector('input[name=paymentMode]:checked')?.value || 'cash';
    if (mode === 'cash') return {paymentMode: mode, installments: 1, firstDebitDate: null, frequency: null, schedule: []};
    const input = field();
    if (!input || !input.checkValidity()) {
      showError('Indiquez un montant à prélever compris entre 0,01 € et le solde de cette ligne.');
      input?.reportValidity();
      return null;
    }
    const schedule = [];
    for (const row of document.querySelectorAll('[data-installment-row]')) {
      const date = row.querySelector('[data-installment-date]');
      const amount = row.querySelector('[data-installment-amount]');
      if (!date.value || !date.checkValidity() || !amount.value || !amount.checkValidity() || amount.valueAsNumber <= 0) {
        showError('Vérifiez la date et le montant de chaque échéance.');
        return null;
      }
      schedule.push({date: date.value, amount: amount.valueAsNumber, status: 'scheduled'});
    }
    if (!schedule.length) {
      showError('Aucune échéance SEPA possible avant la date limite.');
      return null;
    }
    const cents = schedule.reduce((sum, row) => sum + Math.round(row.amount * 100), 0);
    if (cents !== Math.round(total() * 100)) {
      showError('La somme des échéances doit correspondre au montant total à prélever.');
      return null;
    }
    return {paymentMode: mode, debitAmount: total(), installments: schedule.length,
            firstDebitDate: schedule[0].date, frequency: 'monthly', schedule};
  }

  return {mount, total, plan};
})();
