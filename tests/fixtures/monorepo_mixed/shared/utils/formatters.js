const moment = require('moment');
const numeral = require('numeral');

export function formatDate(date, format = 'YYYY-MM-DD') {
    return moment(date).format(format);
}

export function formatCurrency(amount, currency = 'USD') {
    return numeral(amount).format('$0,0.00');
}

export function formatNumber(num, decimals = 2) {
    return numeral(num).format(`0,0.${'0'.repeat(decimals)}`);
}

export function formatPercentage(value) {
    return numeral(value).format('0.00%');
}